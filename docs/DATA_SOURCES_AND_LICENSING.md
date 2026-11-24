# Data sources and licensing (Task 2, Stages 4–6)

Checked 24 Nov 2026 against the licence texts linked below. Licence terms change. Re-check them before any commercial use. **This is an engineering assessment, not legal advice. Every point marked "legal review" is unresolved and must not be read as cleared.**

**Working assumption:** ALEA is a non-commercial personal/research project. If that changes, read "Commercial use" at the end first.

## Sources used by the automated pipeline

| Role | Source | Licence | Commercial use | Redistribution | Automated access | Attribution | Retention | IDs / dates / scores |
|---|---|---|---|---|---|---|---|---|
| Current-season results (primary) | Wikipedia article "2026–27 Premier League", results matrix, read through the MediaWiki API | [CC BY-SA 4.0](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content) | Allowed | Allowed with attribution and share-alike | Allowed via the API with a descriptive User-Agent | Required. Each run records the revision id and the oldid URL (e.g. `https://en.wikipedia.org/w/index.php?oldid=1387424026`) | Allowed | Scores only. No dates and no match IDs. Revision id and timestamp give provenance |
| Fixtures + historical results 2019-20…2025-26 | [OpenFootball football.json](https://github.com/openfootball/football.json) | CC0 1.0 (public-domain dedication) | Allowed | Allowed | Allowed (raw GitHub files) | Not required (given anyway) | Allowed | Dates, local kickoff times and scores. No stable IDs |
| Optional local cross-check | [football-data.co.uk](https://football-data.co.uk/contact.php) `E0.csv` | No licence. Terms allow personal/academic use and at most 2 automated downloads a week | No | No | Limited | n/a | Local only. `--crosscheck-csv` stores its scores in the ledger, so it is refused inside GitHub Actions and must not be used on a ledger you publish | Dates, scores and odds |

### Why Wikipedia for current results

- It is the only free source found with a clear licence that covers commercial use, redistribution, automated access and retention.
- **Verified accuracy:** all 110 current-season results (revision 1387424026, 23 Nov 2026 22:06 UTC) matched football-data.co.uk exactly. There were 0 disagreements.
- **Limitations and mitigations:**
  1. **Community-edited.** Vandalism or mistakes are possible. Every result is stored with its revision id. Disagreement with any second source (OpenFootball scores, or the optional local CSV) is logged as a conflict, and the forecast is not settled until an operator resolves it (`scripts/ledger_admin.py correct`).
  2. **No dates.** Results are matched to fixtures by (season, home, away), which is unique in a league season.
  3. **Freshness.** It is usually updated within hours. The pipeline blocks if a past fixture has no result, unless the gap looks like a postponement (see `docs/PROSPECTIVE_EVALUATION.md`).
  4. **Share-alike.** Redistributed derived data (the ledger's result observations) must stay under CC BY-SA 4.0 with attribution. Model probabilities are ALEA's own output.

### Why OpenFootball for fixtures

- It is CC0, so there is no restriction.
- **Stale.** The 2026-27 results stop at 20 Sep 2026.
- **Placeholder dates.** After October the dates are the default matchweek dates, not the TV-selected ones. Against football-data's actual dates, 13 of 110 kickoffs differ, 9 of them by up to ±2 days.
- **Mitigation:**
  - Forecasts are made only for fixtures at least 48 h after the run (`--min-lead-hours 48`).
  - A match played more than about 2 days before its listed date is detected when its result appears. It is logged as `played_well_before_listed_kickoff`.
- **Residual risk:** a match moved earlier by more than 2 days, and played before a run but not yet on Wikipedia, could be forecast after kickoff. This has not happened. If it does, the operator records `VOID` (`ledger_admin.py event KEY VOID`) and the forecast is excluded from scoring.

## Sources assessed and rejected for automation

| Source | Finding |
|---|---|
| [football-data.org](https://www.football-data.org/index/about) | Needs an API key. The free tier is non-commercial and requires attribution. Redistribution is not allowed and retention is restricted. Usable only as a private cross-check with a key kept in secrets. Not integrated. |
| [TheStatsAPI](https://www.thestatsapi.com/terms) | Commercial licence from about $50/month. Caching and redistribution are limited. Suitable if ALEA becomes commercial. |
| [API-Football](https://www.api-football.com/terms) | Its terms give no licence to publish the data. Not suitable for a public ledger. |
| Official fixture data | Premier League fixture lists are licensed by [Football DataCo](https://www.premierleague.com/en/about/faq/other), with commercial terms via [Stats Perform](https://www.statsperform.com/legal/fdcterms/). The CJEU held in [C-604/10](http://www.eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62010CJ0604) that fixture lists are not protected by copyright merely because of the effort to compile them. Commercial use of fixture data should still be cleared with Football DataCo. |

## Licensing analysis by kind of information (legal review required)

The project assumes **non-commercial personal/research use**. This assumption has not been changed. Different kinds of information are treated differently; none of the points below is legal certainty.

| Information | What ALEA stores or publishes | Claimed licence | Does the licence actually cover it? | Status |
|---|---|---|---|---|
| Match scores of the current season (Wikipedia results matrix) | One row per observed score in `result_observations`, with source name, Wikipedia revision id and the run time; published in the public `prospective-ledger` branch | CC BY-SA 4.0 ([legal code](https://creativecommons.org/licenses/by-sa/4.0/legalcode)) | Only to the extent copyright or sui generis database rights subsist. The [CC FAQ](https://creativecommons.org/faq/) states that purely factual data is not subject to copyright and that CC licence conditions are not triggered where no permission is needed. Individual scores are facts. Section 4 of the legal code extends BY-SA to sui generis database rights when "all or a substantial portion" of a database is extracted and shared, and makes the receiving database Adapted Material for ShareAlike. ALEA extracts the whole results matrix every run, so it treats the ledger's result observations as CC BY-SA 4.0 and attributes them. Whether the Wikipedia article's matrix attracts EU/UK database rights at all is uncertain. | Conservative compliance (attribution + share-alike on the observations). **Legal review** for commercial use. |
| Article text, layout, prose | Not stored. Only the parsed scores and team names are kept; the raw snapshot (`data/raw/live/`) is git-ignored and never committed | CC BY-SA 4.0 (and GFDL where dual-licensed, per [Reusing Wikipedia content](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content)) | Covered, but not redistributed | OK |
| Fixture list (dates, kickoff times, pairings) | Listed kickoff per forecast in `predictions.kickoff_at` and in reports | CC0 per [OpenFootball](https://github.com/openfootball/football.json) ("dedicated to the public domain") | CC0 waives **only the rights OpenFootball's contributors hold**. It cannot clear rights held by others. Premier League fixture lists are licensed commercially by Football DataCo ([Premier League FAQ](https://www.premierleague.com/en/about/faq/other); [Stats Perform terms](https://www.statsperform.com/legal/fdcterms/)). The CJEU held that drawing up a fixture list is not the kind of investment that creates the EU sui generis database right ([C-444/02 Fixtures Marketing v OPAP](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62002CJ0444); joined press release for [C-46/02, C-203/02, C-338/02, C-444/02](https://curia.europa.eu/jcms/upload/docs/application/pdf/2009-02/cp040089en.pdf)) and that fixture lists are not protected by copyright merely because of the skill and labour of compiling them ([C-604/10 Football Dataco v Yahoo](http://www.eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:62010CJ0604)). Post-Brexit UK law and contractual/other claims are not covered by these rulings. | Acceptable for the current non-commercial assumption on the engineering reading. **Legal review** before any commercial use or distribution of the fixture list itself. |
| Historical results 2019-20…2025-26 | Used to fit models; not republished (raw files git-ignored); aggregate metrics only | CC0 (OpenFootball) | Same caveat: CC0 covers OpenFootball's own rights | OK for current use |
| ALEA probabilities | Ledger, reports, API | ALEA's own output | Not third-party data. The model is fitted on the data above; whether model output is a derivative of a database is not settled. **Legal review** for commercial use | — |
| Bookmaker odds (football-data.co.uk) | **Removed from the tree on this branch.** Only aggregates of the champion-vs-market comparison remain (`results/stage9_market/`) | None. [Terms](https://football-data.co.uk/contact.php) allow personal/academic use, not redistribution | Not covered | See "Odds files" below |

### Obligations ALEA meets for CC BY-SA 4.0

- **Attribution (Section 3(a)):** creator ("Wikipedia contributors"), title, the revision-specific URL (`https://en.wikipedia.org/w/index.php?oldid=<revid>`), a link to the licence, and an indication of modification ("scores parsed from the results matrix"). These appear in every `runs/run_*.json` (`sources.results`: title, revid, URL, revision timestamp, retrieval time `retrieved_at`), in every `report.md` ("Data sources and licences" section, always present), in the API (`attribution` object on `/v1/status`, `/v1/predictions/*` and `/v1/evaluation`) and in the data-branch README. Section 3(a)(2) allows attribution "in any reasonable manner", including by a link to a resource that contains it.
- **ShareAlike (Section 3(b), Section 4(b)):** the ledger's result observations remain under CC BY-SA 4.0; no additional terms or technical restrictions are applied to them.
- **No warranty and revocation:** the licence is irrevocable for content already received ([CC FAQ](https://creativecommons.org/faq/)), but rights terminate automatically on non-compliance and are reinstated if cured within 30 days (Section 6). Attribution must therefore never be dropped from public outputs.
- **Automated access:** the MediaWiki API is called once per run with a descriptive User-Agent including a contact URL, as required by the [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy), and with `maxlag=5`. Two runs a week is a negligible load.
- **Retention and provenance:** revision id, revision timestamp, content SHA-256 and retrieval time are kept for every run; fixtures are recorded with their URL, SHA-256 and retrieval time (file modification time on the runner).

### What is not established

- Whether EU/UK sui generis database rights subsist in the Wikipedia results matrix or in OpenFootball's files (if they do not, the CC conditions are not triggered for the scores; ALEA complies anyway).
- Whether Football DataCo could assert rights against republication of listed kickoff times under UK law or contract.
- Whether commercial use of model outputs trained on these sources needs any licence.
- These need a lawyer before any commercial use. Nothing in this repository is a legal clearance.

## Odds files (Task 2 of the final audit)

`results/predictions_closing_odds.csv`, `results/predictions_early_odds.csv` and `results/predictions_closing_dev.csv` contained per-match Bet365 odds (raw and devigged) taken from football-data.co.uk, whose terms do not permit redistribution. They were committed in `8fbba97` (13 Nov 2026).

- **Done on `repair/alea-3.0-consolidated`:** the three files are removed from the tree (`git rm`). No workflow uploads them; no test or document reproduces their contents. `scripts/compare_vs_market.py` now requires `--odds <your local file>` (no tracked default), exits 2 with a clear message if the file is missing or malformed, writes aggregates only, and its tests use synthetic odds. Keep your copy outside the repository or under the git-ignored `data/` directory (e.g. `data/private/odds/`).
- **Not done (needs your approval):** the files remain in the git history of `main`, of six other branches and of the read-only pull-request refs, and they are still in the tree of `main` until PR #4 is merged. **Removal from the latest commit does not make the data legally cleared**, and anyone who cloned the public repository may already hold a copy. The cleanup procedure is in `docs/ODDS_DATA_HISTORY_CLEANUP.md`.

## Stages 4–6: feature data (Task 6)

| Stage | Data needed | Candidates found | Licence | Coverage | Availability timestamps | Decision |
|---|---|---|---|---|---|---|
| 4 xG | Per-match xG, known before the next match | [StatsBomb open data](https://github.com/hudl/open-data/blob/master/README.md) | Non-commercial, attribution | Selected competitions/seasons only. Not a continuous PL history | None | **BLOCKED** |
| | | FBref / Sports Reference | Terms forbid building databases and using the data for ML ([terms](https://www.sports-reference.com/termsofuse.html), [data use](https://www.sports-reference.com/data_use.html)). Opta-based advanced data was removed in Jan 2026 ([FBref blog](https://www.sports-reference.com/blog/category/fbref/)) | — | — | Rejected |
| | | Understat | No published terms or licence ([summary](https://with-bet.com/tools/stats/understat)) | Good | None | Rejected (unclear rights) |
| 5 players / lineups / injuries | Injury and suspension lists and lineups, each with the time they became public | No free licensed source with timestamps. Official lineups appear about 1 h before kickoff | Commercial feeds only | — | Not provided | **BLOCKED**. Lineups are also incompatible with forecasts made ≥48 h ahead |
| 6 context | Rest days, travel, referee, weather | Rest days and travel could be derived from CC0 fixtures, but for PL matches only (no cup/European games), which biases the feature | CC0 | Partial | Derivable | **BLOCKED** (not implemented: the partial coverage would mismeasure rest) |

### Requirements to unblock Stages 4–6

1. A source with a written licence covering storage and model training.
2. Continuous PL coverage for at least 5 seasons.
3. A per-record publication or availability timestamp, so features can be computed as of the forecast time.
4. A pre-registered identical-fixture evaluation against the champion, using the promotion rule in `config/model_registry.json`.

The feature calculators in `stages/stage4..6` stay unit-tested scaffolding, and none of them is wired into the champion.

## Commercial use

If ALEA is used commercially:

- Wikipedia (CC BY-SA) and OpenFootball (CC0) permit commercial use of what they license, with attribution and share-alike for Wikipedia, but see "What is not established" above (legal review).
- The football-data.co.uk cross-check must go (it is already refused inside GitHub Actions), and the odds files must also be purged from history (`docs/ODDS_DATA_HISTORY_CLEANUP.md`).
- Fixture data should be cleared with Football DataCo.
- A paid licensed feed (e.g. TheStatsAPI or Stats Perform) is the robust option.
