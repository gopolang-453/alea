"""Stage 12 backup / restore for the prospective ledger (the persistent store).

* ``backup_ledger`` uses SQLite's online backup API, so the copy is
  transactionally consistent even if a writer is active, and writes a manifest
  with the file SHA-256, the champion-forecast fingerprint and row counts.
* ``verify_backup`` checks the file hash, ``PRAGMA integrity_check`` and the
  fingerprint against the manifest.
* ``restore_ledger`` verifies first, restores through a temporary file and an
  atomic ``os.replace``, keeps the replaced file as ``*.pre-restore-<stamp>``
  and refuses (unless ``allow_history_loss``) to restore a backup that lacks
  forecasts present in the current store.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from stages.stage12.reliability import ReliabilityError, sha256_file
from stages.stage9.prospective_ledger import LedgerError, ProspectiveLedger


def _summary(path: Path) -> Dict[str, Any]:
    with ProspectiveLedger(path, read_only=True) as ledger:
        report = ledger.integrity_report()
        keys = sorted(p["fixture_key"] for p in ledger.predictions())
    return {"integrity_ok": report["ok"], "problems": report["problems"],
            "fingerprint": report["fingerprint"], "challenger_fingerprint": report["challenger_fingerprint"],
            "champion_forecasts": report["champion_forecasts"], "outcomes": report["outcomes"],
            "challenger_forecasts": report["challenger_forecasts"], "fixture_keys": keys}


def backup_ledger(source: str | Path, backup_dir: str | Path, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    src = Path(source)
    if not src.is_file():
        raise ReliabilityError(f"ledger not found: {src}")
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S%fZ")
    out_dir = Path(backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / f".ledger_{stamp}.sqlite.tmp"
    try:
        source_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        target_conn = sqlite3.connect(tmp)
        with target_conn:
            source_conn.backup(target_conn)
        source_conn.close()
        target_conn.close()
    except sqlite3.DatabaseError as exc:
        tmp.unlink(missing_ok=True)
        raise ReliabilityError(f"cannot back up ledger: {exc}") from exc
    summary = _summary(tmp)
    if not summary["integrity_ok"]:
        tmp.unlink(missing_ok=True)
        raise ReliabilityError(f"source ledger failed integrity checks: {summary['problems']}")
    digest = sha256_file(tmp)
    final = out_dir / f"ledger_{stamp}_{digest[:16]}.sqlite"
    os.replace(tmp, final)
    manifest = {"backup": final.name, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": str(src), "sha256": digest, **{k: v for k, v in summary.items() if k != "problems"}}
    (out_dir / f"{final.name}.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify_backup(backup: str | Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
    path = Path(backup)
    problems = []
    if not path.is_file():
        return {"ok": False, "problems": ["backup file missing"]}
    if sha256_file(path) != manifest["sha256"]:
        problems.append("backup SHA-256 does not match manifest")
    try:
        summary = _summary(path)
    except (LedgerError, sqlite3.DatabaseError) as exc:
        return {"ok": False, "problems": problems + [f"backup unreadable: {exc}"]}
    if not summary["integrity_ok"]:
        problems.extend(summary["problems"])
    if summary["fingerprint"] != manifest["fingerprint"]:
        problems.append("champion-forecast fingerprint does not match manifest")
    return {"ok": not problems, "problems": problems}


def restore_ledger(backup: str | Path, manifest: Dict[str, Any], destination: str | Path, *,
                   allow_history_loss: bool = False) -> Dict[str, Any]:
    check = verify_backup(backup, manifest)
    if not check["ok"]:
        raise ReliabilityError(f"refusing to restore: {check['problems']}")
    dest = Path(destination)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    preserved = None
    if dest.exists():
        try:
            current = _summary(dest)
            lost = sorted(set(current["fixture_keys"]) - set(manifest["fixture_keys"]))
        except (LedgerError, sqlite3.DatabaseError):
            lost = []  # current file is unreadable: nothing recoverable to protect
        if lost and not allow_history_loss:
            raise ReliabilityError(f"refusing to restore: backup lacks {len(lost)} forecasts present in the "
                                   f"current ledger (e.g. {lost[:2]}); pass allow_history_loss to override")
        preserved = dest.with_name(f"{dest.name}.pre-restore-{stamp}")
        shutil.copy2(dest, preserved)
    tmp = dest.with_name(f".{dest.name}.restore-{stamp}.tmp")
    shutil.copy2(backup, tmp)
    if sha256_file(tmp) != manifest["sha256"]:
        tmp.unlink(missing_ok=True)
        raise ReliabilityError("copy of backup does not match manifest; destination untouched")
    os.replace(tmp, dest)
    after = _summary(dest)
    if after["fingerprint"] != manifest["fingerprint"] or not after["integrity_ok"]:
        raise ReliabilityError("restored ledger failed verification")
    return {"restored_to": str(dest), "preserved_previous": str(preserved) if preserved else None,
            "fingerprint": after["fingerprint"], "champion_forecasts": after["champion_forecasts"]}
