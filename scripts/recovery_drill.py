#!/usr/bin/env python3
"""Stage 12 recovery drill: integrity -> backup -> corruption -> detect -> restore -> verify.

Operates on COPIES inside a scratch directory, never on the original artifact.
Exits non-zero if any of the six checks fails. Writes a JSON report.

Checks:
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
import shutil
import sys
import tempfile
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact", default=str(ROOT / "alea_predictor_v2_4_1.py"))
    parser.add_argument("--expected-sha256", default=FROZEN_SHA)
    parser.add_argument("--report", default=None, help="optional JSON report path")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="alea_drill_") as tmp:
        report = run_drill(Path(args.artifact), args.expected_sha256, Path(tmp))
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
