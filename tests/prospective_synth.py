"""Synthetic 20-team league used by the prospective pipeline and API tests.

Produces files in the exact formats of the real sources (OpenFootball JSON,
Wikipedia Sports-table wikitext wrapped in a snapshot JSON) so that the full
pipeline runs offline in CI. No third-party data is involved.
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TEAMS = [
    "Arsenal FC", "Aston Villa FC", "AFC Bournemouth", "Brentford FC", "Brighton & Hove Albion FC",
    "Chelsea FC", "Coventry City FC", "Crystal Palace FC", "Everton FC", "Fulham FC",
    "Hull City AFC", "Ipswich Town FC", "Leeds United FC", "Liverpool FC", "Manchester City FC",
    "Manchester United FC", "Newcastle United FC", "Nottingham Forest FC", "Sunderland AFC",
    "Tottenham Hotspur FC",
]
WIKI_NAMES = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton & Hove Albion", "Chelsea",
    "Coventry City", "Crystal Palace", "Everton", "Fulham", "Hull City", "Ipswich Town", "Leeds United",
    "Liverpool", "Manchester City", "Manchester United", "Newcastle United", "Nottingham Forest",
    "Sunderland", "Tottenham Hotspur",
]
CODES = ["ARS", "AVL", "BOU", "BRE", "BHA", "CHE", "COV", "CRY", "EVE", "FUL",
         "HUL", "IPS", "LEE", "LIV", "MCI", "MUN", "NEW", "NFO", "SUN", "TOT"]
SEASON_START = date(2026, 8, 15)


def schedule(n: int = 20):
    """Double round robin (circle method): list of rounds of (home_idx, away_idx)."""
    teams = list(range(n))
    rounds = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = teams[i], teams[n - 1 - i]
            pairs.append((a, b) if (r + i) % 2 == 0 else (b, a))
        rounds.append(pairs)
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]
    return rounds + [[(b, a) for a, b in rnd] for rnd in rounds]


def _scores(rng, n):
    return rng.poisson(1.5, n), rng.poisson(1.15, n)


def build(tmp: Path, *, played_rounds: int = 13, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    hist = tmp / "openfootball"
    hist.mkdir(parents=True)
    rounds = schedule()
    for year in range(2019, 2026):
        season = f"{year}-{(year + 1) % 100:02d}"
        matches = []
        for r, rnd in enumerate(rounds):
            day = date(year, 8, 10) + timedelta(days=7 * r)
            hg, ag = _scores(rng, len(rnd))
            for (h, a), x, y in zip(rnd, hg, ag):
                matches.append({"date": day.isoformat(), "team1": TEAMS[h], "team2": TEAMS[a],
                                "score": {"ft": [int(x), int(y)]}})
        (hist / f"{season}.json").write_text(json.dumps({"name": season, "matches": matches}))
    fixtures, results = [], {}
    for r, rnd in enumerate(rounds):
        day = SEASON_START + timedelta(days=7 * r)
        hg, ag = _scores(rng, len(rnd))
        for (h, a), x, y in zip(rnd, hg, ag):
            fixtures.append({"round": f"Matchday {r + 1}", "date": day.isoformat(), "time": "15:00",
                             "team1": TEAMS[h], "team2": TEAMS[a]})
            results[(h, a)] = (int(x), int(y), r)
    fixtures_path = tmp / "fixtures.json"
    fixtures_path.write_text(json.dumps({"name": "Premier League 2026/27", "matches": fixtures}))
    env = {"tmp": tmp, "historical_dir": hist, "fixtures": fixtures_path, "rounds": rounds,
           "results": results, "wiki": tmp / "wikipedia.json", "ledger": tmp / "ledger.sqlite",
           "out": tmp / "out", "registry": tmp / "registry.json"}
    shutil.copy(ROOT / "config" / "model_registry.json", env["registry"])
    write_wikipedia(env, played_rounds=played_rounds)
    return env


def round_kickoff(r: int) -> datetime:
    day = SEASON_START + timedelta(days=7 * r)
    # 15:00 London: BST until 25 Oct 2026, GMT afterwards.
    hour = 14 if day < date(2026, 10, 25) else 15
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


def write_wikipedia(env: dict, *, played_rounds: int, overrides: dict | None = None,
                    omit: set | None = None, revid: int = 1000, timestamp: str = "2026-11-01T00:00:00Z",
                    extra_cells: dict | None = None) -> None:
    overrides, omit, extra_cells = overrides or {}, omit or set(), extra_cells or {}
    lines = ["{{#invoke:Sports table|main|style=WDL"]
    for code, name in zip(CODES, WIKI_NAMES):
        lines.append(f"|name_{code}=[[{name} F.C.|{name}]]")
    lines.append("|update=synthetic")
    for (h, a), (x, y, r) in sorted(env["results"].items()):
        key = (h, a)
        if key in extra_cells:
            cell = extra_cells[key]
        elif r < played_rounds and key not in omit:
            x, y = overrides.get(key, (x, y))
            cell = f"{x}\u2013{y}"
        else:
            cell = ""
        lines.append(f"|match_{CODES[h]}_{CODES[a]}={cell}")
    lines.append("}}")
    env["wiki"].write_text(json.dumps({"title": "2026\u201327 Premier League", "revid": revid,
                                       "timestamp": timestamp, "wikitext": "\n".join(lines)}))


def argv(env: dict, now: str, *extra: str) -> list:
    return ["--historical-dir", str(env["historical_dir"]), "--fixtures-json", str(env["fixtures"]),
            "--wikipedia-snapshot", str(env["wiki"]), "--ledger", str(env["ledger"]),
            "--output-dir", str(env["out"]), "--registry", str(env["registry"]), "--now", now, *extra]
