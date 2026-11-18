from datetime import datetime, timezone

import pandas as pd
import pytest

from stages.stage1.data_store import (
    DataStore,
    DataValidationError,
    Record,
    ingest_results_frame,
)


def test_result_is_not_visible_on_match_day_and_is_visible_after_safe_cutoff():
    frame = pd.DataFrame(
        [("2024-08-17", "Arsenal", "Wolves", 2, 0)],
        columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"],
    )
    store = DataStore()

    assert ingest_results_frame(store, frame) == 1
    assert len(store.snapshot(datetime(2024, 8, 17, 23, 59, tzinfo=timezone.utc)).filter("result")) == 0
    assert len(store.snapshot(datetime(2024, 8, 18, 12, 0, tzinfo=timezone.utc)).filter("result")) == 1


def test_reimport_is_idempotent():
    frame = pd.DataFrame(
        [("2024-08-17", "Arsenal", "Wolves", 2, 0)],
        columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"],
    )
    store = DataStore()

    assert ingest_results_frame(store, frame) == 1
    assert ingest_results_frame(store, frame) == 0
    assert len(store.all_records()) == 1


def test_conflicting_source_revision_is_not_silently_overwritten():
    store = DataStore()
    when = datetime(2024, 8, 18, 12, tzinfo=timezone.utc)
    first = Record("result", "2024-08-17|arsenal|wolves", when,
                   {"date": "2024-08-17", "home": "arsenal", "away": "wolves", "fthg": 2, "ftag": 0},
                   "test-source")
    revised = Record("result", "2024-08-17|arsenal|wolves", when,
                     {"date": "2024-08-17", "home": "arsenal", "away": "wolves", "fthg": 1, "ftag": 0},
                     "test-source")

    assert store.add(first) is True
    assert store.add(first) is False
    with pytest.raises(ValueError, match="conflicting record"):
        store.add(revised)
    assert len(store.all_records()) == 1


def test_explicit_availability_must_be_timezone_aware():
    frame = pd.DataFrame(
        [("2024-08-17", "Arsenal", "Wolves", 2, 0, "2024-08-17 20:00:00")],
        columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "available_at"],
    )
    with pytest.raises(DataValidationError, match="timezone-aware"):
        ingest_results_frame(DataStore(), frame)


def test_explicit_utc_availability_is_respected():
    frame = pd.DataFrame(
        [("2024-08-17", "Arsenal", "Wolves", 2, 0, "2024-08-17T22:00:00Z")],
        columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "available_at"],
    )
    store = DataStore()

    assert ingest_results_frame(store, frame) == 1
    assert len(store.snapshot(datetime(2024, 8, 17, 21, 59, tzinfo=timezone.utc)).filter("result")) == 0
    assert len(store.snapshot(datetime(2024, 8, 17, 22, 0, tzinfo=timezone.utc)).filter("result")) == 1


def test_negative_scores_and_self_fixtures_fail_closed():
    bad_score = pd.DataFrame(
        [("2024-08-17", "Arsenal", "Wolves", -1, 0)],
        columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"],
    )
    self_fixture = pd.DataFrame(
        [("2024-08-17", "Arsenal", "Arsenal", 1, 0)],
        columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"],
    )

    with pytest.raises(DataValidationError, match="non-negative integers"):
        ingest_results_frame(DataStore(), bad_score)
    with pytest.raises(DataValidationError, match="cannot play itself"):
        ingest_results_frame(DataStore(), self_fixture)
