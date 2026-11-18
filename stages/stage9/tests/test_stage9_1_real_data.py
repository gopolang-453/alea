"""Stage 9.1 offline integration test using the canonical Stage 1 store."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_openfootball import parse_openfootball_file
from stages.stage1.data_store import PersistentDataStore, ingest_results_frame


def test_stage91_openfootball_parse_import_and_safe_availability(tmp_path):
    source = tmp_path / "one-season.json"
    source.write_text(json.dumps({
        "name": "Premier League",
        "matches": [
            {
                "date": "2023-08-11",
                "team1": "Burnley",
                "team2": "Manchester United",
                "round": "Matchday 1",
                "score": {"ft": [0, 3]},
            },
            {
                "date": "2023-08-12",
                "team1": "Arsenal",
                "team2": "Nottingham Forest",
                "round": "Matchday 1",
                "score": {},
            },
        ],
    }), encoding="utf-8")

    frame = parse_openfootball_file(source, "2023-24")
    assert len(frame) == 1
    assert frame.iloc[0]["Season"] == "2023-24"

    with PersistentDataStore(tmp_path / "stage9.sqlite") as store:
        assert ingest_results_frame(
            store, frame, source="openfootball-test", available_offset_hours=36.0
        ) == 1
        assert ingest_results_frame(
            store, frame, source="openfootball-test", available_offset_hours=36.0
        ) == 0
        assert len(store.all_records()) == 1
        assert len(store.snapshot(
            datetime(2023, 8, 11, 23, 59, tzinfo=timezone.utc)
        ).to_results_frame()) == 0
        snapshot = store.snapshot(
            datetime(2023, 8, 12, 12, 0, tzinfo=timezone.utc)
        ).to_results_frame()
        assert len(snapshot) == 1
        assert snapshot.iloc[0]["Season"] == "2023-24"
        assert int(snapshot.iloc[0]["FTHG"]) == 0
        assert int(snapshot.iloc[0]["FTAG"]) == 3
