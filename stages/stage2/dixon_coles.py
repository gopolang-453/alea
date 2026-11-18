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
from scipy.stats import poisson


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
    if lam <= 0 or mu <= 0:
        raise ValueError("expected goals must be positive")
    if abs(rho) > 0.3:
        raise ValueError("rho outside safe range")

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
    """Home / draw / away probabilities from a score matrix."""
    home = np.tril(mat, -1).sum()
    draw = np.trace(mat)
    away = np.triu(mat, 1).sum()
    total = home + draw + away
    if total <= 0:
        raise ValueError("empty matrix")
    return home / total, draw / total, away / total


def btts(mat: np.ndarray) -> float:
    """Both teams to score probability (at least one goal each)."""
    return mat[1:, 1:].sum() / mat.sum()


def over_under(mat: np.ndarray, line: float = 2.5) -> Tuple[float, float]:
    """Over / under a given total-goals line."""
    total = 0.0
    over = 0.0
    for i in range(mat.shape[0]):
        for j in range(mat.shape[1]):
            p = mat[i, j]
            total += p
            if i + j > line:
                over += p
    return over / total, 1.0 - over / total
