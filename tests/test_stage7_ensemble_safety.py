"""Regression tests for safe ensemble construction and scoring."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage7.ensemble import (
    PredictionRecord,
    brier_score,
    ensemble_average,
    log_loss,
)


def rec(model, fixture="fixture-1", probs=(0.5, 0.25, 0.25), outcome="H"):
    return PredictionRecord(model, fixture, *probs, outcome=outcome)


def test_weighted_ensemble_uses_normalised_nonnegative_weights():
    out = ensemble_average({
        "dc": [rec("dc", probs=(0.6, 0.2, 0.2))],
        "elo": [rec("elo", probs=(0.3, 0.4, 0.3))],
    }, weights={"dc": 3, "elo": 1})
    assert len(out) == 1
    assert out[0].p_home == pytest.approx(0.525)
    assert out[0].p_draw == pytest.approx(0.25)
    assert out[0].p_away == pytest.approx(0.225)
    assert out[0].outcome == "H"


@pytest.mark.parametrize("weights", [
    {"dc": -1, "elo": 2},
    {"dc": float("nan"), "elo": 1},
    {"dc": 0, "elo": 0},
    {"dc": 1},
    {"dc": 1, "elo": 1, "extra": 1},
])
def test_invalid_weights_are_rejected(weights):
    with pytest.raises(ValueError):
        ensemble_average({
            "dc": [rec("dc")],
            "elo": [rec("elo")],
        }, weights=weights)


def test_duplicate_predictions_for_same_model_and_fixture_are_rejected():
    with pytest.raises(ValueError, match="duplicate prediction"):
        ensemble_average({
            "dc": [rec("dc"), rec("dc")],
            "elo": [rec("elo")],
        })


def test_models_must_agree_on_observed_outcome():
    with pytest.raises(ValueError, match="disagree on actual outcome"):
        ensemble_average({
            "dc": [rec("dc", outcome="H")],
            "elo": [rec("elo", outcome="A")],
        })


def test_invalid_probability_vectors_and_outcomes_are_rejected():
    with pytest.raises(ValueError, match="sum to 1"):
        log_loss([rec("dc", probs=(0.5, 0.2, 0.2))])
    with pytest.raises(ValueError, match="H, D or A"):
        log_loss([rec("dc", outcome="X")])
    with pytest.raises(ValueError, match="finite"):
        brier_score([rec("dc", probs=(float("nan"), 0.5, 0.5))])



def test_incomplete_fixture_alignment_is_rejected_not_silently_dropped():
    with pytest.raises(ValueError, match="missing predictions"):
        ensemble_average({
            "dc": [rec("dc", fixture="fixture-1")],
            "elo": [rec("elo", fixture="fixture-2")],
        })
