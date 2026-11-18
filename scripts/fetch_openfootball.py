#!/usr/bin/env python3
"""Fetch licensed OpenFootball Premier League season JSON and import to SQLite.

Example:
  python scripts/fetch_openfootball.py --seasons 2019-20 2020-21 2021-22

Raw data and the SQLite database are stored locally and are not committed.
OpenFootball is a volunteer-maintained historical source, not a live-score SLA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from stages.stage1.persistent_store import PersistentDataStore

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master"
DEFAULT_SEASONS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24"]


def fetch_season(season: str, destination: Path) -> tuple[Path, str]:
    url = f"{BASE_URL}/{season}/en.1.json"
    response = requests.get(url, timeout=(10, 45))
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"empty response from {url}")
    # Parse before writing so an upstream HTML/error response is never saved as data.
    document = response.json()
    if not isinstance(document, dict) or not isinstance(document.get("matches"), list):
        raise RuntimeError(f"unexpected OpenFootball schema for {season}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(response.content)
    temporary.replace(destination)
    digest = hashlib.sha256(response.content).hexdigest()
    manifest = {
        "season": season,
        "source_url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "sha256": digest,
        "match_rows": len(document["matches"]),
        "licence": "CC0 1.0 Universal (verify upstream before redistribution)",
    }
    destination.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return destination, url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS)
    parser.add_argument("--data-dir", default="data/raw/openfootball")
    parser.add_argument("--database", default="data/alea.sqlite")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    db_path = Path(args.database)
    total_added = 0
    with PersistentDataStore(db_path) as store:
        for season in args.seasons:
            path, url = fetch_season(season, data_dir / f"{season}.json")
            added = store.ingest_openfootball_file(
                path, season=season, competition="Premier League", source_url=url
            )
            total_added += added
            print(f"{season}: {added} new results imported ({path})")
        print(f"Total new results: {total_added}")
        print(f"Database: {db_path}")
        print(f"Store fingerprint: {store.fingerprint()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
