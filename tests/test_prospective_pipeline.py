"""End-to-end tests of the scheduled prospective pipeline on a synthetic league."""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_prospective_forecast as pipeline  # noqa: E402
from stages.stage9.prospective_ledger import ProspectiveLedger  # noqa: E402
from stages.stage1.data_store import canonical_team  # noqa: E402
from tests.prospective_synth import TEAMS, argv, build, round_kickoff, write_wikipedia  # noqa: E402

NOW1 = "2026-11-10T12:00:00+00:00"   # next round (13) kicks off 14 Nov 15:00 UTC
NOW2 = "2026-11-17T12:00:00+00:00"


@pytest.fixture(scope="module")
def first_run(tmp_path_factory):
    env = build(tmp_path_factory.mktemp("league"))
    code = pipeline.main(argv(env, NOW1, "--init-ledger"))
    return env, code


def _ledger(env, **kw):
    return ProspectiveLedger(env["ledger"], create=False, **kw)


def _latest_run(env):
    runs = sorted((env["out"] / "runs").glob("run_*.json"))
    return json.loads(runs[-1].read_text())


def test_first_run_records_champion_and_challengers(first_run):
    env, code = first_run
    assert code == 0
    with _ledger(env) as ledger:
        preds = ledger.predictions()
        assert len(preds) == 10
        for p in preds:
            assert p["model_version"] == "alea-dc-v2.4.1"
            assert p["data_snapshot_hash"] and len(p["data_snapshot_hash"]) == 64
            assert abs(p["p_home"] + p["p_draw"] + p["p_away"] - 1) < 1e-9
            extra = json.loads(p["payload_json"])["extra"]
            assert extra["wikipedia_revid"] == 1000 and extra["training_matches"] > 2600
            assert datetime.fromisoformat(p["predicted_at"]) < datetime.fromisoformat(p["kickoff_at"])
        challengers = ledger.challenger_predictions()
        assert {c["model_id"] for c in challengers} == {"elo_ordered_logit", "dc_elo_equal_average"}
        assert len(challengers) == 20
        avg = {c["fixture_key"]: c for c in ledger.challenger_predictions("dc_elo_equal_average")}
        elo = {c["fixture_key"]: c for c in ledger.challenger_predictions("elo_ordered_logit")}
        for p in preds:
            k = p["fixture_key"]
            assert avg[k]["p_home"] == pytest.approx((p["p_home"] + elo[k]["p_home"]) / 2, abs=1e-9)
    report = (env["out"] / "report.md").read_text()
    assert "Run id" in report and "Wikipedia" in report and "insufficient data" in report
    assert list((env["out"] / "logs").glob("run_*.log"))


def test_rerun_is_idempotent_and_never_overwrites(first_run):
    env, _ = first_run
    with _ledger(env) as ledger:
        before = (ledger.fingerprint(), ledger.challenger_fingerprint())
    assert pipeline.main(argv(env, "2026-11-10T18:00:00+00:00")) == 0
    run = _latest_run(env)
    assert run["forecasts_recorded"] == 0 and run["forecasts_already_in_ledger"] == 10
    assert run["challenger_forecasts_recorded"] == 0
    with _ledger(env) as ledger:
        assert (ledger.fingerprint(), ledger.challenger_fingerprint()) == before


def test_results_settle_and_next_round_is_forecast(first_run):
    env, _ = first_run
    write_wikipedia(env, played_rounds=14, revid=1001, timestamp="2026-11-15T20:00:00Z")
    assert pipeline.main(argv(env, NOW2)) == 0
    run = _latest_run(env)
    assert len(run["outcomes_settled"]) == 10 and run["forecasts_recorded"] == 10
    with _ledger(env) as ledger:
        ev = json.loads((env["out"] / "evaluation.json").read_text())
        assert ev["counts"]["scored"] == 10
        for m in ("log_loss", "brier", "rps", "accuracy"):
            assert m in ev["champion"]
        assert ev["challengers"]["dc_elo_equal_average"]["n_paired"] == 10
        # Settling again changes nothing.
        assert pipeline.main(argv(env, "2026-11-17T13:00:00+00:00")) == 0
        assert _latest_run(env)["outcomes_settled"] == []
        assert len([o for o in ledger.observations() if o["source"] == "wikipedia"]) == 10


def test_conflicting_later_result_is_logged_not_overwritten(first_run):
    env, _ = first_run
    h, a = env["rounds"][13][0]
    original = env["results"][(h, a)][:2]
    changed = (original[0] + 3, original[1])
    write_wikipedia(env, played_rounds=14, revid=1002, timestamp="2026-11-16T09:00:00Z",
                    overrides={(h, a): changed})
    assert pipeline.main(argv(env, "2026-11-17T14:00:00+00:00")) == 0
    run = _latest_run(env)
    assert len(run["settlement_conflicts"]) == 1
    key = run["settlement_conflicts"][0]
    with _ledger(env) as ledger:
        assert ledger.get_outcome(key)["home_goals"] == original[0]
        assert ledger.fixture_status(key, datetime(2026, 11, 17, 14, tzinfo=timezone.utc)).status == "conflict"
        codes = {i["code"] for i in ledger.issues()}
        assert "result_conflicts_with_settled" in codes
    write_wikipedia(env, played_rounds=14, revid=1003, timestamp="2026-11-16T10:00:00Z")


def test_stale_feed_blocks_forecasting_with_exit_2(first_run):
    env, _ = first_run
    with _ledger(env) as ledger:
        before = len(ledger.predictions())
    # Round 14 (21 Nov) is due by 30 Nov but the feed still ends at round 13.
    assert pipeline.main(argv(env, "2026-11-30T12:00:00+00:00")) == 2
    run = _latest_run(env)
    assert run["status"] == "blocked" and "incomplete" in run["reason"]
    with _ledger(env) as ledger:
        assert len(ledger.predictions()) == before
        assert any(i["code"] == "run_blocked" for i in ledger.issues())
    assert "blocked" in (env["out"] / "report.md").read_text()


def test_cross_source_disagreement_blocks(tmp_path):
    env = build(tmp_path)
    doc = json.loads(env["fixtures"].read_text())
    doc["matches"][0]["score"] = {"ft": [9, 9]}  # OpenFootball disagrees with Wikipedia
    env["fixtures"].write_text(json.dumps(doc))
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 2
    assert "disagree" in _latest_run(env)["reason"]
    with _ledger(env) as ledger:
        assert ledger.predictions() == []


def test_isolated_postponement_is_tolerated_and_logged(tmp_path):
    env = build(tmp_path)
    h, a = env["rounds"][5][3]
    write_wikipedia(env, played_rounds=13, omit={(h, a)})
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 0
    run = _latest_run(env)
    assert len(run["gates"]["suspected_postponed"]) == 1
    with _ledger(env) as ledger:
        assert any(i["code"] == "suspected_postponement" for i in ledger.issues())


def test_unparseable_due_cell_blocks(tmp_path):
    env = build(tmp_path)
    h, a = env["rounds"][12][0]
    write_wikipedia(env, played_rounds=13, extra_cells={(h, a): "P"})
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 2


def test_missing_ledger_is_not_silently_recreated(tmp_path):
    env = build(tmp_path)
    assert pipeline.main(argv(env, NOW1)) == 3
    assert not env["ledger"].exists()
    assert _latest_run(env)["status"] == "failed"


def test_corrupt_ledger_fails_closed(tmp_path):
    env = build(tmp_path)
    env["ledger"].write_bytes(b"this is not a sqlite database" * 100)
    assert pipeline.main(argv(env, NOW1)) == 3


def test_tampered_champion_hash_blocks(tmp_path):
    env = build(tmp_path)
    reg = json.loads(env["registry"].read_text())
    reg["champion"]["module_sha256"] = "0" * 64
    env["registry"].write_text(json.dumps(reg))
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 2
    assert "frozen champion" in _latest_run(env)["reason"]


def test_backdated_run_cannot_use_future_revision(tmp_path):
    env = build(tmp_path)
    write_wikipedia(env, played_rounds=13, timestamp="2026-12-01T00:00:00Z")
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 2
    assert "newer than the run time" in _latest_run(env)["reason"]


def test_fixtures_inside_min_lead_are_not_forecast(tmp_path):
    env = build(tmp_path)
    # 13 Nov 12:00: round 13 kicks off in 27 h, inside the 48 h minimum lead.
    assert pipeline.main(argv(env, "2026-11-13T12:00:00+00:00", "--init-ledger")) == 0
    run = _latest_run(env)
    assert run["forecasts_recorded"] == 0 and len(run["too_close_to_kickoff"]) == 10


def test_never_forecasts_started_or_played_match(tmp_path):
    env = build(tmp_path, played_rounds=13)
    # A round-13 match already has a result although its listed date is later
    # (moved earlier): it must not be forecast.
    h, a = env["rounds"][13][2]
    x, y, _ = env["results"][(h, a)]
    write_wikipedia(env, played_rounds=13, extra_cells={(h, a): f"{x}\u2013{y}"})
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 0
    run = _latest_run(env)
    assert run["forecasts_recorded"] == 9
    moved = (canonical_team(TEAMS[h]), canonical_team(TEAMS[a]))
    assert all((f["home"], f["away"]) != moved for f in run["forecasts"])


def test_inconsistent_team_names_block(tmp_path):
    env = build(tmp_path)
    snap = json.loads(env["wiki"].read_text())
    snap["wikitext"] = snap["wikitext"].replace("|name_TOT=[[Tottenham Hotspur F.C.|Tottenham Hotspur]]",
                                                "|name_TOT=[[Spurs Reserve XI]]")
    env["wiki"].write_text(json.dumps(snap))
    assert pipeline.main(argv(env, NOW1, "--init-ledger")) == 2
    assert "inconsistent" in _latest_run(env)["reason"]


def test_append_only_triggers_reject_sql_tampering(first_run):
    env, _ = first_run
    con = sqlite3.connect(env["ledger"])
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("UPDATE predictions SET p_home = 0.99")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        con.execute("DELETE FROM outcomes")
    con.close()


def test_round_kickoff_helper_matches_fixture_times():
    assert round_kickoff(13) == datetime(2026, 11, 14, 15, tzinfo=timezone.utc)
