"""Unit tests for ALEA 2.5 block-bootstrap utilities."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.alea25.bootstrap import iso_week_key, paired_block_bootstrap


def test_iso_week_key_stable():
    d = date(2024, 1, 3)
    assert iso_week_key(d).startswith("2024-W")


def test_paired_block_bootstrap_identical_losses():
    n = 100
    losses = np.random.default_rng(0).normal(1.0, 0.2, size=n)
    dates = [date(2023, 1, 1) + timedelta(days=i * 2) for i in range(n)]
    res = paired_block_bootstrap(losses, losses, dates, n_boot=200, seed=1)
    assert abs(res["mean_diff"]) < 1e-12
    assert res["ci_low"] <= 0 <= res["ci_high"] or abs(res["ci_low"]) < 1e-9
    assert res["candidate_better"] is False
    assert res["champion_better"] is False


def test_paired_block_bootstrap_detects_clear_improvement():
    rng = np.random.default_rng(2)
    n = 200
    champ = rng.normal(1.05, 0.25, size=n)
    cand = champ - 0.08
    dates = [date(2022, 8, 1) + timedelta(days=i * 3) for i in range(n)]
    res = paired_block_bootstrap(champ, cand, dates, n_boot=300, seed=3)
    assert res["mean_diff"] < -0.05
    assert res["ci_high"] < 0
    assert res["candidate_better"] is True
