# ALEA development candidate

This is not a release. v2.4.1 was not edited. Its SHA-256 is still

`4cfc61085ae742a550944a410ec81a1b21a47cc8ab7688bde0d879c7c24f022a`

The development file is `alea_predictor_dev.py`. Its version string is `alea-dc-dev`, so a saved model cannot be loaded as v2.4.1.

## What was broken

`reg = 0` makes the Poisson attack/defence maximum likelihood estimator unbounded when a team has scored no goals, or conceded no goals. The optimiser stops at a log-strength around −12. Later matches then get probabilities like 10⁻⁷.

That happened on three Premier League matches, all with `reg = 0`:

| Match | v2.4.1 probability of the result that happened | Development candidate |
|---|---:|---:|
| Burnley 1–3 Aston Villa, 27 Aug 2023 | home win 0.000008 | 0.246 / 0.243 / 0.511 |
| Manchester City 4–1 Ipswich, 24 Aug 2024 | away win 0.0000004 | 0.856 / 0.104 / 0.040 |
| Burnley 2–0 Sunderland, 23 Aug 2025 | home win 0.0000003 | 0.099 / 0.171 / 0.730 |

The Sunderland case is the one that dominated the log-loss gap. Sunderland had beaten West Ham 3–0 in their only previous match, so with no penalty their defence went to −11.4. The development fit uses `reg = 1` there. 0.099 for the home win is still too low (they won 2–0, and Bet365 had the home win near 0.41). It is no longer a numerical collapse.

## What was changed

1. `fit_model` refuses `reg = 0` when any team has scored 0 or conceded 0. The likelihood has no maximum in that case.
2. After a fit, a team strength beyond 3 log-points (about 20 times the league rate) is refused.
3. The default tuner no longer offers `reg = 0`. The candidates are 1, 3 and 8, chosen inside each training window only. 0.5 and 2 were not added. Picking them on these 1,140 matches would be tuning on the same matches used to report the score.
4. `Man United` is now an alias of `Manchester United`, same as `Man Utd`. In this file every row said `Man United`, so this is a rename of one club, not a merge of two.

Not changed: the Dixon–Coles formulas, the value engine, the score grid, time decay, or the draw probability. The value engine in this folder is a byte copy of v0.2.1.

## What was tested

`tests/test_dev_repairs.py` was run in this sandbox. It passed.

- `reg = 0` on a team that has scored 0 raises `ValueError`.
- The same data at `reg = 1` gives probabilities above 0.01 that sum to 1.
- Save and load round-trip. The loaded file is `alea-dc-dev`.
- A team playing itself is refused.
- The value engine accepts a three-way market, probabilities sum to 1, and staking stays off.

The untouched v2.4.1 suite was re-run from its own folder. `v241_suite_log.txt` records 16 of 16 files passed, including the 50-digit score test. That suite tests v2.4.1, not this development file.

## Closing-odds comparison

Same 1,140 matches, 11 Aug 2023 to 24 May 2026. Training uses only earlier dates. Retune every 8 match dates, on that training window only. Bet365 closing prices, Shin de-vig. This sample is the one on which the three bad matches were found, so the log-loss drop is an explanation of a bug, not an independent season.

| | Log loss | Brier | RPS | Right result | Smallest probability |
|---|---:|---:|---:|---:|---:|
| v2.4.1 | 0.9964 | 0.5876 | 0.2021 | 0.518 | 2.7e-7 |
| Development candidate | 0.9868 | 0.5881 | 0.2022 | 0.519 | 0.017 |
| Bet365 closing | 0.9595 | 0.5698 | 0.1937 | 0.550 | — |

Development minus v2.4.1 log loss: −0.0096. 95% interval −0.033 to +0.003. It includes zero.

Development minus Bet365 log loss: +0.027. 95% interval +0.015 to +0.038. It does not include zero.

Brier and RPS did not improve. The repair is a log-loss repair of three impossible probabilities, not a better description of the typical match.

By season, development vs Bet365 log loss: 0.948 vs 0.897, 0.981 vs 0.967, 1.032 vs 1.014. Still behind in every season.

Draw probabilities are still low: 0.210 vs 0.216 in 2023/24, 0.226 vs 0.245 in 2024/25, 0.242 vs 0.274 in 2025/26. No draw adjustment was added.

The tuner picked `reg` 1 on 785 matches, 3 on 194, and 8 on 161. It never picked 0.

## Calibration

A temperature on the three probabilities, chosen only from matches already played, was applied to the later matches. Mean temperature 1.01. Log loss on the last 940 matches was 0.9919 against 0.9911 with no temperature. It does not help. It is not in the code.

Rest days were tested earlier against v2.4.1 and made log loss slightly worse. Not added.

xG, injuries, lineups and Elo were not tested. Those tables are not in this dataset.

## Recommendation

Do not give this a release number yet.

Keep it as the development candidate because `reg = 0` can emit a probability of 10⁻⁷, and that is a broken fit, not a forecast. Do not replace v2.4.1 on the basis of the 0.010 log-loss drop: the interval includes zero, Brier did not move, and the model is still behind Bet365. The next check is a season that was not used to find these three matches.
