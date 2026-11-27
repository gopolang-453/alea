"""Extended calibration experiments for ALEA 2.5.

Builds on stages/stage8/calibration.py (temperature scaling) and adds:
- Reliability diagrams (binned)
- Optional isotonic regression per class
- Strict chronology checks (training cutoff strictly before match date)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Sequence

import numpy as np

try:
    from sklearn.isotonic import IsotonicRegression
    _HAS_SKLEARN = True
except ImportError:
    IsotonicRegression = None  # type: ignore
    _HAS_SKLEARN = False

from stages.stage8.calibration import (
    apply_temperature,
    fit_temperature,
    _validated_arrays,
    _log_loss,
)


def reliability_diagram(
    probabilities: Sequence,
    outcomes: Sequence,
    *,
    n_bins: int = 10,
    strategy: str = "uniform",
) -> Dict[str, Any]:
    probs, actual = _validated_arrays(probabilities, outcomes)
    n, k = probs.shape
    assert k == 3

    diagrams = []
    for class_idx, name in enumerate(("home", "draw", "away")):
        p = probs[:, class_idx]
        y = actual[:, class_idx]
        if strategy == "quantile":
            quantiles = np.linspace(0, 1, n_bins + 1)
            edges = np.unique(np.quantile(p, quantiles))
            if len(edges) < 2:
                edges = np.linspace(0, 1, n_bins + 1)
        else:
            edges = np.linspace(0.0, 1.0, n_bins + 1)

        bin_ids = np.digitize(p, edges[1:-1], right=False)
        bins = []
        for b in range(len(edges) - 1):
            mask = bin_ids == b
            count = int(mask.sum())
            if count == 0:
                bins.append({
                    "bin": b,
                    "left": float(edges[b]),
                    "right": float(edges[b + 1]),
                    "count": 0,
                    "mean_predicted": None,
                    "mean_observed": None,
                })
                continue
            bins.append({
                "bin": b,
                "left": float(edges[b]),
                "right": float(edges[b + 1]),
                "count": count,
                "mean_predicted": float(p[mask].mean()),
                "mean_observed": float(y[mask].mean()),
            })
        diagrams.append({"class": name, "class_idx": class_idx, "bins": bins})

    ece = 0.0
    total = 0
    for d in diagrams:
        for b in d["bins"]:
            if b["count"] > 0 and b["mean_predicted"] is not None:
                ece += b["count"] * abs(b["mean_predicted"] - b["mean_observed"])
                total += b["count"]
    ece = ece / total if total else float("nan")

    return {
        "n_samples": n,
        "n_bins": n_bins,
        "strategy": strategy,
        "ece": float(ece),
        "per_class": diagrams,
    }


def fit_isotonic_per_class(
    probabilities: Sequence,
    outcomes: Sequence,
    match_dates: Sequence,
    training_cutoffs: Sequence,
    *,
    min_samples: int = 200,
) -> Dict[str, Any]:
    if not _HAS_SKLEARN:
        return {
            "should_apply": False,
            "reason": "scikit-learn not installed; isotonic calibration unavailable",
            "n_samples": 0,
        }
    probs, actual = _validated_arrays(probabilities, outcomes)
    n = len(probs)
    if n < min_samples:
        return {
            "should_apply": False,
            "reason": f"n={n} < min_samples={min_samples}",
            "n_samples": n,
        }

    for md, tc in zip(match_dates, training_cutoffs):
        md_d = md.date() if isinstance(md, datetime) else md
        tc_d = tc.date() if isinstance(tc, datetime) else tc
        if not (tc_d < md_d):
            raise ValueError(
                f"Training cutoff {tc} is not strictly before match date {md}"
            )

    models = []
    calibrated = np.zeros_like(probs)
    for c in range(3):
        ir = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        ir.fit(probs[:, c], actual[:, c])
        calibrated[:, c] = ir.predict(probs[:, c])
        models.append(ir)

    row_sums = calibrated.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums <= 0, 1.0, row_sums)
    calibrated = calibrated / row_sums

    baseline_ll = _log_loss(probs, actual)
    calibrated_ll = _log_loss(calibrated, actual)

    return {
        "should_apply": calibrated_ll < baseline_ll,
        "method": "isotonic_per_class",
        "n_samples": n,
        "baseline_log_loss": baseline_ll,
        "calibrated_log_loss": calibrated_ll,
        "models": models,
        "calibrated_probs": calibrated,
        "improvement": baseline_ll - calibrated_ll,
    }


def evaluate_calibration_suite(
    probabilities: Sequence,
    outcomes: Sequence,
    match_dates: Sequence,
    training_cutoffs: Sequence,
    *,
    min_samples: int = 100,
) -> Dict[str, Any]:
    probs, actual = _validated_arrays(probabilities, outcomes)

    report: Dict[str, Any] = {
        "n_samples": len(probs),
        "baseline_log_loss": _log_loss(probs, actual),
        "reliability": reliability_diagram(probs, actual, n_bins=10),
    }

    try:
        temp_fit = fit_temperature(
            probs, actual, match_dates, training_cutoffs, min_samples=min_samples
        )
        report["temperature"] = {
            k: v for k, v in temp_fit.items() if k not in ("models",)
        }
        if temp_fit.get("should_apply"):
            calibrated = apply_temperature(probs, temp_fit["temperature"])
            report["temperature"]["calibrated_probs"] = calibrated
            report["temperature"]["post_calibration_reliability"] = reliability_diagram(
                calibrated, actual, n_bins=10
            )
    except Exception as exc:
        report["temperature"] = {"error": str(exc)}

    try:
        iso = fit_isotonic_per_class(
            probs, actual, match_dates, training_cutoffs,
            min_samples=max(min_samples, 200),
        )
        report["isotonic"] = {k: v for k, v in iso.items() if k not in ("models", "calibrated_probs")}
        if "calibrated_probs" in iso:
            report["isotonic"]["calibrated_probs"] = iso["calibrated_probs"]
    except Exception as exc:
        report["isotonic"] = {"error": str(exc)}

    return report
