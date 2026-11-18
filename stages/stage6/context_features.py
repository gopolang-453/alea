"""
ALEA Stage 6 — Advanced contextual factors
------------------------------------------
Experimental feature contracts.
Every function is leakage-safe (explicit as_of) and fail-closed
(returns None or empty when the required data is absent).
No feature is assumed to help; each must be evaluated later.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from data_store import DataStore, Record, canonical_team


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt


def weather_for_fixture(
    store: DataStore,
    fixture_key: str,
    as_of: datetime,
) -> Optional[Dict[str, Any]]:
    """Return weather record if known by as_of, else None."""
    as_of = _ensure_aware(as_of)
    snap = store.snapshot(as_of)
    for r in snap.filter("weather"):
        if r.fixture_key == fixture_key:
            return r.payload
    return None


def venue_info(
    store: DataStore,
    team: str,
    as_of: datetime,
) -> Optional[Dict[str, Any]]:
    """Stadium / neutral / altitude info known by as_of."""
    as_of = _ensure_aware(as_of)
    team_c = canonical_team(team)
    snap = store.snapshot(as_of)
    for r in snap.filter("venue"):
        if canonical_team(r.payload.get("team", "")) == team_c:
            return r.payload
    return None


def referee_tendencies(
    store: DataStore,
    referee: str,
    as_of: datetime,
) -> Optional[Dict[str, float]]:
    """
    Cards / penalties per game for a referee, computed only from
    matches whose results were available before as_of.
    Returns None if fewer than 5 prior matches.
    """
    as_of = _ensure_aware(as_of)
    snap = store.snapshot(as_of)
    matches = [r for r in snap.filter("referee_match") if r.payload.get("referee") == referee]
    if len(matches) < 5:
        return None
    yellows = sum(r.payload.get("yellows", 0) for r in matches)
    reds = sum(r.payload.get("reds", 0) for r in matches)
    pens = sum(r.payload.get("penalties", 0) for r in matches)
    n = len(matches)
    return {
        "matches": n,
        "yellows_per_game": yellows / n,
        "reds_per_game": reds / n,
        "penalties_per_game": pens / n,
    }


def manager_change_flag(
    store: DataStore,
    team: str,
    as_of: datetime,
    lookback_days: int = 60,
) -> bool:
    """True if a manager change for the team was recorded within lookback_days before as_of."""
    as_of = _ensure_aware(as_of)
    team_c = canonical_team(team)
    snap = store.snapshot(as_of)
    for r in snap.filter("manager_change"):
        if canonical_team(r.payload.get("team", "")) != team_c:
            continue
        delta = (as_of - r.available_at).days
        if 0 <= delta <= lookback_days:
            return True
    return False


def travel_distance_km(
    store: DataStore,
    home: str,
    away: str,
    as_of: datetime,
) -> Optional[float]:
    """Return pre-computed travel distance if a record exists, else None."""
    as_of = _ensure_aware(as_of)
    key = f"{canonical_team(home)}|{canonical_team(away)}"
    snap = store.snapshot(as_of)
    for r in snap.filter("travel"):
        if r.payload.get("pair") == key:
            return float(r.payload["distance_km"])
    return None


def is_derby(
    store: DataStore,
    home: str,
    away: str,
    as_of: datetime,
) -> bool:
    """True if a derby flag record exists for the pair and was known by as_of."""
    as_of = _ensure_aware(as_of)
    pair = tuple(sorted([canonical_team(home), canonical_team(away)]))
    snap = store.snapshot(as_of)
    for r in snap.filter("derby"):
        p = r.payload.get("pair")
        if p and tuple(sorted(p)) == pair:
            return True
    return False
