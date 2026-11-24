#!/usr/bin/env python3
"""Operator commands for the prospective ledger (append-only; nothing is ever edited).

  status     per-forecast status (settled / pending / overdue / postponed / void / conflict ...)
  integrity  integrity report; exit 1 if it fails
  issues     data-quality issues
  event      record POSTPONED / RESCHEDULED / CANCELLED / ABANDONED / AWARDED / VOID for a fixture
  correct    resolve a result conflict with an operator correction (original rows are kept)
  backup     verified online backup + manifest
  restore    verified restore from a backup + manifest (keeps the replaced file)

Examples:
  python scripts/ledger_admin.py --ledger L.sqlite event "2026-11-28|arsenal|manchester city" \
      POSTPONED --source "premierleague.com statement" --detail "weather"
  python scripts/ledger_admin.py --ledger L.sqlite event KEY RESCHEDULED --new-kickoff 2027-01-14T19:30:00+00:00 --source ...
  python scripts/ledger_admin.py --ledger L.sqlite correct KEY 2 1 --reason "BBC + Wikipedia rev 123" --operator me
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage9.prospective_ledger import EVENT_TYPES, LedgerError, ProspectiveLedger  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default=str(ROOT / "results/prospective/ledger.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("integrity")
    sub.add_parser("issues")
    ev = sub.add_parser("event")
    ev.add_argument("fixture_key")
    ev.add_argument("event_type", choices=[e for e in EVENT_TYPES if e != "OVERDUE"])
    ev.add_argument("--source", required=True, help="where the information came from (required)")
    ev.add_argument("--detail", default="")
    ev.add_argument("--new-kickoff", default=None, help="ISO UTC kickoff (RESCHEDULED only)")
    co = sub.add_parser("correct")
    co.add_argument("fixture_key")
    co.add_argument("home_goals", type=int)
    co.add_argument("away_goals", type=int)
    co.add_argument("--reason", required=True)
    co.add_argument("--operator", required=True)
    bk = sub.add_parser("backup")
    bk.add_argument("--dir", required=True)
    rs = sub.add_parser("restore")
    rs.add_argument("backup")
    rs.add_argument("--manifest", default=None, help="default: <backup>.manifest.json")
    rs.add_argument("--allow-history-loss", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd in ("backup", "restore"):
        from stages.stage12.ledger_ops import backup_ledger, restore_ledger
        from stages.stage12.reliability import ReliabilityError
        try:
            if a.cmd == "backup":
                out = backup_ledger(a.ledger, a.dir)
                out.pop("fixture_keys", None)
            else:
                manifest = json.loads(Path(a.manifest or f"{a.backup}.manifest.json").read_text())
                out = restore_ledger(a.backup, manifest, a.ledger, allow_history_loss=a.allow_history_loss)
        except ReliabilityError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(out, indent=2))
        return 0

    read_only = a.cmd in ("status", "integrity", "issues")
    try:
        ledger = ProspectiveLedger(a.ledger, create=False, read_only=read_only)
    except LedgerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    with ledger:
        if a.cmd == "status":
            now = _now()
            for p in ledger.predictions():
                st = ledger.fixture_status(p["fixture_key"], now)
                score = f"{st.home_goals}-{st.away_goals}" if st.outcome else ""
                print(f"{st.status:10s} {p['fixture_key']:55s} {score:5s} {st.reason}")
            return 0
        if a.cmd == "integrity":
            rep = ledger.integrity_report()
            print(json.dumps(rep, indent=2))
            return 0 if rep["ok"] else 1
        if a.cmd == "issues":
            for i in ledger.issues():
                print(json.dumps(i))
            return 0
        try:
            if a.cmd == "event":
                if ledger.get_prediction(a.fixture_key) is None:
                    print(f"ERROR: no champion forecast for {a.fixture_key}", file=sys.stderr)
                    return 1
                ko = datetime.fromisoformat(a.new_kickoff) if a.new_kickoff else None
                added = ledger.record_event(a.fixture_key, a.event_type, recorded_at=_now(), source=a.source,
                                            detail=a.detail, new_kickoff_at=ko)
                print("recorded" if added else "already recorded (no change)")
            else:
                ledger.record_correction(a.fixture_key, a.home_goals, a.away_goals, reason=a.reason,
                                         operator=a.operator, recorded_at=_now())
                print("correction recorded")
        except LedgerError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(ledger.fixture_status(a.fixture_key, _now()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
