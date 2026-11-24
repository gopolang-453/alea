import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_stage9_runs import compare


def _frame(shift=0.0, n=30):
    dates = pd.date_range("2024-08-10", periods=n, freq="3D").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "period": "development_walk_forward", "date": dates,
        "home_team": [f"h{i}" for i in range(n)], "away_team": [f"a{i}" for i in range(n)],
        "p_home": 0.45 + shift, "p_draw": 0.27, "p_away": 0.28 - shift,
        "actual": ["H", "D", "A"] * (n // 3),
        "prediction_cutoff_utc": [f"{d}T00:00:00+00:00" for d in dates],
    })


def test_identical_runs_have_zero_difference():
    out = compare(_frame(), _frame(), samples=100)["development_walk_forward"]
    assert out["max_abs_probability_difference"] == 0
    assert out["paired_bootstrap"]["log_loss_difference_candidate_minus_baseline"] == 0


def test_mismatched_fixtures_are_refused():
    with pytest.raises(ValueError):
        compare(_frame(), _frame().iloc[:-1], samples=10)


def test_different_cutoffs_are_refused():
    other = _frame()
    other.loc[0, "prediction_cutoff_utc"] = "2000-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="cutoffs"):
        compare(_frame(), other, samples=10)
