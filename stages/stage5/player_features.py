"""
ALEA Stage 5 — Player intelligence, injuries and suspensions
------------------------------------------------------------
Leakage-safe feature layer.
All functions take an explicit as_of cutoff.
Missing data returns empty structures or None — never invents impact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..stage1.data_store import DataStore, Record, canonical_team, team_id


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt


def injuries_for_team(
    store: DataStore,
    team: str,
    as_of: datetime,
) -> List[Dict[str, Any]]:
    """
    Injury records for a team that were known by as_of.
    Each record is expected to contain at least:
      player, status (injured/doubtful/returning), position (optional)
    """
    as_of = _ensure_aware(as_of)
    team_c = canonical_team(team)
    tid = team_id(team)
    snap = store.snapshot(as_of)
    out = []
    for r in snap.filter("injury"):
        p = r.payload
        if p.get("team_id") == tid or canonical_team(p.get("team", "")) == team_c:
            out.append(p)
    return out


def suspensions_for_team(
    store: DataStore,
    team: str,
    as_of: datetime,
) -> List[Dict[str, Any]]:
    """Suspension records known by as_of (red card, yellow accumulation, etc.)."""
    as_of = _ensure_aware(as_of)
    team_c = canonical_team(team)
    tid = team_id(team)
    snap = store.snapshot(as_of)
    out = []
    for r in snap.filter("suspension"):
        p = r.payload
        if p.get("team_id") == tid or canonical_team(p.get("team", "")) == team_c:
            out.append(p)
    return out


def confirmed_lineup(
    store: DataStore,
    fixture_key: str,
    as_of: datetime,
) -> Optional[Dict[str, Any]]:
    """
    Return the confirmed starting XI for a fixture if it was known by as_of,
    otherwise None.
    Payload expected: {"home_xi": [...], "away_xi": [...], "confirmed": true}
    """
    as_of = _ensure_aware(as_of)
    snap = store.snapshot(as_of)
    for r in snap.filter("lineup"):
        if r.fixture_key == fixture_key and r.payload.get("confirmed"):
            return r.payload
    return None


def player_impact_stub(
    player: str,
    position: str,
    status: str,
) -> Dict[str, float]:
    """
    Simple position-aware impact placeholder.
    This is NOT a trained model. It only encodes the principle that
    a starting goalkeeper absence is larger than a reserve winger absence.
    Real impact must be estimated from data in a later evaluation stage.
    """
    base = {
        "goalkeeper": 0.15,
        "defender": 0.08,
        "midfielder": 0.07,
        "forward": 0.10,
        "winger": 0.06,
    }.get(position.lower(), 0.05)
    multiplier = {
        "injured": 1.0,
        "suspended": 1.0,
        "doubtful": 0.4,
        "returning": 0.3,
    }.get(status.lower(), 0.5)
    return {
        "player": player,
        "position": position,
        "status": status,
        "impact": round(base * multiplier, 3),
    }


def unavailable_impact(
    store: DataStore,
    team: str,
    as_of: datetime,
) -> Dict[str, Any]:
    """
    Aggregate a crude impact score from injuries + suspensions known by as_of.
    Returns the list of affected players and a total impact figure.
    """
    injuries = injuries_for_team(store, team, as_of)
    suspensions = suspensions_for_team(store, team, as_of)
    impacts = []
    for rec in injuries + suspensions:
        impacts.append(player_impact_stub(
            player=rec.get("player", "unknown"),
            position=rec.get("position", "unknown"),
            status=rec.get("status", "injured"),
        ))
    total = sum(i["impact"] for i in impacts)
    return {
        "team": canonical_team(team),
        "as_of": as_of.isoformat(),
        "players": impacts,
        "total_impact": round(total, 3),
        "count": len(impacts),
    }
