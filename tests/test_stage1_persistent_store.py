"""SQLite persistence and source-revision tests for the canonical Stage 1 store."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import (
    DataStore, DataValidationError, PersistentDataStore, Record,
    ingest_results_frame,
)


def sample_frame():
    return pd.DataFrame([{
        "Date": "2023-08-11", "Season": "2023-24",
        "HomeTeam": "Burnley", "AwayTeam": "Man Utd", "FTHG": 0, "FTAG": 3,
    }])


def test_sqlite_store_persists_reopens_and_reimports_idempotently(tmp_path):
    db = tmp_path / "nested" / "alea.sqlite"
    with PersistentDataStore(db) as store:
        assert ingest_results_frame(store, sample_frame(), source="openfootball") == 1
        fingerprint = store.fingerprint()
        assert ingest_results_frame(store, sample_frame(), source="openfootball") == 0
        assert len(store.all_records()) == 1

    with PersistentDataStore(db) as reopened:
        assert len(reopened.all_records()) == 1
        assert reopened.fingerprint() == fingerprint
        snapshot = reopened.snapshot(datetime(2023, 8, 12, 12, tzinfo=timezone.utc))
        frame = snapshot.to_results_frame()
        assert len(frame) == 1
        assert frame.iloc[0]["Season"] == "2023-24"


def test_same_source_revision_conflict_is_rejected(tmp_path):
    db = tmp_path / "conflict.sqlite"
    timestamp = datetime(2023, 8, 12, 12, tzinfo=timezone.utc)
    first = Record(
        "result", "2023-08-11|burnley|manchester united", timestamp,
        {"date": "2023-08-11", "season": "2023-24", "home": "burnley",
         "away": "manchester united", "fthg": 0, "ftag": 3}, "openfootball",
    )
    revised = Record(
        "result", "2023-08-11|burnley|manchester united", timestamp,
        {"date": "2023-08-11", "season": "2023-24", "home": "burnley",
         "away": "manchester united", "fthg": 1, "ftag": 3}, "openfootball",
    )
    with PersistentDataStore(db) as store:
        assert store.add(first) is True
        assert store.add(first) is False
        with pytest.raises(ValueError, match="conflicting record"):
            store.add(revised)
        assert len(store.all_records()) == 1


def test_date_only_results_require_conservative_availability(tmp_path):
    frame = sample_frame()
    with pytest.raises(DataValidationError, match="at least 24 hours"):
        ingest_results_frame(DataStore(), frame, available_offset_hours=3.0)


@pytest.mark.parametrize("bad_score", [-1, 1.5, "unknown", None, 31])
def test_invalid_score_values_fail_closed(bad_score):
    frame = sample_frame()
    # Cast to object so invalid values can reach validation (pandas 2.2+ refuses
    # assigning non-int into int64 columns before our code can fail closed).
    frame["FTHG"] = frame["FTHG"].astype(object)
    frame.loc[0, "FTHG"] = bad_score
    with pytest.raises(DataValidationError):
        ingest_results_frame(DataStore(), frame)


def test_persistent_import_rolls_back_entire_batch_on_invalid_row(tmp_path):
    frame = pd.concat([
        sample_frame(),
        pd.DataFrame([{
            "Date": "2023-08-12", "Season": "2023-24",
            "HomeTeam": "Arsenal", "AwayTeam": "Chelsea", "FTHG": -1, "FTAG": 0,
        }]),
    ], ignore_index=True)
    with PersistentDataStore(tmp_path / "atomic.sqlite") as store:
        with pytest.raises(DataValidationError):
            ingest_results_frame(store, frame, source="openfootball")
        assert store.all_records() == []


def test_explicit_timestamp_does_not_require_date_only_offset(tmp_path):
    frame = sample_frame()
    frame["available_at"] = "2023-08-11T22:00:00Z"
    with PersistentDataStore(tmp_path / "explicit.sqlite") as store:
        assert ingest_results_frame(
            store, frame, source="source-with-time", available_offset_hours=0
        ) == 1
