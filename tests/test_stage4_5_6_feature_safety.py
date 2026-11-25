"""Tests for Stage 4–6 imports and explicit missing/experimental feature states."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import DataStore, Record
from stages.stage4 import xg_features
from stages.stage5 import player_features
from stages.stage6 import context_features


def dt(day):
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def test_stage_modules_import_from_repository_root():
    assert callable(xg_features.team_xg_history)
    assert callable(player_features.unavailable_impact)
    assert callable(context_features.weather_for_fixture)


def test_missing_xg_is_none_not_a_fake_zero():
    store = DataStore()
    assert xg_features.team_xg_history(store, "Arsenal", dt("2024-01-10T00:00:00")) is None
    assert xg_features.fixture_xg(store, "2024-01-05|arsenal|chelsea",
                                  dt("2024-01-10T00:00:00")) is None


def test_xg_history_uses_match_date_not_late_arrival_order():
    store = DataStore()
    # Older match arrived later than the newer match.
    store.add(Record(
        "xg", "2024-01-01|arsenal|chelsea", dt("2024-01-09T00:00:00"),
        {"date": "2024-01-01", "home": "arsenal", "away": "chelsea",
         "home_xg": 0.4, "away_xg": 1.1}, "test",
    ))
    store.add(Record(
        "xg", "2024-01-05|arsenal|liverpool", dt("2024-01-06T00:00:00"),
        {"date": "2024-01-05", "home": "arsenal", "away": "liverpool",
         "home_xg": 2.0, "away_xg": 0.5}, "test",
    ))
    history = xg_features.team_xg_history(
        store, "Arsenal", dt("2024-01-10T00:00:00"), n=1
    )
    assert history["matches"] == 1
    assert history["xg_for"] == pytest.approx(2.0)
    assert history["xg_against"] == pytest.approx(0.5)


def test_player_impact_is_not_invented_without_a_trained_model():
    impact = player_features.player_impact_stub("Player", "goalkeeper", "injured")
    assert impact["impact"] is None
    assert impact["impact_status"] == "not_estimated_untrained_placeholder"

    store = DataStore()
    store.add(Record(
        "injury", "fixture-context|arsenal", dt("2024-01-01T00:00:00"),
        {"team": "Arsenal", "player": "Player", "position": "goalkeeper",
         "status": "injured"}, "test",
    ))
    aggregate = player_features.unavailable_impact(
        store, "Arsenal", dt("2024-01-02T00:00:00")
    )
    assert aggregate["count"] == 1
    assert aggregate["total_impact"] is None
