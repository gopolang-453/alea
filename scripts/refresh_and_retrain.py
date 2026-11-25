#!/usr/bin/env python3
"""Stage 10 — one refresh → train candidate → identical-fixture comparison → promote-only-if-better.

Uses the authoritative ModelRegistry in stages/stage10/automation.py.
Never promotes on placeholder metrics. Never uses an unsafe force path.
Fails closed on missing evidence, insufficient samples, or comparison errors.

Synthetic data runs must be labelled as such and must never be presented as
real Premier League validation.
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

from stages.stage10.automation import ModelRegistry, RegistryError
from stages.stage10.champion_comparison import (
    ComparisonError,
    compare_candidate_to_champion,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", default="results/model_registry")
    parser.add_argument("--artifact", required=True, help="Path to candidate model artifact file")
    parser.add_argument("--version", required=True, help="Candidate version string")
    parser.add_argument("--data-csv", help="Path to match data CSV (Date,HomeTeam,AwayTeam,FTHG,FTAG)")
    parser.add_argument("--champion-params-json", help="Path to frozen champion params JSON (must contain as_of_date)")
    parser.add_argument("--min-holdout", type=int, default=100)
    parser.add_argument("--brier-tolerance", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--synthetic-label", action="store_true",
                        help="Mark this run as synthetic (required when using non-real data)")
    args = parser.parse_args()

    registry = ModelRegistry(args.registry_root)
    champion = registry.champion()

    if champion is None:
        print("No champion registered. Use train_and_register_champion.py to seed the first champion.")
        return 2

    if not args.data_csv or not args.champion_params_json:
        print("ERROR: --data-csv and --champion-params-json are required for a real comparison.", file=sys.stderr)
        return 2

    import pandas as pd
    data = pd.read_csv(args.data_csv)
    with open(args.champion_params_json) as f:
        champion_params = json.load(f)

    try:
        result = compare_candidate_to_champion(data, champion_params)
    except ComparisonError as exc:
        print(f"COMPARISON REJECTED: {exc}", file=sys.stderr)
        return 3

    baseline_metrics = champion["metrics"]
    metrics = result.to_registry_metrics(baseline_metrics)
    metadata = {
        "comparison_baseline_version": champion["version"],
        "evidence": result.to_evidence_dict(),
        "synthetic": bool(args.synthetic_label),
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    print(json.dumps({"metrics": metrics, "evidence": result.to_evidence_dict()}, indent=2))

    if args.dry_run:
        print("Dry-run: not registering or promoting.")
        return 0

    try:
        registry.register(args.version, args.artifact, metrics, metadata=metadata)
    except RegistryError as exc:
        print(f"REGISTER FAILED: {exc}", file=sys.stderr)
        return 4

    try:
        outcome = registry.promote(
            args.version,
            min_holdout_samples=args.min_holdout,
            brier_tolerance=args.brier_tolerance,
        )
        print(f"PROMOTED: {outcome}")
        return 0
    except RegistryError as exc:
        print(f"PROMOTION REJECTED (champion unchanged): {exc}")
        return 0  # candidate registered for audit; champion left intact


if __name__ == "__main__":
    sys.exit(main())
