#!/usr/bin/env python3
"""Stage 10 automation entrypoint: refresh data → retrain → evaluate vs champion → promote only if better.

Designed to be run on a schedule (cron / launchd / Task Scheduler).
One invocation = one decision. Not a long-running daemon.

Example (daily 06:00):
  0 6 * * * cd /path/to/alea && python scripts/refresh_and_retrain.py >> logs/refresh.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage10.automation import ModelRegistry
from stages.stage10.champion_comparison import compare_candidate_to_champion, should_promote


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh → retrain → promote-only-if-better")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate but never promote")
    parser.add_argument("--registry", default="results/model_registry.json", help="Path to registry")
    args = parser.parse_args()

    registry = ModelRegistry(Path(args.registry))
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting refresh_and_retrain")

    # 1. Refresh / ingest (Stage 1 path). In real env this would call OpenFootball fetch.
    # Here we assume the store is already current or the caller has refreshed it.
    print("Data refresh step (caller responsibility or Stage 1 ingest)")

    # 2. Train candidate
    print("Training candidate...")
    # Placeholder: real implementation would call the MLE / Dixon-Coles fit on current store
    candidate = {
        "version": f"candidate-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
        "metrics": {},  # filled by evaluation
        "artifact_path": None,
    }

    # 3. Evaluate candidate vs current champion on identical fixtures
    comparison = compare_candidate_to_champion(registry, candidate)
    print(json.dumps(comparison, indent=2, default=str))

    # 4. Promote only if better
    if args.dry_run:
        print("Dry-run: skipping promotion decision")
        return 0

    if should_promote(comparison):
        registry.promote(candidate, evidence=comparison)
        print(f"Promoted. Champion: {candidate['version']}")
        return 0
    else:
        registry.register_candidate(candidate, evidence=comparison, promoted=False)
        print("Candidate did not beat champion — refused promotion. Champion unchanged.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
