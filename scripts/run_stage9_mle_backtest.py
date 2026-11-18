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
from stages.stage1.persistent_store import PersistentDataStore


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
        if len(training) < min_train_matches:
            cutoff = end
            continue
        if training["Date"].dt.normalize().max() >= test["Date"].dt.normalize().min():
            raise AssertionError("temporal leakage: training date overlaps test block")

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
        "final_holdout": holdout_report,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "development": development_report["model"],
        "final_holdout": holdout_report["model"],
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
