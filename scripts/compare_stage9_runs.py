#!/usr/bin/env python3
"""Paired comparison of two Stage 9 backtest prediction files on identical fixtures.

Both runs must cover exactly the same (period, date, home, away) rows with the
same training cutoffs; otherwise the comparison is refused. Reports per-period
metrics and a paired ISO-week block bootstrap of candidate-minus-baseline loss.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_stage9_mle_backtest import metrics_for_rows, paired_week_bootstrap  # noqa: E402

KEY = ["period", "date", "home_team", "away_team"]


def compare(baseline: pd.DataFrame, candidate: pd.DataFrame, *, samples: int = 2000) -> dict:
    for name, frame in (("baseline", baseline), ("candidate", candidate)):
        if frame.duplicated(KEY).any():
            raise ValueError(f"{name} has duplicate fixture rows")
    merged = baseline.merge(candidate, on=KEY, suffixes=("_base", "_cand"), validate="one_to_one")
    if len(merged) != len(baseline) or len(merged) != len(candidate):
        raise ValueError("runs do not cover identical fixtures")
    if (merged["actual_base"] != merged["actual_cand"]).any():
        raise ValueError("runs disagree on outcomes")
    if (merged["prediction_cutoff_utc_base"] != merged["prediction_cutoff_utc_cand"]).any():
        raise ValueError("runs used different prediction cutoffs")
    out = {}
    for period, group in merged.groupby("period"):
        rows = [
            {"date": r.date, "actual": r.actual_base,
             "p_home": r.p_home_cand, "p_draw": r.p_draw_cand, "p_away": r.p_away_cand,
             "b_home": r.p_home_base, "b_draw": r.p_draw_base, "b_away": r.p_away_base}
            for r in group.itertuples()
        ]
        base_rows = [{"date": r["date"], "actual": r["actual"], "p_home": r["b_home"],
                      "p_draw": r["b_draw"], "p_away": r["b_away"]} for r in rows]
        identical = float((group[["p_home_base", "p_draw_base", "p_away_base"]].values
                           - group[["p_home_cand", "p_draw_cand", "p_away_cand"]].values).__abs__().max())
        out[period] = {
            "n": int(len(group)),
            "baseline": metrics_for_rows(base_rows),
            "candidate": metrics_for_rows(rows),
            "max_abs_probability_difference": identical,
            "paired_bootstrap": paired_week_bootstrap(
                rows, baseline_fields=("b_home", "b_draw", "b_away"), samples=samples),
        }
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, help="baseline predictions.csv")
    parser.add_argument("--candidate", required=True, help="candidate predictions.csv")
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--samples", type=int, default=2000)
    args = parser.parse_args(argv)
    baseline = pd.read_csv(args.baseline)
    candidate = pd.read_csv(args.candidate)
    result = compare(baseline, candidate, samples=args.samples)
    accepted = all(
        p["paired_bootstrap"]["log_loss_difference_ci95_upper"] < 0
        and p["paired_bootstrap"]["brier_difference_candidate_minus_baseline"] <= 0
        for p in result.values()
    )
    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline": args.baseline_label,
        "candidate": args.candidate_label,
        "acceptance_rule": "every period: log-loss diff CI95 upper < 0 and Brier diff <= 0",
        "decision": "ACCEPT" if accepted else "REJECT",
        "periods": result,
    }
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for period, p in result.items():
        b = p["paired_bootstrap"]
        print(f"{period:14s} n={p['n']:4d} {args.baseline_label} LL={p['baseline']['log_loss']:.4f} "
              f"{args.candidate_label} LL={p['candidate']['log_loss']:.4f} "
              f"dLL={b['log_loss_difference_candidate_minus_baseline']:+.4f} "
              f"CI[{b['log_loss_difference_ci95_lower']:+.4f},{b['log_loss_difference_ci95_upper']:+.4f}] "
              f"maxdiff={p['max_abs_probability_difference']:.2e}")
    print("decision:", report["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
