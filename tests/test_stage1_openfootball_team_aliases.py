"""Canonicalise the actual team-name variants in OpenFootball PL seasons."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import canonical_team


def test_openfootball_team_name_variants_collapse_to_stable_ids():
    variants = {
        "Arsenal FC": "arsenal",
        "Aston Villa FC": "aston villa",
        "Brighton & Hove Albion FC": "brighton and hove albion",
        "Brighton & Hove Albion": "brighton and hove albion",
        "Burnley FC": "burnley",
        "Chelsea FC": "chelsea",
        "Crystal Palace FC": "crystal palace",
        "Everton FC": "everton",
        "Fulham FC": "fulham",
        "Leeds United FC": "leeds united",
        "Leicester City FC": "leicester city",
        "Liverpool FC": "liverpool",
        "Manchester City FC": "manchester city",
        "Manchester United FC": "manchester united",
        "Newcastle United FC": "newcastle united",
        "AFC Bournemouth": "bournemouth",
        "Bournemouth": "bournemouth",
        "Southampton FC": "southampton",
        "Tottenham Hotspur FC": "tottenham",
        "Wolverhampton Wanderers FC": "wolverhampton",
        "West Ham United": "west ham united",
        "West Bromwich Albion FC": "west bromwich albion",
        "Nottingham Forest FC": "nottingham forest",
    }
    for source_name, expected in variants.items():
        assert canonical_team(source_name) == expected
