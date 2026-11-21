#!/usr/bin/env python3
"""CLI prediction service (Stage 11).

Refuses predictions for fixtures whose kickoff is already in the past
(information cutoff enforcement).
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

from stages.stage11.prediction_service import PredictionService


def main() -> int:
    parser = argparse.ArgumentParser(description="ALEA prediction CLI")
    parser.add_argument("home", help="Home team")
    parser.add_argument("away", help="Away team")
    parser.add_argument("--kickoff", help="ISO kickoff time (UTC). Required for cutoff check.")
    parser.add_argument("--registry", default="results/model_registry.json")
    args = parser.parse_args()

    svc = PredictionService(registry_path=Path(args.registry))
    try:
        result = svc.predict(args.home, args.away, kickoff=args.kickoff)
        print(json.dumps(result, indent=2))
        return 0
    except ValueError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
