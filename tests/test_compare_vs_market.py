import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_vs_market import run  # noqa: E402


def _files(tmp_path, n=60, same=False):
    rng = np.random.default_rng(1)
    dates = pd.date_range("2024-08-10", periods=n, freq="D").strftime("%Y-%m-%d")
    y = rng.integers(0, 3, n)
    pm = rng.dirichlet([3, 2, 3], n)
    pc = pm if same else rng.dirichlet([3, 2, 3], n)
    champ = pd.DataFrame({"period": "development_walk_forward", "date": dates, "home_team": [f"Home {i}" for i in range(n)],
                          "away_team": [f"Away {i}" for i in range(n)], "p_home": pc[:, 0], "p_draw": pc[:, 1],
                          "p_away": pc[:, 2], "actual": np.array(list("HDA"))[y], "model_version": "m"})
    odds = pd.DataFrame({"date": dates, "home": champ.home_team, "away": champ.away_team, "p_market_home": pm[:, 0],
                         "p_market_draw": pm[:, 1], "p_market_away": pm[:, 2], "y_home": (y == 0).astype(int),
                         "y_draw": (y == 1).astype(int), "y_away": (y == 2).astype(int)})
    champ.to_csv(tmp_path / "c.csv", index=False)
    odds.to_csv(tmp_path / "o.csv", index=False)
    return tmp_path / "c.csv", tmp_path / "o.csv"


def test_identical_forecasts_give_zero_difference(tmp_path):
    res = run(*_files(tmp_path, same=True))
    assert res["joined_fixtures"] == 60 and res["unmatched_odds_rows"] == 0
    assert abs(res["overall"]["diff_log_loss"]) < 1e-12
    lo, hi = res["overall"]["diff_log_loss_ci95"]
    assert abs(lo) < 1e-12 and abs(hi) < 1e-12


def test_report_has_ci_and_calibration(tmp_path):
    res = run(*_files(tmp_path))
    assert res["overall"]["n_week_blocks"] >= 2
    assert len(res["overall"]["diff_brier_ci95"]) == 2
    assert sum(b["n"] for b in res["calibration"]["market"]["bins"]) == 180
