"""Stage 3 — leakage-safe team ratings and recent-result features.

These are features, not a complete probability model. The Elo K-factor,
home advantage and form window are configurable and must be fixed/tuned using
development data only. No feature uses same-calendar-day results for a fixture.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..stage1.data_store import DataStore, canonical_team


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return dt


def _rows(store: DataStore, as_of: datetime, before_date: Optional[date] = None) -> List[dict]:
    cutoff = _aware(as_of)
    records = store.snapshot(cutoff).filter("result")
    rows = []
    for record in records:
        p = record.payload
        event_date = date.fromisoformat(str(p["date"])[:10])
        if before_date is not None and event_date >= before_date:
            continue
        rows.append({
            "date": event_date,
            "home": canonical_team(p["home"]),
            "away": canonical_team(p["away"]),
            "home_goals": int(p["fthg"]),
            "away_goals": int(p["ftag"]),
            "available_at": record.available_at,
        })
    rows.sort(key=lambda r: (r["date"], r["home"], r["away"]))
    return rows


def elo_ratings(
    store: DataStore,
    as_of: datetime,
    *,
    before_date: Optional[date] = None,
    initial_rating: float = 1500.0,
    k_factor: float = 20.0,
    home_advantage: float = 50.0,
) -> Dict[str, float]:
    """Calculate ratings from results available by as_of, in date-batched order."""
    _aware(as_of)
    if k_factor <= 0 or initial_rating <= 0:
        raise ValueError("k_factor and initial_rating must be positive")
    rows = _rows(store, as_of, before_date)
    ratings: Dict[str, float] = {}

    def rating(team: str) -> float:
        return ratings.get(team, float(initial_rating))

    index = 0
    while index < len(rows):
        match_date = rows[index]["date"]
        batch = []
        while index < len(rows) and rows[index]["date"] == match_date:
            batch.append(rows[index])
            index += 1

        # All matches on a date use ratings from before that date.
        deltas: Dict[str, float] = {}
        for match in batch:
            home, away = match["home"], match["away"]
            rh, ra = rating(home), rating(away)
            expected_home = 1.0 / (1.0 + 10.0 ** (-((rh + home_advantage) - ra) / 400.0))
            if match["home_goals"] > match["away_goals"]:
                actual_home = 1.0
            elif match["home_goals"] == match["away_goals"]:
                actual_home = 0.5
            else:
                actual_home = 0.0
            change = k_factor * (actual_home - expected_home)
            deltas[home] = deltas.get(home, 0.0) + change
            deltas[away] = deltas.get(away, 0.0) - change
        for team, delta in deltas.items():
            ratings[team] = rating(team) + delta
    return ratings


def team_form(
    store: DataStore,
    team: str,
    as_of: datetime,
    *,
    before_date: Optional[date] = None,
    n: int = 5,
) -> Optional[Dict[str, float]]:
    """Last-n form from prior completed matches; None when no history exists."""
    if n < 1:
        raise ValueError("n must be at least 1")
    team_name = canonical_team(team)
    matches = []
    for row in _rows(store, as_of, before_date):
        if row["home"] == team_name:
            gf, ga = row["home_goals"], row["away_goals"]
        elif row["away"] == team_name:
            gf, ga = row["away_goals"], row["home_goals"]
        else:
            continue
        points = 3.0 if gf > ga else 1.0 if gf == ga else 0.0
        matches.append((row["date"], points, gf, ga))
    matches = matches[-n:]
    if not matches:
        return None
    count = len(matches)
    points = sum(row[1] for row in matches)
    goals_for = sum(row[2] for row in matches)
    goals_against = sum(row[3] for row in matches)
    return {
        "matches": float(count),
        "points_per_game": points / count,
        "goals_for_per_game": goals_for / count,
        "goals_against_per_game": goals_against / count,
        "goal_difference_per_game": (goals_for - goals_against) / count,
    }


def head_to_head(
    store: DataStore,
    home: str,
    away: str,
    as_of: datetime,
    *,
    before_date: Optional[date] = None,
    n: int = 5,
) -> Optional[Dict[str, float]]:
    """Recent direct meetings before the fixture date; no data returns None."""
    if n < 1:
        raise ValueError("n must be at least 1")
    home_name, away_name = canonical_team(home), canonical_team(away)
    matches = [
        row for row in _rows(store, as_of, before_date)
        if {row["home"], row["away"]} == {home_name, away_name}
    ][-n:]
    if not matches:
        return None
    home_points = []
    for row in matches:
        home_goals = row["home_goals"] if row["home"] == home_name else row["away_goals"]
        away_goals = row["away_goals"] if row["home"] == home_name else row["home_goals"]
        home_points.append(3.0 if home_goals > away_goals else 1.0 if home_goals == away_goals else 0.0)
    return {
        "matches": float(len(matches)),
        "home_team_points_per_game": sum(home_points) / len(home_points),
        "home_team_unbeaten_rate": sum(p > 0 for p in home_points) / len(home_points),
    }


def fixture_team_features(
    store: DataStore,
    home: str,
    away: str,
    fixture_date: date,
    as_of: datetime,
) -> Dict[str, Any]:
    """Collect team features for one fixture using only eligible earlier results."""
    if isinstance(fixture_date, datetime) or not isinstance(fixture_date, date):
        raise ValueError("fixture_date must be a date")
    ratings = elo_ratings(store, as_of, before_date=fixture_date)
    home_name, away_name = canonical_team(home), canonical_team(away)
    home_form = team_form(store, home_name, as_of, before_date=fixture_date)
    away_form = team_form(store, away_name, as_of, before_date=fixture_date)
    h2h = head_to_head(store, home_name, away_name, as_of, before_date=fixture_date)
    home_rating = ratings.get(home_name, 1500.0)
    away_rating = ratings.get(away_name, 1500.0)
    return {
        "home_elo": home_rating,
        "away_elo": away_rating,
        "elo_difference": home_rating - away_rating,
        "home_elo_prior_only": home_name not in ratings,
        "away_elo_prior_only": away_name not in ratings,
        "home_form": home_form,
        "away_form": away_form,
        "head_to_head": h2h,
        "feature_cutoff": _aware(as_of).isoformat(),
        "fixture_date": fixture_date.isoformat(),
    }
