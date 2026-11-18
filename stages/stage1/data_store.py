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
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
        self._record_index: Dict[tuple, Record] = {}

    def add(self, record: Record) -> bool:
        if record.available_at.tzinfo is None:
            raise ValueError("available_at must be timezone-aware")
        if not record.kind or not record.fixture_key or not record.source:
            raise ValueError("kind, fixture_key, and source are required")
        identity = (record.kind, record.fixture_key, record.source, record.source_id)
        previous = self._record_index.get(identity)
        if previous is not None:
            old_payload = json.dumps(previous.to_dict(), sort_keys=True, default=str)
            new_payload = json.dumps(record.to_dict(), sort_keys=True, default=str)
            if old_payload == new_payload:
                return False  # exact re-import: idempotent no-op
            raise ValueError(
                "conflicting record for existing identity; preserve a source revision "
                "with a distinct source_id instead of overwriting history"
            )
        self._record_index[identity] = record
        self._records.append(record)
        return True

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


class PersistentDataStore(DataStore):
    """SQLite-backed append-only store with the same snapshot API as DataStore."""

    def __init__(self, database_path: str | Path) -> None:
        super().__init__()
        self.database_path = str(database_path)
        self._conn = sqlite3.connect(self.database_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                fixture_key TEXT NOT NULL,
                available_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL DEFAULT '',
                UNIQUE(kind, fixture_key, source, source_id)
            )
            """
        )
        self._conn.commit()
        rows = self._conn.execute(
            "SELECT kind, fixture_key, available_at, payload_json, source, source_id FROM records"
        ).fetchall()
        for kind, fixture_key, available_at, payload_json, source, source_id in rows:
            super().add(
                Record(
                    kind=kind,
                    fixture_key=fixture_key,
                    available_at=datetime.fromisoformat(available_at),
                    payload=json.loads(payload_json),
                    source=source,
                    source_id=source_id or None,
                )
            )

    def add(self, record: Record) -> bool:
        added = super().add(record)
        if not added:
            return False
        identity = (record.kind, record.fixture_key, record.source, record.source_id)
        try:
            self._conn.execute(
                """
                INSERT INTO records
                    (kind, fixture_key, available_at, payload_json, source, source_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.kind,
                    record.fixture_key,
                    record.available_at.isoformat(),
                    json.dumps(record.payload, sort_keys=True, default=str),
                    record.source,
                    record.source_id or "",
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            self._record_index.pop(identity, None)
            self._records.pop()
            raise
        return True

    def close(self) -> None:
        if getattr(self, "_conn", None) is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "PersistentDataStore":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def ingest_csv(
    store: DataStore,
    csv_path: str | Path,
    source: str = "football-data",
    available_offset_hours: float = 36.0,
) -> int:
    """Read a football-data-style CSV and ingest validated full-time results."""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    frame = pd.read_csv(path, encoding="utf-8-sig")
    require_columns(frame, ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    parsed_dates = pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce")
    if parsed_dates.isna().any():
        bad_rows = frame.index[parsed_dates.isna()].tolist()
        raise DataValidationError(f"unreadable match dates at CSV rows: {bad_rows[:10]}")
    frame = frame.copy()
    frame["Date"] = parsed_dates
    return ingest_results_frame(
        store,
        frame,
        source=source,
        available_offset_hours=available_offset_hours,
    )


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
    available_offset_hours: float = 36.0,
) -> int:
    """
    Ingest final results with a deliberately conservative availability time.

    If the frame has an `available_at` column, that source publication timestamp
    is used and must be timezone-aware. Otherwise, date-only historical feeds do
    not reveal the actual publication time, so the result is withheld until
    36 hours after midnight UTC on the match date. This is a conservative
    date-only policy, not a claim about the provider's exact publication time.

    Exact duplicate imports are no-ops. Conflicting revisions must use a distinct
    source_id at the Record layer so prior snapshots remain auditable.
    Returns the number of newly added records.
    """
    require_columns(df, ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    if available_offset_hours < 0:
        raise ValueError("available_offset_hours must be non-negative")
    n = 0
    for _, row in df.iterrows():
        date = pd.Timestamp(row["Date"])
        if pd.isna(date):
            raise DataValidationError("invalid or missing match date")
        match_day = date.date()
        if "available_at" in df.columns and pd.notna(row.get("available_at")):
            available_ts = pd.Timestamp(row["available_at"])
            if available_ts.tzinfo is None:
                raise DataValidationError("available_at values must be timezone-aware")
            available = available_ts.tz_convert("UTC").to_pydatetime()
        else:
            # Date-only feeds lack kickoff/result-publication times. Delaying
            # availability is safer than exposing a final score on match day.
            day_start = pd.Timestamp(match_day).tz_localize("UTC")
            available = (day_start + pd.Timedelta(hours=available_offset_hours)).to_pydatetime()
        if available.date() < match_day:
            raise DataValidationError("result cannot be available before its match date")
        home = canonical_team(str(row["HomeTeam"]))
        away = canonical_team(str(row["AwayTeam"]))
        if home == away:
            raise DataValidationError("a team cannot play itself")
        try:
            fthg = int(row["FTHG"])
            ftag = int(row["FTAG"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise DataValidationError("full-time goals must be non-negative integers") from exc
        if fthg < 0 or ftag < 0 or fthg != row["FTHG"] or ftag != row["FTAG"]:
            raise DataValidationError("full-time goals must be non-negative integers")
        key = f"{match_day.isoformat()}|{home}|{away}"
        rec = Record(
            kind="result",
            fixture_key=key,
            available_at=available,
            payload={
                "date": match_day.isoformat(),
                "home": home,
                "away": away,
                "fthg": fthg,
                "ftag": ftag,
            },
            source=source,
        )
        n += int(store.add(rec))
    return n
