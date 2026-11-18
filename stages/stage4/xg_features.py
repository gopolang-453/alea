"""
ALEA Stage 4 — Expected goals (xG) features
-------------------------------------------
Leakage-safe xG feature calculators.
All functions take an explicit as_of cutoff and only use xG records
whose available_at is before that moment.
When no xG data exists for a team or fixture, the functions return
None or empty structures — they never invent numbers.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Sequence

from ..stage1.data_store import DataStore, Record, canonical_team


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt


def _xg_pair(payload: Dict[str, object]) -> tuple[float, float]:
    values = []
    for key in ("home_xg", "away_xg"):
        try:
            value = float(payload[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid {key} value in xG record") from exc
        if value < 0 or value != value or value == float("inf"):
            raise ValueError(f"invalid {key} value in xG record")
        values.append(value)
    return values[0], values[1]


def _event_date(record: Record) -> date:
    raw = record.payload.get("date") or record.fixture_key.split("|", 1)[0]
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError as exc:
        raise ValueError(f"xG record has no valid fixture date: {record.fixture_key}") from exc


def team_xg_history(
    store: DataStore,
    team: str,
    as_of: datetime,
    n: int = 5,
    venue: Optional[str] = None,
) -> Optional[Dict[str, float]]:
    """
    Rolling xG for and against for `team` from the last n matches
    whose xG records were available before as_of.
    venue: "home", "away", or None.
    Returns zeros and matches=0 when no data is available.
    """
    as_of = _ensure_aware(as_of)
    team_c = canonical_team(team)
    snap = store.snapshot(as_of)
    if n < 1:
        raise ValueError("n must be at least 1")
    if venue not in (None, "home", "away"):
        raise ValueError("venue must be 'home', 'away' or None")
    rows = []
    for r in snap.filter("xg"):
        p = r.payload
        home = canonical_team(p.get("home", ""))
        away = canonical_team(p.get("away", ""))
        if home != team_c and away != team_c:
            continue
        is_home = home == team_c
        if venue == "home" and not is_home:
            continue
        if venue == "away" and is_home:
            continue
        home_xg, away_xg = _xg_pair(p)
        xg_for = home_xg if is_home else away_xg
        xg_against = away_xg if is_home else home_xg
        rows.append((_event_date(r), r.available_at, xg_for, xg_against))
    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    window = rows[:n]
    if not window:
        return None
    xgf = sum(w[2] for w in window)
    xga = sum(w[3] for w in window)
    return {
        "matches": len(window),
        "xg_for": xgf / len(window),
        "xg_against": xga / len(window),
        "xg_diff": (xgf - xga) / len(window),
    }


def fixture_xg(
    store: DataStore,
    fixture_key: str,
    as_of: datetime,
) -> Optional[Dict[str, float]]:
    """
    Return the xG pair for a specific fixture if it was known by as_of,
    otherwise None.
    """
    as_of = _ensure_aware(as_of)
    snap = store.snapshot(as_of)
    for r in snap.filter("xg"):
        if r.fixture_key == fixture_key:
            home_xg, away_xg = _xg_pair(r.payload)
            return {"home_xg": home_xg, "away_xg": away_xg}
    return None


def xg_overperformance(
    store: DataStore,
    team: str,
    as_of: datetime,
    n: int = 5,
) -> Optional[float]:
    """
    Goals minus xG over the last n matches (positive = overperforming).
    Requires both result and xG records for the same fixtures.
    Returns None if fewer than n complete pairs are available.
    """
    as_of = _ensure_aware(as_of)
    team_c = canonical_team(team)
    snap = store.snapshot(as_of)
    results = {r.fixture_key: r for r in snap.filter("result")}
    xgs = {r.fixture_key: r for r in snap.filter("xg")}
    pairs = []
    for key, xr in xgs.items():
        if key not in results:
            continue
        rr = results[key]
        p = xr.payload
        home = canonical_team(p.get("home", ""))
        away = canonical_team(p.get("away", ""))
        if home != team_c and away != team_c:
            continue
        is_home = home == team_c
        goals = int(rr.payload["fthg"] if is_home else rr.payload["ftag"])
        xg = float(p["home_xg"] if is_home else p["away_xg"])
        pairs.append((_event_date(xr), xr.available_at, goals - xg))
    pairs.sort(key=lambda x: (x[0], x[1]), reverse=True)
    window = pairs[:n]
    if len(window) < n:
        return None
    return sum(w[2] for w in window) / len(window)
