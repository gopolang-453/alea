#!/usr/bin/env python3
"""Stage 9.4 / 9.5 — score Stage 3, 7 and 8 candidates against the DC champion.

Run after the production MLE walk-forward has written its predictions:

  python scripts/fetch_openfootball.py --seasons 2019-20 ... 2025-26
  python scripts/run_stage9_mle_backtest.py --holdout-season 2025-26 --step-days 7 \
      --output-dir results/stage9_mle
  python scripts/run_stage9_candidate_evaluation.py \
      --champion-predictions results/stage9_mle/predictions.csv

Pre-registered protocol (fixed before any candidate was scored; see
``PROTOCOL`` below and results/stage9_candidates/report.json):

* Champion: frozen alea-dc-v2.4.1, fixed xi=0.0018, reg=1, weekly refit.
* Every candidate is prequential. Features use only results available at the
  champion's prediction cutoff for that block; any mapping is refitted at each
  cutoff on earlier rows whose results were available by that cutoff.
* All models are scored on the identical set of fixtures (rows where every
  candidate has a prediction).
* Acceptance: a candidate replaces the champion only if, on the final holdout,
  the paired ISO-week bootstrap 95% CI of (candidate - champion) log loss lies
  entirely below zero, its Brier is not worse, and its development log loss is
  also lower. Otherwise it is rejected.
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

from stages.stage1.data_store import PersistentDataStore
from stages.stage9.candidates import (
    EloConfig,
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

PROTOCOL = {
    "champion": "alea-dc-v2.4.1 fixed xi=0.0018 reg=1.0, weekly refit (Stage 9 runner output)",
    "elo": {"initial_rating": 1500.0, "k_factor": 20.0, "home_advantage": 50.0,
            "source": "stages.stage3.team_features.elo_ratings defaults"},
    "form": {"window": 5, "ppg_prior_for_teams_with_fewer_than_3_matches": 1.0},
    "elo_burn_in_matches_excluded_from_mapping_training": 380,
    "min_training_rows_for_feature_mappings": 380,
    "min_prior_oos_rows_for_stackers": 380,
    "stacker": "multinomial logistic, ridge 0.01, standardised inputs",
    "ordered_logit_ridge": 0.001,
    "bootstrap": "paired ISO-week block bootstrap, 2000 samples, seed 20261124",
    "acceptance": ("holdout log-loss diff CI95 upper < 0 AND holdout Brier diff <= 0 "
                   "AND development log-loss diff < 0"),
    "candidates": [
        "rate_baseline", "elo_ordered_logit", "form_ordered_logit",
        "dc_restack_control", "dc_plus_elo_stack", "dc_plus_elo_form_stack",
        "dc_rolling_temperature", "dc_elo_equal_average",
    ],
}


def load_results(database: str) -> tuple[pd.DataFrame, str]:
    cutoff = datetime(9999, 12, 31, tzinfo=timezone.utc)
    with PersistentDataStore(database) as store:
        fingerprint = store.fingerprint()
        frame = store.snapshot(cutoff).to_results_frame()
    frame["Date"] = pd.to_datetime(frame["Date"]).dt.normalize()
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
    frame["actual"] = np.where(frame.FTHG > frame.FTAG, "H",
                               np.where(frame.FTHG == frame.FTAG, "D", "A"))
    return frame.sort_values("Date").reset_index(drop=True), fingerprint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default="data/alea_openfootball.sqlite")
    parser.add_argument("--champion-predictions", default="results/stage9_mle/predictions.csv")
    parser.add_argument("--output-dir", default="results/stage9_candidates")
    args = parser.parse_args()

    results, fingerprint = load_results(args.database)
    champ = pd.read_csv(args.champion_predictions)
    champ["Date"] = pd.to_datetime(champ["date"]).dt.normalize()
    champ = champ.rename(columns={"home_team": "HomeTeam", "away_team": "AwayTeam"})
    champ["cutoff_utc"] = pd.to_datetime(champ["prediction_cutoff_utc"], utc=True)
    keyed = results.set_index(["Date", "HomeTeam", "AwayTeam"])
    joined = champ.join(keyed[["available_at", "actual"]].rename(
        columns={"available_at": "result_available_at", "actual": "actual_db"}),
        on=["Date", "HomeTeam", "AwayTeam"])
    if joined["result_available_at"].isna().any():
        raise SystemExit("champion predictions contain fixtures missing from the database")
    if (joined["actual"] != joined["actual_db"]).any():
        raise SystemExit("champion prediction outcomes disagree with the database")
    rows = joined.reset_index(drop=True)
    if (rows["cutoff_utc"] >= rows["result_available_at"]).any():
        raise SystemExit("a champion prediction cutoff is not before its own result")

    # --- Stage 3 features at the champion's cutoff for every prediction row.
    elo_cfg = EloConfig()
    rows[["elo_diff", "form_diff"]] = pre_match_features(results, rows, elo=elo_cfg).values

    # Training pool for feature-only mappings: every historical match with its
    # own pre-match features (as of 00:00 UTC on match day), excluding Elo burn-in.
    pool = results.copy()
    pool["cutoff_utc"] = pool["Date"].dt.tz_localize("UTC")
    pool[["elo_diff", "form_diff"]] = pre_match_features(results, pool, elo=elo_cfg).values
    pool = pool.iloc[PROTOCOL["elo_burn_in_matches_excluded_from_mapping_training"]:].copy()
    pool = pool.rename(columns={"available_at": "result_available_at"})

    dc_p = rows[["p_home", "p_draw", "p_away"]].to_numpy()
    rate_p = rows[["train_rate_home", "train_rate_draw", "train_rate_away"]].to_numpy()
    min_rows = PROTOCOL["min_training_rows_for_feature_mappings"]
    min_stack = PROTOCOL["min_prior_oos_rows_for_stackers"]

    def ordered(column):
        def fit_predict(train, test):
            return OrderedLogit(PROTOCOL["ordered_logit_ridge"]).fit(
                train[column].to_numpy(), train["actual"].to_numpy()).predict(test[column].to_numpy())
        return fit_predict

    def stack(columns):
        def build(frame):
            parts = [dc_logit_features(frame[["p_home", "p_draw", "p_away"]].to_numpy())]
            if columns:
                parts.append(frame[columns].to_numpy() / np.array([100.0 if c == "elo_diff" else 1.0 for c in columns]))
            return np.column_stack(parts)

        def fit_predict(train, test):
            model = MultinomialStacker(0.01).fit(build(train), train["actual"].to_numpy())
            return model.predict(build(test))
        return fit_predict

    def rolling_temperature(train, test):
        t = fit_temperature_mle(train[["p_home", "p_draw", "p_away"]].to_numpy(), train["actual"].to_numpy())
        return temperature_scale(test[["p_home", "p_draw", "p_away"]].to_numpy(), t)

    elo_p = prequential(rows, ordered("elo_diff"), min_training_rows=min_rows, training_pool=pool)
    candidates = {
        "dc_champion": dc_p,
        "rate_baseline": rate_p,
        "elo_ordered_logit": elo_p,
        "form_ordered_logit": prequential(rows, ordered("form_diff"), min_training_rows=min_rows, training_pool=pool),
        "dc_restack_control": prequential(rows, stack([]), min_training_rows=min_stack),
        "dc_plus_elo_stack": prequential(rows, stack(["elo_diff"]), min_training_rows=min_stack),
        "dc_plus_elo_form_stack": prequential(rows, stack(["elo_diff", "form_diff"]), min_training_rows=min_stack),
        "dc_rolling_temperature": prequential(rows, rolling_temperature, min_training_rows=min_stack),
        "dc_elo_equal_average": (dc_p + elo_p) / 2.0,
    }

    common = np.all([np.all(np.isfinite(p), axis=1) for p in candidates.values()], axis=0)
    for name, p in candidates.items():
        ok = p[common]
        if not np.allclose(ok.sum(axis=1), 1.0, atol=1e-8) or (ok < 0).any():
            raise SystemExit(f"{name} produced invalid probability rows")
    scored = rows.loc[common].reset_index(drop=True)
    is_holdout = scored["period"].astype(str).str.startswith("final_holdout").to_numpy()
    periods = {"development": ~is_holdout, "final_holdout": is_holdout}

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database_fingerprint": fingerprint,
        "champion_predictions": args.champion_predictions,
        "protocol": PROTOCOL,
        "n_rows_total": int(len(rows)),
        "n_rows_scored_common": int(common.sum()),
        "first_scored_date": str(scored["Date"].min().date()),
        "periods": {}, "by_season": {}, "decisions": {},
    }
    for period, mask in periods.items():
        out = {}
        outcomes = scored.loc[mask, "actual"].to_numpy()
        dates = scored.loc[mask, "Date"].to_numpy()
        champion_p = candidates["dc_champion"][common][mask]
        for name, p in candidates.items():
            entry = scores(p[common][mask], outcomes)
            if name != "dc_champion":
                entry["vs_champion"] = paired_block_bootstrap(p[common][mask], champion_p, outcomes, dates)
            out[name] = entry
        report["periods"][period] = out
    for season, frame in scored.groupby("season"):
        mask = (scored["season"] == season).to_numpy()
        report["by_season"][str(season)] = {
            name: round(scores(p[common][mask], scored.loc[mask, "actual"].to_numpy())["log_loss"], 4)
            for name, p in candidates.items()
        }
    for name in candidates:
        if name == "dc_champion":
            continue
        hold = report["periods"]["final_holdout"][name]["vs_champion"]
        dev = report["periods"]["development"][name]["vs_champion"]
        accepted = hold["log_loss_ci95"][1] < 0 and hold["brier_diff"] <= 0 and dev["log_loss_diff"] < 0
        report["decisions"][name] = "ACCEPT" if accepted else "REJECT"

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    export = scored[["period", "season", "Date", "HomeTeam", "AwayTeam", "actual", "elo_diff", "form_diff"]].copy()
    for name, p in candidates.items():
        for j, label in enumerate("HDA"):
            export[f"{name}_{label}"] = p[common][:, j]
    export.to_csv(output / "predictions.csv", index=False, float_format="%.6f")

    for period in periods:
        print(f"\n== {period} ==")
        for name, entry in report["periods"][period].items():
            vs = entry.get("vs_champion")
            extra = "" if vs is None else (
                f"  dLL {vs['log_loss_diff']:+.4f} CI [{vs['log_loss_ci95'][0]:+.4f}, {vs['log_loss_ci95'][1]:+.4f}]")
            print(f"{name:26s} n={entry['n']:4d} LL={entry['log_loss']:.4f} Brier={entry['brier']:.4f} "
                  f"RPS={entry['rps']:.4f} acc={entry['accuracy']:.3f}{extra}")
    print("\nDecisions:", json.dumps(report["decisions"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
