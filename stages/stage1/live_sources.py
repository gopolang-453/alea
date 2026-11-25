"""Current-season data sources for prospective forecasting.

Licensing summary (details and evidence: ``docs/DATA_SOURCES_AND_LICENSING.md``)

* Results  - English Wikipedia season article, ``{{#invoke:Sports table}}``
  ``match_HOME_AWAY=score`` fields. Text licence CC BY-SA 4.0: commercial use,
  redistribution, automated access through the MediaWiki API and retention are
  permitted with attribution and share-alike. Every snapshot records the
  revision id, so each settled score can be traced to an exact page revision.
* Fixtures - OpenFootball ``football.json`` (CC0 / public domain). Dates after
  the first weeks of the season are default matchweek dates; actual kickoffs
  can differ by about two days (TV selections). The pipeline compensates with
  a minimum forecast lead time and never uses OpenFootball times as truth.
* Optional cross-check - a *local* football-data.co.uk CSV. Its fair-use
  policy allows personal / academic use with at most two automated downloads
  per week and forbids commercial use; it is never committed or uploaded.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from stages.stage1.data_store import canonical_team

LONDON = ZoneInfo("Europe/London")
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
# Wikimedia's User-Agent policy requires a descriptive agent with contact info.
USER_AGENT = "ALEA-prospective/3.0 (https://github.com/gopolang-453/alea; research forecasting; via GitHub issues)"
WIKIPEDIA_ATTRIBUTION = ("Results from Wikipedia, '{title}' (revision {revid}), "
                         "CC BY-SA 4.0, https://en.wikipedia.org/w/index.php?oldid={revid}")


class SourceError(RuntimeError):
    """A source could not be read or failed structural validation."""


def london_to_utc(date_str: str, time_str: Optional[str]) -> datetime:
    time_str = (time_str or "15:00")[:5]
    local = datetime.fromisoformat(f"{date_str}T{time_str}").replace(tzinfo=LONDON)
    return local.astimezone(timezone.utc)


def wikipedia_title(season: str) -> str:
    start, end = season.split("-")
    return f"{start}\u2013{end} Premier League"


# --------------------------------------------------------------------- Wikipedia
_SCORE = re.compile(r"(\d{1,2})\s*[\u2013\u2014\-]\s*(\d{1,2})")
_LINK = re.compile(r"\[\[[^|\]]*\|([^\]]*)\]\]")
_PLAIN_LINK = re.compile(r"\[\[([^|\]]*)\]\]")
_REF = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", re.S)
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


@dataclass
class WikipediaResults:
    title: str
    revid: Optional[int]
    revision_timestamp: Optional[str]
    update_date: Optional[str]
    teams: Dict[str, str]
    results: pd.DataFrame                    # home, away, FTHG, FTAG (canonical names)
    unplayed: List[tuple] = field(default_factory=list)
    unparsed: List[dict] = field(default_factory=list)
    content_sha256: str = ""

    @property
    def attribution(self) -> str:
        return WIKIPEDIA_ATTRIBUTION.format(title=self.title, revid=self.revid)


def parse_wikipedia_results(wikitext: str, *, title: str = "", revid: Optional[int] = None,
                            revision_timestamp: Optional[str] = None) -> WikipediaResults:
    """Parse the Sports-table module parameters of a league season article.

    Cell semantics: empty or ``a`` (placeholder link text) = not yet played;
    ``N–M`` = full-time score. Anything else (for example a postponement
    note) is returned in ``unparsed`` for the data-quality log and is never
    guessed into a score.
    """
    text = _COMMENT.sub("", wikitext)
    teams_raw = dict(re.findall(r"^\|\s*name_([A-Z0-9]{2,4})\s*=\s*(.+?)\s*$", text, re.M))
    if len(teams_raw) < 2:
        raise SourceError("no team definitions (name_XXX=) found in the Wikipedia article")
    teams: Dict[str, str] = {}
    for code, raw in teams_raw.items():
        name = _LINK.sub(r"\1", raw)
        name = _PLAIN_LINK.sub(r"\1", name)
        name = _TEMPLATE.sub("", name).strip()
        teams[code] = canonical_team(name)
    if len(set(teams.values())) != len(teams):
        raise SourceError("two Wikipedia team codes map to the same canonical team")
    update = re.search(r"^\|\s*update\s*=\s*(.+?)\s*$", text, re.M)
    rows, unplayed, unparsed = [], [], []
    for home_code, away_code, value in re.findall(
            r"^\|\s*match_([A-Z0-9]{2,4})_([A-Z0-9]{2,4})\s*=(.*)$", text, re.M):
        if home_code not in teams or away_code not in teams:
            raise SourceError(f"match_{home_code}_{away_code} references an undefined team code")
        home, away = teams[home_code], teams[away_code]
        cell = _REF.sub("", value)
        cell = _TEMPLATE.sub("", cell)
        cell = _LINK.sub(r"\1", cell)
        cell = _PLAIN_LINK.sub(r"\1", cell).strip()
        if cell in ("", "a", "—", "\u2014"):
            unplayed.append((home, away))
            continue
        m = _SCORE.fullmatch(cell)
        if not m:
            unparsed.append({"home": home, "away": away, "cell": value.strip()[:120]})
            continue
        rows.append({"home": home, "away": away, "FTHG": int(m.group(1)), "FTAG": int(m.group(2))})
    results = pd.DataFrame(rows, columns=["home", "away", "FTHG", "FTAG"])
    if results.duplicated(["home", "away"]).any():
        raise SourceError("Wikipedia article repeats a home/away pairing")
    return WikipediaResults(
        title=title, revid=revid, revision_timestamp=revision_timestamp,
        update_date=update.group(1) if update else None, teams=teams, results=results,
        unplayed=unplayed, unparsed=unparsed,
        content_sha256=hashlib.sha256(wikitext.encode("utf-8")).hexdigest(),
    )


def fetch_wikipedia_snapshot(season: str, *, session=None, timeout: float = 30.0) -> dict:
    """Latest revision of the season article via the MediaWiki API (no key needed)."""
    import requests

    title = wikipedia_title(season)
    http = session or requests.Session()
    response = http.get(WIKIPEDIA_API, params={
        "action": "query", "prop": "revisions", "titles": title,
        "rvprop": "ids|timestamp|content", "rvslots": "main",
        "format": "json", "formatversion": "2", "maxlag": "5",
    }, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    if response.status_code != 200:
        raise SourceError(f"Wikipedia API HTTP {response.status_code}")
    try:
        page = response.json()["query"]["pages"][0]
        revision = page["revisions"][0]
        content = revision["slots"]["main"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise SourceError(f"unexpected Wikipedia API response for {title!r}: {exc}") from exc
    return {"title": title, "revid": revision["revid"], "timestamp": revision["timestamp"],
            "fetched_at": datetime.now(timezone.utc).isoformat(), "wikitext": content}


def load_wikipedia_snapshot(path: str | Path) -> WikipediaResults:
    try:
        snap = json.loads(Path(path).read_text(encoding="utf-8"))
        return parse_wikipedia_results(snap["wikitext"], title=snap.get("title", ""),
                                       revid=snap.get("revid"), revision_timestamp=snap.get("timestamp"))
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise SourceError(f"cannot read Wikipedia snapshot {path}: {exc}") from exc


# ------------------------------------------------------------------- OpenFootball
def load_openfootball_fixtures(path: str | Path) -> pd.DataFrame:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError(f"cannot read fixture list {path}: {exc}") from exc
    rows = [{"kickoff_utc": london_to_utc(m["date"], m.get("time")),
             "home": canonical_team(m["team1"]), "away": canonical_team(m["team2"])}
            for m in document.get("matches", [])]
    frame = pd.DataFrame(rows, columns=["kickoff_utc", "home", "away"])
    if frame.duplicated(["home", "away"]).any():
        raise SourceError("fixture list repeats a home/away pairing")
    return frame


def load_openfootball_results(path: str | Path) -> pd.DataFrame:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for match in document.get("matches", []):
        score = match.get("score")
        if isinstance(score, list):
            score = {"ft": score}
        if not score or not score.get("ft"):
            continue
        rows.append({"kickoff_utc": london_to_utc(match["date"], match.get("time")),
                     "home": canonical_team(match["team1"]), "away": canonical_team(match["team2"]),
                     "FTHG": int(score["ft"][0]), "FTAG": int(score["ft"][1])})
    return pd.DataFrame(rows, columns=["kickoff_utc", "home", "away", "FTHG", "FTAG"])


def validate_fixture_list(fixtures: pd.DataFrame, *, teams: int = 20) -> List[str]:
    """Structural checks for a double round-robin league. Returns problems."""
    problems = []
    names = sorted(set(fixtures.home) | set(fixtures.away))
    if len(names) != teams:
        problems.append(f"fixture list has {len(names)} teams, expected {teams}")
    expected = teams * (teams - 1)
    if len(fixtures) != expected:
        problems.append(f"fixture list has {len(fixtures)} matches, expected {expected}")
    for team in names:
        h, a = int((fixtures.home == team).sum()), int((fixtures.away == team).sum())
        if h != teams - 1 or a != teams - 1:
            problems.append(f"{team}: {h} home / {a} away fixtures, expected {teams - 1} each")
    if (fixtures.home == fixtures.away).any():
        problems.append("a fixture has the same home and away team")
    return problems


def attach_kickoffs(results: pd.DataFrame, fixtures: pd.DataFrame) -> pd.DataFrame:
    """Join results to the fixture list by (home, away) - unique within a season."""
    merged = results.merge(fixtures, on=["home", "away"], how="left", validate="one_to_one")
    return merged[["kickoff_utc", "home", "away", "FTHG", "FTAG"]]


def results_not_in_fixtures(results: pd.DataFrame, fixtures: pd.DataFrame) -> List[tuple]:
    known = set(zip(fixtures.home, fixtures.away))
    return sorted(p for p in zip(results.home, results.away) if p not in known)


def expected_full_time(kickoff_utc: datetime) -> datetime:
    return kickoff_utc + timedelta(hours=2)
