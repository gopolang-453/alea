"""Regression tests for the legacy in-memory Stage 1 feature store."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import (
    DataStore,
    DataValidationError,
    Record,
    ingest_results_frame,
)


def test_add_is_idempotent_for_same_source_record():
    store = DataStore()
    record = Record(
        kind="result",
        fixture_key="2023-08-11|burnley|manchester united",
        available_at=datetime(2023, 8, 12, tzinfo=timezone.utc),
        payload={"fthg": 0, "ftag": 3},
        source="unit-test",
    )
    store.add(record)
    store.add(record)
    assert len(store.all_records()) == 1


def test_conflicting_duplicate_record_is_rejected():
    store = DataStore()
    timestamp = datetime(2023, 8, 12, tzinfo=timezone.utc)
    store.add(Record("result", "fixture-1", timestamp, {"fthg": 0, "ftag": 3}, "source"))
    with pytest.raises(DataValidationError, match="conflicting duplicate"):
        store.add(Record("result", "fixture-1", timestamp, {"fthg": 1, "ftag": 3}, "source"))


def test_date_only_ingestion_uses_next_day_availability():
    store = DataStore()
    frame = pd.DataFrame([{
        "Date": "2023-08-11",
        "HomeTeam": "Burnley",
        "AwayTeam": "Man Utd",
        "FTHG": 0,
        "FTAG": 3,
    }])
    assert ingest_results_frame(store, frame) == 1
    record = store.all_records()[0]
    assert record.available_at == datetime(2023, 8, 12, tzinfo=timezone.utc)
    assert ingest_results_frame(store, frame) == 0
    assert len(store.all_records()) == 1


@pytest.mark.parametrize("offset", [0, 3, 23.99])
def test_same_day_availability_offsets_are_rejected(offset):
    store = DataStore()
    frame = pd.DataFrame([{
        "Date": "2023-08-11", "HomeTeam": "Burnley", "AwayTeam": "Man Utd",
        "FTHG": 0, "FTAG": 3,
    }])
    with pytest.raises(DataValidationError, match="at least 24 hours"):
        ingest_results_frame(store, frame, available_offset_hours=offset)


@pytest.mark.parametrize("bad_score", [-1, 1.5, "unknown", None])
def test_malformed_scores_are_rejected(bad_score):
    store = DataStore()
    frame = pd.DataFrame([{
        "Date": "2023-08-11", "HomeTeam": "Burnley", "AwayTeam": "Man Utd",
        "FTHG": bad_score, "FTAG": 3,
    }])
    with pytest.raises(DataValidationError):
        ingest_results_frame(store, frame)
