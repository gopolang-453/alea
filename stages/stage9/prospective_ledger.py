"""Stage 9 prospective evaluation ledger.

Stores predictions before kickoff. Never overwrites an existing prediction.
After the match, the actual result can be recorded once.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class LedgerError(ValueError):
    pass


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise LedgerError("datetime must be timezone-aware")
    return dt.astimezone(timezone.utc)


class ProspectiveLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                fixture_key TEXT PRIMARY KEY,
                predicted_at TEXT NOT NULL,
                kickoff_at TEXT NOT NULL,
                p_home REAL NOT NULL,
                p_draw REAL NOT NULL,
                p_away REAL NOT NULL,
                expected_goals_home REAL,
                expected_goals_away REAL,
                model_version TEXT NOT NULL,
                code_sha TEXT,
                data_snapshot_hash TEXT,
                payload_json TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS outcomes (
                fixture_key TEXT PRIMARY KEY,
                recorded_at TEXT NOT NULL,
                home_goals INTEGER NOT NULL,
                away_goals INTEGER NOT NULL,
                outcome TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ProspectiveLedger":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def record_prediction(
        self,
        *,
        fixture_key: str,
        predicted_at: datetime,
        kickoff_at: datetime,
        p_home: float,
        p_draw: float,
        p_away: float,
        model_version: str,
        expected_goals_home: Optional[float] = None,
        expected_goals_away: Optional[float] = None,
        code_sha: Optional[str] = None,
        data_snapshot_hash: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        predicted_at = _utc(predicted_at)
        kickoff_at = _utc(kickoff_at)
        if predicted_at >= kickoff_at:
            raise LedgerError("prediction must be recorded before kickoff")
        total = p_home + p_draw + p_away
        if abs(total - 1.0) > 1e-6 or min(p_home, p_draw, p_away) < 0:
            raise LedgerError("probabilities must be non-negative and sum to 1")
        payload = {
            "fixture_key": fixture_key,
            "p_home": p_home,
            "p_draw": p_draw,
            "p_away": p_away,
            "model_version": model_version,
            "extra": extra or {},
        }
        payload_json = json.dumps(payload, sort_keys=True)
        existing = self._conn.execute(
            "SELECT payload_json FROM predictions WHERE fixture_key=?",
            (fixture_key,),
        ).fetchone()
        if existing is not None:
            if existing["payload_json"] == payload_json:
                return False
            raise LedgerError(f"prediction already exists for {fixture_key} and differs")
        self._conn.execute(
            """INSERT INTO predictions
            (fixture_key, predicted_at, kickoff_at, p_home, p_draw, p_away,
             expected_goals_home, expected_goals_away, model_version, code_sha,
             data_snapshot_hash, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fixture_key,
                predicted_at.isoformat(),
                kickoff_at.isoformat(),
                p_home,
                p_draw,
                p_away,
                expected_goals_home,
                expected_goals_away,
                model_version,
                code_sha,
                data_snapshot_hash,
                payload_json,
            ),
        )
        self._conn.commit()
        return True

    def record_outcome(
        self,
        fixture_key: str,
        home_goals: int,
        away_goals: int,
        recorded_at: datetime,
    ) -> bool:
        recorded_at = _utc(recorded_at)
        if home_goals < 0 or away_goals < 0:
            raise LedgerError("goals must be non-negative")
        outcome = "H" if home_goals > away_goals else ("D" if home_goals == away_goals else "A")
        existing = self._conn.execute(
            "SELECT home_goals, away_goals FROM outcomes WHERE fixture_key=?",
            (fixture_key,),
        ).fetchone()
        if existing is not None:
            if existing["home_goals"] == home_goals and existing["away_goals"] == away_goals:
                return False
            raise LedgerError(f"outcome already recorded for {fixture_key} and differs")
        self._conn.execute(
            """INSERT INTO outcomes (fixture_key, recorded_at, home_goals, away_goals, outcome)
            VALUES (?, ?, ?, ?, ?)""",
            (fixture_key, recorded_at.isoformat(), home_goals, away_goals, outcome),
        )
        self._conn.commit()
        return True

    def get_prediction(self, fixture_key: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM predictions WHERE fixture_key=?",
            (fixture_key,),
        ).fetchone()
        return dict(row) if row else None

    def fingerprint(self) -> str:
        rows = self._conn.execute(
            "SELECT fixture_key, payload_json FROM predictions ORDER BY fixture_key"
        ).fetchall()
        payload = json.dumps([tuple(r) for r in rows])
        return hashlib.sha256(payload.encode()).hexdigest()
