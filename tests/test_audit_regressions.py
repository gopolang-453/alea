"""Regression tests for defects found in the November 2026 final audit of PR #4.

Each test names the defect it guards against. All data is synthetic.
"""
import json
import shutil
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_prospective_forecast as pipeline  # noqa: E402
from scripts import verify_ledger_update  # noqa: E402
from stages.stage9 import prospective_evaluation as pe  # noqa: E402
from stages.stage9.prospective_ledger import LedgerError, ProspectiveLedger  # noqa: E402
from stages.stage12.ledger_ops import verify_append_only_update  # noqa: E402
from tests.prospective_synth import argv, build, write_wikipedia  # noqa: E402

NOW1 = "2026-11-10T12:00:00+00:00"
UTC = timezone.utc
WORKFLOW = ROOT / ".github" / "workflows" / "weekly-prospective-forecast.yml"


def _latest_run(env):
    return json.loads(sorted((env["out"] / "runs").glob("run_*.json"))[-1].read_text())


def _drop_triggers(path):
    conn = sqlite3.connect(path)
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")
    conn.commit()
    return conn


@pytest.fixture(scope="module")
def first_run(tmp_path_factory):
    env = build(tmp_path_factory.mktemp("league"))
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 0
    return env


# ------------------------------------------------------------ commit gate
def test_commit_gate_accepts_a_genuine_append(first_run, tmp_path):
    env = first_run
    before = tmp_path / "before.sqlite"
    shutil.copy(env["ledger"], before)
    after = tmp_path / "after.sqlite"
    shutil.copy(env["ledger"], after)
    with ProspectiveLedger(after, create=False) as ledger:
        ledger.log_issue("info", "synthetic", "new row", at=datetime(2026, 11, 11, tzinfo=UTC))
    verdict = verify_append_only_update(before, after)
    assert verdict["ok"], verdict["problems"]
    assert verdict["row_counts"]["data_quality_issues"]["after"] == \
        verdict["row_counts"]["data_quality_issues"]["before"] + 1


def test_commit_gate_rejects_rewritten_or_deleted_rows(first_run, tmp_path):
    before = tmp_path / "before.sqlite"
    shutil.copy(first_run["ledger"], before)
    for sql in ("DELETE FROM challenger_predictions WHERE rowid = (SELECT min(rowid) FROM challenger_predictions)",
                "UPDATE runs SET status='ok-edited'"):
        after = tmp_path / "after.sqlite"
        shutil.copy(first_run["ledger"], after)
        conn = _drop_triggers(after)
        conn.execute(sql)
        conn.commit()
        conn.close()
        verdict = verify_append_only_update(before, after)
        assert not verdict["ok"]
        assert any("changed or removed" in p or "triggers missing" in p for p in verdict["problems"])


def test_commit_gate_rejects_missing_corrupt_or_emptied_ledger(first_run, tmp_path):
    before = tmp_path / "before.sqlite"
    shutil.copy(first_run["ledger"], before)
    assert not verify_append_only_update(before, tmp_path / "absent.sqlite")["ok"]
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64 + b"garbage" * 200)
    assert not verify_append_only_update(before, corrupt)["ok"]
    fresh = tmp_path / "fresh.sqlite"
    ProspectiveLedger(fresh).close()  # a newly initialised, empty ledger
    verdict = verify_append_only_update(before, fresh)
    assert not verdict["ok"] and any("predictions:" in p for p in verdict["problems"])


def test_commit_gate_cli_exit_codes(first_run, tmp_path):
    report = tmp_path / "verdict.json"
    assert verify_ledger_update.main(["--before", str(first_run["ledger"]), "--after",
                                      str(first_run["ledger"]), "--report", str(report)]) == 0
    assert json.loads(report.read_text())["ok"] is True
    assert verify_ledger_update.main(["--before", str(first_run["ledger"]),
                                      "--after", str(tmp_path / "nope.sqlite")]) == 1


# --------------------------------------------------------- integrity report
def test_integrity_detects_duplicate_match_and_orphan_challenger(first_run, tmp_path):
    copy = tmp_path / "l.sqlite"
    shutil.copy(first_run["ledger"], copy)
    conn = _drop_triggers(copy)
    row = conn.execute("SELECT * FROM predictions LIMIT 1").fetchone()
    day, home, away = row[0].split("|")
    moved = f"{(date.fromisoformat(day) + timedelta(days=3)).isoformat()}|{home}|{away}"
    payload = json.loads(row[11])
    payload["fixture_key"] = moved
    conn.execute("INSERT INTO predictions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                 (moved, *row[1:11], json.dumps(payload, sort_keys=True)))
    conn.execute("INSERT INTO challenger_predictions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 ("2026-12-01|x fc|y fc", "elo_ordered_logit", "2026-11-10T12:00:00+00:00",
                  "2026-12-01T15:00:00+00:00", 0.5, 0.3, 0.3, "v", None, None, "{}"))
    conn.commit()
    conn.close()
    with ProspectiveLedger(copy, read_only=True) as ledger:
        problems = ledger.integrity_report()["problems"]
    assert any("duplicate forecast for the match" in p for p in problems)
    assert any("no champion forecast" in p for p in problems)
    assert any("probabilities do not sum to 1" in p for p in problems)


# ------------------------------------------------- pipeline: freshness gate
def test_international_break_is_not_treated_as_stale_feed(tmp_path):
    """Defect: gaps of up to 21 days in the 2026-27 list blocked every run as 'stale'."""
    env = build(tmp_path)
    doc = json.loads(env["fixtures"].read_text())
    for m in doc["matches"]:
        if int(m["round"].split()[-1]) >= 14:  # rounds after the last played one move 3 weeks later
            m["date"] = (date.fromisoformat(m["date"]) + timedelta(days=21)).isoformat()
    env["fixtures"].write_text(json.dumps(doc))
    # Latest result 7 Nov; next round 5 Dec; run on 1 Dec is ~570 h after the last result.
    assert pipeline.main(argv(env, "2026-12-01T12:00:00+00:00", "--init-ledger")) == 0
    run = _latest_run(env)
    assert run["gates"]["freshness"]["status"] == "fresh"
    assert run["gates"]["freshness"]["fixtures_played_since_latest_result"] == 0
    assert run["forecasts_recorded"] == 10


def test_feed_missing_played_fixtures_is_still_blocked(tmp_path):
    env = build(tmp_path)
    # Round 14 (21 Nov) has been played by 30 Nov but the feed stops at round 13.
    assert pipeline.main(argv(env, "2026-11-30T12:00:00+00:00", "--init-ledger")) == 2
    assert _latest_run(env)["status"] == "blocked"


# ----------------------------------------- pipeline: interruption / rerun
def test_interrupted_run_then_rerun_completes_without_duplicates(tmp_path, monkeypatch):
    env = build(tmp_path)
    original = ProspectiveLedger.record_challenger_prediction
    calls = {"n": 0}

    def crash_after_three(self, **kw):
        calls["n"] += 1
        if calls["n"] > 3:
            raise RuntimeError("simulated runner interruption")
        return original(self, **kw)

    monkeypatch.setattr(ProspectiveLedger, "record_challenger_prediction", crash_after_three)
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 1
    snapshot = tmp_path / "snap.sqlite"
    shutil.copy(env["ledger"], snapshot)
    with ProspectiveLedger(env["ledger"], create=False) as ledger:
        partial = ledger.integrity_report()
        assert partial["ok"]
        assert len(ledger.challenger_predictions()) == 3
        recorded = {p["fixture_key"]: p["payload_json"] for p in ledger.predictions()}
    monkeypatch.setattr(ProspectiveLedger, "record_challenger_prediction", original)
    # Rerun a few minutes later with the same data: completes the run idempotently.
    assert pipeline.main(argv(env, "2026-11-10T12:05:00+00:00")) == 0
    with ProspectiveLedger(env["ledger"], create=False) as ledger:
        assert ledger.integrity_report()["ok"]
        after = {p["fixture_key"]: p["payload_json"] for p in ledger.predictions()}
        assert all(after[k] == v for k, v in recorded.items())  # partial rows kept verbatim
        assert 0 < len(recorded) < 10 and len(after) == 10
        assert len(ledger.challenger_predictions()) == 20
    assert verify_append_only_update(snapshot, env["ledger"])["ok"]
    # Third run: nothing new, nothing changed.
    shutil.copy(env["ledger"], snapshot)
    assert pipeline.main(argv(env, "2026-11-10T12:10:00+00:00")) == 0
    with ProspectiveLedger(env["ledger"], create=False) as ledger:
        assert len(ledger.challenger_predictions()) == 20
    assert verify_append_only_update(snapshot, env["ledger"])["ok"]


def test_late_challengers_need_the_champions_information_set(tmp_path, monkeypatch):
    """Defect: challengers added in a later run could use results the champion never saw."""
    env = build(tmp_path)
    write_wikipedia(env, played_rounds=12, revid=999, timestamp="2026-11-02T09:00:00Z")
    monkeypatch.setattr(pipeline, "challenger_probabilities", lambda *a, **k: {})
    # 3 Nov: feed ends at round 12 (31 Oct); the 14 Nov round is forecast by the champion only.
    assert pipeline.main(argv(env, "2026-11-03T12:00:00+00:00", "--init-ledger", "--horizon-days", "14")) == 0
    monkeypatch.undo()
    with ProspectiveLedger(env["ledger"], create=False) as ledger:
        champion_keys = {p["fixture_key"] for p in ledger.predictions()}
        assert champion_keys and not ledger.challenger_predictions()
    # A week later one more round of results exists: the champion's forecasts for
    # the round still ahead used fewer matches, so no challenger may be added for them.
    write_wikipedia(env, played_rounds=13, revid=1001, timestamp="2026-11-09T09:00:00Z")
    assert pipeline.main(argv(env, NOW1)) == 0
    with ProspectiveLedger(env["ledger"], create=False) as ledger:
        late = [c for c in ledger.challenger_predictions() if c["fixture_key"] in champion_keys]
        codes = {i["code"] for i in ledger.issues()}
    assert late == []
    assert "challenger_not_recorded_information_changed" in codes


def test_challenger_rows_record_training_matches(tmp_path):
    env = build(tmp_path)
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 0
    with ProspectiveLedger(env["ledger"], create=False) as ledger:
        champ = {p["fixture_key"]: json.loads(p["payload_json"])["extra"]["training_matches"]
                 for p in ledger.predictions()}
        for c in ledger.challenger_predictions():
            assert json.loads(c["payload_json"])["extra"]["training_matches"] == champ[c["fixture_key"]]


def test_provenance_has_urls_and_retrieval_timestamps(tmp_path):
    env = build(tmp_path)
    snap = json.loads(env["wiki"].read_text())
    snap["fetched_at"] = "2026-11-10T11:59:00+00:00"
    env["wiki"].write_text(json.dumps(snap))
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 0
    sources = _latest_run(env)["sources"]
    assert sources["results"]["url"] == "https://en.wikipedia.org/w/index.php?oldid=1000"
    assert sources["results"]["retrieved_at"] == "2026-11-10T11:59:00+00:00"
    assert sources["fixtures"]["url"].startswith("https://raw.githubusercontent.com/openfootball/")
    assert sources["fixtures"]["retrieved_at"]
    assert "CC BY-SA 4.0" in sources["wikipedia_attribution"]


def test_crosscheck_csv_refused_in_github_actions(tmp_path, monkeypatch):
    env = build(tmp_path)
    csv = tmp_path / "fd.csv"
    csv.write_text("Date,HomeTeam,AwayTeam,FTHG,FTAG\n")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert pipeline.main(argv(env, NOW1, "--init-ledger", "--crosscheck-csv", str(csv))) == 2
    assert "local use only" in _latest_run(env)["reason"]
    with ProspectiveLedger(env["ledger"], create=False) as ledger:
        assert ledger.predictions() == []


def test_post_write_integrity_failure_returns_3(tmp_path, monkeypatch):
    env = build(tmp_path)
    real = ProspectiveLedger.integrity_report
    calls = {"n": 0}

    def fail_second(self):
        calls["n"] += 1
        report = real(self)
        if calls["n"] == 2:
            report = {**report, "ok": False, "problems": ["simulated corruption after write"]}
        return report

    monkeypatch.setattr(ProspectiveLedger, "integrity_report", fail_second)
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 3
    run = _latest_run(env)
    assert run["status"] == "failed" and "after writing" in run["reason"]


# ------------------------------------------------ evaluation: pairing rules
def _settle_all(ledger, at):
    for p in ledger.predictions():
        ledger.record_outcome(p["fixture_key"], 1, 0, at)


def test_pairing_excludes_wrong_version_late_or_better_informed_challengers(first_run, tmp_path):
    copy = tmp_path / "l.sqlite"
    shutil.copy(first_run["ledger"], copy)
    registry = json.loads((ROOT / "config" / "model_registry.json").read_text())
    with ProspectiveLedger(copy, create=False) as ledger:
        _settle_all(ledger, datetime(2026, 11, 20, tzinfo=UTC))
        base = pe.evaluate_ledger(ledger, registry, datetime(2026, 11, 20, tzinfo=UTC))
    assert base["challengers"]["elo_ordered_logit"]["n_paired"] == 10
    assert base["challengers"]["elo_ordered_logit"]["settled_but_not_paired"] == {}

    conn = _drop_triggers(copy)
    rows = conn.execute("SELECT rowid, payload_json FROM challenger_predictions "
                        "WHERE model_id='elo_ordered_logit' ORDER BY rowid").fetchall()
    conn.execute("UPDATE challenger_predictions SET model_version='other' WHERE rowid=?", (rows[0][0],))
    extra = json.loads(rows[1][1])
    extra["extra"]["training_matches"] += 1
    conn.execute("UPDATE challenger_predictions SET payload_json=? WHERE rowid=?",
                 (json.dumps(extra, sort_keys=True), rows[1][0]))
    conn.execute("UPDATE challenger_predictions SET predicted_at=kickoff_at WHERE rowid=?", (rows[2][0],))
    conn.commit()
    conn.close()
    with ProspectiveLedger(copy, read_only=True) as ledger:
        res = pe.evaluate_ledger(ledger, registry, datetime(2026, 11, 20, tzinfo=UTC))
    entry = res["challengers"]["elo_ordered_logit"]
    assert entry["n_paired"] == 7
    assert entry["settled_but_not_paired"] == {
        "model_version_differs_from_registry": 1,
        "information_set_differs_from_champion": 1,
        "challenger_forecast_not_before_kickoff": 1,
    }


def test_metric_formulas_against_hand_calculation():
    p = np.array([[0.5, 0.3, 0.2], [0.2, 0.3, 0.5]])
    rows = pe._metric_rows(p, np.array([0, 1]))
    assert rows["log_loss"] == pytest.approx([-np.log(0.5), -np.log(0.3)])
    assert rows["brier"] == pytest.approx([0.25 + 0.09 + 0.04, 0.04 + 0.49 + 0.25])
    # RPS (3 ordered outcomes, normalised by r-1 = 2): cumulative H, H+D.
    assert rows["rps"] == pytest.approx([((0.5 - 1) ** 2 + (0.8 - 1) ** 2) / 2,
                                         ((0.2 - 0) ** 2 + (0.5 - 1) ** 2) / 2])
    assert rows["accuracy"].tolist() == [1.0, 0.0]


def test_minimum_counts_paired_settled_not_total_forecasts():
    rule = {"min_paired_settled_fixtures": 300}
    great = {"log_loss_ci95": [-0.05, -0.01], "brier_diff": -0.01}
    assert pe.promotion_decision({"n_paired": 299, "paired": great}, rule).startswith("insufficient")
    verdict = pe.promotion_decision({"n_paired": 300, "paired": great}, rule)
    assert "eligible for human review" in verdict and "no automatic promotion" in verdict


# ------------------------------------------------------ workflow (static)
def test_workflow_separates_diagnostics_from_commit_permission():
    import yaml

    wf = yaml.safe_load(WORKFLOW.read_text())
    steps = {s.get("id"): s for s in wf["jobs"]["forecast"]["steps"] if s.get("id")}
    text = WORKFLOW.read_text()
    commands = "\n".join(s.get("run", "") for s in wf["jobs"]["forecast"]["steps"])
    commands = "\n".join(line for line in commands.splitlines() if not line.strip().startswith("#"))
    assert "git add -A" not in commands and "git add ." not in commands
    commit_if = steps["commit"]["if"]
    assert "steps.verify.outputs.exit_code == '0'" in commit_if and "env.LIVE == 'true'" in commit_if
    assert "verify_ledger_update.py" in steps["verify"]["run"]
    live = wf["env"]["LIVE"]
    assert "refs/heads/main" in live and "'push'" not in live
    data_checkout = [s for s in wf["jobs"]["forecast"]["steps"]
                     if s.get("with", {}).get("ref") == "${{ env.DATA_BRANCH }}"][0]
    assert data_checkout["with"]["persist-credentials"] == "${{ env.LIVE == 'true' }}"
    assert wf["concurrency"]["cancel-in-progress"] is False
    assert "--crosscheck-csv" not in text
    assert "--init-ledger" not in text


def test_break_exemption_has_a_hard_ceiling():
    """Audit: an incomplete fixture list must not make a long-dead feed look fresh."""
    import pandas as pd
    from scripts.run_prospective_forecast import MAX_SCHEDULED_BREAK_HOURS, MATCH_DURATION, GateError, run_gates
    k = pd.Timestamp("2026-11-21T15:00:00Z")
    fixtures = pd.DataFrame({"home": ["arsenal"], "away": ["chelsea"], "kickoff_utc": [k]})
    results = pd.DataFrame({"home": ["arsenal"], "away": ["chelsea"], "FTHG": [1], "FTAG": [0]})
    within = (k + MATCH_DURATION + pd.Timedelta(hours=MAX_SCHEDULED_BREAK_HOURS - 1)).to_pydatetime()
    beyond = (k + MATCH_DURATION + pd.Timedelta(hours=MAX_SCHEDULED_BREAK_HOURS + 1)).to_pydatetime()
    assert run_gates(fixtures, results, {}, within, grace_hours=36, max_age_hours=240)["freshness"]["status"] == "fresh"
    with pytest.raises(GateError, match="stale"):
        run_gates(fixtures, results, {}, beyond, grace_hours=36, max_age_hours=240)
