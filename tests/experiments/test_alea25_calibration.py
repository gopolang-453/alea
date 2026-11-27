"""Unit tests for ALEA 2.5 extended calibration."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.alea25.calibration_ext import reliability_diagram, evaluate_calibration_suite


def _make_data(n=120, seed=0):
    rng = np.random.default_rng(seed)
    probs = np.clip(rng.dirichlet((2, 1, 1), size=n), 0.01, 0.98)
    probs = probs / probs.sum(axis=1, keepdims=True)
    outcomes = np.zeros_like(probs)
    for i in range(n):
        outcomes[i, rng.choice(3, p=probs[i])] = 1.0
    dates = [date(2024, 2, 1) + timedelta(days=i) for i in range(n)]
    cutoffs = [d - timedelta(days=1) for d in dates]
    return probs, outcomes, dates, cutoffs


def test_reliability_diagram_runs():
    probs, outcomes, _, _ = _make_data()
    diag = reliability_diagram(probs, outcomes, n_bins=8)
    assert diag["n_samples"] == 120
    assert "ece" in diag
    assert len(diag["per_class"]) == 3


def test_evaluate_calibration_suite_smoke():
    probs, outcomes, dates, cutoffs = _make_data(n=150)
    report = evaluate_calibration_suite(probs, outcomes, dates, cutoffs, min_samples=50)
    assert report["n_samples"] == 150
    assert "reliability" in report
    assert "temperature" in report
    assert "baseline_log_loss" in report
