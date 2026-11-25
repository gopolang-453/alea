"""Keep the served ledger copy in step with the public data branch.

The scheduled workflow is the only writer of the ledger; it commits
``ledger.sqlite`` and ``fixtures_upcoming.json`` to the ``prospective-ledger``
branch. A hosted ALEA instance downloads those two files on a timer and swaps
them in atomically, but only if the downloaded ledger passes the same
append-only commit gate the workflow uses (every existing row unchanged, all
triggers present, integrity check ok). A failed or suspicious download never
replaces the copy being served; the API keeps serving the last verified copy.

No credentials are needed: the repository and the data branch are public.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from stages.stage12.ledger_ops import verify_append_only_update
from stages.stage9.prospective_ledger import LedgerError, ProspectiveLedger

log = logging.getLogger("alea.sync")
MAX_BYTES = 50 * 1024 * 1024
DEFAULT_SOURCE = "https://raw.githubusercontent.com/gopolang-453/alea/prospective-ledger"


def _download(url: str, timeout: float = 30.0) -> bytes:
    if not url.startswith("https://"):
        raise ValueError("sync source must be https")
    req = urllib.request.Request(url, headers={"User-Agent": "alea-ledger-sync/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - https enforced above
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("download exceeds size limit")
    return data


class LedgerSync:
    def __init__(self, source: str, ledger_path: str | Path, fixtures_path: str | Path, *,
                 interval_minutes: float = 30.0, fetch: Callable[[str], bytes] = _download) -> None:
        self.source = source.rstrip("/")
        self.ledger_path = Path(ledger_path)
        self.fixtures_path = Path(fixtures_path)
        self.interval = max(60.0, interval_minutes * 60.0)
        self.fetch = fetch
        self._lock = threading.Lock()
        self.state: Dict[str, Any] = {"source": self.source, "last_attempt_at": None,
                                      "last_success_at": None, "last_change_at": None, "last_error": None}

    # ------------------------------------------------------------------
    def _verified_ledger(self, data: bytes) -> Optional[Path]:
        """Write the download beside the live copy and return it if it is safe to serve."""
        tmp = self.ledger_path.with_name(self.ledger_path.name + ".download")
        tmp.write_bytes(data)
        try:
            if self.ledger_path.exists():
                if self.ledger_path.read_bytes() == data:
                    tmp.unlink()
                    return None
                verdict = verify_append_only_update(self.ledger_path, tmp)
                if not verdict["ok"]:
                    raise LedgerError("downloaded ledger is not an append-only successor: "
                                      + "; ".join(verdict["problems"][:3]))
            else:
                with ProspectiveLedger(tmp, read_only=True) as led:
                    report = led.integrity_report()
                if not report["ok"]:
                    raise LedgerError("downloaded ledger failed its integrity check")
            return tmp
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def sync_once(self) -> Dict[str, Any]:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            self.state["last_attempt_at"] = now
            changed = []
            try:
                self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
                fresh = self._verified_ledger(self.fetch(f"{self.source}/ledger.sqlite"))
                if fresh is not None:
                    os.replace(fresh, self.ledger_path)
                    changed.append("ledger")
                try:
                    raw = self.fetch(f"{self.source}/fixtures_upcoming.json")
                    doc = json.loads(raw)
                    if not isinstance(doc.get("fixtures"), list):
                        raise ValueError("fixture list has no fixtures array")
                    if not self.fixtures_path.exists() or self.fixtures_path.read_bytes() != raw:
                        tmp = self.fixtures_path.with_name(self.fixtures_path.name + ".download")
                        tmp.write_bytes(raw)
                        os.replace(tmp, self.fixtures_path)
                        changed.append("fixtures")
                except Exception as exc:  # optional file: the ledger is what matters
                    log.warning("fixture list not synced: %s", exc)
                self.state.update(last_success_at=now, last_error=None)
                if changed:
                    self.state["last_change_at"] = now
                    log.info("synced %s from %s", ", ".join(changed), self.source)
            except Exception as exc:
                log.error("ledger sync failed (still serving the last verified copy): %s", exc)
                self.state["last_error"] = "sync failed; serving the last verified copy"
            return dict(self.state, changed=changed)

    def status(self) -> Dict[str, Any]:
        return dict(self.state)

    def start(self) -> threading.Thread:
        def loop():
            while True:
                time.sleep(self.interval)
                self.sync_once()
        t = threading.Thread(target=loop, name="ledger-sync", daemon=True)
        t.start()
        return t
