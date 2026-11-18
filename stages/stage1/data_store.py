"""
ALEA Stage 1 — Data collection and data management layer
---------------------------------------------------------
Wraps the existing strict cleaners from alea_predictor_*.py and adds:

- Explicit "available_at" timestamps so historical predictions never see
  information that arrived after the decision time.
- Canonical team identifiers (stable across name variants).
- Snapshot storage so an old view of the data can be reproduced.
- Fail-closed stubs for xG / injuries / lineups (present but refuse to
  invent data when the source is missing).

This module does not fetch live data. It defines the contracts and the
validation gates that later fetchers must satisfy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd


# ---------------------------------------------------------------------------
# Canonical team identity
# ---------------------------------------------------------------------------

# Minimal alias table. Extend as new variants appear in real sources.
_ALIASES: Dict[str, str] = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "manchester utd": "manchester united",
    "man city": "manchester city",
    "manchester city": "manchester city",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
    "brighton": "brighton and hove albion",
    "west ham": "west ham united",
    "newcastle": "newcastle united",
    "nott'm forest": "nottingham forest",
    "nottingham forest": "nottingham forest",
    "leicester": "leicester city",
    "ipswich": "ipswich town",
}


def canonical_team(name: str) -> str:
    """Return a stable lowercase identifier for a team name."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"unreadable team name: {name!r}")
    key = " ".join(name.lower().strip().replace(".", "").split())
    return _ALIASES.get(key, key)


def team_id(name: str) -> str:
    """Short stable id derived from the canonical name."""
    return hashlib.sha256(canonical_team(name).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Snapshot / availability
# ---------------------------------------------------------------------------

@dataclass
class Record:
    """One atomic piece of information with an explicit availability time."""
    kind: str                     # "result", "odds", "xg", "injury", "lineup", ...
    fixture_key: str              # "YYYY-MM-DD|home|away"
    available_at: datetime        # when this record became known
    payload: Dict[str, Any]
    source: str
    source_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = self.__dict__.copy()
        d["available_at"] = self.available_at.isoformat()
        return d


@dataclass
class Snapshot:
    """Immutable view of all records available up to a given moment."""
    as_of: datetime
    records: List[Record] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def filter(self, kind: Optional[str] = None) -> List[Record]:
        rows = [r for r in self.records if r.available_at <= self.as_of]
        if kind is not None:
            rows = [r for r in rows if r.kind == kind]
        return rows

    def to_results_frame(self) -> pd.DataFrame:
        """Return a DataFrame of results that were known by as_of."""
        rows = []
        for r in self.filter("result"):
            p = r.payload
            rows.append({
                "Date": p["date"],
                "HomeTeam": p["home"],
                "AwayTeam": p["away"],
                "FTHG": p["fthg"],
                "FTAG": p["ftag"],
                "available_at": r.available_at,
                "source": r.source,
            })
        if not rows:
            return pd.DataFrame(columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
        df = pd.DataFrame(rows)
        df["Date"] = pd.to_datetime(df["Date"])
        return df.sort_values("Date").reset_index(drop=True)


class DataStore:
    """
    Append-only store. New information is added; old snapshots stay reproducible.
    """

    def __init__(self) -> None:
        self._records: List[Record] = []

    def add(self, record: Record) -> None:
        if record.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        self._records.append(record)

    def snapshot(self, as_of: datetime) -> Snapshot:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        visible = [r for r in self._records if r.available_at <= as_of]
        return Snapshot(as_of=as_of, records=visible)

    def all_records(self) -> List[Record]:
        return list(self._records)

    def fingerprint(self) -> str:
        """Stable hash of the entire store (for tests and provenance)."""
        payload = json.dumps(
            [r.to_dict() for r in sorted(self._records, key=lambda x: (x.available_at, x.fixture_key, x.kind))],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Validation helpers that Stage 1 requires
# ---------------------------------------------------------------------------

class DataValidationError(ValueError):
    pass


def detect_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Return the subset of rows that are duplicate fixtures (same date + teams)."""
    if df.empty:
        return df
    key = ["Date", "HomeTeam", "AwayTeam"]
    return df[df.duplicated(subset=key, keep=False)].copy()


def assert_no_future_results(df: pd.DataFrame, as_of: datetime) -> None:
    """Fail if any played result is dated after the snapshot time."""
    if df.empty:
        return
    dates = pd.to_datetime(df["Date"])
    future = dates > pd.Timestamp(as_of).tz_localize(None) if as_of.tzinfo else dates > pd.Timestamp(as_of)
    if future.any():
        bad = df.loc[future, ["Date", "HomeTeam", "AwayTeam"]].to_dict("records")
        raise DataValidationError(f"results exist after snapshot time: {bad}")


def require_columns(df: pd.DataFrame, cols: Sequence[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise DataValidationError(f"missing required columns: {missing}")


# ---------------------------------------------------------------------------
# Fail-closed stubs for later stages
# ---------------------------------------------------------------------------

def xg_for_fixture(store: DataStore, fixture_key: str, as_of: datetime) -> Optional[Dict[str, float]]:
    """
    Return {'home_xg': float, 'away_xg': float} if both values were known
    by as_of, otherwise None. Never invents numbers.
    """
    snap = store.snapshot(as_of)
    for r in snap.filter("xg"):
        if r.fixture_key == fixture_key:
            return {
                "home_xg": float(r.payload["home_xg"]),
                "away_xg": float(r.payload["away_xg"]),
            }
    return None


def injuries_for_team(store: DataStore, team: str, as_of: datetime) -> List[Dict[str, Any]]:
    """Return injury records for a team that were known by as_of. Empty list if none."""
    cid = team_id(team)
    snap = store.snapshot(as_of)
    out = []
    for r in snap.filter("injury"):
        if r.payload.get("team_id") == cid or canonical_team(r.payload.get("team", "")) == canonical_team(team):
            out.append(r.payload)
    return out


# ---------------------------------------------------------------------------
# Convenience loader from an existing cleaned ALEA DataFrame
# ---------------------------------------------------------------------------

def ingest_results_frame(
    store: DataStore,
    df: pd.DataFrame,
    source: str = "football-data",
    available_offset_hours: float = 3.0,
) -> int:
    """
    Turn a standard ALEA results DataFrame into timestamped records.
    Each result is marked available `available_offset_hours` after the match date
    (conservative default: assume the score is known a few hours after kick-off).
    Returns the number of records added.
    """
    require_columns(df, ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    n = 0
    for _, row in df.iterrows():
        date = pd.Timestamp(row["Date"])
        # Treat the match date as midnight UTC, then add the offset
        available = (date.tz_localize("UTC") + pd.Timedelta(hours=available_offset_hours)).to_pydatetime()
        home = canonical_team(str(row["HomeTeam"]))
        away = canonical_team(str(row["AwayTeam"]))
        key = f"{date.date().isoformat()}|{home}|{away}"
        rec = Record(
            kind="result",
            fixture_key=key,
            available_at=available,
            payload={
                "date": date.date().isoformat(),
                "home": home,
                "away": away,
                "fthg": int(row["FTHG"]),
                "ftag": int(row["FTAG"]),
            },
            source=source,
        )
        store.add(rec)
        n += 1
    return n
