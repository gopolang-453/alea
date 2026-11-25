"""
ALEA Stage 7 — Machine learning and model ensemble scaffolding
--------------------------------------------------------------
Defines the contracts for candidate models and a simple ensemble.
No model is trained here. The module only:
- Accepts out-of-sample prediction records
- Computes basic metrics
- Produces a weighted ensemble of already-generated probabilities
- Refuses to invent weights or predictions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass
class PredictionRecord:
    """One out-of-sample prediction from a named model."""
    model: str
    fixture_key: str
    p_home: float
    p_draw: float
    p_away: float
    # optional: actual outcome once known ("H", "D", "A")
    outcome: Optional[str] = None


def _validate_probs(p_home: float, p_draw: float, p_away: float) -> None:
    values = np.asarray([p_home, p_draw, p_away], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("probabilities must be finite")
    if np.any(values < 0) or np.any(values > 1):
        raise ValueError("each probability must be between 0 and 1")
    total = float(values.sum())
    if not np.isclose(total, 1.0, atol=1e-8, rtol=0.0):
        raise ValueError(f"probabilities must sum to 1 within 1e-8, got {total}")


def _outcome_index(outcome: Optional[str]) -> int:
    try:
        return {"H": 0, "D": 1, "A": 2}[outcome]
    except (KeyError, TypeError):
        raise ValueError(f"outcome must be H, D or A; got {outcome!r}")


def log_loss(records: Sequence[PredictionRecord]) -> Optional[float]:
    """Multiclass log loss. Returns None if no records have an outcome."""
    losses = []
    for r in records:
        if r.outcome is None:
            continue
        _validate_probs(r.p_home, r.p_draw, r.p_away)
        idx = _outcome_index(r.outcome)
        p = (r.p_home, r.p_draw, r.p_away)[idx]
        losses.append(-np.log(max(p, 1e-15)))
    if not losses:
        return None
    return float(np.mean(losses))


def brier_score(records: Sequence[PredictionRecord]) -> Optional[float]:
    """Multiclass Brier score. Returns None if no outcomes."""
    scores = []
    for r in records:
        if r.outcome is None:
            continue
        _validate_probs(r.p_home, r.p_draw, r.p_away)
        actual = [0, 0, 0]
        actual[_outcome_index(r.outcome)] = 1
        pred = [r.p_home, r.p_draw, r.p_away]
        scores.append(sum((a - p) ** 2 for a, p in zip(actual, pred)))
    if not scores:
        return None
    return float(np.mean(scores))


def ensemble_average(
    records_by_model: Dict[str, Sequence[PredictionRecord]],
    weights: Optional[Dict[str, float]] = None,
) -> List[PredictionRecord]:
    """Average aligned, validated model probabilities; reject ambiguous inputs."""
    if not records_by_model:
        return []
    models = list(records_by_model.keys())
    if len(set(models)) != len(models) or any(not isinstance(m, str) or not m for m in models):
        raise ValueError("model names must be unique non-empty strings")

    if weights is None:
        normalised = {m: 1.0 / len(models) for m in models}
    else:
        if set(weights) != set(models):
            raise ValueError("weights must contain exactly one entry for every model")
        raw = {}
        for model in models:
            try:
                weight = float(weights[model])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid weight for {model}") from exc
            if not np.isfinite(weight) or weight < 0:
                raise ValueError("weights must be finite and non-negative")
            raw[model] = weight
        total_weight = sum(raw.values())
        if total_weight <= 0:
            raise ValueError("weights must sum to a positive number")
        normalised = {m: w / total_weight for m, w in raw.items()}

    by_fix: Dict[str, Dict[str, PredictionRecord]] = {}
    for model, recs in records_by_model.items():
        for record in recs:
            if record.model != model:
                raise ValueError(f"record model {record.model!r} does not match collection {model!r}")
            if not record.fixture_key:
                raise ValueError("fixture_key must be non-empty")
            _validate_probs(record.p_home, record.p_draw, record.p_away)
            if record.outcome is not None:
                _outcome_index(record.outcome)
            model_map = by_fix.setdefault(record.fixture_key, {})
            if model in model_map:
                raise ValueError(f"duplicate prediction for {model!r}, fixture {record.fixture_key!r}")
            model_map[model] = record

    out = []
    for fixture_key in sorted(by_fix):
        model_map = by_fix[fixture_key]
        if set(model_map) != set(models):
            missing = sorted(set(models) - set(model_map))
            raise ValueError(
                f"fixture {fixture_key!r} is missing predictions from models: {missing}"
            )
        outcomes = {record.outcome for record in model_map.values() if record.outcome is not None}
        if len(outcomes) > 1:
            raise ValueError(f"models disagree on actual outcome for fixture {fixture_key!r}")
        outcome = next(iter(outcomes)) if outcomes else None
        probs = [
            sum(normalised[m] * getattr(model_map[m], field) for m in models)
            for field in ("p_home", "p_draw", "p_away")
        ]
        total = sum(probs)
        out.append(PredictionRecord(
            model="ensemble",
            fixture_key=fixture_key,
            p_home=probs[0] / total,
            p_draw=probs[1] / total,
            p_away=probs[2] / total,
            outcome=outcome,
        ))
    return out


def select_best_model(records_by_model: Dict[str, Sequence[PredictionRecord]]) -> Optional[str]:
    """Return the model name with the lowest log loss, or None if no outcomes."""
    best = None
    best_ll = float("inf")
    for name, recs in records_by_model.items():
        ll = log_loss(recs)
        if ll is None:
            continue
        if ll < best_ll:
            best_ll = ll
            best = name
    return best
