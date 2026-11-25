"""Stage 8 — leakage-aware multiclass temperature calibration.

Fit only on chronological, out-of-sample predictions. The caller must provide
both each match date and the training cutoff used to create that prediction;
the cutoff must be strictly earlier than the match date.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Sequence

import numpy as np
from scipy.optimize import minimize_scalar


def _validated_arrays(probabilities: Sequence, outcomes: Sequence) -> tuple[np.ndarray, np.ndarray]:
    probs = np.asarray(probabilities, dtype=float)
    actual = np.asarray(outcomes, dtype=float)
    if probs.ndim != 2 or probs.shape[1] != 3 or actual.shape != probs.shape:
        raise ValueError("probabilities and outcomes must both have shape (n, 3)")
    if len(probs) == 0 or not np.all(np.isfinite(probs)) or not np.all(np.isfinite(actual)):
        raise ValueError("calibration arrays must be non-empty and finite")
    if np.any(probs < 0) or np.any(probs > 1):
        raise ValueError("probabilities must be between 0 and 1")
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-8, rtol=0):
        raise ValueError("each probability row must sum to 1")
    if np.any(actual < 0) or np.any(actual > 1):
        raise ValueError("outcomes must be one-hot vectors")
    if not np.allclose(actual.sum(axis=1), 1.0, atol=1e-8, rtol=0):
        raise ValueError("each outcome row must sum to 1")
    if not np.all(np.isclose(actual, 0.0) | np.isclose(actual, 1.0)):
        raise ValueError("outcomes must contain only 0 and 1")
    return probs, actual


def _log_loss(probs: np.ndarray, actual: np.ndarray) -> float:
    chosen = np.sum(probs * actual, axis=1)
    return float(-np.mean(np.log(np.clip(chosen, 1e-15, 1.0))))


def apply_temperature(probabilities: Sequence, temperature: float) -> np.ndarray:
    """Apply scalar softmax temperature scaling to rows of 1X2 probabilities."""
    probs = np.asarray(probabilities, dtype=float)
    if probs.ndim != 2 or probs.shape[1] != 3 or len(probs) == 0:
        raise ValueError("probabilities must have shape (n, 3)")
    if not np.all(np.isfinite(probs)) or np.any(probs < 0):
        raise ValueError("probabilities must be finite and non-negative")
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-8, rtol=0):
        raise ValueError("each probability row must sum to 1")
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    logits = np.log(np.clip(probs, 1e-15, 1.0)) / float(temperature)
    logits -= logits.max(axis=1, keepdims=True)
    exp = np.exp(logits)
    return exp / exp.sum(axis=1, keepdims=True)


def fit_temperature(
    probabilities: Sequence,
    outcomes: Sequence,
    match_dates: Sequence,
    training_cutoffs: Sequence,
    *,
    min_samples: int = 50,
    min_improvement: float = 0.001,
) -> Dict[str, Any]:
    """Fit T on out-of-sample predictions and prove each training cutoff precedes its match.

    ``should_apply`` is True only when the in-sample log-loss gain on the
    calibration window is at least ``min_improvement`` (default 0.001 nats per
    match). A smaller gain is indistinguishable from fitting noise, and
    earlier runs switched calibration on for a 0.00005 gain.
    """
    if not np.isfinite(min_improvement) or min_improvement < 0:
        raise ValueError("min_improvement must be a finite non-negative number")
    probs, actual = _validated_arrays(probabilities, outcomes)
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")
    if len(probs) < min_samples:
        raise ValueError(f"at least {min_samples} calibration matches are required")
    if len(match_dates) != len(probs) or len(training_cutoffs) != len(probs):
        raise ValueError("match_dates and training_cutoffs must match prediction count")

    for index, (match_date, cutoff) in enumerate(zip(match_dates, training_cutoffs)):
        try:
            match_day = date.fromisoformat(str(match_date)[:10])
            cutoff_day = date.fromisoformat(str(cutoff)[:10])
        except ValueError as exc:
            raise ValueError(f"invalid date/cutoff in calibration row {index}") from exc
        if cutoff_day >= match_day:
            raise ValueError(
                f"calibration prediction {index} is not out-of-sample: cutoff {cutoff} >= match {match_date}"
            )

    baseline = _log_loss(probs, actual)

    def objective(temperature: float) -> float:
        calibrated = apply_temperature(probs, temperature)
        return _log_loss(calibrated, actual)

    result = minimize_scalar(
        objective, bounds=(0.05, 10.0), method="bounded",
        options={"xatol": 1e-5, "maxiter": 500},
    )
    if not result.success or not np.isfinite(result.fun) or not np.isfinite(result.x):
        raise RuntimeError(f"temperature optimisation failed: {result.message}")
    temperature = float(result.x)
    calibrated_loss = float(result.fun)
    improvement = baseline - calibrated_loss
    return {
        "method": "multiclass_temperature_scaling",
        "temperature": temperature,
        "n_samples": int(len(probs)),
        "baseline_log_loss": baseline,
        "calibrated_log_loss": calibrated_loss,
        "log_loss_improvement": improvement,
        "min_improvement": float(min_improvement),
        "should_apply": bool(
            improvement >= max(min_improvement, 1e-8) and abs(temperature - 1.0) > 1e-3
        ),
        "calibration_match_start": str(min(match_dates)),
        "calibration_match_end": str(max(match_dates)),
        "training_cutoffs_strictly_before_matches": True,
    }
