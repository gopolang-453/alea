"""ALEA Value Engine v0.2.1

A separate, deliberately conservative layer for comparing ALEA probabilities
with bookmaker prices. It does NOT predict matches and does NOT claim profit.

Core ideas:
- Decimal odds imply raw probability q = 1 / odds.
- For a complete mutually-exclusive market, sum(q) - 1 is the overround.
- Proportional de-vig normalises q to sum to one. This is transparent; it is
  not asserted to be the bookmaker's true internal method.
- Model expected value per 1 unit staked is p_model * decimal_odds - 1.
- A candidate is flagged only when both EV and model-vs-market probability
  edge clear user-defined thresholds. This is a research flag, not a bet tip.
- Staking is intentionally disabled. Enable it only after independent,
  out-of-sample calibration and profitability tests.

No network calls, scraping, bookmaker login, or bet placement.

v0.2.1: probabilities_from_score_matrix now takes the grid's tail (nothing is renormalised) and
  probabilities_from_prediction() reads ALEA's exact markets. Everything else is v0.2.

v0.2 changes (each has its own test in tests/):
  D1  analyse_market accepts probabilities rounded to 4 decimals (ALEA's predict()
      output) - tolerance scales with the number of outcomes, then renormalises
      exactly. Larger errors (e.g. 0.99 total) are still rejected.
  D2  `won` is parsed strictly. "False"/"false"/"0"/"no" are losses, "True"/"true"/
      "1"/"yes" wins; anything else makes the record invalid and it is counted as
      skipped. The old bool("False") booked a loss as a win.
  D3  A market needs at least two outcomes. A NEGATIVE overround is NOT rejected
      (best prices combined across bookmakers can legitimately sum below 100%);
      it is reported in `market_warnings` so it can be checked.
  ROI  backtest_flat_bets reports a bootstrap confidence interval for ROI
      (clustered by match_id when supplied, so several bets on one match are not
      treated as independent), sorts by `kickoff` when every record has one, and
      says plainly when the interval includes zero.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping, Sequence, Any
import math
import random
from datetime import datetime

ENGINE_VERSION = "alea-value-v0.2.1"
DISCLAIMER = (
    "Research estimate only. Positive estimated EV is not proof of a real edge; "
    "model error, odds movement, limits, and execution costs can erase it."
)


def _validate_market(model_probabilities: Mapping[str, float],
                     decimal_odds: Mapping[str, float],
                     probability_tolerance: float | None = None):
    """Returns (keys, normalised_probabilities, probability_sum_error, warnings).

    probability_tolerance: largest allowed |sum(p) - 1|. Default assumes the
    probabilities may have been rounded to 4 decimals (each can be off by 5e-5),
    i.e. n_outcomes * 5e-5. Anything larger is rejected, not silently fixed.
    """
    if not model_probabilities or set(model_probabilities) != set(decimal_odds):
        raise ValueError("Model probabilities and decimal odds must have identical, non-empty outcome keys.")
    if len(model_probabilities) < 2:
        raise ValueError("A market needs at least two mutually exclusive outcomes; "
                         "a single-outcome 'market' has no opposing side to price against.")
    keys = list(model_probabilities)
    probs = [float(model_probabilities[k]) for k in keys]
    odds = [float(decimal_odds[k]) for k in keys]
    if any(not math.isfinite(p) or p < 0 or p > 1 for p in probs):
        raise ValueError("Every model probability must be finite and between 0 and 1.")
    tol = probability_tolerance if probability_tolerance is not None else len(keys) * 5e-5 + 1e-9
    total = sum(probs)
    if abs(total - 1.0) > tol:
        raise ValueError(f"Model probabilities must sum to 1.0 (tolerance {tol:.2e}); got {total:.8f}.")
    if any(not math.isfinite(o) or o <= 1.0 for o in odds):
        raise ValueError("Decimal odds must be finite and greater than 1.00.")
    normalised = [p / total for p in probs]
    warnings: list[str] = []
    overround = sum(1.0 / o for o in odds) - 1.0
    if overround < 0:
        warnings.append(
            f"Negative overround ({100 * overround:.2f}%): the odds imply less than 100% total probability. "
            "Check that the market is complete and that all prices come from one bookmaker at one "
            "timestamp; if they are best prices combined from several bookmakers this can be a genuine "
            "arbitrage, but it can also be a data error."
        )
    return keys, normalised, abs(total - 1.0), warnings


def analyse_market(model_probabilities: Mapping[str, float],
                   decimal_odds: Mapping[str, float],
                   min_ev: float = 0.02,
                   min_probability_edge: float = 0.02,
                   probability_tolerance: float | None = None) -> dict[str, Any]:
    """Compare one complete market, e.g. {home, draw, away} or {over, under}.

    min_ev=0.02 means at least +2% estimated net return per unit staked.
    min_probability_edge=0.02 means model probability at least 2 percentage
    points above the proportional de-vig market probability.
    """
    keys, norm_probs, prob_sum_error, market_warnings = _validate_market(
        model_probabilities, decimal_odds, probability_tolerance)
    if min_ev < 0 or min_probability_edge < 0:
        raise ValueError("Thresholds must be non-negative.")

    raw = {k: 1.0 / float(decimal_odds[k]) for k in keys}
    implied_sum = sum(raw.values())
    overround = implied_sum - 1.0
    fair_market = {k: raw[k] / implied_sum for k in keys}

    outcomes = {}
    for k in keys:
        p = norm_probs[keys.index(k)]
        odds = float(decimal_odds[k])
        ev = p * odds - 1.0
        edge = p - fair_market[k]
        outcomes[k] = {
            "model_probability": p,
            "bookmaker_raw_implied_probability": raw[k],
            "market_probability_proportional_devig": fair_market[k],
            "probability_edge": edge,
            "decimal_odds": odds,
            "model_fair_odds": (1.0 / p if p > 0 else None),
            "expected_net_return_per_unit": ev,
            "candidate": bool(ev >= min_ev and edge >= min_probability_edge),
        }

    candidates = [k for k in keys if outcomes[k]["candidate"]]
    return {
        "engine_version": ENGINE_VERSION,
        "disclaimer": DISCLAIMER,
        "market_overround": overround,
        "market_overround_percent": 100.0 * overround,
        "raw_implied_probability_sum": implied_sum,
        "probability_sum_error": prob_sum_error,
        "market_warnings": market_warnings,
        "devig_method": "proportional normalisation",
        "thresholds": {"min_ev": min_ev, "min_probability_edge": min_probability_edge},
        "outcomes": outcomes,
        "candidate_outcomes": candidates,
        "staking_enabled": False,
    }


def probabilities_from_score_matrix(matrix: Sequence[Sequence[float]], tail_probability: float = 0.0,
                                    max_tail: float = 1e-6) -> dict[str, float]:
    """Derive goal markets from ALEA's EXACT score grid (rows = home goals, columns = away goals).

    The grid from alea_predictor_v2_4_1.score_matrix sums to 1 - tail, where `tail` is the probability of more
    than N goals by either side. Pass that tail in `tail_probability`; matrix sum + tail must equal 1.
    Nothing is renormalised. What can and cannot be known from a grid alone:
      - over/under totals are EXACT (under k = the cells with total <= k; over = 1 - under, which includes the tail);
      - home / draw / away / BTTS are LOWER BOUNDS, each short of the truth by at most `tail`, because a tail
        scoreline cannot be assigned to an outcome without the formulas ALEA uses.
    If tail > max_tail this refuses: use probabilities_from_prediction(pred), which carries ALEA's exact
    full-distribution markets.
    """
    rows = [list(map(float, row)) for row in matrix]
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError("Score matrix must be a non-empty rectangular matrix.")
    if len(rows) != len(rows[0]):
        raise ValueError("Score matrix must be square.")
    n = len(rows)
    if any(not math.isfinite(v) or v < 0 for row in rows for v in row):
        raise ValueError("Score matrix contains invalid probabilities.")
    if not math.isfinite(tail_probability) or tail_probability < 0:
        raise ValueError("tail_probability must be finite and >= 0.")
    total = sum(sum(row) for row in rows)
    if not math.isclose(total + tail_probability, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Score matrix plus tail must sum to 1.0; got {total:.12f} + {tail_probability:.3e}. "
                         "Pass tail_probability, or use probabilities_from_prediction().")
    if tail_probability > max_tail:
        raise ValueError(f"The grid omits {tail_probability:.2e} of the probability (limit {max_tail:.0e}); home/draw/"
                         "away/BTTS cannot be derived exactly from it. Use probabilities_from_prediction().")

    home = draw = away = 0.0
    btts_yes = 0.0
    under = {1: 0.0, 2: 0.0, 3: 0.0}        # P(total <= k), exact
    for h in range(n):
        for a in range(n):
            p = rows[h][a]
            if h > a: home += p
            elif h == a: draw += p
            else: away += p
            for k in under:
                if h + a <= k: under[k] += p
            if h >= 1 and a >= 1: btts_yes += p
    return {
        "home": home, "draw": draw, "away": away,
        "over_1_5": 1.0 - under[1], "under_1_5": under[1],
        "over_2_5": 1.0 - under[2], "under_2_5": under[2],
        "over_3_5": 1.0 - under[3], "under_3_5": under[3],
        "btts_yes": btts_yes, "btts_no": 1.0 - btts_yes,
    }


def probabilities_from_prediction(pred: Mapping[str, Any]) -> dict[str, float]:
    """Markets from an ALEA predict() result. Uses the full-precision, full-distribution `markets` entry when
    present (v2.4.1+), else the 4-decimal rounded p_* fields (then pass probability_tolerance to analyse_market)."""
    mk = pred.get("markets")
    if mk is not None:
        return {"home": mk["home"], "draw": mk["draw"], "away": mk["away"],
                "over_1_5": mk["over_1_5"], "under_1_5": 1.0 - mk["over_1_5"],
                "over_2_5": mk["over_2_5"], "under_2_5": mk["under_2_5"],
                "over_3_5": mk["over_3_5"], "under_3_5": 1.0 - mk["over_3_5"],
                "btts_yes": mk["btts_yes"], "btts_no": mk["btts_no"]}
    return {"home": pred["p_home_win"], "draw": pred["p_draw"], "away": pred["p_away_win"],
            "over_1_5": pred["p_over_1.5"], "under_1_5": 1.0 - pred["p_over_1.5"],
            "over_2_5": pred["p_over_2.5"], "under_2_5": pred["p_under_2.5"],
            "over_3_5": pred["p_over_3.5"], "under_3_5": 1.0 - pred["p_over_3.5"],
            "btts_yes": pred["p_btts_yes"], "btts_no": pred["p_btts_no"]}


_TRUE = {"true", "1", "yes", "y", "won", "win"}
_FALSE = {"false", "0", "no", "n", "lost", "loss"}


def _parse_won(value: Any) -> bool:
    """Strict outcome parsing (fixes D2). Raises ValueError for anything ambiguous."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"ambiguous 'won' value: {value!r}")
    if isinstance(value, str):
        t = value.strip().casefold()
        if t in _TRUE:
            return True
        if t in _FALSE:
            return False
    raise ValueError(f"ambiguous 'won' value: {value!r}")


def roi_confidence_interval(profits: Sequence[float],
                            cluster_ids: Sequence[Any] | None = None,
                            n_boot: int = 5000, level: float = 0.95,
                            seed: int = 12345) -> dict[str, Any]:
    """Bootstrap (percentile) confidence interval for ROI = total profit / number of bets.

    If cluster_ids is given (e.g. match ids), whole clusters are resampled, because
    several bets on the same match are not independent. Seeded, so it is repeatable.
    """
    n = len(profits)
    if n < 2:
        return {"roi": (sum(profits) / n if n else None), "ci_low": None, "ci_high": None,
                "level": level, "n_bets": n, "n_clusters": n, "includes_zero": None,
                "note": "fewer than 2 bets: no interval can be computed"}
    if not 0 < level < 1:
        raise ValueError("level must be between 0 and 1")
    if cluster_ids is None:
        cluster_ids = list(range(n))
    sums: dict[Any, float] = {}
    counts: dict[Any, int] = {}
    for pr, cid in zip(profits, cluster_ids):
        sums[cid] = sums.get(cid, 0.0) + pr
        counts[cid] = counts.get(cid, 0) + 1
    cs = [sums[c] for c in sums]
    cc = [counts[c] for c in sums]
    k = len(cs)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        tot = cnt = 0
        for _ in range(k):
            idx = rng.randrange(k)
            tot += cs[idx]
            cnt += cc[idx]
        boots.append(tot / cnt)
    boots.sort()
    a = (1 - level) / 2
    lo = boots[int(a * (n_boot - 1))]
    hi = boots[int((1 - a) * (n_boot - 1))]
    roi = sum(profits) / n
    return {"roi": roi, "ci_low": lo, "ci_high": hi, "level": level, "n_bets": n,
            "n_clusters": k, "includes_zero": bool(lo <= 0.0 <= hi), "n_boot": n_boot,
            "note": ("interval includes zero: results are not distinguishable from luck"
                     if lo <= 0.0 <= hi else "interval excludes zero")}


def backtest_flat_bets(records: Sequence[Mapping[str, Any]],
                       min_ev: float = 0.02,
                       min_probability_edge: float = 0.02,
                       n_boot: int = 5000, ci_level: float = 0.95,
                       seed: int = 12345) -> dict[str, Any]:
    """Evaluate historical *pre-match* selections.

    Each record requires: model_probability, decimal_odds, won, market_probability
    (de-vigged probability from the SAME timestamp as decimal_odds).
    Optional: match_id (bets on one match are resampled together in the CI) and
    kickoff (ISO date/time; if EVERY record has one, bets are processed in time
    order, which is what the drawdown needs; otherwise the supplied order is used
    and the result says so).
    Use only odds genuinely available at the prediction timestamp.
    One unit flat stake per qualifying selection; no compounding.
    """
    parsed = []
    skipped = 0
    for rec in records:
        try:
            p = float(rec["model_probability"])
            odds = float(rec["decimal_odds"])
            market_p = float(rec["market_probability"])
            won = _parse_won(rec["won"])
            if not (0 <= p <= 1 and 0 <= market_p <= 1 and math.isfinite(p)
                    and math.isfinite(market_p) and math.isfinite(odds) and odds > 1):
                raise ValueError("out-of-range value")
            kick = rec.get("kickoff")
            kick_dt = datetime.fromisoformat(str(kick)) if kick not in (None, "") else None
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        parsed.append((kick_dt, rec.get("match_id"), p, odds, market_p, won))

    chronological = bool(parsed) and all(x[0] is not None for x in parsed)
    if chronological:
        parsed.sort(key=lambda x: x[0])

    profits: list[float] = []
    cluster_ids: list[Any] = []
    wins = 0
    have_ids = True
    for n_i, (_, mid, p, odds, market_p, won) in enumerate(parsed):
        ev = p * odds - 1.0
        edge = p - market_p
        if ev < min_ev or edge < min_probability_edge:
            continue
        profits.append(odds - 1.0 if won else -1.0)
        wins += int(won)
        if mid is None:
            have_ids = False
            cluster_ids.append(("_row", n_i))
        else:
            cluster_ids.append(mid)
    bets = len(profits)
    profit = sum(profits)

    peak = equity = max_drawdown = 0.0
    for net in profits:
        equity += net
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)

    ci = roi_confidence_interval(profits, cluster_ids if bets else None,
                                 n_boot=n_boot, level=ci_level, seed=seed)
    warnings = []
    if skipped:
        warnings.append(f"{skipped} record(s) skipped as invalid (including ambiguous 'won' values).")
    if not chronological:
        warnings.append("Not every record has a 'kickoff', so the supplied order was used; "
                        "drawdown is only meaningful if that order is chronological.")
    if bets and not have_ids:
        warnings.append("Some bets have no match_id; they were treated as independent in the interval.")
    if bets and ci.get("includes_zero"):
        warnings.append("ROI confidence interval includes zero: not distinguishable from luck.")
    return {
        "n_input_records": len(records),
        "n_skipped_invalid_records": skipped,
        "qualifying_bets": bets,
        "wins": wins,
        "hit_rate": wins / bets if bets else None,
        "flat_stake_units": float(bets),
        "net_profit_units": profit,
        "roi_per_unit_staked": profit / bets if bets else None,
        "roi_confidence_interval": ci,
        "max_drawdown_units": max_drawdown,
        "processed_chronologically": chronological,
        "thresholds": {"min_ev": min_ev, "min_probability_edge": min_probability_edge},
        "staking_enabled": False,
        "warnings": warnings,
        "warning": "Historical results do not guarantee future performance. Require a large, untouched, chronological test set.",
    }


if __name__ == "__main__":
    # Transparent worked example only; numbers are illustrative, not a real fixture.
    example = analyse_market(
        {"home": 0.50, "draw": 0.27, "away": 0.23},
        {"home": 2.05, "draw": 3.40, "away": 4.10},
    )
    from pprint import pprint
    pprint(example)
