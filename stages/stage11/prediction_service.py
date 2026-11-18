"""Stage 11 — traceable prediction response and immutable prediction history."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional
import re

import numpy as np

import alea_predictor_v2_4_1 as dc
from ..stage1.data_store import canonical_team


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def build_prediction(
    params: Dict[str, Any],
    home: str,
    away: str,
    fixture_date: date,
    prediction_time: datetime,
    data_snapshot_sha256: str,
    *,
    kickoff_at: Optional[datetime] = None,
    feature_status: Optional[Dict[str, str]] = None,
    allow_new_teams: bool = False,
) -> Dict[str, Any]:
    """Build a JSON-safe prediction and enforce the pre-kickoff data cutoff."""
    predicted_at = _aware(prediction_time, "prediction_time")
    if isinstance(fixture_date, datetime) or not isinstance(fixture_date, date):
        raise ValueError("fixture_date must be a date")
    if not isinstance(data_snapshot_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", data_snapshot_sha256):
        raise ValueError("a full 64-character SHA-256 data fingerprint is required")
    home_id, away_id = canonical_team(home), canonical_team(away)
    if home_id == away_id:
        raise ValueError("home and away teams must be different")
    known_teams = {canonical_team(team) for team in params.get("teams", [])}
    unknown = [team for team in (home_id, away_id) if team not in known_teams]
    if unknown and not allow_new_teams:
        raise ValueError(f"unknown team(s) {unknown}; explicitly allow new-team priors only for genuine new teams")
    if not params.get("model_version"):
        raise ValueError("model parameters must include model_version")

    if kickoff_at is not None:
        kickoff = _aware(kickoff_at, "kickoff_at")
        if predicted_at >= kickoff:
            raise ValueError("prediction must be generated before kickoff")
        if kickoff.date() != fixture_date:
            raise ValueError("kickoff_at date does not match fixture_date")
    elif predicted_at.date() >= fixture_date:
        raise ValueError("without a kickoff timestamp, prediction must be made before fixture day")

    data_through = params.get("data_through")
    training_cutoff = params.get("as_of_date")
    if not data_through or not training_cutoff:
        raise ValueError("model parameters must include data_through and as_of_date")
    if date.fromisoformat(str(data_through)[:10]) >= fixture_date:
        raise ValueError("model contains results from the fixture date or later")
    if date.fromisoformat(str(training_cutoff)[:10]) >= fixture_date:
        raise ValueError("model training cutoff must precede fixture date")

    raw = dc.predict(params, home_id, away_id, allow_new_teams=allow_new_teams)
    markets = raw["markets"]
    p = [float(markets["home"]), float(markets["draw"]), float(markets["away"])]
    if not np.all(np.isfinite(p)) or min(p) < 0 or not np.isclose(sum(p), 1.0, atol=1e-8):
        raise ValueError("prediction engine returned an invalid 1X2 probability vector")

    status = feature_status or {
        "elo_form": "experimental_not_connected_to_probability_model",
        "xg": "unavailable_no_licensed_historical_source",
        "injuries_lineups": "unavailable_no_timestamped_source",
        "context": "unavailable_no_timestamped_source",
    }
    return {
        "fixture": {
            "home": home,
            "away": away,
            "date": fixture_date.isoformat(),
            "kickoff_at": kickoff_at.isoformat() if kickoff_at else None,
        },
        "prediction_time": predicted_at.isoformat(),
        "model": {
            "version": params.get("model_version"),
            "trained_through": data_through,
            "training_cutoff": training_cutoff,
            "training_matches": params.get("n_matches_trained"),
        },
        "data_snapshot_sha256": data_snapshot_sha256,
        "probabilities_1x2": {
            "home": p[0],
            "draw": p[1],
            "away": p[2],
        },
        "expected_goals": {
            "home": float(raw["lambda_home"]),
            "away": float(raw["lambda_away"]),
        },
        "markets": {
            "over_1_5": float(markets["over_1_5"]),
            "over_2_5": float(markets["over_2_5"]),
            "over_3_5": float(markets["over_3_5"]),
            "under_2_5": float(markets["under_2_5"]),
            "btts_yes": float(markets["btts_yes"]),
            "btts_no": float(markets["btts_no"]),
        },
        "most_likely_score": raw["most_likely_score"],
        "top_scorelines": [
            {"score": score, "probability": float(probability)}
            for score, probability in raw["top_scores"]
        ],
        "quality": {
            "tail_probability": float(raw["tail_probability"]),
            "prior_only_teams": list(raw["prior_only_teams"]),
            "rho_clipped_for_pair": bool(raw["rho_clipped_for_pair"]),
            "feature_status": status,
        },
        "disclaimer": dc.DISCLAIMER,
    }


class PredictionHistory:
    """Append-only SQLite history; an identical prediction ID is idempotent."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                prediction_id TEXT PRIMARY KEY,
                fixture_date TEXT NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                model_version TEXT NOT NULL,
                prediction_time TEXT NOT NULL,
                data_snapshot_sha256 TEXT NOT NULL,
                response_json TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PredictionHistory":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def save(self, response: Dict[str, Any]) -> str:
        serialised = json.dumps(response, sort_keys=True, separators=(",", ":"))
        prediction_id = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
        fixture = response["fixture"]
        model = response["model"]
        self._conn.execute(
            """INSERT OR IGNORE INTO predictions
            (prediction_id, fixture_date, home_team, away_team, model_version,
             prediction_time, data_snapshot_sha256, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                prediction_id, fixture["date"], fixture["home"], fixture["away"],
                str(model["version"]), response["prediction_time"],
                response["data_snapshot_sha256"], serialised,
            ),
        )
        self._conn.commit()
        return prediction_id

    def get(self, prediction_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT response_json FROM predictions WHERE prediction_id=?",
            (prediction_id,),
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0])
