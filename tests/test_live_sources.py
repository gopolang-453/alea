"""Wikipedia results parser and OpenFootball fixture validation."""
import json

import pandas as pd
import pytest

from stages.stage1.live_sources import (
    SourceError,
    attach_kickoffs,
    fetch_wikipedia_snapshot,
    load_openfootball_fixtures,
    parse_wikipedia_results,
    results_not_in_fixtures,
    validate_fixture_list,
    wikipedia_title,
)
from tests.prospective_synth import TEAMS, schedule

WIKITEXT = """{{#invoke:Sports table|main|style=WDL
<!--Team definitions-->
|name_ARS=[[Arsenal F.C.|Arsenal]]
|name_BHA=[[Brighton & Hove Albion F.C.|Brighton & Hove Albion]]
|name_IPS=[[Ipswich Town F.C.|Ipswich Town]]  
|name_TOT=[[Tottenham Hotspur]]
|update=23 November 2026
|match_ARS_BHA=[[Some rivalry|2–1]]
|match_ARS_IPS=3–0<ref>{{cite web |title=x}}</ref>
|match_ARS_TOT=[[North London derby|a]]
|match_BHA_ARS=
|match_BHA_IPS=0 – 0{{efn|played behind closed doors}}
|match_IPS_ARS=P
|match_TOT_ARS=1-4
}}"""


def test_parse_scores_links_refs_and_notes():
    r = parse_wikipedia_results(WIKITEXT, title="t", revid=5, revision_timestamp="2026-11-23T22:06:16Z")
    assert r.update_date == "23 November 2026"
    assert set(r.teams.values()) == {"arsenal", "brighton and hove albion", "ipswich town", "tottenham"}
    got = {(x.home, x.away): (x.FTHG, x.FTAG) for x in r.results.itertuples()}
    assert got == {("arsenal", "brighton and hove albion"): (2, 1), ("arsenal", "ipswich town"): (3, 0),
                   ("brighton and hove albion", "ipswich town"): (0, 0), ("tottenham", "arsenal"): (1, 4)}
    assert ("arsenal", "tottenham") in r.unplayed and ("brighton and hove albion", "arsenal") in r.unplayed
    assert r.unparsed == [{"home": "ipswich town", "away": "arsenal", "cell": "P"}]
    assert "oldid=5" in r.attribution and "CC BY-SA 4.0" in r.attribution
    assert len(r.content_sha256) == 64


def test_comments_are_ignored():
    text = WIKITEXT.replace("|match_TOT_ARS=1-4", "<!--|match_TOT_ARS=1-4-->")
    r = parse_wikipedia_results(text)
    assert ("tottenham", "arsenal") not in set(zip(r.results.home, r.results.away))


def test_undefined_team_code_and_missing_teams_fail():
    with pytest.raises(SourceError):
        parse_wikipedia_results(WIKITEXT + "\n|match_ARS_XXX=1–0")
    with pytest.raises(SourceError):
        parse_wikipedia_results("|match_ARS_TOT=1–0")


def test_duplicate_canonical_names_fail():
    with pytest.raises(SourceError):
        parse_wikipedia_results(WIKITEXT + "\n|name_AR2=[[Arsenal F.C.|Arsenal FC]]")


def _fixture_file(tmp_path, drop=0):
    rounds = schedule()
    matches = [{"date": "2026-08-15", "time": "15:00", "team1": TEAMS[h], "team2": TEAMS[a]}
               for rnd in rounds for h, a in rnd]
    if drop:
        matches = matches[:-drop]
    path = tmp_path / "fx.json"
    path.write_text(json.dumps({"matches": matches}))
    return path


def test_fixture_list_validation(tmp_path):
    fx = load_openfootball_fixtures(_fixture_file(tmp_path))
    assert validate_fixture_list(fx) == []
    short = load_openfootball_fixtures(_fixture_file(tmp_path, drop=1))
    problems = validate_fixture_list(short)
    assert any("379 matches" in p for p in problems)


def test_duplicate_pairing_in_fixture_list(tmp_path):
    path = tmp_path / "dup.json"
    m = {"date": "2026-08-15", "team1": "Arsenal FC", "team2": "Chelsea FC"}
    path.write_text(json.dumps({"matches": [m, {**m, "date": "2026-09-01"}]}))
    with pytest.raises(SourceError):
        load_openfootball_fixtures(path)


def test_attach_kickoffs_and_strays(tmp_path):
    fx = load_openfootball_fixtures(_fixture_file(tmp_path))
    res = pd.DataFrame({"home": ["arsenal", "nobody"], "away": ["chelsea", "arsenal"],
                        "FTHG": [1, 0], "FTAG": [0, 0]})
    assert results_not_in_fixtures(res, fx) == [("nobody", "arsenal")]
    joined = attach_kickoffs(res.iloc[:1], fx)
    assert joined.kickoff_utc.notna().all()


def test_title_and_fetch_error_handling():
    assert wikipedia_title("2026-27") == "2026\u201327 Premier League"

    class Resp:
        def __init__(self, status, payload):
            self.status_code, self._payload = status, payload

        def json(self):
            return self._payload

    class Session:
        def __init__(self, resp):
            self.resp, self.calls = resp, []

        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append(headers)
            return self.resp

    s = Session(Resp(503, {}))
    with pytest.raises(SourceError, match="503"):
        fetch_wikipedia_snapshot("2026-27", session=s)
    assert "github.com/gopolang-453/alea" in s.calls[0]["User-Agent"]
    with pytest.raises(SourceError):
        fetch_wikipedia_snapshot("2026-27", session=Session(Resp(200, {"query": {"pages": [{}]}})))
    ok = {"query": {"pages": [{"revisions": [{"revid": 9, "timestamp": "2026-11-23T00:00:00Z",
                                              "slots": {"main": {"content": WIKITEXT}}}]}]}}
    snap = fetch_wikipedia_snapshot("2026-27", session=Session(Resp(200, ok)))
    assert snap["revid"] == 9 and snap["wikitext"] == WIKITEXT
