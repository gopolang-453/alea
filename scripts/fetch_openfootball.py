#!/usr/bin/env python3
"""Fetch licensed OpenFootball Premier League JSON and import results to SQLite.

Example:
  python scripts/fetch_openfootball.py --seasons 2019-20 2020-21 2021-22

Raw source files and the SQLite database remain local and are not committed.
OpenFootball is a volunteer-maintained historical source, not a live-score SLA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import PersistentDataStore, ingest_results_frame

BASE_URL = "https://raw.githubusercontent.com/openfootball/football.json/master"
DEFAULT_SEASONS = ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24"]


def season_window(season: str) -> tuple[date, date]:
    """Inclusive date range a Premier League season may occupy.

    "2019-20" -> 1 Aug 2019 .. 31 Aug 2020 (the COVID restart ran to 26 Jul 2020).
    """
    try:
        start_year = int(season[:4])
        end_suffix = int(season[5:7])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"season must look like 2019-20, got {season!r}") from exc
    if len(season) != 7 or season[4] != "-" or (start_year + 1) % 100 != end_suffix:
        raise ValueError(f"season must look like 2019-20, got {season!r}")
    return date(start_year, 8, 1), date(start_year + 1, 8, 31)


def _checked_match_date(raw, season: str, index: int, corrections: list) -> str:
    """Validate a match date against its season; repair only a provable year typo.

    Upstream 2019-20 lists 66 post-restart matches (Jun-Jul 2020) with the year
    2019. Left alone, those results would sit in training data a year before
    they were played. A date is corrected only when it lies before the season
    window in the season's first calendar year and moving it forward exactly
    one year lands inside the window;
    every correction is returned for the manifest. Anything else fails closed.
    """
    try:
        parsed = date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"match {index} has unreadable date {raw!r}") from exc
    start, end = season_window(season)
    if start <= parsed <= end:
        return parsed.isoformat()
    try:
        shifted = parsed.replace(year=parsed.year + 1)
    except ValueError:
        shifted = None
    # Only the observed pattern is repaired: a Jan-Jul date written with the
    # season's first year instead of its second year.
    if (
        parsed.year == start.year and parsed < start
        and shifted is not None and start <= shifted <= end
    ):
        corrections.append({"index": index, "listed": parsed.isoformat(), "corrected": shifted.isoformat()})
        return shifted.isoformat()
    raise ValueError(
        f"match {index} date {parsed.isoformat()} is outside season {season} "
        f"({start.isoformat()}..{end.isoformat()})"
    )


def parse_openfootball_file(
    path: str | Path, season: str, *, corrections: list | None = None
) -> pd.DataFrame:
    """Parse completed matches. ``corrections`` (if given) receives date repairs."""
    file_path = Path(path)
    corrections = [] if corrections is None else corrections
    try:
        document = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read OpenFootball JSON {file_path}: {exc}") from exc
    matches = document.get("matches")
    if not isinstance(matches, list):
        raise ValueError("OpenFootball document must contain a matches list")
    rows = []
    for index, match in enumerate(matches):
        if not isinstance(match, dict):
            raise ValueError(f"match {index} is not an object")
        score_block = match.get("score")
        if score_block is None:
            score_block = {}
        if isinstance(score_block, list):
            # From 2025-26 upstream writes some results (observed: only 0-0)
            # as a bare two-element list instead of {"ft": [h, a]}. Treat a
            # bare list as the full-time score; anything else stays malformed.
            score_block = {"ft": score_block}
        if not isinstance(score_block, dict):
            raise ValueError(f"match {index} has malformed score object")
        score = score_block.get("ft")
        if score is None:
            continue
        if not isinstance(score, list) or len(score) != 2:
            raise ValueError(f"match {index} has malformed full-time score")
        rows.append({
            "Date": _checked_match_date(match.get("date"), season, index, corrections),
            "Season": season,
            "HomeTeam": match.get("team1"),
            "AwayTeam": match.get("team2"),
            "FTHG": score[0],
            "FTAG": score[1],
        })
    if not rows:
        raise ValueError(f"no completed matches found in {file_path}")
    return pd.DataFrame(rows)


def fetch_season(season: str, destination: Path) -> tuple[Path, str]:
    url = f"{BASE_URL}/{season}/en.1.json"
    response = requests.get(url, timeout=(10, 45))
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"empty response from {url}")
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
    parser.add_argument("--database", default="data/alea_openfootball.sqlite")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    database = Path(args.database)
    database.parent.mkdir(parents=True, exist_ok=True)
    total_added = 0
    with PersistentDataStore(database) as store:
        for season in args.seasons:
            path, url = fetch_season(season, data_dir / f"{season}.json")
            corrections: list = []
            frame = parse_openfootball_file(path, season, corrections=corrections)
            if corrections:
                manifest_path = path.with_suffix(".manifest.json")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["date_corrections"] = corrections
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                print(f"{season}: corrected {len(corrections)} upstream year-typo dates (see manifest)")
            added = ingest_results_frame(
                store, frame, source=url, available_offset_hours=36.0
            )
            total_added += added
            print(f"{season}: {added} new results imported from {url}")
        print(f"Total new results: {total_added}")
        print(f"Database: {database}")
        print(f"Store fingerprint: {store.fingerprint()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
