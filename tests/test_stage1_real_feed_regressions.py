"""Regressions found by running the pipeline on real OpenFootball data (24 Nov 2026).

1. From 2025-26 upstream writes 0-0 results as a bare list ``"score": [0, 0]``
   instead of ``{"ft": [0, 0]}``; the importer crashed on it.
2. Upstream 2019-20 dates 66 post-COVID-restart matches (Jun-Jul 2020) with the
   year 2019. Imported as-is they would be in training data a year early.
3. ``Sunderland AFC`` / ``Hull City AFC`` kept their suffix and became new teams.
4. Concatenating with an empty seed frame produced object-dtype goals, which
   crashed scipy inside fit_model (CI run 45056028252).
5. CSV dates were parsed with free-form ``dayfirst`` inference.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_openfootball import parse_openfootball_file, season_window
from scripts.run_stage9_mle_backtest import _coerce_goals, validate_historical_dataset
from stages.stage1.data_store import canonical_team, parse_match_dates


def _write(tmp_path, matches):
    path = tmp_path / "season.json"
    path.write_text(json.dumps({"name": "test", "matches": matches}), encoding="utf-8")
    return path


def test_bare_list_score_is_read_as_full_time(tmp_path):
    path = _write(tmp_path, [
        {"date": "2025-08-16", "team1": "Aston Villa FC", "team2": "Newcastle United FC", "score": [0, 0]},
        {"date": "2025-08-15", "team1": "Liverpool FC", "team2": "AFC Bournemouth",
         "score": {"ft": [4, 2], "ht": [1, 0]}},
        {"date": "2025-08-17", "team1": "Chelsea FC", "team2": "Crystal Palace FC"},
    ])
    frame = parse_openfootball_file(path, "2025-26")
    assert len(frame) == 2
    villa = frame[frame.HomeTeam == "Aston Villa FC"].iloc[0]
    assert (villa.FTHG, villa.FTAG) == (0, 0)


def test_malformed_scores_still_fail_closed(tmp_path):
    path = _write(tmp_path, [{"date": "2025-08-16", "team1": "A", "team2": "B", "score": [1, 2, 3]}])
    with pytest.raises(ValueError, match="malformed full-time score"):
        parse_openfootball_file(path, "2025-26")
    path = _write(tmp_path, [{"date": "2025-08-16", "team1": "A", "team2": "B", "score": "1-0"}])
    with pytest.raises(ValueError, match="malformed score"):
        parse_openfootball_file(path, "2025-26")


def test_one_year_typo_is_corrected_and_recorded(tmp_path):
    path = _write(tmp_path, [
        {"date": "2019-08-09", "team1": "Liverpool FC", "team2": "Norwich City", "score": {"ft": [4, 1]}},
        {"date": "2019-07-01", "team1": "AFC Bournemouth", "team2": "Newcastle United", "score": {"ft": [1, 4]}},
    ])
    corrections = []
    frame = parse_openfootball_file(path, "2019-20", corrections=corrections)
    assert list(frame.Date) == ["2019-08-09", "2020-07-01"]
    assert corrections == [{"index": 1, "listed": "2019-07-01", "corrected": "2020-07-01"}]


def test_dates_that_cannot_be_explained_fail_closed(tmp_path):
    for bad in ("2018-12-01", "2021-09-01", "not-a-date"):
        path = _write(tmp_path, [{"date": bad, "team1": "A", "team2": "B", "score": {"ft": [1, 0]}}])
        with pytest.raises(ValueError):
            parse_openfootball_file(path, "2019-20")
    with pytest.raises(ValueError):
        season_window("2019-21")


def test_afc_and_fc_suffixes_map_to_one_team():
    assert canonical_team("Sunderland AFC") == canonical_team("Sunderland") == "sunderland"
    assert canonical_team("Hull City AFC") == canonical_team("Hull City")
    assert canonical_team("AFC Bournemouth") == canonical_team("Bournemouth")
    assert canonical_team("Liverpool FC") == "liverpool"
    # A one-word name is never emptied.
    assert canonical_team("AFC") == "afc"


def test_coerce_goals_fixes_object_dtype_after_empty_concat():
    seed = pd.DataFrame(columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    later = pd.DataFrame({"Date": ["2024-01-01"], "HomeTeam": ["a"], "AwayTeam": ["b"],
                          "FTHG": [2], "FTAG": [1]})
    joined = pd.concat([seed, later], ignore_index=True)
    assert joined["FTHG"].dtype == object  # the condition that crashed scipy
    fixed = _coerce_goals(joined)
    assert fixed["FTHG"].dtype == np.int64 and fixed["FTAG"].dtype == np.int64
    with pytest.raises(ValueError):
        _coerce_goals(later.assign(FTHG=[1.5]))


def test_historical_validation_rejects_dates_outside_season():
    rows = []
    teams = [f"t{i}" for i in range(20)]
    day = pd.Timestamp("2019-08-10")
    for i in range(380):
        rows.append({"Date": day + pd.Timedelta(days=i % 250), "Season": "2019-20",
                     "HomeTeam": teams[i % 20], "AwayTeam": teams[(i + 1 + i // 20) % 20],
                     "FTHG": 1, "FTAG": 0, "available_at": "2020-01-01T00:00:00+00:00"})
    frame = pd.DataFrame(rows).drop_duplicates(["Date", "HomeTeam", "AwayTeam"])
    frame = frame[frame.HomeTeam != frame.AwayTeam]
    # Pad back to 380 unique fixtures.
    extra = 0
    while len(frame) < 380:
        extra += 1
        frame.loc[len(frame) + 10_000] = {"Date": pd.Timestamp("2020-03-01") + pd.Timedelta(days=extra),
                                          "Season": "2019-20", "HomeTeam": "t0", "AwayTeam": "t1",
                                          "FTHG": 0, "FTAG": 0,
                                          "available_at": "2020-06-01T00:00:00+00:00"}
    frame = frame.reset_index(drop=True)
    validate_historical_dataset(frame)
    frame.loc[0, "Date"] = pd.Timestamp("2019-07-01")
    with pytest.raises(ValueError, match="outside"):
        validate_historical_dataset(frame)


def test_csv_dates_use_explicit_formats_only():
    parsed = parse_match_dates(pd.Series(["09/08/2019", "10/08/19", "2019-08-11", "Aug 12 2019"]))
    assert list(parsed[:3].dt.strftime("%Y-%m-%d")) == ["2019-08-09", "2019-08-10", "2019-08-11"]
    assert pd.isna(parsed.iloc[3])
