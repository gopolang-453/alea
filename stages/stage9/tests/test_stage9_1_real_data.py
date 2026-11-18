"""Stage 9.1 smoke test using the real Stage 1 persistent-store interface.

This test is deliberately offline and uses a tiny fixture. Full historical
integration is a separate opt-in data-fetch/backtest command; no local CSV
files are assumed to exist in a clean checkout.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.persistent_store import PersistentDataStore


def test_stage91_ingests_a_played_fixture_and_rejects_same_day_visibility(tmp_path):
    source = tmp_path / "one-season.json"
    source.write_text(json.dumps({
        "name": "Premier League",
        "matches": [{
            "date": "2023-08-11",
            "team1": "Burnley",
            "team2": "Manchester United",
            "round": "Matchday 1",
            "score": {"ft": [0, 3]},
        }],
    }), encoding="utf-8")

    with PersistentDataStore(tmp_path / "stage9.sqlite") as store:
        assert store.ingest_openfootball_file(source, season="2023-24") == 1
        assert store.ingest_openfootball_file(source, season="2023-24") == 0
        assert len(store.snapshot(
            datetime(2023, 8, 11, 23, 59, tzinfo=timezone.utc)
        ).to_results_frame()) == 0
        frame = store.snapshot(
            datetime(2023, 8, 12, 0, 0, tzinfo=timezone.utc)
        ).to_results_frame()
        assert len(frame) == 1
        assert int(frame.iloc[0]["FTHG"]) == 0
        assert int(frame.iloc[0]["FTAG"]) == 3
