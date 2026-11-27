"""Unit tests for ALEA 3.0 form features."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.alea30.form_features import (
    fixture_form_features,
    form_from_history,
    team_match_history,
)


def _sample_data():
    rows = [
        ("2020-08-01", "alpha", "beta", 2, 0),
        ("2020-08-08", "alpha", "gamma", 1, 1),
        ("2020-08-15", "beta", "alpha", 0, 3),
        ("2020-08-22", "gamma", "beta", 2, 1),
        ("2020-08-29", "alpha", "beta", 0, 0),
    ]
    return pd.DataFrame(rows, columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])


def test_no_future_leakage():
    df = _sample_data()
    feats = fixture_form_features(df, "alpha", "beta", date(2020, 8, 15))
    assert feats["home_l5_n"] == 2.0
    assert feats["home_l5_ppg"] == pytest.approx(2.0)


def test_empty_history():
    df = _sample_data()
    feats = fixture_form_features(df, "newclub", "alpha", date(2020, 8, 1))
    assert feats["home_l5_n"] == 0.0
    assert feats["home_l5_ppg"] == 0.0


def test_venue_split():
    df = _sample_data()
    hist_home = team_match_history(df, "alpha", date(2020, 9, 1), venue="home")
    hist_away = team_match_history(df, "alpha", date(2020, 9, 1), venue="away")
    assert len(hist_home) >= 1
    assert len(hist_away) >= 1
