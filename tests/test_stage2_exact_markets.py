"""Numerical regression tests for the full-distribution Dixon-Coles markets."""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage2.dixon_coles import (
    btts,
    exact_btts,
    exact_one_x_two,
    exact_over_under,
    one_x_two,
    over_under,
    score_matrix,
)


@pytest.mark.parametrize("lam,mu,rho", [
    (0.35, 0.55, -0.08),
    (1.45, 1.10, -0.12),
    (2.6, 0.75, -0.04),
])
def test_exact_markets_match_a_wide_score_grid(lam, mu, rho):
    matrix, tail = score_matrix(lam, mu, rho, max_goals=80)
    assert tail < 1e-12
    expected_1x2 = exact_one_x_two(lam, mu, rho)
    grid_1x2 = one_x_two(matrix)
    assert np.allclose(expected_1x2, grid_1x2, atol=1e-12, rtol=1e-12)
    assert abs(sum(expected_1x2) - 1.0) < 1e-12
    assert abs(exact_btts(lam, mu, rho) - btts(matrix)) < 1e-12

    for line in (-0.5, 0.5, 1.5, 2.5, 3.5):
        exact_over, exact_under = exact_over_under(lam, mu, rho, line)
        grid_over, grid_under = over_under(matrix, line)
        assert abs(exact_over - grid_over) < 1e-12
        assert abs(exact_under - grid_under) < 1e-12
        assert abs(exact_over + exact_under - 1.0) < 1e-12


@pytest.mark.parametrize("lam,mu,rho", [
    (0, 1, 0),
    (float("nan"), 1, 0),
    (1, float("inf"), 0),
    (1, 1, float("nan")),
    (10, 10, -0.3),
])
def test_invalid_parameters_are_rejected(lam, mu, rho):
    with pytest.raises(ValueError):
        score_matrix(lam, mu, rho)


def test_score_grid_requires_at_least_one_goal_cell():
    with pytest.raises(ValueError, match="max_goals"):
        score_matrix(1.2, 0.9, -0.05, max_goals=0)
