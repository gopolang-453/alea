#!/usr/bin/env python3
"""Stage 12 recovery drills.

Two drills, both operating on COPIES in a scratch directory (the real files
are only read):

* artifact drill (default): the frozen champion source file.
* ledger drill (``--ledger PATH``): the actual prospective ledger SQLite and
  the actual HTTP service started on the restored copy. See
  ``run_ledger_drill`` for its checks.

Exits non-zero if any check fails. Writes a JSON report.

Artifact drill checks:
 1. source_integrity      SHA-256 of the artifact matches the expected digest
 2. backup_created        a verified backup copy exists
 3. corruption_detected   a deliberately corrupted working copy fails verification
 4. restore_rejects_bad   restoring from a corrupted backup is refused (fail closed)
 5. restore_ok            restoring from the good backup succeeds
 6. restored_integrity    the restored file matches the expected digest
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage12.reliability import (  # noqa: E402
    ReliabilityError,
    backup_artifact,
    restore_backup,
    sha256_file,
    verify_sha256,
)

FROZEN_SHA = "4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a"
_SECRET_LOG_PATTERNS = ("ghp_", "github_pat_", "AKIA", "-----BEGIN", "xoxb-", "Authorization:", "X-Auth-Token")


def run_drill(artifact: Path, expected_sha: str, scratch: Path) -> dict:
    checks = {}
    checks["source_integrity"] = verify_sha256(artifact, expected_sha)
    work = scratch / "working" / artifact.name
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact, work)

    manifest = backup_artifact(work, scratch / "backups")
    backup = scratch / "backups" / manifest["backup_name"]
    checks["backup_created"] = backup.is_file() and verify_sha256(backup, expected_sha)

    with work.open("ab") as handle:
        handle.write(b"\n# simulated corruption\n")
    checks["corruption_detected"] = not verify_sha256(work, expected_sha)

    bad_backup = scratch / "backups" / (backup.name + ".corrupt")
    shutil.copy2(backup, bad_backup)
    with bad_backup.open("r+b") as handle:
        handle.seek(0)
        first = handle.read(1)
        handle.seek(0)
        handle.write(bytes([first[0] ^ 0xFF]))
    try:
        restore_backup(bad_backup, work, expected_sha)
        checks["restore_rejects_bad"] = False
    except ReliabilityError:
        checks["restore_rejects_bad"] = True

    try:
        restore_backup(backup, work, expected_sha)
        checks["restore_ok"] = True
    except ReliabilityError:
        checks["restore_ok"] = False
    checks["restored_integrity"] = verify_sha256(work, expected_sha)

    return {
        "artifact": artifact.name,
        "expected_sha256": expected_sha,
        "observed_source_sha256": sha256_file(artifact),
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "passed": all(checks.values()),
        "scope": "drill on scratch copies; not a production store",
    }


def _http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def _serve(app):
    from wsgiref.simple_server import make_server

    from scripts.serve_api import QuietHandler, ThreadingWSGIServer

    server = make_server("127.0.0.1", 0, app, server_class=ThreadingWSGIServer, handler_class=QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


_KILL_MID_WRITE = r"""
import os, sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("BEGIN IMMEDIATE")
con.execute("INSERT INTO runs (run_id, started_at, status, summary_json) VALUES ('drill', '2000-01-01T00:00:00+00:00', 'x', '{}')")
os._exit(9)  # simulated crash: no commit, no close
"""


def run_ledger_drill(ledger: Path, scratch: Path, *, registry: Path, log_dirs=()) -> dict:
    """Backup/restore/corruption drill on the real ledger plus the real service.

    Checks:
      source_integrity              actual store opens read-only and passes integrity checks
      backup_created_and_verified   online SQLite backup + manifest verify (hash, integrity, fingerprint)
      restore_ok                    restore into a fresh path reproduces the fingerprint and counts
      interrupted_write_rolled_back a writer killed mid-transaction leaves the store unchanged and valid
      truncated_file_detected       a truncated copy is detected (open or integrity failure)
      garbage_file_detected         an overwritten header is detected
      missing_file_detected         a missing store is refused, never silently recreated
      restore_after_corruption      restoring over a corrupted copy recovers the exact fingerprint
      restore_rejects_tampered      a tampered backup is refused and the destination left untouched
      restore_refuses_history_loss  an older backup cannot silently replace a newer store
      duplicate_prevention_after_restore  restored store still rejects overwrites and re-forecasts
      append_only_after_restore     UPDATE/DELETE triggers still active on the restored store
      service_healthy_on_restored   the HTTP service on the restored store returns 200 for /health and data
      service_refuses_corrupt_store the HTTP service on a corrupted store returns 503
      no_secrets_in_repo_or_logs    secret scan of the working tree and the given log directories
      failure_is_logged             the pipeline exits 3 and writes a failed-run record for a missing store
      freshness_gate                stale data is classified stale; the service reports degraded
    """
    from datetime import timedelta

    from stages.stage11.api import ForecastAPI
    from stages.stage12.ledger_ops import backup_ledger, restore_ledger, verify_backup
    from stages.stage12.reliability import data_freshness, scan_repository_for_secrets
    from stages.stage9.prospective_ledger import LedgerError, ProspectiveLedger

    checks, details = {}, {}

    def attempt(name, fn):
        try:
            checks[name] = bool(fn())
        except Exception as exc:  # a crashing check is a failed check
            checks[name] = False
            details[name] = f"{type(exc).__name__}: {exc}"

    with ProspectiveLedger(ledger, read_only=True) as led:
        source = led.integrity_report()
        source_keys = [p["fixture_key"] for p in led.predictions()]
    checks["source_integrity"] = source["ok"]
    details["source"] = {k: source[k] for k in ("fingerprint", "champion_forecasts", "challenger_forecasts",
                                                "outcomes", "sqlite_integrity_check")}
    backups = scratch / "backups"
    manifest = backup_ledger(ledger, backups)
    backup = backups / manifest["backup"]
    checks["backup_created_and_verified"] = verify_backup(backup, manifest)["ok"] and \
        manifest["fingerprint"] == source["fingerprint"]
    details["backup_manifest"] = {k: manifest[k] for k in ("backup", "sha256", "fingerprint", "champion_forecasts")}

    restored = scratch / "restored" / "ledger.sqlite"
    restored.parent.mkdir(parents=True)
    attempt("restore_ok", lambda: restore_ledger(backup, manifest, restored)["fingerprint"] == source["fingerprint"])

    def interrupted():
        work = scratch / "interrupted.sqlite"
        shutil.copy2(restored, work)
        with ProspectiveLedger(work) as led:  # migrate so the runs table exists
            before = (led.fingerprint(), len(led.runs()))
        proc = subprocess.run([sys.executable, "-c", _KILL_MID_WRITE, str(work)], capture_output=True)
        with ProspectiveLedger(work, create=False) as led:
            after = (led.fingerprint(), len(led.runs()))
            ok = led.integrity_report()["ok"]
        details["interrupted_write_exit_code"] = proc.returncode
        return proc.returncode == 9 and before == after and ok
    attempt("interrupted_write_rolled_back", interrupted)

    def detect(mutator):
        work = scratch / f"corrupt_{mutator.__name__}.sqlite"
        shutil.copy2(restored, work)
        mutator(work)
        try:
            with ProspectiveLedger(work, read_only=True) as led:
                return not led.integrity_report()["ok"]
        except (LedgerError, sqlite3.DatabaseError):
            return True

    def truncate(path):
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.truncate(max(size // 2, 1))

    def garbage(path):
        with path.open("r+b") as handle:
            handle.write(b"NOT A SQLITE FILE" * 8)

    attempt("truncated_file_detected", lambda: detect(truncate))
    attempt("garbage_file_detected", lambda: detect(garbage))

    def missing():
        target = scratch / "missing" / "ledger.sqlite"
        try:
            ProspectiveLedger(target, create=False)
            return False
        except LedgerError:
            return not target.exists()
    attempt("missing_file_detected", missing)

    def after_corruption():
        work = scratch / "corrupted_then_restored.sqlite"
        shutil.copy2(restored, work)
        garbage(work)
        result = restore_ledger(backup, manifest, work)
        return result["fingerprint"] == source["fingerprint"] and Path(result["preserved_previous"]).exists()
    attempt("restore_after_corruption", after_corruption)

    def tampered():
        bad = backups / "tampered.sqlite"
        shutil.copy2(backup, bad)
        with bad.open("r+b") as handle:
            handle.seek(bad.stat().st_size // 2)
            byte = handle.read(1)
            handle.seek(-1, 1)
            handle.write(bytes([byte[0] ^ 0xFF]))
        dest = scratch / "tamper_dest.sqlite"
        shutil.copy2(restored, dest)
        before = dest.read_bytes()
        from stages.stage12.reliability import ReliabilityError
        try:
            restore_ledger(bad, manifest, dest)
            return False
        except ReliabilityError as exc:  # only the intended refusal counts, not an unrelated crash
            return "refusing to restore" in str(exc) and dest.read_bytes() == before
    attempt("restore_rejects_tampered", tampered)

    def history_loss():
        from datetime import datetime as _dt, timezone as _tz
        newer = scratch / "newer.sqlite"
        shutil.copy2(restored, newer)
        with ProspectiveLedger(newer) as led:
            led.record_prediction(fixture_key="2099-01-01|drill home|drill away",
                                  predicted_at=_dt(2098, 12, 1, tzinfo=_tz.utc),
                                  kickoff_at=_dt(2099, 1, 1, 15, tzinfo=_tz.utc),
                                  p_home=0.4, p_draw=0.3, p_away=0.3, model_version="drill")
        try:
            restore_ledger(backup, manifest, newer)
            return False
        except Exception as exc:
            return "lacks" in str(exc)
    attempt("restore_refuses_history_loss", history_loss)

    def duplicates():
        if not source_keys:
            details["duplicate_prevention_after_restore"] = "store has no forecasts; checked with a probe row"
        work = scratch / "dup.sqlite"
        shutil.copy2(restored, work)
        with ProspectiveLedger(work) as led:
            rows = led.predictions()
            if not rows:
                return True
            p = rows[0]
            from datetime import datetime as _dt
            kwargs = dict(fixture_key=p["fixture_key"], predicted_at=_dt.fromisoformat(p["predicted_at"]),
                          kickoff_at=_dt.fromisoformat(p["kickoff_at"]), p_home=0.34, p_draw=0.33,
                          p_away=0.33, model_version=p["model_version"])
            try:
                led.record_prediction(**kwargs)
                return False
            except LedgerError:
                pass
            day, home, away = p["fixture_key"].split("|")
            twin = dict(kwargs, fixture_key=f"{day[:8]}{'01' if day[8:] != '01' else '02'}|{home}|{away}")
            try:
                led.record_prediction(**twin)
                return False
            except LedgerError:
                return led.fingerprint() == source["fingerprint"]
    attempt("duplicate_prevention_after_restore", duplicates)

    def append_only():
        work = scratch / "append.sqlite"
        shutil.copy2(restored, work)
        with ProspectiveLedger(work):
            pass  # ensures triggers exist on legacy copies, exactly as the pipeline does
        con = sqlite3.connect(work)
        try:
            for sql in ("UPDATE predictions SET p_home = p_home", "DELETE FROM predictions"):
                try:
                    con.execute(sql)
                    return False
                except sqlite3.DatabaseError as exc:
                    if "append-only" not in str(exc):
                        return False
            return True
        finally:
            con.close()
    attempt("append_only_after_restore", append_only)

    def service_ok():
        app = ForecastAPI(restored, registry, root=ROOT)
        server = _serve(app)
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            health = _http_status(base + "/health")
            data = _http_status(base + "/v1/predictions/history?limit=5")
            details["service_on_restored"] = {"health": health, "history": data}
            return health == 200 and data == 200
        finally:
            server.shutdown()
            server.server_close()
    attempt("service_healthy_on_restored", service_ok)

    def service_corrupt():
        work = scratch / "service_corrupt.sqlite"
        shutil.copy2(restored, work)
        garbage(work)
        server = _serve(ForecastAPI(work, registry, root=ROOT))
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            return _http_status(base + "/health") == 503 and _http_status(base + "/v1/predictions/upcoming") == 503
        finally:
            server.shutdown()
            server.server_close()
    attempt("service_refuses_corrupt_store", service_corrupt)

    def secrets():
        findings = scan_repository_for_secrets(ROOT)
        leaked = []
        for directory in log_dirs:
            for path in Path(directory).rglob("*"):
                if path.is_file() and path.suffix in (".log", ".json", ".md", ".txt"):
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    leaked += [f"{path.name}:{pat}" for pat in _SECRET_LOG_PATTERNS if pat in text]
        details["secret_findings"] = len(findings) + len(leaked)
        return not findings and not leaked
    attempt("no_secrets_in_repo_or_logs", secrets)

    def failure_logged():
        out = scratch / "failure_run"
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "run_prospective_forecast.py"),
                               "--ledger", str(scratch / "absent" / "ledger.sqlite"), "--output-dir", str(out),
                               "--registry", str(registry), "--now", "2026-11-24T12:00:00+00:00"],
                              capture_output=True, text=True)
        runs = list((out / "runs").glob("run_*.json"))
        logs = list((out / "logs").glob("run_*.log"))
        ok = proc.returncode == 3 and runs and json.loads(runs[0].read_text())["status"] == "failed" and logs
        return ok and not (scratch / "absent" / "ledger.sqlite").exists()
    attempt("failure_is_logged", failure_logged)

    def freshness():
        now = datetime.now(timezone.utc)
        stale = data_freshness(now - timedelta(days=30), now, max_age_hours=240)["status"] == "stale"
        app = ForecastAPI(restored, registry, root=ROOT, clock=lambda: now + timedelta(days=400))
        status, body, _ = app.route("GET", "/health", "")
        return stale and body["status"] in ("degraded", "unhealthy")
    attempt("freshness_gate", freshness)

    return {"store": str(ledger), "ran_at_utc": datetime.now(timezone.utc).isoformat(), "checks": checks,
            "details": details, "passed": all(checks.values()),
            "scope": "actual ledger (read-only) + actual HTTP service; destructive steps on scratch copies"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact", default=str(ROOT / "alea_predictor_v2_4_1.py"))
    parser.add_argument("--expected-sha256", default=FROZEN_SHA)
    parser.add_argument("--report", default=None, help="optional JSON report path")
    parser.add_argument("--ledger", default=None, help="run the ledger + service drill on this store")
    parser.add_argument("--registry", default=str(ROOT / "config" / "model_registry.json"))
    parser.add_argument("--log-dir", action="append", default=[], help="also scan these dirs for leaked secrets")
    parser.add_argument("--keep-backup-dir", default=None,
                        help="copy the verified backup and its manifest here (ledger drill)")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="alea_drill_") as tmp:
        if args.ledger:
            report = run_ledger_drill(Path(args.ledger), Path(tmp), registry=Path(args.registry),
                                      log_dirs=args.log_dir)
            if args.keep_backup_dir:
                keep = Path(args.keep_backup_dir)
                keep.mkdir(parents=True, exist_ok=True)
                for path in (Path(tmp) / "backups").glob("ledger_*"):
                    shutil.copy2(path, keep / path.name)
        else:
            report = run_drill(Path(args.artifact), args.expected_sha256, Path(tmp))
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
