"""Stage 9 prospective evaluation ledger (append-only SQLite store).

Design rules
------------
* A forecast is written once, before kickoff, and never modified or deleted.
  SQLite triggers reject ``UPDATE``/``DELETE`` on every evidence table, so the
  rule also holds against ad-hoc SQL, not only against this class.
* The original two tables (``predictions`` and ``outcomes``) keep their exact
  schema and contents. The ledger fingerprint is computed over
  ``predictions`` only, so additive schema upgrades never change it.
* Results are first stored as *observations* (one row per source and score).
  A fixture is settled only when every source in the run agrees. A later
  observation that disagrees with a settled outcome is logged as a conflict;
  the settled row is never overwritten. An operator resolves a conflict by
  appending a correction (``record_correction``) with a reason.
* Postponed / rescheduled / cancelled / abandoned / awarded matches are
  recorded as append-only ``fixture_events``. ``fixture_status`` derives the
  scoring status from those events (see ``docs/PROSPECTIVE_EVALUATION.md``).
* Challenger forecasts live in their own table keyed by (fixture, model) so
  that the champion table and its fingerprint stay untouched.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class LedgerError(ValueError):
    pass


class ConflictingResultError(LedgerError):
    pass


EVENT_TYPES = ("POSTPONED", "RESCHEDULED", "CANCELLED", "ABANDONED", "AWARDED", "VOID", "OVERDUE")
# Event types that remove a forecast from scoring permanently.
VOIDING_EVENTS = ("CANCELLED", "AWARDED", "VOID")
MATCH_DURATION = timedelta(hours=2)

_APPEND_ONLY_TABLES = (
    "predictions", "outcomes", "challenger_predictions", "fixture_events",
    "result_observations", "outcome_corrections", "data_quality_issues", "runs",
)

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS predictions (
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
    )""",
    """CREATE TABLE IF NOT EXISTS outcomes (
        fixture_key TEXT PRIMARY KEY,
        recorded_at TEXT NOT NULL,
        home_goals INTEGER NOT NULL,
        away_goals INTEGER NOT NULL,
        outcome TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS challenger_predictions (
        fixture_key TEXT NOT NULL,
        model_id TEXT NOT NULL,
        predicted_at TEXT NOT NULL,
        kickoff_at TEXT NOT NULL,
        p_home REAL NOT NULL,
        p_draw REAL NOT NULL,
        p_away REAL NOT NULL,
        model_version TEXT NOT NULL,
        code_sha TEXT,
        data_snapshot_hash TEXT,
        payload_json TEXT NOT NULL,
        PRIMARY KEY (fixture_key, model_id)
    )""",
    """CREATE TABLE IF NOT EXISTS fixture_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixture_key TEXT NOT NULL,
        event_type TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        source TEXT NOT NULL,
        new_kickoff_at TEXT,
        detail TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS result_observations (
        observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixture_key TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        source TEXT NOT NULL,
        source_ref TEXT,
        home_goals INTEGER NOT NULL,
        away_goals INTEGER NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS outcome_corrections (
        correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        fixture_key TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        home_goals INTEGER NOT NULL,
        away_goals INTEGER NOT NULL,
        reason TEXT NOT NULL,
        operator TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS data_quality_issues (
        issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        recorded_at TEXT NOT NULL,
        run_id TEXT,
        severity TEXT NOT NULL,
        code TEXT NOT NULL,
        fixture_key TEXT,
        detail TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        status TEXT NOT NULL,
        summary_json TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_obs_fixture ON result_observations(fixture_key)",
    "CREATE INDEX IF NOT EXISTS idx_events_fixture ON fixture_events(fixture_key)",
]


def _utc(dt: datetime) -> datetime:
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise LedgerError("datetime must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def outcome_label(home_goals: int, away_goals: int) -> str:
    return "H" if home_goals > away_goals else ("D" if home_goals == away_goals else "A")


def season_of(day: date) -> str:
    """English season label: matches from July onwards belong to ``YYYY-YY``."""
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def split_fixture_key(key: str) -> Tuple[date, str, str]:
    try:
        day, home, away = key.split("|")
        return date.fromisoformat(day), home, away
    except ValueError as exc:
        raise LedgerError(f"malformed fixture key {key!r}") from exc


def match_identity(key: str) -> Tuple[str, str, str]:
    """(season, home, away): unique per league season regardless of date moves."""
    day, home, away = split_fixture_key(key)
    return season_of(day), home, away


def _validate_probs(p_home: float, p_draw: float, p_away: float) -> None:
    values = (p_home, p_draw, p_away)
    if any(not isinstance(v, (int, float)) or v != v for v in values):
        raise LedgerError("probabilities must be finite numbers")
    if min(values) < 0 or abs(sum(values) - 1.0) > 1e-6:
        raise LedgerError("probabilities must be non-negative and sum to 1")


def _validate_goals(home_goals: int, away_goals: int) -> None:
    for g in (home_goals, away_goals):
        if isinstance(g, bool) or not isinstance(g, int) or g < 0 or g > 30:
            raise LedgerError(f"implausible goal count {g!r}")


@dataclass(frozen=True)
class FixtureStatus:
    fixture_key: str
    status: str            # settled | void | conflict | pending | overdue | postponed | abandoned
    scorable: bool
    home_goals: Optional[int] = None
    away_goals: Optional[int] = None
    outcome: Optional[str] = None
    reason: str = ""


class ProspectiveLedger:
    """Append-only forecast ledger.

    ``create=False`` refuses to create a missing database, so a lost ledger
    file can never be silently replaced by an empty one. ``read_only=True``
    opens with SQLite ``mode=ro`` (used by the prediction service).
    """

    def __init__(self, path: str | Path, *, create: bool = True, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if not self.path.exists():
            if read_only or not create:
                raise LedgerError(f"ledger database not found: {self.path}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        if read_only:
            self._conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        else:
            self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError as exc:
            self._conn.close()
            raise LedgerError(f"ledger database is unreadable or corrupt: {exc}") from exc
        if not read_only:
            self._migrate()

    # ------------------------------------------------------------------ schema
    def _migrate(self) -> None:
        with self._conn:
            for statement in _SCHEMA:
                self._conn.execute(statement)
            for table in _APPEND_ONLY_TABLES:
                for action in ("UPDATE", "DELETE"):
                    self._conn.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} "
                        f"BEFORE {action} ON {table} "
                        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
                    )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ProspectiveLedger":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _has_table(self, name: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    # -------------------------------------------------------------- forecasts
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
        _validate_probs(p_home, p_draw, p_away)
        split_fixture_key(fixture_key)
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
            "SELECT payload_json FROM predictions WHERE fixture_key=?", (fixture_key,)).fetchone()
        if existing is not None:
            if existing["payload_json"] == payload_json:
                return False
            raise LedgerError(f"prediction already exists for {fixture_key} and differs")
        twin = self.find_prediction_for_match(fixture_key)
        if twin is not None:
            raise LedgerError(f"{fixture_key} is already forecast under {twin['fixture_key']} "
                              "(same season and pairing; a rescheduled match is not re-forecast)")
        with self._conn:
            self._conn.execute(
                """INSERT INTO predictions
                (fixture_key, predicted_at, kickoff_at, p_home, p_draw, p_away,
                 expected_goals_home, expected_goals_away, model_version, code_sha,
                 data_snapshot_hash, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fixture_key, predicted_at.isoformat(), kickoff_at.isoformat(), p_home, p_draw,
                 p_away, expected_goals_home, expected_goals_away, model_version, code_sha,
                 data_snapshot_hash, payload_json),
            )
        return True

    def record_challenger_prediction(
        self,
        *,
        model_id: str,
        fixture_key: str,
        predicted_at: datetime,
        kickoff_at: datetime,
        p_home: float,
        p_draw: float,
        p_away: float,
        model_version: str,
        code_sha: Optional[str] = None,
        data_snapshot_hash: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        predicted_at = _utc(predicted_at)
        kickoff_at = _utc(kickoff_at)
        if predicted_at >= kickoff_at:
            raise LedgerError("prediction must be recorded before kickoff")
        _validate_probs(p_home, p_draw, p_away)
        split_fixture_key(fixture_key)
        payload_json = json.dumps({"fixture_key": fixture_key, "model_id": model_id,
                                   "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
                                   "model_version": model_version, "extra": extra or {}},
                                  sort_keys=True)
        existing = self._conn.execute(
            "SELECT payload_json FROM challenger_predictions WHERE fixture_key=? AND model_id=?",
            (fixture_key, model_id)).fetchone()
        if existing is not None:
            if existing["payload_json"] == payload_json:
                return False
            raise LedgerError(f"challenger {model_id} already forecast {fixture_key} differently")
        with self._conn:
            self._conn.execute(
                """INSERT INTO challenger_predictions
                (fixture_key, model_id, predicted_at, kickoff_at, p_home, p_draw, p_away,
                 model_version, code_sha, data_snapshot_hash, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (fixture_key, model_id, predicted_at.isoformat(), kickoff_at.isoformat(),
                 p_home, p_draw, p_away, model_version, code_sha, data_snapshot_hash, payload_json),
            )
        return True

    def get_prediction(self, fixture_key: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM predictions WHERE fixture_key=?", (fixture_key,)).fetchone()
        return dict(row) if row else None

    def find_prediction_for_match(self, fixture_key: str) -> Optional[Dict[str, Any]]:
        """Existing champion forecast for the same (season, home, away), any date."""
        season, home, away = match_identity(fixture_key)
        rows = self._conn.execute(
            "SELECT * FROM predictions WHERE fixture_key LIKE ?", (f"%|{home}|{away}",)).fetchall()
        for row in rows:
            if match_identity(row["fixture_key"]) == (season, home, away):
                return dict(row)
        return None

    def predictions(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._conn.execute("SELECT * FROM predictions ORDER BY kickoff_at, fixture_key")]

    def challenger_predictions(self, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._has_table("challenger_predictions"):
            return []
        if model_id is None:
            rows = self._conn.execute("SELECT * FROM challenger_predictions ORDER BY kickoff_at, fixture_key, model_id")
        else:
            rows = self._conn.execute("SELECT * FROM challenger_predictions WHERE model_id=? "
                                      "ORDER BY kickoff_at, fixture_key", (model_id,))
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- results
    def record_outcome(self, fixture_key: str, home_goals: int, away_goals: int,
                       recorded_at: datetime) -> bool:
        """Settle a fixture once. Identical repeat -> False; different score -> error."""
        recorded_at = _utc(recorded_at)
        if home_goals < 0 or away_goals < 0:
            raise LedgerError("goals must be non-negative")
        existing = self._conn.execute(
            "SELECT home_goals, away_goals FROM outcomes WHERE fixture_key=?", (fixture_key,)).fetchone()
        if existing is not None:
            if existing["home_goals"] == home_goals and existing["away_goals"] == away_goals:
                return False
            raise ConflictingResultError(f"outcome already recorded for {fixture_key} and differs")
        with self._conn:
            self._conn.execute(
                "INSERT INTO outcomes (fixture_key, recorded_at, home_goals, away_goals, outcome) "
                "VALUES (?, ?, ?, ?, ?)",
                (fixture_key, recorded_at.isoformat(), home_goals, away_goals,
                 outcome_label(home_goals, away_goals)),
            )
        return True

    def observe_and_settle(
        self,
        fixture_key: str,
        observations: Sequence[Tuple[str, int, int, Optional[str]]],
        observed_at: datetime,
        *,
        run_id: Optional[str] = None,
    ) -> str:
        """Store source observations, then settle if they agree.

        ``observations`` is a list of ``(source, home_goals, away_goals,
        source_ref)``. Returns one of ``settled``, ``already_settled``,
        ``conflict`` (sources disagree, or they disagree with a settled
        outcome; nothing is overwritten) or ``no_observation``.
        """
        observed_at = _utc(observed_at)
        if not observations:
            return "no_observation"
        for source, hg, ag, ref in observations:
            _validate_goals(hg, ag)
            seen = self._conn.execute(
                "SELECT 1 FROM result_observations WHERE fixture_key=? AND source=? "
                "AND home_goals=? AND away_goals=? AND COALESCE(source_ref,'')=COALESCE(?, '')",
                (fixture_key, source, hg, ag, ref)).fetchone()
            if seen is None:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO result_observations (fixture_key, observed_at, source, source_ref, "
                        "home_goals, away_goals) VALUES (?, ?, ?, ?, ?, ?)",
                        (fixture_key, observed_at.isoformat(), source, ref, hg, ag))
        scores = {(hg, ag) for _, hg, ag, _ in observations}
        if len(scores) > 1:
            detail = "; ".join(f"{s}={hg}-{ag}" for s, hg, ag, _ in observations)
            self.log_issue("error", "conflicting_sources", detail, fixture_key=fixture_key,
                           run_id=run_id, at=observed_at)
            return "conflict"
        (hg, ag), = scores
        settled = self.effective_outcome(fixture_key)
        if settled is not None:
            if (settled[0], settled[1]) == (hg, ag):
                return "already_settled"
            sources = ",".join(sorted({s for s, *_ in observations}))
            self.log_issue("error", "result_conflicts_with_settled",
                           f"settled {settled[0]}-{settled[1]}, now observed {hg}-{ag} from {sources}",
                           fixture_key=fixture_key, run_id=run_id, at=observed_at)
            return "conflict"
        self.record_outcome(fixture_key, hg, ag, observed_at)
        return "settled"

    def record_correction(self, fixture_key: str, home_goals: int, away_goals: int, *,
                          reason: str, operator: str, recorded_at: datetime) -> None:
        """Operator resolution of a conflict. The original outcome row stays as is."""
        _validate_goals(home_goals, away_goals)
        if not reason.strip() or not operator.strip():
            raise LedgerError("a correction needs a reason and an operator")
        if self.get_outcome(fixture_key) is None:
            raise LedgerError("nothing to correct: fixture has no settled outcome")
        with self._conn:
            self._conn.execute(
                "INSERT INTO outcome_corrections (fixture_key, recorded_at, home_goals, away_goals, reason, operator) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fixture_key, _utc(recorded_at).isoformat(), home_goals, away_goals, reason, operator))

    def get_outcome(self, fixture_key: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM outcomes WHERE fixture_key=?", (fixture_key,)).fetchone()
        return dict(row) if row else None

    def effective_outcome(self, fixture_key: str) -> Optional[Tuple[int, int, str]]:
        """Latest correction if any, else the settled outcome."""
        if self._has_table("outcome_corrections"):
            row = self._conn.execute(
                "SELECT home_goals, away_goals FROM outcome_corrections WHERE fixture_key=? "
                "ORDER BY correction_id DESC LIMIT 1", (fixture_key,)).fetchone()
            if row is not None:
                return row["home_goals"], row["away_goals"], outcome_label(row["home_goals"], row["away_goals"])
        out = self.get_outcome(fixture_key)
        if out is None:
            return None
        return out["home_goals"], out["away_goals"], out["outcome"]

    def observations(self, fixture_key: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._has_table("result_observations"):
            return []
        if fixture_key is None:
            rows = self._conn.execute("SELECT * FROM result_observations ORDER BY observation_id")
        else:
            rows = self._conn.execute("SELECT * FROM result_observations WHERE fixture_key=? "
                                      "ORDER BY observation_id", (fixture_key,))
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- events
    def record_event(self, fixture_key: str, event_type: str, *, recorded_at: datetime, source: str,
                     detail: str = "", new_kickoff_at: Optional[datetime] = None) -> bool:
        event_type = event_type.upper()
        if event_type not in EVENT_TYPES:
            raise LedgerError(f"unknown event type {event_type!r}; expected one of {EVENT_TYPES}")
        if event_type == "RESCHEDULED" and new_kickoff_at is None:
            raise LedgerError("a RESCHEDULED event needs new_kickoff_at")
        split_fixture_key(fixture_key)
        new_ko = _utc(new_kickoff_at).isoformat() if new_kickoff_at else None
        exists = self._conn.execute(
            "SELECT 1 FROM fixture_events WHERE fixture_key=? AND event_type=? AND source=? "
            "AND COALESCE(new_kickoff_at,'')=COALESCE(?, '') AND detail=?",
            (fixture_key, event_type, source, new_ko, detail)).fetchone()
        if exists:
            return False
        with self._conn:
            self._conn.execute(
                "INSERT INTO fixture_events (fixture_key, event_type, recorded_at, source, new_kickoff_at, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (fixture_key, event_type, _utc(recorded_at).isoformat(), source, new_ko, detail))
        return True

    def events(self, fixture_key: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self._has_table("fixture_events"):
            return []
        if fixture_key is None:
            rows = self._conn.execute("SELECT * FROM fixture_events ORDER BY event_id")
        else:
            rows = self._conn.execute("SELECT * FROM fixture_events WHERE fixture_key=? ORDER BY event_id",
                                      (fixture_key,))
        return [dict(r) for r in rows]

    def open_conflicts(self) -> List[str]:
        if not self._has_table("data_quality_issues"):
            return []
        keys = {r["fixture_key"] for r in self._conn.execute(
            "SELECT DISTINCT fixture_key FROM data_quality_issues WHERE code IN "
            "('conflicting_sources', 'result_conflicts_with_settled') AND fixture_key IS NOT NULL")}
        resolved = set()
        for key in keys:
            last_issue = self._conn.execute(
                "SELECT MAX(recorded_at) AS t FROM data_quality_issues WHERE fixture_key=? AND code IN "
                "('conflicting_sources', 'result_conflicts_with_settled')", (key,)).fetchone()["t"]
            fix = self._conn.execute(
                "SELECT MAX(recorded_at) AS t FROM outcome_corrections WHERE fixture_key=?", (key,)).fetchone()["t"]
            if fix is not None and _parse(fix) >= _parse(last_issue):
                resolved.add(key)
        return sorted(keys - resolved)

    def fixture_status(self, fixture_key: str, now: datetime, *, grace_hours: float = 60.0) -> FixtureStatus:
        """Scoring status of one champion forecast (pre-registered rules).

        * CANCELLED / AWARDED / VOID event -> ``void`` (never scored).
        * Latest RESCHEDULED kickoff earlier than or equal to ``predicted_at``
          -> ``void`` (the forecast would not be pre-kickoff any more).
        * Open result conflict -> ``conflict`` (excluded until corrected).
        * Settled outcome -> ``settled`` (scored; a forecast whose match was
          rescheduled to a later date stays valid and is scored).
        * ABANDONED without a later result -> ``abandoned`` (outstanding).
        * POSTPONED without a later result -> ``postponed`` (outstanding).
        * Otherwise ``pending`` before kickoff + 2 h + grace, else ``overdue``.
        """
        now = _utc(now)
        pred = self.get_prediction(fixture_key)
        if pred is None:
            raise LedgerError(f"no champion forecast for {fixture_key}")
        events = self.events(fixture_key)
        types = [e["event_type"] for e in events]
        for e in events:
            if e["event_type"] in VOIDING_EVENTS:
                return FixtureStatus(fixture_key, "void", False, reason=f"{e['event_type']}: {e['detail']}")
        kickoff = _parse(pred["kickoff_at"])
        resched = [e for e in events if e["event_type"] == "RESCHEDULED"]
        if resched:
            kickoff = _parse(resched[-1]["new_kickoff_at"])
            if kickoff <= _parse(pred["predicted_at"]):
                return FixtureStatus(fixture_key, "void", False,
                                     reason="rescheduled to a kickoff at or before the forecast time")
        if fixture_key in self.open_conflicts():
            return FixtureStatus(fixture_key, "conflict", False, reason="conflicting results; needs correction")
        outcome = self.effective_outcome(fixture_key)
        if outcome is not None:
            note = "rescheduled" if resched else ""
            return FixtureStatus(fixture_key, "settled", True, outcome[0], outcome[1], outcome[2], note)
        if "ABANDONED" in types:
            return FixtureStatus(fixture_key, "abandoned", False, reason="abandoned; awaiting replay result")
        if "POSTPONED" in types and not resched:
            return FixtureStatus(fixture_key, "postponed", False, reason="postponed; no new date recorded")
        if now <= kickoff + MATCH_DURATION + timedelta(hours=grace_hours):
            return FixtureStatus(fixture_key, "pending", False)
        return FixtureStatus(fixture_key, "overdue", False,
                             reason=f"no result {grace_hours:.0f} h after expected full time")

    # ---------------------------------------------------------- data quality
    def log_issue(self, severity: str, code: str, detail: str, *, fixture_key: Optional[str] = None,
                  run_id: Optional[str] = None, at: Optional[datetime] = None) -> bool:
        if severity not in ("info", "warning", "error"):
            raise LedgerError("severity must be info, warning or error")
        exists = self._conn.execute(
            "SELECT 1 FROM data_quality_issues WHERE code=? AND COALESCE(fixture_key,'')=COALESCE(?, '') "
            "AND detail=?", (code, fixture_key, detail)).fetchone()
        if exists:
            return False
        with self._conn:
            self._conn.execute(
                "INSERT INTO data_quality_issues (recorded_at, run_id, severity, code, fixture_key, detail) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ((_utc(at) if at else datetime.now(timezone.utc)).isoformat(), run_id, severity, code,
                 fixture_key, detail))
        return True

    def issues(self) -> List[Dict[str, Any]]:
        if not self._has_table("data_quality_issues"):
            return []
        return [dict(r) for r in self._conn.execute("SELECT * FROM data_quality_issues ORDER BY issue_id")]

    def record_run(self, run_id: str, started_at: datetime, status: str, summary: Dict[str, Any]) -> bool:
        if self._conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone():
            return False
        with self._conn:
            self._conn.execute("INSERT INTO runs (run_id, started_at, status, summary_json) VALUES (?, ?, ?, ?)",
                               (run_id, _utc(started_at).isoformat(), status,
                                json.dumps(summary, sort_keys=True, default=str)))
        return True

    def runs(self) -> List[Dict[str, Any]]:
        if not self._has_table("runs"):
            return []
        return [dict(r) for r in self._conn.execute("SELECT * FROM runs ORDER BY started_at")]

    # -------------------------------------------------------------- integrity
    def fingerprint(self) -> str:
        """SHA-256 over champion forecasts only (unchanged by schema upgrades)."""
        rows = self._conn.execute(
            "SELECT fixture_key, payload_json FROM predictions ORDER BY fixture_key").fetchall()
        payload = json.dumps([tuple(r) for r in rows])
        return hashlib.sha256(payload.encode()).hexdigest()

    def challenger_fingerprint(self) -> str:
        rows = self._conn.execute(
            "SELECT fixture_key, model_id, payload_json FROM challenger_predictions "
            "ORDER BY fixture_key, model_id").fetchall() if self._has_table("challenger_predictions") else []
        return hashlib.sha256(json.dumps([tuple(r) for r in rows]).encode()).hexdigest()

    def integrity_report(self) -> Dict[str, Any]:
        """Physical and logical checks. ``ok`` is False if anything fails."""
        problems: List[str] = []
        check = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            problems.append(f"sqlite integrity_check: {check}")
        preds = self.predictions()
        for p in preds:
            try:
                payload = json.loads(p["payload_json"])
            except json.JSONDecodeError:
                problems.append(f"{p['fixture_key']}: payload is not JSON")
                continue
            if payload.get("fixture_key") != p["fixture_key"] or any(
                    abs(payload.get(c, -1) - p[c]) > 1e-12 for c in ("p_home", "p_draw", "p_away")):
                problems.append(f"{p['fixture_key']}: payload does not match columns")
            if abs(p["p_home"] + p["p_draw"] + p["p_away"] - 1) > 1e-6:
                problems.append(f"{p['fixture_key']}: probabilities do not sum to 1")
            if _parse(p["predicted_at"]) >= _parse(p["kickoff_at"]):
                problems.append(f"{p['fixture_key']}: predicted at/after kickoff")
        for c in self.challenger_predictions():
            if _parse(c["predicted_at"]) >= _parse(c["kickoff_at"]):
                problems.append(f"{c['fixture_key']}/{c['model_id']}: predicted at/after kickoff")
        for o in [dict(r) for r in self._conn.execute("SELECT * FROM outcomes")]:
            if o["outcome"] != outcome_label(o["home_goals"], o["away_goals"]):
                problems.append(f"{o['fixture_key']}: outcome label inconsistent with score")
        triggers = {r[0] for r in self._conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        expected = {f"{t}_no_{a}" for t in _APPEND_ONLY_TABLES for a in ("update", "delete")}
        missing = sorted(expected - triggers)
        if missing and not self.read_only:
            problems.append(f"append-only triggers missing: {missing}")
        return {
            "ok": not problems,
            "problems": problems,
            "sqlite_integrity_check": check,
            "champion_forecasts": len(preds),
            "challenger_forecasts": len(self.challenger_predictions()),
            "outcomes": self._conn.execute("SELECT count(*) FROM outcomes").fetchone()[0],
            "fingerprint": self.fingerprint(),
            "challenger_fingerprint": self.challenger_fingerprint(),
            "append_only_triggers_missing": missing,
        }


def iter_keys(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [r["fixture_key"] for r in rows]
