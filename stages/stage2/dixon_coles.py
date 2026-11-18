"""
ALEA Stage 2 — Dixon-Coles mathematical engine
----------------------------------------------
Self-contained, testable implementation of the core formulas.
This module exists so the mathematical properties required by Stage 2
can be verified independently of the large production predictor.
The production code in alea_predictor_*.py implements the same formulas.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy.stats import poisson, skellam


def dixon_coles_tau(h: int, a: int, lam: float, mu: float, rho: float) -> float:
    """
    Dixon-Coles low-score correction factor.
    Returns 1.0 for all scorelines except 0-0, 1-0, 0-1, 1-1.
    """
    if h == 0 and a == 0:
        return 1.0 - lam * mu * rho
    if h == 1 and a == 0:
        return 1.0 + mu * rho
    if h == 0 and a == 1:
        return 1.0 + lam * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def _validate_parameters(lam: float, mu: float, rho: float, max_goals: int = 15) -> None:
    if not (np.isfinite(lam) and np.isfinite(mu) and np.isfinite(rho)):
        raise ValueError("lambda, mu and rho must be finite")
    if lam <= 0 or mu <= 0:
        raise ValueError("expected goals must be positive")
    if not isinstance(max_goals, int) or isinstance(max_goals, bool) or max_goals < 1:
        raise ValueError("max_goals must be an integer >= 1")
    if abs(rho) > 0.3:
        raise ValueError("rho outside safe range")
    factors = (1 - lam * mu * rho, 1 + lam * rho, 1 + mu * rho, 1 - rho)
    if min(factors) <= 0:
        raise ValueError("Dixon-Coles correction factor is non-positive for this pairing")


def dixon_coles_corrections(lam: float, mu: float, rho: float) -> Tuple[float, float, float, float]:
    """Additive changes to the independent-Poisson cells (00, 01, 10, 11)."""
    _validate_parameters(lam, mu, rho)
    f0, f1 = np.exp(-lam), lam * np.exp(-lam)
    g0, g1 = np.exp(-mu), mu * np.exp(-mu)
    return (
        -f0 * g0 * lam * mu * rho,
        f0 * g1 * lam * rho,
        f1 * g0 * mu * rho,
        -f1 * g1 * rho,
    )


def exact_one_x_two(lam: float, mu: float, rho: float = 0.0) -> Tuple[float, float, float]:
    """Full-distribution home/draw/away probabilities; no score-grid truncation."""
    _validate_parameters(lam, mu, rho)
    d00, d01, d10, d11 = dixon_coles_corrections(lam, mu, rho)
    values = (
        float(skellam.sf(0, lam, mu) + d10),
        float(skellam.pmf(0, lam, mu) + d00 + d11),
        float(skellam.cdf(-1, lam, mu) + d01),
    )
    if not np.all(np.isfinite(values)) or min(values) < -1e-12 or max(values) > 1 + 1e-12:
        raise ValueError("invalid exact 1X2 probabilities")
    return values


def exact_btts(lam: float, mu: float, rho: float = 0.0) -> float:
    """Full-distribution both-teams-to-score probability."""
    _validate_parameters(lam, mu, rho)
    _, _, _, d11 = dixon_coles_corrections(lam, mu, rho)
    value = float((1 - np.exp(-lam)) * (1 - np.exp(-mu)) + d11)
    if not np.isfinite(value) or value < -1e-12 or value > 1 + 1e-12:
        raise ValueError("invalid exact BTTS probability")
    return value


def exact_over_under(lam: float, mu: float, rho: float = 0.0, line: float = 2.5) -> Tuple[float, float]:
    """Full-distribution over/under probabilities for any finite goal line."""
    _validate_parameters(lam, mu, rho)
    if not np.isfinite(line):
        raise ValueError("goal line must be finite")
    k = int(np.floor(line))
    d00, d01, d10, d11 = dixon_coles_corrections(lam, mu, rho)
    correction = 0.0
    if k == 0:
        correction = d00
    elif k == 1:
        correction = d00 + d01 + d10
    elif k >= 2:
        correction = d00 + d01 + d10 + d11
    under = float(poisson.cdf(k, lam + mu) + correction) if k >= 0 else 0.0
    over = 1.0 - under
    if not np.isfinite(over) or not np.isfinite(under) or min(over, under) < -1e-12:
        raise ValueError("invalid exact over/under probabilities")
    return over, under


def score_matrix(
    lam: float,
    mu: float,
    rho: float = 0.0,
    max_goals: int = 15,
) -> Tuple[np.ndarray, float]:
    """
    Return the joint probability matrix P(H=i, A=j) for i,j = 0..max_goals
    and the probability mass outside the grid (the tail).

    The matrix cells are the true Dixon-Coles probabilities.
    They sum to 1 - tail.
    """
    _validate_parameters(lam, mu, rho, max_goals)

    i = np.arange(0, max_goals + 1)
    j = np.arange(0, max_goals + 1)
    # Independent Poisson probabilities
    ph = poisson.pmf(i, lam)
    pa = poisson.pmf(j, mu)
    base = np.outer(ph, pa)

    # Apply tau correction
    mat = base.copy()
    mat[0, 0] *= dixon_coles_tau(0, 0, lam, mu, rho)
    mat[1, 0] *= dixon_coles_tau(1, 0, lam, mu, rho)
    mat[0, 1] *= dixon_coles_tau(0, 1, lam, mu, rho)
    mat[1, 1] *= dixon_coles_tau(1, 1, lam, mu, rho)

    # Guard against negative probabilities from extreme rho
    if np.any(mat < 0):
        raise ValueError("negative probability produced — rho too large for these rates")

    grid_mass = mat.sum()
    tail = 1.0 - grid_mass
    return mat, tail


def one_x_two(mat: np.ndarray) -> Tuple[float, float, float]:
    """Grid-conditional 1X2 probabilities.

    This normalises only the supplied finite grid. For the full distribution,
    use exact_one_x_two(lam, mu, rho) instead.
    """
    home = np.tril(mat, -1).sum()
    draw = np.trace(mat)
    away = np.triu(mat, 1).sum()
    total = home + draw + away
    if total <= 0:
        raise ValueError("empty matrix")
    return home / total, draw / total, away / total


def btts(mat: np.ndarray) -> float:
    """Grid-conditional BTTS probability. Use exact_btts for the full distribution."""
    return mat[1:, 1:].sum() / mat.sum()


def over_under(mat: np.ndarray, line: float = 2.5) -> Tuple[float, float]:
    """Grid-conditional over/under. Use exact_over_under for the full distribution."""
    total = 0.0
    over = 0.0
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            p = mat[i, j]
            total += p
            if i + j > line:
                over += p
    return over / total, 1.0 - over / total
