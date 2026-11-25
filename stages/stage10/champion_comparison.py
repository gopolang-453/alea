"""Stage 10 — candidate vs registered champion comparison on identical fixtures.

Authoritative comparison for promotion decisions.

Rules enforced here:
- Champion parameters are treated as frozen (not refit for the comparison).
- Only fixtures strictly after the champion's as_of_date are used.
- Candidate is evaluated with leakage-safe walk-forward on those same fixtures.
- Scoring uses production-style log_loss / Brier / RPS.
- Paired bootstrap CI on per-match log-loss difference (candidate - champion).
- Insufficient shared fixtures or missing champion metadata raise ComparisonError.

Synthetic results must never be presented as real Premier League validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import alea_predictor_v2_4_1 as dc
except ImportError:  # pragma: no cover
    dc = None


class ComparisonError(ValueError):
    """Raised when a candidate cannot be validly compared to the champion."""


@dataclass
class HeadToHeadResult:
    n_shared_fixtures: int
    champion_log_loss: float
    candidate_log_loss: float
    champion_brier: float
    candidate_brier: float
    champion_rps: float
    candidate_rps: float
    paired_log_loss_diff_mean: float
    paired_log_loss_diff_ci_low: float
    paired_log_loss_diff_ci_high: float
    includes_zero: bool
    fold_log: List[Dict[str, Any]] = field(default_factory=list)
    n_skipped_unknown_team: int = 0

    def passes_promotion_gate(self, min_improvement: float = 0.0) -> bool:
        return self.paired_log_loss_diff_ci_high < -abs(min_improvement)

    def to_evidence_dict(self) -> Dict[str, Any]:
        return {
            "n_shared_fixtures": self.n_shared_fixtures,
            "champion_log_loss": float(self.champion_log_loss),
            "candidate_log_loss": float(self.candidate_log_loss),
            "champion_brier": float(self.champion_brier),
            "candidate_brier": float(self.candidate_brier),
            "champion_rps": float(self.champion_rps),
            "candidate_rps": float(self.candidate_rps),
            "paired_log_loss_diff_mean": float(self.paired_log_loss_diff_mean),
            "paired_log_loss_diff_ci_low": float(self.paired_log_loss_diff_ci_low),
            "paired_log_loss_diff_ci_high": float(self.paired_log_loss_diff_ci_high),
            "includes_zero": bool(self.includes_zero),
            "n_skipped_unknown_team": int(self.n_skipped_unknown_team),
        }

    def to_registry_metrics(self, baseline_metrics: Dict[str, float]) -> Dict[str, float]:
        """Exact metric keys required by ModelRegistry.promote."""
        return {
            "n_holdout": float(self.n_shared_fixtures),
            "holdout_log_loss": float(self.candidate_log_loss),
            "baseline_holdout_log_loss": float(baseline_metrics.get("holdout_log_loss", self.champion_log_loss)),
            "log_loss_diff_ci_upper": float(self.paired_log_loss_diff_ci_high),
            "holdout_brier": float(self.candidate_brier),
            "baseline_holdout_brier": float(baseline_metrics.get("holdout_brier", self.champion_brier)),
            "brier_diff_ci_upper": float(self.candidate_brier - self.champion_brier),
        }


def _require_dc():
    if dc is None:
        raise ComparisonError("alea_predictor_v2_4_1 is not importable")


def _log_loss(p: np.ndarray, o: np.ndarray) -> float:
    eps = 1e-12
    return float(-np.mean(np.log(np.clip(np.sum(p * o, axis=1), eps, 1.0))))


def _brier(p: np.ndarray, o: np.ndarray) -> float:
    return float(np.mean(np.sum((p - o) ** 2, axis=1)))


def _rps(p: np.ndarray, o: np.ndarray) -> float:
    cum_p = np.cumsum(p, axis=1)
    cum_o = np.cumsum(o, axis=1)
    return float(np.mean(np.sum((cum_p - cum_o) ** 2, axis=1)))


def _bootstrap_ci(diffs: np.ndarray, n_boot: int = 1000, seed: int = 42) -> Dict[str, Any]:
    if hasattr(dc, "paired_bootstrap_ci"):
        return dc.paired_bootstrap_ci(diffs)
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, len(diffs), size=len(diffs))
        boots[i] = float(np.mean(diffs[idx]))
    boots.sort()
    lo = float(boots[int(0.025 * n_boot)])
    hi = float(boots[int(0.975 * n_boot)])
    return {
        "mean": float(np.mean(diffs)),
        "ci_low": lo,
        "ci_high": hi,
        "includes_zero": bool(lo <= 0.0 <= hi),
    }


def compare_candidate_to_champion(
    data: pd.DataFrame,
    champion_params: Dict[str, Any],
    candidate_fit_kwargs: Optional[Dict[str, Any]] = None,
    min_shared_fixtures: int = 30,
    min_train_matches: int = 40,
    step_days: int = 14,
) -> HeadToHeadResult:
    """Paired head-to-head on identical post-cutoff fixtures. Fail closed."""
    _require_dc()
    if not isinstance(data, pd.DataFrame) or data.empty:
        raise ComparisonError("data must be a non-empty DataFrame")
    required_cols = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    missing = required_cols - set(data.columns)
    if missing:
        raise ComparisonError(f"data missing required columns: {sorted(missing)}")
    if champion_params is None or "as_of_date" not in champion_params:
        raise ComparisonError("champion_params must include as_of_date")

    as_of = pd.Timestamp(champion_params["as_of_date"])
    work = data.copy()
    work["Date"] = pd.to_datetime(work["Date"])
    post = work[work["Date"] > as_of].sort_values("Date").reset_index(drop=True)
    if len(post) < min_shared_fixtures:
        raise ComparisonError(
            f"Only {len(post)} post-cutoff fixtures; need at least {min_shared_fixtures}."
        )

    candidate_fit_kwargs = dict(candidate_fit_kwargs or {})
    xi = float(candidate_fit_kwargs.get("xi", 0.0))
    reg = float(candidate_fit_kwargs.get("reg", 1.0))

    candidate_probs: List[List[float]] = []
    champion_probs: List[List[float]] = []
    outcomes: List[List[float]] = []
    fold_log: List[Dict[str, Any]] = []
    n_skipped = 0

    dates = sorted(post["Date"].unique())
    cut = dates[0]
    end_limit = dates[-1]

    while cut <= end_limit:
        end = cut + pd.Timedelta(days=step_days)
        train = work[work["Date"] < cut]
        test = post[(post["Date"] >= cut) & (post["Date"] < end)]
        if len(train) < min_train_matches or test.empty:
            cut = end
            continue
        try:
            cand_params = dc.fit_model(train, xi=xi, reg=reg, live=False)
        except Exception as exc:
            raise ComparisonError(f"candidate fit failed at {cut.date()}: {exc}") from exc

        tested = 0
        for row in test.itertuples(index=False):
            try:
                cpred = dc.predict(cand_params, row.HomeTeam, row.AwayTeam)
                hpred = dc.predict(champion_params, row.HomeTeam, row.AwayTeam)
            except (KeyError, ValueError, TypeError):
                n_skipped += 1
                continue
            candidate_probs.append([float(cpred["p_home_win"]), float(cpred["p_draw"]), float(cpred["p_away_win"])])
            champion_probs.append([float(hpred["p_home_win"]), float(hpred["p_draw"]), float(hpred["p_away_win"])])
            if int(row.FTHG) > int(row.FTAG):
                outcomes.append([1.0, 0.0, 0.0])
            elif int(row.FTHG) == int(row.FTAG):
                outcomes.append([0.0, 1.0, 0.0])
            else:
                outcomes.append([0.0, 0.0, 1.0])
            tested += 1
        if tested:
            fold_log.append({"cutoff": str(cut.date()), "n_train": int(len(train)), "n_test": int(tested)})
        cut = end

    n_shared = len(outcomes)
    if n_shared < min_shared_fixtures:
        raise ComparisonError(
            f"Only {n_shared} shared fixtures; need at least {min_shared_fixtures}."
        )

    cp = np.asarray(candidate_probs, dtype=float)
    hp = np.asarray(champion_probs, dtype=float)
    oa = np.asarray(outcomes, dtype=float)

    eps = 1e-12
    cand_ll = -np.log(np.clip(np.sum(cp * oa, axis=1), eps, 1.0))
    champ_ll = -np.log(np.clip(np.sum(hp * oa, axis=1), eps, 1.0))
    diffs = cand_ll - champ_ll
    ci = _bootstrap_ci(diffs)

    return HeadToHeadResult(
        n_shared_fixtures=n_shared,
        champion_log_loss=_log_loss(hp, oa),
        candidate_log_loss=_log_loss(cp, oa),
        champion_brier=_brier(hp, oa),
        candidate_brier=_brier(cp, oa),
        champion_rps=_rps(hp, oa),
        candidate_rps=_rps(cp, oa),
        paired_log_loss_diff_mean=float(ci["mean"]),
        paired_log_loss_diff_ci_low=float(ci["ci_low"]),
        paired_log_loss_diff_ci_high=float(ci["ci_high"]),
        includes_zero=bool(ci["includes_zero"]),
        fold_log=fold_log,
        n_skipped_unknown_team=n_skipped,
    )


def head_to_head(*args, **kwargs) -> HeadToHeadResult:
    """Alias for older imports."""
    return compare_candidate_to_champion(*args, **kwargs)
