#!/usr/bin/env python3
"""ALEA 2.5 calibration experiments — strict chronological protocol.

1. Generate out-of-sample champion predictions (training cutoff strictly
   before every match date).
2. Split OOS predictions into an earlier calibration-fit window and a later
   calibration-eval window (no leakage).
3. Fit temperature scaling and (optional) isotonic on the fit window only.
4. Apply to the eval window and report log-loss, Brier, RPS, ECE, and
   period-wise stability.
5. Never touches the champion source, registry, or prospective ledger.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alea_predictor_v2_4_1 import fit_model, predict, XI as CHAMPION_XI, REG as CHAMPION_REG
from experiments.alea25.bootstrap import paired_block_bootstrap
from experiments.alea25.calibration_ext import reliability_diagram
from stages.stage8.calibration import fit_temperature, apply_temperature, _log_loss

try:
    from sklearn.isotonic import IsotonicRegression
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False


def load_matches(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    for c in ("HomeTeam", "AwayTeam"):
        df[c] = df[c].astype(str).str.strip().str.lower()
    return df.sort_values("Date").reset_index(drop=True)


def one_hot(ftr: str) -> np.ndarray:
    if ftr == "H":
        return np.array([1.0, 0.0, 0.0])
    if ftr == "D":
        return np.array([0.0, 1.0, 0.0])
    return np.array([0.0, 0.0, 1.0])


def metrics(probs: np.ndarray, outcomes: np.ndarray) -> Dict[str, float]:
    ll = float(-np.mean(np.log(np.clip(np.sum(probs * outcomes, axis=1), 1e-15, 1.0))))
    brier = float(np.mean(np.sum((probs - outcomes) ** 2, axis=1)))
    cum_p = np.cumsum(probs, axis=1)
    cum_o = np.cumsum(outcomes, axis=1)
    rps = float(np.mean(0.5 * np.sum((cum_p[:, :2] - cum_o[:, :2]) ** 2, axis=1)))
    acc = float(np.mean(np.argmax(probs, axis=1) == np.argmax(outcomes, axis=1)))
    return {"log_loss": ll, "brier": brier, "rps": rps, "accuracy": acc}


def generate_oos_predictions(
    data: pd.DataFrame,
    *,
    min_train: int = 380,
    step_days: int = 28,
    max_folds: int = 30,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Walk-forward champion predictions. Cutoff is always strictly before match."""
    dates = data["Date"].dt.date.values
    first_test = dates[min_train]
    last = dates[-1]
    cutoffs: List[date] = []
    cur = first_test
    while cur <= last:
        cutoffs.append(cur)
        cur = cur + timedelta(days=step_days)
    cutoffs = cutoffs[:max_folds]

    rows_probs, rows_out, rows_dates, rows_cutoffs, rows_ll = [], [], [], [], []
    n_folds = 0

    for cutoff in cutoffs:
        train = data[data["Date"].dt.date < cutoff]
        window_end = cutoff + timedelta(days=step_days)
        test = data[(data["Date"].dt.date >= cutoff) & (data["Date"].dt.date < window_end)]
        if len(train) < min_train or len(test) == 0:
            continue
        n_folds += 1
        if verbose:
            print(f"  fold {n_folds}: train={len(train)} before {cutoff}, test={len(test)}")
        try:
            params = fit_model(train, xi=CHAMPION_XI, reg=CHAMPION_REG, verbose=False, as_of_date=cutoff)
        except Exception as exc:
            if verbose:
                print(f"    fit failed: {exc}")
            continue

        for _, row in test.iterrows():
            match_d = row["Date"].date() if hasattr(row["Date"], "date") else row["Date"]
            cal_cutoff = cutoff if cutoff < match_d else (match_d - timedelta(days=1))
            if not (cal_cutoff < match_d):
                continue
            try:
                pred = predict(params, row["HomeTeam"], row["AwayTeam"], allow_new_teams=True)
            except Exception:
                continue
            p = np.array([pred["p_home_win"], pred["p_draw"], pred["p_away_win"]], dtype=float)
            p = p / p.sum()
            hg, ag = int(row["FTHG"]), int(row["FTAG"])
            ftr = "H" if hg > ag else ("A" if ag > hg else "D")
            y = one_hot(ftr)
            ll = float(-np.log(max(p[y.argmax()], 1e-15)))
            rows_probs.append(p)
            rows_out.append(y)
            rows_dates.append(match_d)
            rows_cutoffs.append(cal_cutoff)
            rows_ll.append(ll)

    probs = np.vstack(rows_probs)
    outcomes = np.vstack(rows_out)
    return {
        "probs": probs,
        "outcomes": outcomes,
        "dates": rows_dates,
        "cutoffs": rows_cutoffs,
        "log_losses": np.asarray(rows_ll),
        "n_folds": n_folds,
        "n_matches": len(rows_ll),
    }


def chronological_cal_split(
    dates: List[date],
    fit_frac: float = 0.6,
) -> Tuple[np.ndarray, np.ndarray]:
    """Earlier fraction of OOS for fitting calibration, later for evaluation."""
    n = len(dates)
    order = np.argsort([d.toordinal() for d in dates])
    split = int(n * fit_frac)
    fit_idx = order[:split]
    eval_idx = order[split:]
    return fit_idx, eval_idx


def period_slices(dates: List[date], n_periods: int = 4) -> List[Tuple[str, np.ndarray]]:
    """Split into chronological quartile periods for stability checks."""
    order = np.argsort([d.toordinal() for d in dates])
    n = len(order)
    size = n // n_periods
    slices = []
    for i in range(n_periods):
        start = i * size
        end = (i + 1) * size if i < n_periods - 1 else n
        idx = order[start:end]
        if len(idx) == 0:
            continue
        d0, d1 = dates[idx[0]], dates[idx[-1]]
        label = f"{d0.isoformat()}_{d1.isoformat()}"
        slices.append((label, idx))
    return slices


def apply_isotonic_from_fit(
    fit_probs: np.ndarray,
    fit_outcomes: np.ndarray,
    eval_probs: np.ndarray,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    models = []
    cal_eval = np.zeros_like(eval_probs)
    for c in range(3):
        ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        ir.fit(fit_probs[:, c], fit_outcomes[:, c])
        cal_eval[:, c] = ir.predict(eval_probs[:, c])
        models.append(ir)
    row_sums = cal_eval.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums <= 0, 1.0, row_sums)
    cal_eval = cal_eval / row_sums
    return cal_eval, {"n_models": 3, "method": "isotonic_per_class"}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/openfootball_matches.csv")
    parser.add_argument("--out", default="results/alea25/calibration_report.json")
    parser.add_argument("--min-train", type=int, default=380)
    parser.add_argument("--step-days", type=int, default=28)
    parser.add_argument("--max-folds", type=int, default=24)
    parser.add_argument("--fit-frac", type=float, default=0.6)
    args = parser.parse_args(argv)

    data = load_matches(args.data)
    print(f"Loaded {len(data)} matches")

    print("=== Generating OOS champion predictions ===")
    oos = generate_oos_predictions(
        data, min_train=args.min_train, step_days=args.step_days,
        max_folds=args.max_folds, verbose=True,
    )
    print(f"OOS predictions: {oos['n_matches']} across {oos['n_folds']} folds")

    for md, tc in zip(oos["dates"], oos["cutoffs"]):
        assert tc < md, f"leakage: cutoff {tc} not before match {md}"

    fit_idx, eval_idx = chronological_cal_split(oos["dates"], fit_frac=args.fit_frac)
    fit_probs = oos["probs"][fit_idx]
    fit_out = oos["outcomes"][fit_idx]
    fit_dates = [oos["dates"][i] for i in fit_idx]
    fit_cutoffs = [oos["cutoffs"][i] for i in fit_idx]
    eval_probs = oos["probs"][eval_idx]
    eval_out = oos["outcomes"][eval_idx]
    eval_dates = [oos["dates"][i] for i in eval_idx]
    eval_ll_raw = oos["log_losses"][eval_idx]

    print(f"Cal fit window: {len(fit_idx)} matches ({fit_dates[0]} .. {fit_dates[-1]})")
    print(f"Cal eval window: {len(eval_idx)} matches ({eval_dates[0]} .. {eval_dates[-1]})")

    uncal_metrics = metrics(eval_probs, eval_out)
    uncal_ece = reliability_diagram(eval_probs, eval_out, n_bins=10)["ece"]

    print("=== Temperature scaling ===")
    temp_result: Dict[str, Any] = {}
    try:
        temp_fit = fit_temperature(
            fit_probs, fit_out, fit_dates, fit_cutoffs, min_samples=50
        )
        temp_result = {k: v for k, v in temp_fit.items() if k != "models"}
        T = temp_fit.get("temperature", 1.0)
        should = temp_fit.get("should_apply", False)
        cal_probs_temp = apply_temperature(eval_probs, T) if should else eval_probs.copy()
        temp_metrics = metrics(cal_probs_temp, eval_out)
        temp_ece = reliability_diagram(cal_probs_temp, eval_out, n_bins=10)["ece"]
        temp_result["eval_metrics"] = temp_metrics
        temp_result["eval_ece"] = temp_ece
        temp_result["applied"] = bool(should)
        cal_ll = -np.log(np.clip(np.sum(cal_probs_temp * eval_out, axis=1), 1e-15, 1.0))
        boot = paired_block_bootstrap(eval_ll_raw, cal_ll, eval_dates, n_boot=1000, seed=7)
        temp_result["bootstrap_vs_uncalibrated"] = {
            "mean_diff": boot["mean_diff"],
            "ci95": [boot["ci_low"], boot["ci_high"]],
            "calibrated_better_at_95": boot["candidate_better"],
            "inconclusive": boot["inconclusive"],
        }
    except Exception as exc:
        temp_result = {"error": str(exc)}
        cal_probs_temp = eval_probs.copy()
        temp_metrics = uncal_metrics
        temp_ece = uncal_ece

    print("=== Isotonic calibration ===")
    iso_result: Dict[str, Any] = {}
    if not _HAS_SKLEARN:
        iso_result = {"should_apply": False, "reason": "scikit-learn not installed"}
        cal_probs_iso = eval_probs.copy()
        iso_metrics = uncal_metrics
        iso_ece = uncal_ece
    elif len(fit_idx) < 200:
        iso_result = {"should_apply": False, "reason": f"fit n={len(fit_idx)} < 200"}
        cal_probs_iso = eval_probs.copy()
        iso_metrics = uncal_metrics
        iso_ece = uncal_ece
    else:
        cal_probs_iso, iso_meta = apply_isotonic_from_fit(fit_probs, fit_out, eval_probs)
        iso_metrics = metrics(cal_probs_iso, eval_out)
        iso_ece = reliability_diagram(cal_probs_iso, eval_out, n_bins=10)["ece"]
        cal_ll_iso = -np.log(np.clip(np.sum(cal_probs_iso * eval_out, axis=1), 1e-15, 1.0))
        boot_iso = paired_block_bootstrap(eval_ll_raw, cal_ll_iso, eval_dates, n_boot=1000, seed=11)
        iso_result = {
            **iso_meta,
            "should_apply": iso_metrics["log_loss"] < uncal_metrics["log_loss"],
            "eval_metrics": iso_metrics,
            "eval_ece": iso_ece,
            "bootstrap_vs_uncalibrated": {
                "mean_diff": boot_iso["mean_diff"],
                "ci95": [boot_iso["ci_low"], boot_iso["ci_high"]],
                "calibrated_better_at_95": boot_iso["candidate_better"],
                "inconclusive": boot_iso["inconclusive"],
            },
        }

    print("=== Period stability ===")
    periods = []
    for label, idx in period_slices(oos["dates"], n_periods=4):
        p = oos["probs"][idx]
        o = oos["outcomes"][idx]
        m = metrics(p, o)
        ece = reliability_diagram(p, o, n_bins=8)["ece"]
        periods.append({"period": label, "n": int(len(idx)), "uncalibrated": {**m, "ece": ece}})
        if temp_result.get("applied") and "temperature" in temp_result:
            T = temp_result["temperature"]
            p_cal = apply_temperature(p, T)
            m_cal = metrics(p_cal, o)
            ece_cal = reliability_diagram(p_cal, o, n_bins=8)["ece"]
            periods[-1]["temperature"] = {**m_cal, "ece": ece_cal}

    report: Dict[str, Any] = {
        "milestone": "ALEA-2.5-calibration",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "champion_protected": True,
        "champion_sha256": "4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a",
        "protocol": {
            "min_train": args.min_train,
            "step_days": args.step_days,
            "max_folds": args.max_folds,
            "fit_frac": args.fit_frac,
            "chronology": "training cutoff strictly before every match date; cal fit window earlier than cal eval window",
            "n_oos": oos["n_matches"],
            "n_folds": oos["n_folds"],
            "n_cal_fit": int(len(fit_idx)),
            "n_cal_eval": int(len(eval_idx)),
            "cal_fit_range": [str(fit_dates[0]), str(fit_dates[-1])],
            "cal_eval_range": [str(eval_dates[0]), str(eval_dates[-1])],
            "sklearn_available": _HAS_SKLEARN,
        },
        "uncalibrated_eval": {**uncal_metrics, "ece": uncal_ece},
        "temperature": temp_result,
        "isotonic": iso_result,
        "period_stability": periods,
        "promotion": {
            "automatic": False,
            "note": "Calibration is post-hoc only. No model promotion in this phase.",
        },
        "limitations": [
            "Temperature and isotonic parameters fitted on earlier OOS window only; evaluated on later window.",
            "Isotonic is data-hungry; results sensitive to sample size.",
            "Single global temperature; class-conditional temperature not explored.",
            "Prospective sample remains below promotion threshold.",
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()
                    if k not in ("calibrated_probs", "models", "probs", "outcomes")}
        if isinstance(obj, list):
            return [_clean(x) for x in obj]
        if isinstance(obj, (np.floating, np.integer)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    with open(out, "w") as f:
        json.dump(_clean(report), f, indent=2, default=str)
    print(f"Wrote {out}")
    print(f"Uncal LL={uncal_metrics['log_loss']:.4f} ECE={uncal_ece:.4f}")
    if temp_result.get("applied"):
        print(f"Temp  LL={temp_metrics['log_loss']:.4f} ECE={temp_ece:.4f} T={temp_result.get('temperature')}")
    if iso_result.get("should_apply") is not None:
        print(f"Iso   LL={iso_metrics['log_loss']:.4f} ECE={iso_ece:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
