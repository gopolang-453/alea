"""Settlement, fixture events, conflicts and schema-upgrade rules of the ledger."""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from stages.stage9.prospective_evaluation import evaluate_ledger, promotion_decision, render_markdown
from stages.stage9.prospective_ledger import (
    ConflictingResultError,
    LedgerError,
    ProspectiveLedger,
    match_identity,
    season_of,
)

KO = datetime(2026, 11, 28, 15, tzinfo=timezone.utc)
PRED_AT = KO - timedelta(days=4)
KEY = "2026-11-28|arsenal|chelsea"
REGISTRY = {
    "champion": {"model_version": "alea-dc-v2.4.1"},
    "challengers": [{"model_id": "c1", "model_version": "c1-v1"}],
    "promotion_rule": {"min_paired_settled_fixtures": 300},
}


def _pred(ledger, key=KEY, kickoff=KO, predicted=PRED_AT, p=(0.5, 0.3, 0.2), version="alea-dc-v2.4.1"):
    return ledger.record_prediction(fixture_key=key, predicted_at=predicted, kickoff_at=kickoff,
                                    p_home=p[0], p_draw=p[1], p_away=p[2], model_version=version)


@pytest.fixture
def ledger(tmp_path):
    with ProspectiveLedger(tmp_path / "l.sqlite") as led:
        _pred(led)
        yield led


def test_season_and_identity():
    assert season_of(datetime(2026, 8, 1).date()) == "2026-27"
    assert season_of(datetime(2027, 5, 20).date()) == "2026-27"
    assert match_identity("2027-01-03|a|b") == ("2026-27", "a", "b")
    with pytest.raises(LedgerError):
        match_identity("not-a-key")


def test_pending_then_overdue_when_result_missing(ledger):
    assert ledger.fixture_status(KEY, KO - timedelta(hours=1)).status == "pending"
    assert ledger.fixture_status(KEY, KO + timedelta(hours=30)).status == "pending"
    st = ledger.fixture_status(KEY, KO + timedelta(days=4))
    assert st.status == "overdue" and not st.scorable


def test_settlement_is_idempotent(ledger):
    obs = [("wikipedia", 2, 1, "r1")]
    assert ledger.observe_and_settle(KEY, obs, KO + timedelta(hours=3)) == "settled"
    assert ledger.observe_and_settle(KEY, obs, KO + timedelta(hours=9)) == "already_settled"
    assert len(ledger.observations(KEY)) == 1
    st = ledger.fixture_status(KEY, KO + timedelta(days=1))
    assert (st.status, st.outcome, st.home_goals, st.away_goals) == ("settled", "H", 2, 1)


def test_conflicting_sources_in_one_run_do_not_settle(ledger):
    obs = [("wikipedia", 2, 1, "r1"), ("openfootball", 1, 1, None)]
    assert ledger.observe_and_settle(KEY, obs, KO + timedelta(hours=3)) == "conflict"
    assert ledger.get_outcome(KEY) is None
    assert ledger.fixture_status(KEY, KO + timedelta(days=1)).status == "conflict"
    assert ledger.issues()[0]["code"] == "conflicting_sources"


def test_conflict_with_settled_result_then_operator_correction(ledger):
    ledger.observe_and_settle(KEY, [("wikipedia", 2, 1, "r1")], KO + timedelta(hours=3))
    assert ledger.observe_and_settle(KEY, [("wikipedia", 2, 2, "r2")], KO + timedelta(hours=6)) == "conflict"
    assert ledger.get_outcome(KEY)["home_goals"] == 2 and ledger.get_outcome(KEY)["away_goals"] == 1
    assert ledger.fixture_status(KEY, KO + timedelta(days=1)).status == "conflict"
    with pytest.raises(ConflictingResultError):
        ledger.record_outcome(KEY, 2, 2, KO + timedelta(hours=7))
    with pytest.raises(LedgerError):
        ledger.record_correction(KEY, 2, 2, reason="", operator="ops", recorded_at=KO + timedelta(hours=8))
    ledger.record_correction(KEY, 2, 2, reason="official match report", operator="ops",
                             recorded_at=KO + timedelta(hours=8))
    st = ledger.fixture_status(KEY, KO + timedelta(days=1))
    assert (st.status, st.outcome) == ("settled", "D")
    assert ledger.get_outcome(KEY)["away_goals"] == 1  # original row untouched


def test_postponed_then_rescheduled_later_remains_valid(ledger):
    ledger.record_event(KEY, "POSTPONED", recorded_at=KO - timedelta(hours=20), source="ops", detail="weather")
    assert ledger.fixture_status(KEY, KO + timedelta(days=5)).status == "postponed"
    new_ko = KO + timedelta(days=30)
    with pytest.raises(LedgerError):
        ledger.record_event(KEY, "RESCHEDULED", recorded_at=KO, source="ops")
    ledger.record_event(KEY, "RESCHEDULED", recorded_at=KO, source="ops", new_kickoff_at=new_ko)
    assert ledger.fixture_status(KEY, KO + timedelta(days=5)).status == "pending"
    ledger.observe_and_settle(KEY, [("wikipedia", 0, 0, "r9")], new_ko + timedelta(hours=3))
    st = ledger.fixture_status(KEY, new_ko + timedelta(days=1))
    assert st.status == "settled" and st.scorable and st.reason == "rescheduled"


def test_rescheduled_earlier_than_forecast_is_void(ledger):
    ledger.record_event(KEY, "RESCHEDULED", recorded_at=KO, source="ops",
                        new_kickoff_at=PRED_AT - timedelta(hours=1))
    ledger.observe_and_settle(KEY, [("wikipedia", 1, 0, "r")], KO)
    st = ledger.fixture_status(KEY, KO + timedelta(days=1))
    assert st.status == "void" and not st.scorable


@pytest.mark.parametrize("event", ["CANCELLED", "AWARDED", "VOID"])
def test_voiding_events_exclude_from_scoring(ledger, event):
    ledger.record_event(KEY, event, recorded_at=KO + timedelta(hours=1), source="ops", detail="x")
    ledger.observe_and_settle(KEY, [("wikipedia", 3, 0, "r")], KO + timedelta(hours=3))
    assert ledger.fixture_status(KEY, KO + timedelta(days=1)).status == "void"


def test_abandoned_waits_for_replay(ledger):
    ledger.record_event(KEY, "ABANDONED", recorded_at=KO + timedelta(hours=1), source="ops", detail="floodlights")
    assert ledger.fixture_status(KEY, KO + timedelta(days=3)).status == "abandoned"
    ledger.observe_and_settle(KEY, [("wikipedia", 1, 2, "r")], KO + timedelta(days=20))
    assert ledger.fixture_status(KEY, KO + timedelta(days=21)).status == "settled"


def test_duplicate_events_are_ignored_and_unknown_rejected(ledger):
    assert ledger.record_event(KEY, "POSTPONED", recorded_at=KO, source="ops", detail="d") is True
    assert ledger.record_event(KEY, "postponed", recorded_at=KO, source="ops", detail="d") is False
    with pytest.raises(LedgerError):
        ledger.record_event(KEY, "MOVED", recorded_at=KO, source="ops")


def test_rescheduled_pair_cannot_be_forecast_twice(ledger):
    with pytest.raises(LedgerError, match="already forecast"):
        _pred(ledger, key="2026-12-15|arsenal|chelsea", kickoff=KO + timedelta(days=17))
    # Same pairing next season is a different match.
    assert _pred(ledger, key="2027-11-28|arsenal|chelsea", kickoff=KO + timedelta(days=365),
                 predicted=KO + timedelta(days=360)) is True


def test_goal_validation(ledger):
    with pytest.raises(LedgerError):
        ledger.observe_and_settle(KEY, [("wikipedia", -1, 0, None)], KO)
    with pytest.raises(LedgerError):
        ledger.observe_and_settle(KEY, [("wikipedia", 1.5, 0, None)], KO)
    assert ledger.observe_and_settle(KEY, [], KO) == "no_observation"


def test_challenger_rows_are_append_only_and_pre_kickoff(ledger):
    kw = dict(model_id="c1", fixture_key=KEY, predicted_at=PRED_AT, kickoff_at=KO,
              p_home=0.4, p_draw=0.3, p_away=0.3, model_version="c1-v1")
    assert ledger.record_challenger_prediction(**kw) is True
    assert ledger.record_challenger_prediction(**kw) is False
    with pytest.raises(LedgerError):
        ledger.record_challenger_prediction(**{**kw, "p_home": 0.5, "p_away": 0.2})
    with pytest.raises(LedgerError):
        ledger.record_challenger_prediction(**{**kw, "model_id": "c2", "predicted_at": KO})


def test_missing_and_read_only_modes(tmp_path):
    with pytest.raises(LedgerError):
        ProspectiveLedger(tmp_path / "missing.sqlite", create=False)
    with pytest.raises(LedgerError):
        ProspectiveLedger(tmp_path / "missing.sqlite", read_only=True)
    assert not (tmp_path / "missing.sqlite").exists()
    path = tmp_path / "l.sqlite"
    with ProspectiveLedger(path) as led:
        _pred(led)
    with ProspectiveLedger(path, read_only=True) as ro:
        assert len(ro.predictions()) == 1
        with pytest.raises(sqlite3.OperationalError):
            _pred(ro, key="2026-11-29|x|y")


def test_corrupt_file_is_reported(tmp_path):
    path = tmp_path / "bad.sqlite"
    path.write_bytes(b"\x00garbage" * 512)
    with pytest.raises(LedgerError, match="corrupt"):
        ProspectiveLedger(path)


def test_upgrade_of_legacy_ledger_preserves_rows_and_fingerprint(tmp_path):
    """A ledger created by the original two-table schema keeps its fingerprint."""
    path = tmp_path / "legacy.sqlite"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE predictions (fixture_key TEXT PRIMARY KEY, predicted_at TEXT NOT NULL,
        kickoff_at TEXT NOT NULL, p_home REAL NOT NULL, p_draw REAL NOT NULL, p_away REAL NOT NULL,
        expected_goals_home REAL, expected_goals_away REAL, model_version TEXT NOT NULL, code_sha TEXT,
        data_snapshot_hash TEXT, payload_json TEXT NOT NULL)""")
    con.execute("""CREATE TABLE outcomes (fixture_key TEXT PRIMARY KEY, recorded_at TEXT NOT NULL,
        home_goals INTEGER NOT NULL, away_goals INTEGER NOT NULL, outcome TEXT NOT NULL)""")
    payload = json.dumps({"fixture_key": KEY, "p_home": 0.5, "p_draw": 0.3, "p_away": 0.2,
                          "model_version": "alea-dc-v2.4.1", "extra": {}}, sort_keys=True)
    con.execute("INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (KEY, PRED_AT.isoformat(), KO.isoformat(), 0.5, 0.3, 0.2, None, None, "alea-dc-v2.4.1",
                 "sha", "hash", payload))
    con.commit()
    expected = hashlib.sha256(json.dumps([(KEY, payload)]).encode()).hexdigest()
    con.close()
    with ProspectiveLedger(path, read_only=True) as ro:
        assert ro.fingerprint() == expected
        assert ro.challenger_predictions() == [] and ro.events() == []
    with ProspectiveLedger(path, create=False) as led:
        assert led.fingerprint() == expected
        report = led.integrity_report()
        assert report["ok"], report["problems"]
        assert led.get_prediction(KEY)["payload_json"] == payload


def test_integrity_report_detects_tampering_done_without_triggers(tmp_path):
    path = tmp_path / "l.sqlite"
    with ProspectiveLedger(path) as led:
        _pred(led)
    con = sqlite3.connect(path)
    con.execute("DROP TRIGGER predictions_no_update")
    con.execute("UPDATE predictions SET p_home = 0.6")
    con.commit()
    con.close()
    with ProspectiveLedger(path, read_only=True) as ro:
        report = ro.integrity_report()
    assert not report["ok"]
    assert any("payload does not match" in p for p in report["problems"])
    assert any("sum to 1" in p for p in report["problems"])


def _settled_ledger(tmp_path, n_weeks=4, per_week=5, challenger_shift=0.0):
    led = ProspectiveLedger(tmp_path / "eval.sqlite")
    rng = np.random.default_rng(3)
    for w in range(n_weeks):
        for i in range(per_week):
            ko = KO + timedelta(days=7 * w)
            key = f"{ko.date().isoformat()}|h{w}_{i}|a{w}_{i}"
            _pred(led, key=key, kickoff=ko, predicted=ko - timedelta(days=3))
            led.record_challenger_prediction(model_id="c1", fixture_key=key, predicted_at=ko - timedelta(days=3),
                                             kickoff_at=ko, p_home=0.5 - challenger_shift,
                                             p_draw=0.3, p_away=0.2 + challenger_shift, model_version="c1-v1")
            hg, ag = int(rng.integers(0, 3)), int(rng.integers(0, 3))
            led.observe_and_settle(key, [("wikipedia", hg, ag, "r")], ko + timedelta(hours=3))
    return led


def test_evaluation_metrics_cis_and_decision(tmp_path):
    led = _settled_ledger(tmp_path, challenger_shift=0.05)
    ev = evaluate_ledger(led, REGISTRY, KO + timedelta(days=60))
    ch = ev["champion"]
    assert ch["n"] == 20 and ch["n_week_blocks"] == 4
    for m in ("log_loss", "brier", "rps", "accuracy"):
        lo, hi = ch[f"{m}_ci95"]
        assert lo <= ch[m] <= hi
    # Constant probabilities -> metrics are easy to verify by hand.
    outcomes = [s["outcome"] for s in ev["settled"]]
    p = {"H": 0.5, "D": 0.3, "A": 0.2}
    assert ch["log_loss"] == pytest.approx(-np.mean([np.log(p[o]) for o in outcomes]))
    cmp_ = ev["challengers"]["c1"]
    assert cmp_["n_paired"] == 20 and cmp_["paired"]["log_loss_ci95"] is not None
    assert cmp_["decision"].startswith("insufficient data (20 of 300")
    md = render_markdown(ev)
    assert "| log_loss |" in md and "c1" in md
    led.close()


def test_promotion_rule():
    rule = {"min_paired_settled_fixtures": 300}
    good = {"n_paired": 400, "paired": {"log_loss_ci95": [-0.02, -0.001], "brier_diff": -0.001}}
    assert "eligible" in promotion_decision(good, rule)
    wide = {"n_paired": 400, "paired": {"log_loss_ci95": [-0.02, 0.003], "brier_diff": -0.001}}
    assert "champion retained" in promotion_decision(wide, rule)
    worse_brier = {"n_paired": 400, "paired": {"log_loss_ci95": [-0.02, -0.001], "brier_diff": 0.001}}
    assert "champion retained" in promotion_decision(worse_brier, rule)


def test_evaluation_flags_foreign_model_versions(tmp_path):
    with ProspectiveLedger(tmp_path / "f.sqlite") as led:
        _pred(led, version="something-else")
        ev = evaluate_ledger(led, REGISTRY, KO + timedelta(days=1))
        assert ev["foreign_model_versions_in_champion_table"] == ["something-else"]
        assert "WARNING" in render_markdown(ev)
