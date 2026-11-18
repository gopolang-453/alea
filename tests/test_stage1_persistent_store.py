"""Offline regression tests for the persistent Stage 1 store."""

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.persistent_store import DataValidationError, PersistentDataStore


def test_import_is_idempotent_and_survives_reopen(tmp_path):
    db = tmp_path / "alea.sqlite"
    with PersistentDataStore(db) as store:
        assert store.add_result(
            competition="Premier League", season="2023-24",
            match_date=date(2023, 8, 11), home="Burnley", away="Man Utd",
            home_goals=0, away_goals=3, source="unit-test",
        ) is True
        assert store.add_result(
            competition="Premier League", season="2023-24",
            match_date=date(2023, 8, 11), home="Burnley", away="Manchester United",
            home_goals=0, away_goals=3, source="unit-test",
        ) is False
        assert len(store.all_records()) == 1
        fingerprint = store.fingerprint()

    with PersistentDataStore(db) as reopened:
        assert len(reopened.all_records()) == 1
        assert reopened.fingerprint() == fingerprint
        frame = reopened.snapshot(datetime(2023, 8, 13, tzinfo=timezone.utc)).to_results_frame()
        assert len(frame) == 1
        assert frame.iloc[0]["HomeTeam"] == "burnley"
        assert frame.iloc[0]["AwayTeam"] == "manchester united"


def test_conflicting_duplicate_fails_closed(tmp_path):
    with PersistentDataStore(tmp_path / "conflict.sqlite") as store:
        store.add_result(
            competition="Premier League", season="2023-24",
            match_date=date(2023, 8, 11), home="Burnley", away="Man Utd",
            home_goals=0, away_goals=3, source="source-a",
        )
        with pytest.raises(DataValidationError, match="conflicting duplicate"):
            store.add_result(
                competition="Premier League", season="2023-24",
                match_date=date(2023, 8, 11), home="Burnley", away="Man Utd",
                home_goals=1, away_goals=3, source="source-b",
            )


def test_date_only_result_is_not_available_on_match_day(tmp_path):
    with PersistentDataStore(tmp_path / "cutoff.sqlite") as store:
        store.add_result(
            competition="Premier League", season="2023-24",
            match_date=date(2023, 8, 11), home="Burnley", away="Man Utd",
            home_goals=0, away_goals=3, source="unit-test",
        )
        same_day = store.snapshot(datetime(2023, 8, 11, 23, 59, tzinfo=timezone.utc))
        next_day = store.snapshot(datetime(2023, 8, 12, 0, 0, tzinfo=timezone.utc))
        assert len(same_day.to_results_frame()) == 0
        assert len(next_day.to_results_frame()) == 1


@pytest.mark.parametrize("home,away,hg,ag", [
    ("", "Arsenal", 1, 0),
    ("Arsenal", "Arsenal", 1, 0),
    ("Arsenal", "Chelsea", -1, 0),
    ("Arsenal", "Chelsea", 1.5, 0),
    ("Arsenal", "Chelsea", 1, None),
])
def test_invalid_records_are_rejected(tmp_path, home, away, hg, ag):
    with PersistentDataStore(tmp_path / "invalid.sqlite") as store:
        with pytest.raises(DataValidationError):
            store.add_result(
                competition="Premier League", season="2023-24",
                match_date=date(2023, 8, 11), home=home, away=away,
                home_goals=hg, away_goals=ag, source="unit-test",
            )


def test_openfootball_import_skips_unplayed_fixtures_and_is_idempotent(tmp_path):
    source = tmp_path / "season.json"
    source.write_text(json.dumps({
        "name": "Premier League",
        "matches": [
            {"date": "2023-08-11", "team1": "Burnley", "team2": "Man Utd",
             "round": "Matchday 1", "score": {"ft": [0, 3]}},
            {"date": "2023-08-12", "team1": "Arsenal", "team2": "Nottingham Forest",
             "round": "Matchday 1", "score": {}},
        ],
    }), encoding="utf-8")

    with PersistentDataStore(tmp_path / "openfootball.sqlite") as store:
        assert store.ingest_openfootball_file(source, season="2023-24") == 1
        assert store.ingest_openfootball_file(source, season="2023-24") == 0
        assert len(store.all_records()) == 1



def test_explicit_availability_cannot_precede_match_date(tmp_path):
    with PersistentDataStore(tmp_path / "early.sqlite") as store:
        with pytest.raises(DataValidationError, match="before its match date"):
            store.add_result(
                competition="Premier League", season="2023-24",
                match_date=date(2023, 8, 11), home="Burnley", away="Man Utd",
                home_goals=0, away_goals=3, source="unit-test",
                available_at=datetime(2023, 8, 10, 23, 0, tzinfo=timezone.utc),
            )


@pytest.mark.parametrize("match_date", [None, "", "not-a-date"])
def test_openfootball_missing_or_invalid_date_is_rejected(tmp_path, match_date):
    source = tmp_path / "bad-date.json"
    source.write_text(json.dumps({
        "matches": [{
            "date": match_date, "team1": "Burnley", "team2": "Manchester United",
            "score": {"ft": [0, 3]},
        }],
    }), encoding="utf-8")
    with PersistentDataStore(tmp_path / "bad-date.sqlite") as store:
        with pytest.raises(DataValidationError, match="match date"):
            store.ingest_openfootball_file(source, season="2023-24")


def test_malformed_score_container_is_rejected(tmp_path):
    source = tmp_path / "bad-score.json"
    source.write_text(json.dumps({
        "matches": [{
            "date": "2023-08-11", "team1": "Burnley", "team2": "Manchester United",
            "score": ["0", "3"],
        }],
    }), encoding="utf-8")
    with PersistentDataStore(tmp_path / "bad-score.sqlite") as store:
        with pytest.raises(DataValidationError, match="score object"):
            store.ingest_openfootball_file(source, season="2023-24")
