#!/usr/bin/env python3
"""Command-line access to frozen forecasts (same logic as the HTTP API).

Examples:
  python scripts/predict_cli.py upcoming --days 7
  python scripts/predict_cli.py fixture "2026-11-28|arsenal|manchester city"
  python scripts/predict_cli.py history --team arsenal
  python scripts/predict_cli.py health

Forecasts are produced only by the scheduled pipeline
(``scripts/run_prospective_forecast.py``); this tool never fits a model and
never forecasts a match that has started.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage11.api import ApiError, ForecastAPI  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", default=str(ROOT / "results/prospective/ledger.sqlite"))
    parser.add_argument("--registry", default=str(ROOT / "config/model_registry.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("upcoming")
    up.add_argument("--days", default="7")
    up.add_argument("--include-challengers", action="store_true")
    fx = sub.add_parser("fixture")
    fx.add_argument("key")
    hi = sub.add_parser("history")
    hi.add_argument("--team")
    hi.add_argument("--status")
    sub.add_parser("health")
    sub.add_parser("evaluation")
    args = parser.parse_args(argv)
    api = ForecastAPI(args.ledger, args.registry, root=ROOT)
    try:
        if args.command == "upcoming":
            q = {"days": args.days, "include_challengers": str(args.include_challengers).lower()}
            status, body, _ = api.route("GET", "/v1/predictions/upcoming", urlencode(q))
        elif args.command == "fixture":
            status, body, _ = api.route("GET", f"/v1/predictions/{args.key}", "")
        elif args.command == "history":
            q = {k: v for k, v in (("team", args.team), ("status", args.status)) if v}
            status, body, _ = api.route("GET", "/v1/predictions/history", urlencode(q))
        elif args.command == "health":
            status, body, _ = api.route("GET", "/health", "")
        else:
            status, body, _ = api.route("GET", "/v1/evaluation", "")
    except ApiError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(body, indent=2, default=str))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
