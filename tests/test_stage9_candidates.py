"""Stage 9.4/9.5 candidate machinery: Elo parity, leakage safety, valid probabilities."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import DataStore, ingest_results_frame
from stages.stage3.team_features import elo_ratings
from stages.stage9.candidates import (
    IncrementalTeamState,
    MultinomialStacker,
    OrderedLogit,
    dc_logit_features,
    fit_temperature_mle,
    paired_block_bootstrap,
    pre_match_features,
    prequential,
    scores,
    temperature_scale,
)


def synthetic_league(n_days=60, seed=7):
    rng = np.random.default_rng(seed)
    teams = [f"team {c}" for c in "abcdefgh"]
    strength = {t: s for t, s in zip(teams, np.linspace(-0.4, 0.4, len(teams)))}
    rows = []
    start = pd.Timestamp("2024-08-03")
    for d in range(n_days):
        day = start + pd.Timedelta(days=3 * d)
        order = rng.permutation(teams)
        for i in range(0, len(order), 2):
            h, a = order[i], order[i + 1]
            hg = rng.poisson(np.exp(0.25 + strength[h] - strength[a]))
            ag = rng.poisson(np.exp(0.0 + strength[a] - strength[h]))
            rows.append({"Date": day, "HomeTeam": h, "AwayTeam": a, "FTHG": int(hg), "FTAG": int(ag)})
    frame = pd.DataFrame(rows)
    frame["available_at"] = (frame["Date"].dt.tz_localize("UTC") + pd.Timedelta(hours=36))
    return frame


def test_incremental_elo_matches_stage3_elo_ratings():
    frame = synthetic_league()
    store = DataStore()
    ingest_results_frame(store, frame.drop(columns=["available_at"]), source="synthetic")
    as_of = datetime(2024, 11, 1, tzinfo=timezone.utc)
    expected = elo_ratings(store, as_of)
    queries = pd.DataFrame({"HomeTeam": ["team a"], "AwayTeam": ["team h"], "cutoff_utc": [as_of]})
    features = pre_match_features(frame, queries)
    state = IncrementalTeamState()
    for _, batch in frame[frame.available_at <= as_of].groupby("Date"):
        state.apply_batch(batch)
    for team, rating in expected.items():
        assert state.rating(team) == pytest.approx(rating, abs=1e-9)
    assert features.loc[0, "elo_diff"] == pytest.approx(expected["team a"] + 50.0 - expected["team h"])


def test_features_never_use_results_after_cutoff():
    frame = synthetic_league()
    cutoff = pd.Timestamp("2024-09-15", tz="UTC")
    queries = pd.DataFrame({"HomeTeam": ["team a", "team c"], "AwayTeam": ["team b", "team d"],
                            "cutoff_utc": [cutoff, cutoff]})
    before = pre_match_features(frame, queries)
    scrambled = frame.copy()
    future = scrambled.available_at > cutoff
    scrambled.loc[future, ["FTHG", "FTAG"]] = scrambled.loc[future, ["FTAG", "FTHG"]].values + 5
    after = pre_match_features(scrambled, queries)
    pd.testing.assert_frame_equal(before, after)


def test_form_prior_for_teams_without_history():
    state = IncrementalTeamState()
    assert state.ppg("newly promoted") == 1.0
    assert state.ppg("newly promoted", prior=0.8) == 0.8


def test_batches_must_be_single_date_and_increasing():
    frame = synthetic_league(n_days=3)
    state = IncrementalTeamState()
    with pytest.raises(ValueError):
        state.apply_batch(frame)
    first, second = [g for _, g in frame.groupby("Date")][:2]
    state.apply_batch(second)
    with pytest.raises(ValueError):
        state.apply_batch(first)


def test_ordered_logit_and_stacker_return_valid_probabilities():
    rng = np.random.default_rng(1)
    x = rng.normal(size=600)
    p_home = 1 / (1 + np.exp(-(0.3 + 1.2 * x)))
    labels = np.where(rng.random(600) < p_home * 0.8, "H", np.where(rng.random(600) < 0.5, "D", "A"))
    probs = OrderedLogit().fit(x, labels).predict(x)
    assert np.allclose(probs.sum(axis=1), 1.0) and (probs > 0).all()
    assert probs[np.argmax(x), 0] > probs[np.argmin(x), 0]
    feats = np.column_stack([x, rng.normal(size=600)])
    stacked = MultinomialStacker().fit(feats, labels).predict(feats)
    assert np.allclose(stacked.sum(axis=1), 1.0) and (stacked > 0).all()
    with pytest.raises(ValueError):
        OrderedLogit().fit(x[:10], labels[:10])
    with pytest.raises(ValueError):
        MultinomialStacker().fit(feats[:50], labels[:50])


def test_temperature_helpers():
    p = np.tile([0.7, 0.2, 0.1], (300, 1))
    labels = np.array(["H"] * 140 + ["D"] * 90 + ["A"] * 70)
    t = fit_temperature_mle(p, labels)
    assert t > 1.0  # overconfident input gets softened
    q = temperature_scale(p, t)
    assert np.allclose(q.sum(axis=1), 1.0)
    assert np.allclose(temperature_scale(p, 1.0), p)
    assert np.isfinite(dc_logit_features(p)).all()


def test_prequential_uses_only_available_rows():
    base = pd.Timestamp("2024-01-01", tz="UTC")
    rows = pd.DataFrame({
        "cutoff_utc": [base + pd.Timedelta(days=7 * (i // 10)) for i in range(60)],
        "actual": ["H", "D", "A"] * 20,
    })
    rows["result_available_at"] = rows["cutoff_utc"] + pd.Timedelta(days=2)
    seen = []

    def fit_predict(train, test):
        seen.append((test["cutoff_utc"].iloc[0], train["result_available_at"].max()))
        return np.tile([1 / 3, 1 / 3, 1 / 3], (len(test), 1))

    out = prequential(rows, fit_predict, min_training_rows=10)
    assert np.isnan(out[:10]).all() and np.isfinite(out[10:]).all()
    for cutoff, latest in seen:
        assert latest <= cutoff


def test_scores_and_bootstrap_on_identical_models():
    p = np.tile([0.5, 0.3, 0.2], (40, 1))
    labels = ["H"] * 20 + ["D"] * 12 + ["A"] * 8
    s = scores(p, labels)
    assert s["n"] == 40 and 0 < s["log_loss"] < 2 and 0 <= s["rps"] <= 1
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    boot = paired_block_bootstrap(p, p, labels, dates, samples=200)
    assert boot["log_loss_diff"] == 0 and boot["log_loss_ci95"] == [0.0, 0.0]
