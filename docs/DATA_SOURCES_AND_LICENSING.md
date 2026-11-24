# Data sources and licensing (Task 2, Stages 4–6)

Checked 24 Nov 2026. Licence terms change. Re-check them before any commercial use. This is an engineering assessment, not legal advice.

**Working assumption:** ALEA is a non-commercial personal/research project. If that changes, read "Commercial use" at the end first.

## Sources used by the automated pipeline

| Role | Source | Licence | Commercial use | Redistribution | Automated access | Attribution | Retention | IDs / dates / scores |
|---|---|---|---|---|---|---|---|---|
| Current-season results (primary) | Wikipedia article "2026–27 Premier League", results matrix, read through the MediaWiki API | [CC BY-SA 4.0](https://en.wikipedia.org/wiki/Wikipedia:Reusing_Wikipedia_content) | Allowed | Allowed with attribution and share-alike | Allowed via the API with a descriptive User-Agent | Required. Each run records the revision id and the oldid URL (e.g. `https://en.wikipedia.org/w/index.php?oldid=1387424026`) | Allowed | Scores only. No dates and no match IDs. Revision id and timestamp give provenance |
| Fixtures + historical results 2019-20…2025-26 | [OpenFootball football.json](https://github.com/openfootball/football.json) | CC0 1.0 (public-domain dedication) | Allowed | Allowed | Allowed (raw GitHub files) | Not required (given anyway) | Allowed | Dates, local kickoff times and scores. No stable IDs |
| Optional local cross-check | [football-data.co.uk](https://football-data.co.uk/contact.php) `E0.csv` | No licence. Terms allow personal/academic use and at most 2 automated downloads a week | No | No | Limited | n/a | Local only | Dates, scores and odds |

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

## Already-committed third-party data (flag)

`results/predictions_closing_odds.csv`, `results/predictions_early_odds.csv` and `results/predictions_closing_dev.csv` were committed before this work (commit `8fbba97`). They contain raw Bet365 odds taken from football-data.co.uk, whose terms do not permit redistribution.

- **Recommendation:** remove them from the public tree and history, or get permission. They have **not** been deleted, because that is the owner's decision.
- New analysis (`scripts/compare_vs_market.py`) writes aggregates only.

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

- Wikipedia (CC BY-SA) and OpenFootball (CC0) remain usable with attribution and share-alike.
- The football-data.co.uk cross-check and the committed odds files must go.
- Fixture data should be cleared with Football DataCo.
- A paid licensed feed (e.g. TheStatsAPI or Stats Perform) is the robust option.
