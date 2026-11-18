"""Stage 3 temporal-safety and feature-contract tests."""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import DataStore, Record
from stages.stage3.team_features import (
    elo_ratings,
    fixture_team_features,
    head_to_head,
    team_form,
)


def stamp(day):
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def add_result(store, day, home, away, hg, ag, available_day=None):
    store.add(Record(
        "result", f"{day}|{home}|{away}",
        stamp(f"{available_day or day}T23:00:00"),
        {"date": day, "home": home, "away": away, "fthg": hg, "ftag": ag},
        "test",
    ))


def test_features_exclude_same_day_and_not_yet_available_results():
    store = DataStore()
    add_result(store, "2024-01-01", "Arsenal", "Chelsea", 2, 0)
    add_result(store, "2024-01-05", "Chelsea", "Liverpool", 1, 1)
    add_result(store, "2024-01-10", "Arsenal", "Liverpool", 0, 4)

    features = fixture_team_features(
        store, "Arsenal", "Chelsea", date(2024, 1, 10), stamp("2024-01-10T12:00:00")
    )
    # The 10 January result is not yet available at noon and is also on fixture date.
    assert features["home_form"]["matches"] == 1
    assert features["away_form"] is None
    assert features["head_to_head"]["matches"] == 1


def test_form_and_h2h_return_none_when_no_history():
    store = DataStore()
    assert team_form(store, "Arsenal", stamp("2024-01-10T12:00:00")) is None
    assert head_to_head(store, "Arsenal", "Chelsea", stamp("2024-01-10T12:00:00")) is None


def test_elo_ratings_are_deterministic_for_same_day_batch():
    first = DataStore()
    second = DataStore()
    matches = [
        ("2024-01-01", "Arsenal", "Chelsea", 2, 0),
        ("2024-01-01", "Liverpool", "Everton", 1, 1),
        ("2024-01-02", "Chelsea", "Liverpool", 0, 1),
    ]
    for row in matches:
        add_result(first, *row)
    for row in reversed(matches):
        add_result(second, *row)

    as_of = stamp("2024-01-05T00:00:00")
    assert elo_ratings(first, as_of) == pytest.approx(elo_ratings(second, as_of))


def test_fixture_features_flag_new_teams_and_do_not_invent_form():
    store = DataStore()
    features = fixture_team_features(
        store, "New Team", "Arsenal", date(2024, 1, 10), stamp("2024-01-09T12:00:00")
    )
    assert features["home_elo"] == 1500.0
    assert features["home_elo_prior_only"] is True
    assert features["away_elo_prior_only"] is True
    assert features["home_form"] is None
    assert features["away_form"] is None


def test_invalid_elo_parameters_are_rejected():
    with pytest.raises(ValueError, match="finite"):
        elo_ratings(DataStore(), stamp("2024-01-10T00:00:00"), home_advantage=float("nan"))
