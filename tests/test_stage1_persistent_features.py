"""Persistent Stage 1 feature records can coexist with results and feed later stages."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.persistent_store import DataValidationError, PersistentDataStore
from stages.stage3.team_features import elo_ratings
from stages.stage4.xg_features import fixture_xg, team_xg_history
from stages.stage5.player_features import injuries_for_team
from stages.stage6.context_features import weather_for_fixture


def test_persistent_feature_records_are_timestamped_idempotent_and_visible_to_stages(tmp_path):
    db = tmp_path / "features.sqlite"
    fixture = "2024-01-01|arsenal|chelsea"
    before = datetime(2024, 1, 2, tzinfo=timezone.utc)
    after = datetime(2024, 1, 3, tzinfo=timezone.utc)

    with PersistentDataStore(db) as store:
        assert store.add_result(
            competition="Premier League", season="2023-24",
            match_date=date(2024, 1, 1), home="Arsenal", away="Chelsea",
            home_goals=2, away_goals=0, source="test-results",
        )
        result_fingerprint = store.fingerprint()

        xg_payload = {
            "date": "2024-01-01", "home": "arsenal", "away": "chelsea",
            "home_xg": 1.7, "away_xg": 0.4,
        }
        assert store.add_feature_record(
            kind="xg", fixture_key=fixture, available_at=after,
            event_date=date(2024, 1, 1), payload=xg_payload,
            source="test-xg", source_id="fixture-1",
        )
        assert not store.add_feature_record(
            kind="xg", fixture_key=fixture, available_at=after,
            event_date=date(2024, 1, 1), payload=xg_payload,
            source="test-xg", source_id="fixture-1",
        )
        assert store.fingerprint() != result_fingerprint

        # Same fixture can have different feature kinds/sources; result remains intact.
        assert store.add_feature_record(
            kind="injury", fixture_key=fixture, available_at=before,
            event_date=date(2024, 1, 1),
            payload={"team": "Arsenal", "player": "Example Player", "status": "injured"},
            source="test-injuries", source_id="player-1",
        )
        assert store.add_feature_record(
            kind="weather", fixture_key=fixture, available_at=before,
            event_date=date(2024, 1, 1), payload={"temperature_c": 12},
            source="test-weather", source_id="fixture-1",
        )

        assert fixture_xg(store, fixture, before) is None
        assert fixture_xg(store, fixture, after) == {"home_xg": 1.7, "away_xg": 0.4}
        assert team_xg_history(store, "Arsenal", after, n=1)["xg_for"] == 1.7
        assert injuries_for_team(store, "Arsenal", before)[0]["player"] == "Example Player"
        assert weather_for_fixture(store, fixture, before) == {"temperature_c": 12}
        results = store.snapshot(after).to_results_frame()
        assert len(results) == 1
        assert int(results.iloc[0]["FTHG"]) == 2

        with pytest.raises(DataValidationError, match="conflicting duplicate feature"):
            store.add_feature_record(
                kind="xg", fixture_key=fixture, available_at=after,
                event_date=date(2024, 1, 1),
                payload={**xg_payload, "home_xg": 2.2},
                source="test-xg", source_id="fixture-1",
            )


def test_feature_records_require_timezone_aware_availability_and_finite_json(tmp_path):
    with PersistentDataStore(tmp_path / "invalid.sqlite") as store:
        with pytest.raises(DataValidationError, match="timezone-aware"):
            store.add_feature_record(
                kind="xg", fixture_key="fixture", available_at=datetime(2024, 1, 1),
                payload={"home_xg": 1.0, "away_xg": 0.5}, source="test",
            )
        with pytest.raises(ValueError):
            store.add_feature_record(
                kind="xg", fixture_key="fixture",
                available_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                payload={"home_xg": float("nan")}, source="test",
            )


def test_stage3_elo_calculator_accepts_persistent_result_snapshots(tmp_path):
    with PersistentDataStore(tmp_path / "elo.sqlite") as store:
        store.add_result(
            competition="Premier League", season="2023-24",
            match_date=date(2024, 1, 1), home="Arsenal", away="Chelsea",
            home_goals=3, away_goals=0, source="test-results",
        )
        ratings = elo_ratings(
            store, datetime(2024, 1, 3, tzinfo=timezone.utc),
            initial_rating=1500, k_factor=20, home_advantage=0,
        )
        assert set(ratings) == {"arsenal", "chelsea"}
        assert ratings["arsenal"] > 1500
        assert ratings["chelsea"] < 1500
