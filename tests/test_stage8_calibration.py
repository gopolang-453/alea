"""Stage 8 calibration validation and chronology tests."""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage8.calibration import apply_temperature, fit_temperature


def calibration_data():
    probabilities = np.tile([0.8, 0.1, 0.1], (100, 1))
    outcomes = np.asarray(
        [[1, 0, 0]] * 60 + [[0, 1, 0]] * 20 + [[0, 0, 1]] * 20,
        dtype=float,
    )
    dates = [date(2024, 1, 2) + timedelta(days=i) for i in range(100)]
    cutoffs = [day - timedelta(days=1) for day in dates]
    return probabilities, outcomes, dates, cutoffs


def test_temperature_calibration_improves_overconfident_out_of_sample_predictions():
    probabilities, outcomes, dates, cutoffs = calibration_data()
    fitted = fit_temperature(probabilities, outcomes, dates, cutoffs, min_samples=50)
    calibrated = apply_temperature(probabilities, fitted["temperature"])
    assert fitted["should_apply"] is True
    assert fitted["calibrated_log_loss"] < fitted["baseline_log_loss"]
    assert np.allclose(calibrated.sum(axis=1), 1.0)
    assert np.array_equal(np.argmax(probabilities, axis=1), np.argmax(calibrated, axis=1))


def test_calibration_refuses_same_day_or_future_training_cutoff():
    probabilities, outcomes, dates, cutoffs = calibration_data()
    cutoffs[10] = dates[10]
    with pytest.raises(ValueError, match="not out-of-sample"):
        fit_temperature(probabilities, outcomes, dates, cutoffs, min_samples=50)


def test_calibration_requires_sufficient_data_and_valid_probability_vectors():
    probabilities, outcomes, dates, cutoffs = calibration_data()
    with pytest.raises(ValueError, match="at least"):
        fit_temperature(probabilities[:10], outcomes[:10], dates[:10], cutoffs[:10])
    bad = probabilities.copy()
    bad[0] = [0.7, 0.2, 0.2]
    with pytest.raises(ValueError, match="sum to 1"):
        fit_temperature(bad, outcomes, dates, cutoffs, min_samples=50)
