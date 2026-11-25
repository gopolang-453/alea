#!/usr/bin/env python3
"""Commit gate for the weekly workflow: is AFTER a safe append-only successor of BEFORE?

Exit 0 only if the updated ledger passes the integrity report, keeps every
append-only trigger and preserves every pre-existing row unchanged. Exit 1
otherwise. The JSON verdict is printed and optionally written to --report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage12.ledger_ops import verify_append_only_update  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="snapshot taken before the run")
    parser.add_argument("--after", required=True, help="ledger after the run")
    parser.add_argument("--report", default=None)
    args = parser.parse_args(argv)
    verdict = verify_append_only_update(args.before, args.after)
    text = json.dumps(verdict, indent=2, sort_keys=True)
    print(text)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
