import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_prospective_forecast import (
    GateError,
    _london_to_utc,
    fixture_key,
    load_results_csv,
    run_gates,
)
from stages.stage1.data_store import canonical_team


def _fixtures():
    return pd.DataFrame({
        "kickoff_utc": [_london_to_utc("2026-11-21", "15:00"), _london_to_utc("2026-11-28", "15:00")],
        "home": ["arsenal", "leeds united"],
        "away": ["chelsea", "coventry city"],
    })


def _results(hg=2):
    return pd.DataFrame({"kickoff_utc": [_london_to_utc("2026-11-21", "15:00")],
                         "home": ["arsenal"], "away": ["chelsea"], "FTHG": [hg], "FTAG": [1]})


NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)


def test_gates_pass_on_complete_consistent_fresh_feed():
    report = run_gates(_fixtures(), _results(), _results(), NOW, grace_hours=36, max_age_hours=240)
    assert report["fixtures_due"] == 1 and report["cross_checked_results"] == 1
    assert report["freshness"]["status"] == "fresh"


def test_gate_blocks_when_past_fixture_has_no_result():
    empty = _results().iloc[0:0]
    with pytest.raises(GateError, match="incomplete"):
        run_gates(_fixtures(), empty, empty, NOW, grace_hours=36, max_age_hours=240)


def test_gate_blocks_when_feeds_disagree():
    with pytest.raises(GateError, match="disagree"):
        run_gates(_fixtures(), _results(2), _results(3), NOW, grace_hours=36, max_age_hours=240)


def test_gate_blocks_stale_feed():
    later = datetime(2026, 12, 20, tzinfo=timezone.utc)
    fixtures = _fixtures().iloc[:1]
    with pytest.raises(GateError, match="stale"):
        run_gates(fixtures, _results(), _results(), later, grace_hours=36, max_age_hours=240)


def test_london_kickoffs_convert_across_dst():
    assert _london_to_utc("2026-08-22", "15:00").hour == 14  # BST
    assert _london_to_utc("2026-11-28", "15:00").hour == 15  # GMT
    assert fixture_key(_london_to_utc("2026-11-28", "20:00"), "a", "b") == "2026-11-28|a|b"


def test_football_data_short_names_match_openfootball_long_names():
    pairs = {"Hull": "Hull City AFC", "Coventry": "Coventry City FC", "Leeds": "Leeds United FC",
             "Nott'm Forest": "Nottingham Forest FC", "Man United": "Manchester United FC",
             "Brighton": "Brighton & Hove Albion FC", "Bournemouth": "AFC Bournemouth",
             "Tottenham": "Tottenham Hotspur FC", "Ipswich": "Ipswich Town FC"}
    for short, long in pairs.items():
        assert canonical_team(short) == canonical_team(long)


def test_results_csv_parsing(tmp_path):
    path = tmp_path / "E0.csv"
    path.write_text("\ufeffDiv,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG\n"
                    "E0,21/11/2026,15:00,Arsenal,Chelsea,2,1\n", encoding="utf-8")
    frame = load_results_csv(path)
    assert frame.loc[0, "home"] == "arsenal" and frame.loc[0, "FTHG"] == 2
    assert frame.loc[0, "kickoff_utc"] == _london_to_utc("2026-11-21", "15:00")
