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
    total = p_home + p_draw + p_away
    if not (0.99 <= total <= 1.01):
        raise ValueError(f"probabilities must sum to 1, got {total}")
    if min(p_home, p_draw, p_away) < 0:
        raise ValueError("negative probability")


def log_loss(records: Sequence[PredictionRecord]) -> Optional[float]:
    """Multiclass log loss. Returns None if no records have an outcome."""
    losses = []
    for r in records:
        if r.outcome is None:
            continue
        _validate_probs(r.p_home, r.p_draw, r.p_away)
        p = {"H": r.p_home, "D": r.p_draw, "A": r.p_away}[r.outcome]
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
        actual = {"H": [1, 0, 0], "D": [0, 1, 0], "A": [0, 0, 1]}[r.outcome]
        pred = [r.p_home, r.p_draw, r.p_away]
        scores.append(sum((a - p) ** 2 for a, p in zip(actual, pred)))
    if not scores:
        return None
    return float(np.mean(scores))


def ensemble_average(
    records_by_model: Dict[str, Sequence[PredictionRecord]],
    weights: Optional[Dict[str, float]] = None,
) -> List[PredictionRecord]:
    """
    Produce a probability-weighted average ensemble.
    If weights is None, equal weights are used.
    Only fixtures present in every model are included.
    """
    if not records_by_model:
        return []
    models = list(records_by_model.keys())
    if weights is None:
        weights = {m: 1.0 / len(models) for m in models}
    else:
        s = sum(weights.values())
        if s <= 0:
            raise ValueError("weights must sum to a positive number")
        weights = {m: w / s for m, w in weights.items()}

    # Index by fixture
    by_fix: Dict[str, Dict[str, PredictionRecord]] = {}
    for m, recs in records_by_model.items():
        for r in recs:
            by_fix.setdefault(r.fixture_key, {})[m] = r

    out = []
    for fix, model_map in by_fix.items():
        if set(model_map.keys()) != set(models):
            continue  # require all models
        ph = sum(weights[m] * model_map[m].p_home for m in models)
        pd = sum(weights[m] * model_map[m].p_draw for m in models)
        pa = sum(weights[m] * model_map[m].p_away for m in models)
        # renormalise in case of floating point
        total = ph + pd + pa
        out.append(PredictionRecord(
            model="ensemble",
            fixture_key=fix,
            p_home=ph / total,
            p_draw=pd / total,
            p_away=pa / total,
            outcome=model_map[models[0]].outcome,
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
