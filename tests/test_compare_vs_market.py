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


def test_cli_requires_odds_argument(tmp_path, capsys):
    import pytest
    from scripts.compare_vs_market import main
    with pytest.raises(SystemExit) as exc:
        main(["--out-dir", str(tmp_path)])
    assert exc.value.code == 2  # argparse: --odds is required, no tracked default


def test_cli_missing_odds_file_fails_safely(tmp_path, capsys):
    from scripts.compare_vs_market import main
    out = tmp_path / "out"
    assert main(["--odds", str(tmp_path / "absent.csv"), "--out-dir", str(out)]) == 2
    assert "not found" in capsys.readouterr().err
    assert not out.exists()


def test_cli_rejects_wrong_columns_and_writes_aggregates_only(tmp_path, capsys):
    from scripts.compare_vs_market import main
    champ, odds = _files(tmp_path)
    bad = tmp_path / "bad.csv"
    pd.read_csv(odds).drop(columns=["p_market_draw"]).to_csv(bad, index=False)
    assert main(["--champion", str(champ), "--odds", str(bad), "--out-dir", str(tmp_path / "x")]) == 2
    out = tmp_path / "out"
    assert main(["--champion", str(champ), "--odds", str(odds), "--out-dir", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["champion_vs_market.json", "champion_vs_market.md"]
    text = (out / "champion_vs_market.json").read_text() + (out / "champion_vs_market.md").read_text()
    # No per-fixture rows: no team names or individual market probabilities.
    assert "Home 1" not in text and "Away 1" not in text
    first_p = f"{pd.read_csv(odds).p_market_home.iloc[0]:.6f}"
    assert first_p not in text
