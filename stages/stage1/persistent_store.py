"""SQLite-backed, idempotent Stage 1 store for reproducible ALEA experiments.

Results without a trustworthy kickoff/completion timestamp are conservatively
made available at 00:00 UTC on the following calendar day. This avoids using a
same-day result to predict another match when match ordering is unknown.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd


class DataValidationError(ValueError):
    """Raised when a source record is malformed or conflicts with stored data."""


def canonical_team(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise DataValidationError(f"invalid team name: {name!r}")
    key = " ".join(name.lower().replace(".", "").strip().split())
    aliases = {
        "man utd": "manchester united",
        "man united": "manchester united",
        "manchester utd": "manchester united",
        "man city": "manchester city",
        "spurs": "tottenham",
        "tottenham hotspur": "tottenham",
        "wolves": "wolverhampton",
        "wolverhampton wanderers": "wolverhampton",
        "brighton": "brighton and hove albion",
        "west ham": "west ham united",
        "newcastle": "newcastle united",
        "nott'm forest": "nottingham forest",
        "leicester": "leicester city",
        "ipswich": "ipswich town",
    }
    return aliases.get(key, key)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataValidationError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def conservative_result_availability(match_date: date) -> datetime:
    """Date-only results are not visible until the following UTC day."""
    return datetime.combine(match_date + timedelta(days=1), time.min, tzinfo=timezone.utc)


def _parse_date(value: Any) -> date:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise DataValidationError("match date is missing")
    try:
        parsed = pd.Timestamp(value)
        if pd.isna(parsed):
            raise ValueError("date parsed as NaT")
        return parsed.date()
    except Exception as exc:
        raise DataValidationError(f"invalid match date: {value!r}") from exc


def _validate_goals(home_goals: Any, away_goals: Any) -> tuple[int, int]:
    values = []
    for label, value in (("home goals", home_goals), ("away goals", away_goals)):
        if isinstance(value, bool):
            raise DataValidationError(f"{label} must be a non-negative integer")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DataValidationError(f"{label} is missing or non-numeric") from exc
        if not number.is_integer() or number < 0 or number > 30:
            raise DataValidationError(f"{label} outside valid integer range: {value!r}")
        values.append(int(number))
    return values[0], values[1]


@dataclass(frozen=True)
class StoredRecord:
    kind: str
    fixture_key: str
    available_at: datetime
    payload: Dict[str, Any]
    source: str
    source_id: Optional[str] = None


@dataclass
class Snapshot:
    as_of: datetime
    records: List[StoredRecord]

    def filter(self, kind: Optional[str] = None) -> List[StoredRecord]:
        rows = [r for r in self.records if r.available_at <= self.as_of]
        return rows if kind is None else [r for r in rows if r.kind == kind]

    def to_results_frame(self) -> pd.DataFrame:
        rows = []
        for record in self.filter("result"):
            p = record.payload
            rows.append({
                "Date": p["date"],
                "HomeTeam": p["home"],
                "AwayTeam": p["away"],
                "FTHG": p["fthg"],
                "FTAG": p["ftag"],
                "available_at": record.available_at,
                "source": record.source,
            })
        columns = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "available_at", "source"]
        frame = pd.DataFrame(rows, columns=columns)
        if not frame.empty:
            frame["Date"] = pd.to_datetime(frame["Date"])
            frame = frame.sort_values(["Date", "HomeTeam", "AwayTeam"]).reset_index(drop=True)
        return frame


class PersistentDataStore:
    """Append-only SQLite store. Identical imports are no-ops; conflicts fail closed."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                fixture_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                event_date TEXT NOT NULL,
                available_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT,
                content_hash TEXT NOT NULL
            )
        """)
        row = self._conn.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )
        elif int(row["value"]) != self.SCHEMA_VERSION:
            raise DataValidationError(
                f"unsupported database schema {row['value']}; expected {self.SCHEMA_VERSION}"
            )
        self._conn.commit()

    def __enter__(self) -> "PersistentDataStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def add_result(
        self,
        *,
        competition: str,
        season: str,
        match_date: date,
        home: str,
        away: str,
        home_goals: Any,
        away_goals: Any,
        source: str,
        source_id: Optional[str] = None,
        available_at: Optional[datetime] = None,
    ) -> bool:
        if not all(isinstance(v, str) and v.strip() for v in (competition, season, source)):
            raise DataValidationError("competition, season and source are required strings")
        if isinstance(match_date, datetime) or not isinstance(match_date, date):
            raise DataValidationError("match_date must be a date without a time component")
        home_name, away_name = canonical_team(home), canonical_team(away)
        if home_name == away_name:
            raise DataValidationError("a team cannot play itself")
        hg, ag = _validate_goals(home_goals, away_goals)
        availability = _aware_utc(available_at) if available_at else conservative_result_availability(match_date)
        if availability.date() < match_date:
            raise DataValidationError("result cannot be available before its match date")
        key = "|".join((competition.strip().lower(), season.strip(), match_date.isoformat(), home_name, away_name))
        payload = {
            "competition": competition.strip(),
            "season": season.strip(),
            "date": match_date.isoformat(),
            "home": home_name,
            "away": away_name,
            "fthg": hg,
            "ftag": ag,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        existing = self._conn.execute(
            "SELECT payload_json FROM records WHERE fixture_key=?", (key,)
        ).fetchone()
        if existing is not None:
            if existing["payload_json"] != payload_json:
                raise DataValidationError(f"conflicting duplicate fixture: {key}")
            return False
        outer_transaction = self._conn.in_transaction
        self._conn.execute(
            """INSERT INTO records
            (fixture_key, kind, event_date, available_at, payload_json, source, source_id, content_hash)
            VALUES (?, 'result', ?, ?, ?, ?, ?, ?)""",
            (key, match_date.isoformat(), availability.isoformat(), payload_json, source, source_id, digest),
        )
        if not outer_transaction:
            self._conn.commit()
        return True

    def ingest_openfootball_file(
        self,
        path: str | Path,
        *,
        season: str,
        competition: str = "Premier League",
        source_url: Optional[str] = None,
    ) -> int:
        file_path = Path(path)
        try:
            document = json.loads(file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataValidationError(f"cannot read OpenFootball JSON {file_path}: {exc}") from exc
        matches = document.get("matches")
        if not isinstance(matches, list):
            raise DataValidationError("OpenFootball document must contain a matches list")
        added = 0
        source = source_url or f"openfootball:{file_path.name}"
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            for index, match in enumerate(matches):
                if not isinstance(match, dict):
                    raise DataValidationError(f"match {index} is not an object")
                score_block = match.get("score") or {}
                if not isinstance(score_block, dict):
                    raise DataValidationError(f"match {index} has malformed score object")
                score = score_block.get("ft")
                if score is None:
                    continue  # upcoming/unplayed fixture, not a result
                if not isinstance(score, list) or len(score) != 2:
                    raise DataValidationError(f"match {index} has malformed full-time score")
                added += self.add_result(
                    competition=competition,
                    season=season,
                    match_date=_parse_date(match.get("date")),
                    home=match.get("team1"),
                    away=match.get("team2"),
                    home_goals=score[0],
                    away_goals=score[1],
                    source=source,
                    source_id=str(match.get("round") or index),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return added

    def snapshot(self, as_of: datetime) -> Snapshot:
        cutoff = _aware_utc(as_of).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM records WHERE available_at <= ? ORDER BY event_date, fixture_key",
            (cutoff,),
        ).fetchall()
        records = [
            StoredRecord(
                kind=row["kind"],
                fixture_key=row["fixture_key"],
                available_at=datetime.fromisoformat(row["available_at"]),
                payload=json.loads(row["payload_json"]),
                source=row["source"],
                source_id=row["source_id"],
            )
            for row in rows
        ]
        return Snapshot(as_of=_aware_utc(as_of), records=records)

    def all_records(self) -> List[StoredRecord]:
        rows = self._conn.execute("SELECT * FROM records ORDER BY fixture_key").fetchall()
        return [
            StoredRecord(
                kind=row["kind"],
                fixture_key=row["fixture_key"],
                available_at=datetime.fromisoformat(row["available_at"]),
                payload=json.loads(row["payload_json"]),
                source=row["source"],
                source_id=row["source_id"],
            )
            for row in rows
        ]

    def fingerprint(self) -> str:
        rows = self._conn.execute(
            "SELECT fixture_key, content_hash, available_at, source FROM records ORDER BY fixture_key"
        ).fetchall()
        serialised = json.dumps([tuple(row) for row in rows], separators=(",", ":"))
        return hashlib.sha256(serialised.encode("utf-8")).hexdigest()
