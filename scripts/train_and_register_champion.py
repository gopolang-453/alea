#!/usr/bin/env python3
"""Seed or register a model into the Stage 10 registry.

This script only REGISTERS. It does not auto-promote unless the registry
currently has no champion and the caller supplies complete promotion evidence.

There is deliberately no --force promotion path.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", default="results/model_registry")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--metrics-json", required=True,
                        help="JSON file containing the exact metrics dict required by ModelRegistry")
    parser.add_argument("--metadata-json", default=None)
    parser.add_argument("--promote-if-no-champion", action="store_true",
                        help="If registry has no champion, attempt promote after register")
    args = parser.parse_args()

    with open(args.metrics_json) as f:
        metrics = json.load(f)
    metadata = {}
    if args.metadata_json:
        with open(args.metadata_json) as f:
            metadata = json.load(f)
    metadata.setdefault("registered_via", "train_and_register_champion.py")
    metadata.setdefault("run_at_utc", datetime.now(timezone.utc).isoformat())

    registry = ModelRegistry(args.registry_root)
    try:
        record = registry.register(args.version, args.artifact, metrics, metadata=metadata)
        print(f"Registered: {record['version']} sha256={record['sha256'][:16]}...")
    except RegistryError as exc:
        print(f"REGISTER FAILED: {exc}", file=sys.stderr)
        return 1

    if args.promote_if_no_champion and registry.champion() is None:
        try:
            outcome = registry.promote(args.version, min_holdout_samples=1)
            print(f"Seeded as champion: {outcome}")
        except RegistryError as exc:
            print(f"Could not seed champion (evidence incomplete): {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
