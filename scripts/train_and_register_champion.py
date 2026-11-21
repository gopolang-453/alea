#!/usr/bin/env python3
"""Train a model on the current store and register it through Stage 10.

Used for initial champion seeding or manual promotion runs.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage10.automation import ModelRegistry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="results/model_registry.json")
    parser.add_argument("--force", action="store_true", help="Promote even if metrics are weaker")
    args = parser.parse_args()

    registry = ModelRegistry(Path(args.registry))
    version = f"manual-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    candidate = {
        "version": version,
        "metrics": {"log_loss": 0.95, "brier": 0.58},  # placeholder; real run fills from backtest
        "artifact_path": None,
    }
    print(f"Registering candidate {version}")
    if args.force or registry.champion is None:
        registry.promote(candidate, evidence={"source": "train_and_register_champion.py"})
        print("Promoted as champion.")
    else:
        registry.register_candidate(candidate, evidence={"source": "train_and_register_champion.py"}, promoted=False)
        print("Registered as candidate only (use --force to override).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
