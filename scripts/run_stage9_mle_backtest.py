#!/usr/bin/env python3
"""Production Dixon-Coles walk-forward evaluation with a final untouched season.

Run after importing OpenFootball results:
  python scripts/fetch_openfootball.py
  python scripts/run_stage9_mle_backtest.py --holdout-season 2023-24

The holdout season is evaluated prequentially: at each date block, the model may
use earlier completed results from that same season, but never that block's
results. Hyperparameters are fixed before the run and are not tuned on holdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import alea_predictor_v2_4_1 as dc
from stages.stage1.data_store import PersistentDataStore
from stages.stage8.calibration import apply_temperature, fit_temperature


def _outcome_indices(rows: list[dict]) -> np.ndarray:
    mapping = {"H": 0, "D": 1, "A": 2}
    try:
        return np.asarray([mapping[row["actual"]] for row in rows], dtype=int)
    except KeyError as exc:
        raise ValueError(f"invalid actual outcome: {exc}") from exc


def _probability_matrix(rows: list[dict], fields: tuple[str, str, str]) -> np.ndarray:
    matrix = np.asarray([[float(row[field]) for field in fields] for row in rows], dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != 3 or not np.all(np.isfinite(matrix)):
        raise ValueError("prediction probabilities must be a finite n x 3 matrix")
    if np.any(matrix < 0) or not np.allclose(matrix.sum(axis=1), 1.0, atol=1e-8):
        raise ValueError("prediction probability rows must be non-negative and sum to 1")
    return matrix


def paired_week_bootstrap(
    rows: list[dict],
    candidate_fields: tuple[str, str, str] = ("p_home", "p_draw", "p_away"),
    baseline_fields: tuple[str, str, str] = (
        "train_rate_home", "train_rate_draw", "train_rate_away"
    ),
    *,
    samples: int = 1000,
    seed: int = 20261118,
) -> dict:
    """Paired bootstrap of candidate-minus-baseline losses, resampling ISO-week blocks."""
    if samples < 1:
        raise ValueError("bootstrap samples must be positive")
    if not rows:
        raise ValueError("cannot bootstrap an empty prediction set")
    candidate = _probability_matrix(rows, candidate_fields)
    baseline = _probability_matrix(rows, baseline_fields)
    actual = _outcome_indices(rows)
    one_hot = np.eye(3)[actual]
    indices = np.arange(len(rows))
    candidate_log = -np.log(np.clip(candidate[indices, actual], 1e-15, 1.0))
    baseline_log = -np.log(np.clip(baseline[indices, actual], 1e-15, 1.0))
    candidate_brier = np.sum((candidate - one_hot) ** 2, axis=1)
    baseline_brier = np.sum((baseline - one_hot) ** 2, axis=1)
    log_diff = candidate_log - baseline_log
    brier_diff = candidate_brier - baseline_brier

    groups: dict[tuple[int, int], list[int]] = {}
    for index, row in enumerate(rows):
        iso = pd.Timestamp(row["date"]).isocalendar()
        groups.setdefault((int(iso.year), int(iso.week)), []).append(index)
    blocks = [np.asarray(group, dtype=int) for group in groups.values()]
    rng = np.random.default_rng(seed)
    boot_log = np.empty(samples, dtype=float)
    boot_brier = np.empty(samples, dtype=float)
    for iteration in range(samples):
        chosen = rng.integers(0, len(blocks), size=len(blocks))
        sample_indices = np.concatenate([blocks[index] for index in chosen])
        boot_log[iteration] = float(np.mean(log_diff[sample_indices]))
        boot_brier[iteration] = float(np.mean(brier_diff[sample_indices]))

    return {
        "method": "paired_iso_week_block_bootstrap",
        "n_predictions": int(len(rows)),
        "n_week_blocks": int(len(blocks)),
        "bootstrap_samples": int(samples),
        "seed": int(seed),
        "log_loss_difference_candidate_minus_baseline": float(np.mean(log_diff)),
        "log_loss_difference_ci95_lower": float(np.quantile(boot_log, 0.025)),
        "log_loss_difference_ci95_upper": float(np.quantile(boot_log, 0.975)),
        "brier_difference_candidate_minus_baseline": float(np.mean(brier_diff)),
        "brier_difference_ci95_lower": float(np.quantile(boot_brier, 0.025)),
        "brier_difference_ci95_upper": float(np.quantile(boot_brier, 0.975)),
    }


def metrics_for_rows(
    rows: list[dict],
    fields: tuple[str, str, str] = ("p_home", "p_draw", "p_away"),
) -> dict:
    probs = _probability_matrix(rows, fields)
    outcomes = np.eye(3)[_outcome_indices(rows)]
    return {
        "log_loss": dc.log_loss_score(probs, outcomes),
        "brier": dc.brier_score(probs, outcomes),
        "rps": dc.rps_score(probs, outcomes),
        "accuracy": float(np.mean(np.argmax(probs, axis=1) == np.argmax(outcomes, axis=1))),
    }


def evaluate_period(
    evaluation: pd.DataFrame,
    seed_training: pd.DataFrame,
    *,
    label: str,
    min_train_matches: int,
    step_days: int,
    xi: float,
    reg: float,
) -> tuple[dict, list[dict]]:
    evaluation = evaluation.sort_values("Date").reset_index(drop=True).copy()
    seed_training = seed_training.sort_values("Date").reset_index(drop=True).copy()
    if evaluation.empty:
        raise ValueError(f"{label}: no evaluation matches")
    if step_days < 1:
        raise ValueError("step_days must be >= 1")

    day = evaluation["Date"].dt.normalize()
    if seed_training.empty:
        cutoff = dc._first_cutoff_date(day, min_train_matches)
        if cutoff is None:
            raise ValueError(f"{label}: fewer than {min_train_matches} matches before a test date")
    else:
        cutoff = day.min()

    last_day = day.max()
    prediction_rows: list[dict] = []
    fold_rows: list[dict] = []

    while cutoff <= last_day:
        end = cutoff + pd.Timedelta(days=step_days)
        earlier_eval = evaluation[day < cutoff]
        test = evaluation[(day >= cutoff) & (day < end)]
        training = pd.concat([seed_training, earlier_eval], ignore_index=True)
        training = training.sort_values("Date").reset_index(drop=True)

        if test.empty:
            cutoff = end
            continue
        if "available_at" not in training.columns or training["available_at"].isna().any():
            raise ValueError("walk-forward data must contain timezone-aware available_at timestamps")
        cutoff_utc = pd.Timestamp(cutoff)
        cutoff_utc = cutoff_utc.tz_localize("UTC") if cutoff_utc.tzinfo is None else cutoff_utc.tz_convert("UTC")
        availability = pd.to_datetime(training["available_at"], utc=True, errors="coerce")
        if availability.isna().any():
            raise ValueError("walk-forward data contains invalid available_at timestamps")
        training = training.loc[availability <= cutoff_utc].copy()
        training = training.sort_values("Date").reset_index(drop=True)
        if len(training) < min_train_matches:
            cutoff = end
            continue
        if training["Date"].dt.normalize().max() >= test["Date"].dt.normalize().min():
            raise AssertionError("temporal leakage: training date overlaps test block")
        if pd.to_datetime(training["available_at"], utc=True).max() > cutoff_utc:
            raise AssertionError("availability leakage: a training result was not available at prediction cutoff")

        # A failed production MLE fit aborts the evaluation. Never silently skip a fold.
        params = dc.fit_model(
            training, xi=xi, reg=reg, verbose=False, as_of_date=cutoff
        )
        train_outcomes = np.vstack([
            dc._actual_outcome(int(row.FTHG), int(row.FTAG))
            for row in training.itertuples()
        ])
        train_rate = np.clip(train_outcomes.mean(axis=0), 1e-12, 1.0)
        train_rate /= train_rate.sum()

        fold_count = 0
        for row in test.itertuples():
            home, away = row.HomeTeam, row.AwayTeam
            prior_only = home not in params["attack"] or away not in params["attack"]
            probs = dc._predict_outcome_probs(
                params, home, away, allow_new_teams=True
            )
            actual = dc._actual_outcome(int(row.FTHG), int(row.FTAG))
            prediction_rows.append({
                "period": label,
                "season": getattr(row, "Season", ""),
                "date": row.Date.date().isoformat(),
                "home_team": home,
                "away_team": away,
                "p_home": float(probs[0]),
                "p_draw": float(probs[1]),
                "p_away": float(probs[2]),
                "actual": ("H" if actual[0] else "D" if actual[1] else "A"),
                "train_rate_home": float(train_rate[0]),
                "train_rate_draw": float(train_rate[1]),
                "train_rate_away": float(train_rate[2]),
                "training_cutoff": str(cutoff.date()),
                "training_data_through": str(training["Date"].max().date()),
                "prediction_cutoff_utc": cutoff_utc.isoformat(),
                "training_matches": int(len(training)),
                "training_data_sha256": params["data_sha256"],
                "model_version": params["model_version"],
                "prior_only_team": bool(prior_only),
            })
            fold_count += 1

        fold_rows.append({
            "cutoff": str(cutoff.date()),
            "train_matches": int(len(training)),
            "test_matches": int(fold_count),
            "train_max_date": str(training["Date"].max().date()),
            "train_max_available_at": pd.to_datetime(training["available_at"], utc=True).max().isoformat(),
            "test_min_date": str(test["Date"].min().date()),
            "test_max_date": str(test["Date"].max().date()),
            "fit_model_version": params["model_version"],
            "fit_data_sha256": params["data_sha256"],
        })
        print(f"{label} | {cutoff.date()} | train={len(training)} | test={fold_count}")
        cutoff = end

    if not prediction_rows:
        raise ValueError(f"{label}: walk-forward produced no predictions")

    probs = np.asarray([[r["p_home"], r["p_draw"], r["p_away"]] for r in prediction_rows])
    outcomes = np.asarray([
        [1.0, 0.0, 0.0] if r["actual"] == "H"
        else [0.0, 1.0, 0.0] if r["actual"] == "D"
        else [0.0, 0.0, 1.0]
        for r in prediction_rows
    ])
    rate_probs = np.asarray([
        [r["train_rate_home"], r["train_rate_draw"], r["train_rate_away"]]
        for r in prediction_rows
    ])
    uniform = np.tile([1 / 3, 1 / 3, 1 / 3], (len(outcomes), 1))

    report = {
        "period": label,
        "n_predictions": int(len(prediction_rows)),
        "n_folds": len(fold_rows),
        "n_prior_only_team_predictions": int(sum(r["prior_only_team"] for r in prediction_rows)),
        "model": {
            "log_loss": dc.log_loss_score(probs, outcomes),
            "brier": dc.brier_score(probs, outcomes),
            "rps": dc.rps_score(probs, outcomes),
            "accuracy": float(np.mean(np.argmax(probs, axis=1) == np.argmax(outcomes, axis=1))),
        },
        "training_rate_baseline": {
            "log_loss": dc.log_loss_score(rate_probs, outcomes),
            "brier": dc.brier_score(rate_probs, outcomes),
            "rps": dc.rps_score(rate_probs, outcomes),
            "accuracy": float(np.mean(np.argmax(rate_probs, axis=1) == np.argmax(outcomes, axis=1))),
        },
        "uniform_baseline": {
            "log_loss": dc.log_loss_score(uniform, outcomes),
            "brier": dc.brier_score(uniform, outcomes),
            "rps": dc.rps_score(uniform, outcomes),
            "accuracy": float(np.mean(np.argmax(uniform, axis=1) == np.argmax(outcomes, axis=1))),
        },
        "model_vs_training_rate": paired_week_bootstrap(prediction_rows),
        "folds": fold_rows,
    }
    return report, prediction_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/alea.sqlite")
    parser.add_argument("--holdout-season", default="2023-24")
    parser.add_argument("--min-train-matches", type=int, default=380)
    parser.add_argument("--step-days", type=int, default=28)
    parser.add_argument("--xi", type=float, default=0.0018)
    parser.add_argument("--reg", type=float, default=1.0)
    parser.add_argument("--output-dir", default="results/stage9_mle")
    args = parser.parse_args()

    cutoff = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    with PersistentDataStore(args.database) as store:
        fingerprint = store.fingerprint()
        data = store.snapshot(cutoff).to_results_frame()

    if data.empty or "Season" not in data.columns:
        raise SystemExit("No imported results found. Run scripts/fetch_openfootball.py first.")
    data["Date"] = pd.to_datetime(data["Date"])
    data = data.sort_values("Date").reset_index(drop=True)
    holdout = data[data["Season"] == args.holdout_season].copy()
    if holdout.empty:
        raise SystemExit(f"Holdout season {args.holdout_season!r} is not in the database.")
    holdout_start = holdout["Date"].min()
    development = data[data["Date"] < holdout_start].copy()
    if development.empty:
        raise SystemExit("No development seasons precede the selected holdout season.")

    print(f"Dataset rows: {len(data)}; development: {len(development)}; holdout: {len(holdout)}")
    print(f"Database fingerprint: {fingerprint}")
    print(f"Fixed parameters: xi={args.xi}, reg={args.reg}; no holdout tuning")

    development_report, development_rows = evaluate_period(
        development, pd.DataFrame(columns=development.columns),
        label="development_walk_forward",
        min_train_matches=args.min_train_matches,
        step_days=args.step_days, xi=args.xi, reg=args.reg,
    )
    holdout_report, holdout_rows = evaluate_period(
        holdout, development,
        label=f"final_holdout_{args.holdout_season}",
        min_train_matches=args.min_train_matches,
        step_days=args.step_days, xi=args.xi, reg=args.reg,
    )

    # Fit calibration only on development-period out-of-sample predictions.
    development_probs = _probability_matrix(
        development_rows, ("p_home", "p_draw", "p_away")
    )
    development_outcomes = np.eye(3)[_outcome_indices(development_rows)]
    calibration = fit_temperature(
        development_probs,
        development_outcomes,
        [row["date"] for row in development_rows],
        [row["training_data_through"] for row in development_rows],
        min_samples=50,
    )

    holdout_probs = _probability_matrix(holdout_rows, ("p_home", "p_draw", "p_away"))
    calibrated_holdout_probs = apply_temperature(
        holdout_probs, calibration["temperature"]
    )
    for row, calibrated in zip(holdout_rows, calibrated_holdout_probs):
        row["p_home_calibrated"] = float(calibrated[0])
        row["p_draw_calibrated"] = float(calibrated[1])
        row["p_away_calibrated"] = float(calibrated[2])

    calibrated_metrics = metrics_for_rows(
        holdout_rows, ("p_home_calibrated", "p_draw_calibrated", "p_away_calibrated")
    )
    calibrated_comparison = paired_week_bootstrap(
        holdout_rows,
        candidate_fields=("p_home_calibrated", "p_draw_calibrated", "p_away_calibrated"),
    )
    selected_fields = (
        ("p_home_calibrated", "p_draw_calibrated", "p_away_calibrated")
        if calibration["should_apply"]
        else ("p_home", "p_draw", "p_away")
    )
    selected_metrics = calibrated_metrics if calibration["should_apply"] else holdout_report["model"]
    selected_comparison = calibrated_comparison if calibration["should_apply"] else holdout_report["model_vs_training_rate"]
    selected_model_name = (
        "production_mle_temperature_scaled"
        if calibration["should_apply"] else "production_mle_raw"
    )
    holdout_report["calibrated_model"] = calibrated_metrics
    holdout_report["calibrated_vs_training_rate"] = calibrated_comparison
    holdout_report["selected_model"] = selected_model_name
    holdout_report["selected_metrics"] = selected_metrics

    registry_metrics = {
        "n_holdout": holdout_report["n_predictions"],
        "holdout_log_loss": selected_metrics["log_loss"],
        "baseline_holdout_log_loss": holdout_report["training_rate_baseline"]["log_loss"],
        "log_loss_diff_ci_upper": selected_comparison["log_loss_difference_ci95_upper"],
        "holdout_brier": selected_metrics["brier"],
        "baseline_holdout_brier": holdout_report["training_rate_baseline"]["brier"],
        "brier_diff_ci_upper": selected_comparison["brier_difference_ci95_upper"],
    }

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    predictions = development_rows + holdout_rows
    pd.DataFrame(predictions).to_csv(output / "predictions.csv", index=False)
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database_fingerprint": fingerprint,
        "model_file": "alea_predictor_v2_4_1.py",
        "model_version": dc.MODEL_VERSION,
        "holdout_season": args.holdout_season,
        "protocol": {
            "split": "chronological expanding window; calendar dates kept together",
            "minimum_training_matches": args.min_train_matches,
            "test_block_days": args.step_days,
            "xi": args.xi,
            "reg": args.reg,
            "hyperparameters_tuned_on_holdout": False,
            "unknown_team_policy": "league-average prior, flagged in prediction rows",
        },
        "development": development_report,
        "calibration": calibration,
        "final_holdout": holdout_report,
        "registry_metrics_vs_training_rate_benchmark": registry_metrics,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "development": development_report["model"],
        "final_holdout": holdout_report["model"],
        "selected_holdout_model": selected_model_name,
        "selected_holdout_metrics": selected_metrics,
        "calibration": calibration,
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
