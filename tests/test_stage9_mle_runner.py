"""Offline temporal-split tests for the Stage 9 production MLE runner."""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import run_stage9_mle_backtest as runner


def make_matches(start, n_days, season):
    rows = []
    for offset in range(n_days):
        day = start + timedelta(days=offset)
        rows.extend([
            {"Date": pd.Timestamp(day), "Season": season, "available_at":
             pd.Timestamp(day).tz_localize("UTC") + pd.Timedelta(hours=36),
             "HomeTeam": "arsenal", "AwayTeam": "chelsea", "FTHG": 2, "FTAG": 1},
            {"Date": pd.Timestamp(day), "Season": season, "available_at":
             pd.Timestamp(day).tz_localize("UTC") + pd.Timedelta(hours=36),
             "HomeTeam": "chelsea", "AwayTeam": "arsenal", "FTHG": 0, "FTAG": 0},
        ])
    return pd.DataFrame(rows)


def test_development_runner_keeps_calendar_dates_out_of_training(monkeypatch):
    data = make_matches(date(2024, 1, 1), 20, "2023-24")
    fit_cutoffs = []

    def fake_fit(training, xi, reg, verbose, as_of_date):
        fit_cutoffs.append((training["Date"].max(), pd.Timestamp(as_of_date)))
        cutoff_utc = pd.Timestamp(as_of_date).tz_localize("UTC")
        assert training["Date"].max().normalize() < pd.Timestamp(as_of_date).normalize()
        assert pd.to_datetime(training["available_at"], utc=True).max() <= cutoff_utc
        teams = set(training["HomeTeam"]) | set(training["AwayTeam"])
        return {
            "attack": {team: 0.0 for team in teams},
            "data_sha256": "testhash",
            "model_version": "test-model",
        }

    monkeypatch.setattr(runner.dc, "fit_model", fake_fit)
    monkeypatch.setattr(
        runner.dc, "_predict_outcome_probs",
        lambda params, home, away, allow_new_teams: np.array([0.5, 0.25, 0.25]),
    )
    report, predictions = runner.evaluate_period(
        data, pd.DataFrame(columns=data.columns),
        label="test", min_train_matches=4, step_days=7, xi=0.0, reg=1.0,
    )
    assert report["n_predictions"] == len(predictions)
    assert report["n_folds"] == len(fit_cutoffs)
    assert report["n_predictions"] > 0
    assert all(train_max.normalize() < cutoff.normalize() for train_max, cutoff in fit_cutoffs)


def test_holdout_runner_starts_from_development_data_without_using_future_holdout(monkeypatch):
    development = make_matches(date(2023, 1, 1), 10, "2022-23")
    holdout = make_matches(date(2024, 1, 1), 5, "2023-24")
    seen = []

    def fake_fit(training, xi, reg, verbose, as_of_date):
        cutoff = pd.Timestamp(as_of_date)
        assert training["Date"].max().normalize() < cutoff.normalize()
        assert pd.to_datetime(training["available_at"], utc=True).max() <= cutoff.tz_localize("UTC")
        seen.append((training["Date"].max(), cutoff))
        teams = set(training["HomeTeam"]) | set(training["AwayTeam"])
        return {
            "attack": {team: 0.0 for team in teams},
            "data_sha256": "testhash",
            "model_version": "test-model",
        }

    monkeypatch.setattr(runner.dc, "fit_model", fake_fit)
    monkeypatch.setattr(
        runner.dc, "_predict_outcome_probs",
        lambda params, home, away, allow_new_teams: np.array([0.5, 0.25, 0.25]),
    )
    report, predictions = runner.evaluate_period(
        holdout, development, label="holdout",
        min_train_matches=4, step_days=7, xi=0.0, reg=1.0,
    )
    assert report["n_predictions"] == len(holdout)
    assert len(predictions) == len(holdout)
    assert seen
    assert all(train_max < cutoff for train_max, cutoff in seen)



def test_runner_excludes_results_not_yet_available_at_prediction_cutoff(monkeypatch):
    seed = make_matches(date(2024, 1, 1), 2, "2023-24")
    # Make the second day's results arrive after the third-day prediction cutoff.
    seed.loc[seed["Date"] == pd.Timestamp("2024-01-02"), "available_at"] = (
        pd.Timestamp("2024-01-02", tz="UTC") + pd.Timedelta(hours=36)
    )
    seed.loc[seed["Date"] == pd.Timestamp("2024-01-01"), "available_at"] = (
        pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=12)
    )
    evaluation = make_matches(date(2024, 1, 3), 1, "2023-24")
    seen = []

    def fake_fit(training, xi, reg, verbose, as_of_date):
        seen.append(training["Date"].dt.date.unique().tolist())
        teams = set(training["HomeTeam"]) | set(training["AwayTeam"])
        return {
            "attack": {team: 0.0 for team in teams},
            "data_sha256": "testhash",
            "model_version": "test-model",
        }

    monkeypatch.setattr(runner.dc, "fit_model", fake_fit)
    monkeypatch.setattr(
        runner.dc, "_predict_outcome_probs",
        lambda params, home, away, allow_new_teams: np.array([0.5, 0.25, 0.25]),
    )
    report, predictions = runner.evaluate_period(
        evaluation, seed, label="availability",
        min_train_matches=2, step_days=7, xi=0.0, reg=1.0,
    )
    assert report["n_predictions"] == 2
    assert len(seen) == 1
    assert set(seen[0]) == {date(2024, 1, 1)}
