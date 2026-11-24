"""Stage 9.4 / 9.5 candidate models scored on the champion's exact fixtures.

Every candidate here is *prequential*: a prediction for a match in a test block
uses only results whose ``available_at`` is at or before that block's
prediction cutoff, and any fitted mapping (ordered logit, stacker, temperature)
is fitted only on earlier rows whose results were available by that cutoff.

The functions are deliberately small and dependency-free (numpy + scipy) so
they can be unit-tested on synthetic data and audited line by line.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

OUTCOMES = ("H", "D", "A")
_EPS = 1e-12


# ---------------------------------------------------------------------------
# Pre-match team features (Stage 3) computed incrementally
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EloConfig:
    """Stage 3 defaults (``stages.stage3.team_features.elo_ratings``)."""

    initial_rating: float = 1500.0
    k_factor: float = 20.0
    home_advantage: float = 50.0


class IncrementalTeamState:
    """Elo + recent form, advanced one date batch at a time.

    Produces exactly the ratings ``stage3.elo_ratings`` would return for the
    same set of available results (same date batching, same update rule), but
    without recomputing from scratch for every prediction cutoff.
    """

    def __init__(self, elo: EloConfig = EloConfig(), form_window: int = 5) -> None:
        if form_window < 1:
            raise ValueError("form_window must be positive")
        self.elo = elo
        self.form_window = form_window
        self.ratings: Dict[str, float] = {}
        self.points: Dict[str, List[int]] = {}
        self.last_date: Optional[pd.Timestamp] = None

    def rating(self, team: str) -> float:
        return self.ratings.get(team, float(self.elo.initial_rating))

    def ppg(self, team: str, prior: float = 1.0, min_matches: int = 3) -> float:
        """Points per game over the last ``form_window`` matches.

        Teams with fewer than ``min_matches`` earlier Premier League matches in
        the store (in practice: newly promoted clubs) receive ``prior``. That
        prior is a fixed, documented model assumption, not invented data.
        """
        history = self.points.get(team, [])
        if len(history) < min_matches:
            return float(prior)
        recent = history[-self.form_window:]
        return float(sum(recent)) / len(recent)

    def apply_batch(self, batch: pd.DataFrame) -> None:
        """Apply all results from one calendar date simultaneously."""
        if batch.empty:
            return
        day = pd.Timestamp(batch["Date"].iloc[0]).normalize()
        if (pd.to_datetime(batch["Date"]).dt.normalize() != day).any():
            raise ValueError("a batch must contain a single match date")
        if self.last_date is not None and day <= self.last_date:
            raise ValueError("date batches must be applied in strictly increasing order")
        deltas: Dict[str, float] = {}
        for row in batch.itertuples(index=False):
            home, away = row.HomeTeam, row.AwayTeam
            rh, ra = self.rating(home), self.rating(away)
            expected_home = 1.0 / (1.0 + 10.0 ** (-((rh + self.elo.home_advantage) - ra) / 400.0))
            hg, ag = int(row.FTHG), int(row.FTAG)
            actual_home = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
            change = self.elo.k_factor * (actual_home - expected_home)
            deltas[home] = deltas.get(home, 0.0) + change
            deltas[away] = deltas.get(away, 0.0) - change
            home_pts, away_pts = (3, 0) if hg > ag else (1, 1) if hg == ag else (0, 3)
            self.points.setdefault(home, []).append(home_pts)
            self.points.setdefault(away, []).append(away_pts)
        for team, delta in deltas.items():
            self.ratings[team] = self.rating(team) + delta
        self.last_date = day


def pre_match_features(
    results: pd.DataFrame,
    queries: pd.DataFrame,
    *,
    elo: EloConfig = EloConfig(),
    form_window: int = 5,
    form_prior: float = 1.0,
) -> pd.DataFrame:
    """Elo difference and form difference for each query, as of its cutoff.

    ``results`` needs Date, HomeTeam, AwayTeam, FTHG, FTAG, available_at.
    ``queries`` needs HomeTeam, AwayTeam and ``cutoff_utc`` (tz-aware). A
    result is used for a query only when ``available_at <= cutoff_utc``.
    Returns columns ``elo_diff`` (home rating + home advantage - away rating)
    and ``form_diff`` (home PPG - away PPG), aligned with ``queries.index``.
    """
    needed = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "available_at"}
    missing = needed - set(results.columns)
    if missing:
        raise ValueError(f"results missing columns {sorted(missing)}")
    res = results.copy()
    res["Date"] = pd.to_datetime(res["Date"]).dt.normalize()
    res["available_at"] = pd.to_datetime(res["available_at"], utc=True)
    if res["available_at"].isna().any():
        raise ValueError("every result needs an available_at timestamp")
    # Availability must be monotone in match date so a date prefix is exactly
    # the set of available results. The Stage 1 date-only policy guarantees it.
    by_date = res.groupby("Date")["available_at"].agg(["min", "max"]).sort_index()
    later_min = by_date["min"].iloc[1:].reset_index(drop=True)
    earlier_max = by_date["max"].iloc[:-1].reset_index(drop=True)
    if (later_min < earlier_max).any():
        raise ValueError("available_at is not monotone in match date; cannot batch safely")
    res = res.sort_values(["Date", "HomeTeam", "AwayTeam"]).reset_index(drop=True)
    batches = [group for _, group in res.groupby("Date", sort=True)]
    batch_available = [group["available_at"].max() for group in batches]

    q = queries.copy()
    q["cutoff_utc"] = pd.to_datetime(q["cutoff_utc"], utc=True)
    order = q["cutoff_utc"].reset_index(drop=True).argsort(kind="stable").to_numpy()
    state = IncrementalTeamState(elo, form_window)
    next_batch = 0
    elo_diff = np.empty(len(q))
    form_diff = np.empty(len(q))
    for position in order:
        cutoff = q["cutoff_utc"].iloc[position]
        while next_batch < len(batches) and batch_available[next_batch] <= cutoff:
            state.apply_batch(batches[next_batch])
            next_batch += 1
        home, away = q["HomeTeam"].iloc[position], q["AwayTeam"].iloc[position]
        elo_diff[position] = state.rating(home) + elo.home_advantage - state.rating(away)
        form_diff[position] = state.ppg(home, form_prior) - state.ppg(away, form_prior)
    return pd.DataFrame({"elo_diff": elo_diff, "form_diff": form_diff}, index=queries.index)


# ---------------------------------------------------------------------------
# Probability mappings fitted on training rows only
# ---------------------------------------------------------------------------

def _outcome_index(labels: Sequence[str]) -> np.ndarray:
    lookup = {label: index for index, label in enumerate(OUTCOMES)}
    try:
        return np.asarray([lookup[label] for label in labels], dtype=int)
    except KeyError as exc:
        raise ValueError(f"unknown outcome label {exc}") from exc


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * x))


class OrderedLogit:
    """Three-way ordered logit on a single score: away < draw < home.

    P(A) = s(c1 - b*x), P(A or D) = s(c2 - b*x), with c1 < c2 enforced by a
    positive gap parameterisation. A small ridge on b keeps tiny samples sane.
    """

    def __init__(self, ridge: float = 1e-3) -> None:
        self.ridge = float(ridge)
        self.params: Optional[np.ndarray] = None

    @staticmethod
    def _probs(theta: np.ndarray, x: np.ndarray) -> np.ndarray:
        b, c1, log_gap = theta
        c2 = c1 + np.exp(log_gap)
        p_a = _sigmoid(c1 - b * x)
        p_ad = _sigmoid(c2 - b * x)
        p = np.column_stack([1.0 - p_ad, p_ad - p_a, p_a])
        return np.clip(p, _EPS, 1.0) / np.clip(p, _EPS, 1.0).sum(axis=1, keepdims=True)

    def fit(self, x: Sequence[float], outcomes: Sequence[str]) -> "OrderedLogit":
        x = np.asarray(x, dtype=float)
        y = _outcome_index(outcomes)
        if len(x) != len(y) or len(x) < 30 or not np.all(np.isfinite(x)):
            raise ValueError("ordered logit needs at least 30 finite training rows")

        def loss(theta: np.ndarray) -> float:
            p = self._probs(theta, x)
            return float(-np.mean(np.log(p[np.arange(len(y)), y])) + self.ridge * theta[0] ** 2)

        result = minimize(loss, x0=np.array([0.5, -0.5, 0.0]), method="L-BFGS-B")
        if not result.success or not np.all(np.isfinite(result.x)):
            raise RuntimeError(f"ordered logit fit failed: {result.message}")
        self.params = result.x
        return self

    def predict(self, x: Sequence[float]) -> np.ndarray:
        if self.params is None:
            raise RuntimeError("fit before predict")
        return self._probs(self.params, np.asarray(x, dtype=float))


class MultinomialStacker:
    """Multinomial logistic regression with H as the reference class.

    Used to combine Dixon-Coles probabilities with Elo/form features. Inputs
    are standardised on the training rows; a ridge penalty discourages large
    weights when the training sample is short.
    """

    def __init__(self, ridge: float = 1e-2) -> None:
        self.ridge = float(ridge)
        self.mean: Optional[np.ndarray] = None
        self.scale: Optional[np.ndarray] = None
        self.weights: Optional[np.ndarray] = None

    def _design(self, features: np.ndarray) -> np.ndarray:
        z = (features - self.mean) / self.scale
        return np.column_stack([np.ones(len(z)), z])

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        logits = logits - logits.max(axis=1, keepdims=True)
        expo = np.exp(logits)
        return expo / expo.sum(axis=1, keepdims=True)

    def fit(self, features: np.ndarray, outcomes: Sequence[str]) -> "MultinomialStacker":
        features = np.asarray(features, dtype=float)
        y = _outcome_index(outcomes)
        if features.ndim != 2 or len(features) != len(y) or len(y) < 100:
            raise ValueError("stacker needs a 2-D feature matrix with at least 100 rows")
        if not np.all(np.isfinite(features)):
            raise ValueError("stacker features must be finite")
        self.mean = features.mean(axis=0)
        self.scale = np.where(features.std(axis=0) > 1e-9, features.std(axis=0), 1.0)
        design = self._design(features)
        k = design.shape[1]
        one_hot = np.eye(3)[y]

        def loss_grad(flat: np.ndarray) -> Tuple[float, np.ndarray]:
            w = np.column_stack([np.zeros(k), flat.reshape(k, 2)])
            p = self._softmax(design @ w)
            nll = -np.mean(np.log(np.clip(p[np.arange(len(y)), y], _EPS, 1.0)))
            penalty = self.ridge * np.sum(w[1:, :] ** 2)
            grad_full = design.T @ (p - one_hot) / len(y)
            grad_full[1:, :] += 2 * self.ridge * w[1:, :]
            return float(nll + penalty), grad_full[:, 1:].ravel()

        result = minimize(loss_grad, x0=np.zeros(k * 2), jac=True, method="L-BFGS-B")
        if not np.all(np.isfinite(result.x)):
            raise RuntimeError(f"stacker fit failed: {result.message}")
        self.weights = np.column_stack([np.zeros(k), result.x.reshape(k, 2)])
        return self

    def predict(self, features: np.ndarray) -> np.ndarray:
        if self.weights is None:
            raise RuntimeError("fit before predict")
        return self._softmax(self._design(np.asarray(features, dtype=float)) @ self.weights)


def dc_logit_features(p: np.ndarray) -> np.ndarray:
    """Log-odds of home and away against the draw from a DC probability matrix."""
    p = np.clip(np.asarray(p, dtype=float), _EPS, 1.0)
    return np.column_stack([np.log(p[:, 0] / p[:, 1]), np.log(p[:, 2] / p[:, 1])])


def temperature_scale(p: np.ndarray, temperature: float) -> np.ndarray:
    logits = np.log(np.clip(np.asarray(p, dtype=float), _EPS, 1.0)) / float(temperature)
    logits -= logits.max(axis=1, keepdims=True)
    expo = np.exp(logits)
    return expo / expo.sum(axis=1, keepdims=True)


def fit_temperature_mle(p: np.ndarray, outcomes: Sequence[str]) -> float:
    from scipy.optimize import minimize_scalar

    y = _outcome_index(outcomes)
    p = np.asarray(p, dtype=float)

    def loss(t: float) -> float:
        q = temperature_scale(p, t)
        return float(-np.mean(np.log(np.clip(q[np.arange(len(y)), y], _EPS, 1.0))))

    result = minimize_scalar(loss, bounds=(0.2, 5.0), method="bounded")
    return float(result.x)


# ---------------------------------------------------------------------------
# Prequential driver
# ---------------------------------------------------------------------------

def prequential(
    rows: pd.DataFrame,
    fit_predict,
    *,
    min_training_rows: int,
    training_pool: Optional[pd.DataFrame] = None,
) -> np.ndarray:
    """Refit at every distinct prediction cutoff using only earlier, available rows.

    ``rows`` are the prediction rows (one per fixture) with ``cutoff_utc``,
    ``result_available_at`` and ``actual``. ``training_pool`` (defaults to
    ``rows``) supplies training examples; an example is eligible for cutoff
    ``c`` only when its ``result_available_at <= c``. ``fit_predict(train,
    test)`` returns an n_test x 3 probability matrix. Blocks with fewer than
    ``min_training_rows`` eligible examples get NaN (scored as unavailable).
    """
    pool = rows if training_pool is None else training_pool
    pool_available = pd.to_datetime(pool["result_available_at"], utc=True)
    cutoffs = pd.to_datetime(rows["cutoff_utc"], utc=True)
    out = np.full((len(rows), 3), np.nan)
    for cutoff in sorted(cutoffs.unique()):
        test_mask = (cutoffs == cutoff).values
        train = pool.loc[(pool_available <= cutoff).values]
        if len(train) < min_training_rows:
            continue
        test = rows.loc[test_mask]
        # Defensive leakage check: nothing in training may be from the test block.
        if pd.to_datetime(train["result_available_at"], utc=True).max() > cutoff:
            raise AssertionError("training example not available at prediction cutoff")
        out[test_mask] = fit_predict(train, test)
    return out


def scores(p: np.ndarray, outcomes: Sequence[str]) -> Dict[str, float]:
    y = _outcome_index(outcomes)
    p = np.asarray(p, dtype=float)
    one_hot = np.eye(3)[y]
    cum_p, cum_o = np.cumsum(p, axis=1)[:, :2], np.cumsum(one_hot, axis=1)[:, :2]
    return {
        "n": int(len(y)),
        "log_loss": float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], _EPS, 1.0)))),
        "brier": float(np.mean(np.sum((p - one_hot) ** 2, axis=1))),
        "rps": float(np.mean(np.sum((cum_p - cum_o) ** 2, axis=1) / 2.0)),
        "accuracy": float(np.mean(np.argmax(p, axis=1) == y)),
        "mean_p_draw": float(np.mean(p[:, 1])),
        "actual_draw_rate": float(np.mean(y == 1)),
    }


def paired_block_bootstrap(
    candidate: np.ndarray,
    champion: np.ndarray,
    outcomes: Sequence[str],
    dates: Iterable,
    *,
    samples: int = 2000,
    seed: int = 20261124,
) -> Dict[str, float]:
    """Candidate-minus-champion log-loss and Brier, resampling ISO-week blocks."""
    y = _outcome_index(outcomes)
    one_hot = np.eye(3)[y]
    idx = np.arange(len(y))
    ll = -np.log(np.clip(candidate[idx, y], _EPS, 1)) + np.log(np.clip(champion[idx, y], _EPS, 1))
    br = np.sum((candidate - one_hot) ** 2, axis=1) - np.sum((champion - one_hot) ** 2, axis=1)
    groups: Dict[Tuple[int, int], List[int]] = {}
    for i, value in enumerate(dates):
        iso = pd.Timestamp(value).isocalendar()
        groups.setdefault((int(iso.year), int(iso.week)), []).append(i)
    blocks = [np.asarray(g) for g in groups.values()]
    rng = np.random.default_rng(seed)
    boot_ll, boot_br = np.empty(samples), np.empty(samples)
    for s in range(samples):
        chosen = np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))])
        boot_ll[s], boot_br[s] = ll[chosen].mean(), br[chosen].mean()
    return {
        "log_loss_diff": float(ll.mean()),
        "log_loss_ci95": [float(np.quantile(boot_ll, 0.025)), float(np.quantile(boot_ll, 0.975))],
        "brier_diff": float(br.mean()),
        "brier_ci95": [float(np.quantile(boot_br, 0.025)), float(np.quantile(boot_br, 0.975))],
        "n_week_blocks": int(len(blocks)),
    }
