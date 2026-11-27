"""Block-bootstrap confidence intervals for paired model comparisons.

Matches that occur in the same ISO week share unobserved conditions
(weather, referee, fatigue after international breaks, etc.).  Treating
them as independent understates uncertainty.  This module resamples
ISO-week blocks.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


def iso_week_key(d) -> str:
    """Return a stable ISO year-week string."""
    if hasattr(d, "isocalendar"):
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    # fallback for strings
    ts = pd.Timestamp(d)
    y, w, _ = ts.isocalendar()
    return f"{y}-W{w:02d}"


def paired_block_bootstrap(
    champion_losses: Sequence[float],
    candidate_losses: Sequence[float],
    match_dates: Sequence,
    *,
    n_boot: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """
    Paired block-bootstrap of the mean loss difference (candidate - champion).

    Negative mean difference means the candidate is better (lower loss).
    Returns the mean difference and a (1-alpha) confidence interval.
    """
    champ = np.asarray(champion_losses, dtype=float)
    cand = np.asarray(candidate_losses, dtype=float)
    if champ.shape != cand.shape or len(champ) == 0:
        raise ValueError("champion_losses and candidate_losses must be same non-empty shape")
    if len(match_dates) != len(champ):
        raise ValueError("match_dates length must match losses")

    keys = np.array([iso_week_key(d) for d in match_dates])
    unique_weeks = np.unique(keys)
    week_to_idx = {w: np.where(keys == w)[0] for w in unique_weeks}

    rng = np.random.default_rng(seed)
    diffs = []
    n_weeks = len(unique_weeks)
    for _ in range(n_boot):
        sampled_weeks = rng.choice(unique_weeks, size=n_weeks, replace=True)
        idx = np.concatenate([week_to_idx[w] for w in sampled_weeks])
        d = cand[idx].mean() - champ[idx].mean()
        diffs.append(d)

    diffs = np.asarray(diffs)
    mean_diff = float(cand.mean() - champ.mean())
    lo = float(np.quantile(diffs, alpha / 2))
    hi = float(np.quantile(diffs, 1 - alpha / 2))

    return {
        "mean_diff": mean_diff,
        "ci_low": lo,
        "ci_high": hi,
        "alpha": alpha,
        "n_boot": n_boot,
        "n_matches": len(champ),
        "n_weeks": n_weeks,
        "seed": seed,
        "candidate_better": hi < 0,  # entire CI below zero
        "inconclusive": lo < 0 < hi,
        "champion_better": lo > 0,
    }


def summarise_paired_comparison(
    champion_metrics: Dict[str, float],
    candidate_metrics: Dict[str, float],
    champion_losses: Sequence[float],
    candidate_losses: Sequence[float],
    match_dates: Sequence,
    *,
    model_id: str,
    n_boot: int = 2000,
) -> Dict[str, Any]:
    """High-level summary used in experiment reports."""
    boot = paired_block_bootstrap(
        champion_losses, candidate_losses, match_dates, n_boot=n_boot
    )
    return {
        "model_id": model_id,
        "champion_log_loss": champion_metrics.get("log_loss"),
        "candidate_log_loss": candidate_metrics.get("log_loss"),
        "log_loss_diff": boot["mean_diff"],
        "log_loss_ci95": [boot["ci_low"], boot["ci_high"]],
        "candidate_better_at_95": boot["candidate_better"],
        "inconclusive_at_95": boot["inconclusive"],
        "n_matches": boot["n_matches"],
        "n_weeks": boot["n_weeks"],
        "bootstrap": boot,
    }
