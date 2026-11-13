"""TEST 10 - teams with no training data: league-average prior, not a crash and not an invented strength.
BEFORE (v2.3.1): a team missing from training raised ValueError (and backtests silently skipped its matches).
AFTER (v2.4): flagged league-average prior for genuinely new teams; a typo is still an error with suggestions."""
import _paths
import numpy as np
import alea_predictor_v2_4_1 as a
from _common import make
old = _paths.optional_import("alea_predictor_v2_3_1")

df, teams, *_ = make(3, n_matches=700, promoted_matches=40)
p = a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, live=True)
if old is not None:
    try: old.predict(old.fit_model(df, xi=0.0018, reg=1.0, verbose=False), "Newcomers", teams[1]); raise SystemExit("?")
    except ValueError as e: print("BEFORE v2.3.1: predict() for an unseen team ->", str(e)[:60])
# 1) the prior is the average team in goal terms: ln(mean(exp(strength))) for attack and for defence
assert abs(p["attack_prior"] - np.log(np.mean(np.exp(list(p["attack"].values()))))) < 1e-12
assert abs(p["defence_prior"] - np.log(np.mean(np.exp(list(p["defence"].values()))))) < 1e-12
q = a.predict(p, "Newcomers", teams[1], allow_new_teams=True)
assert q["prior_only_teams"] == ["Newcomers"] and q["n_obs_home"] == 0
assert abs(q["p_home_win"] + q["p_draw"] + q["p_away_win"] - 1) < 2e-4
# 2) two prior-only teams -> a league-average match: expected goals close to the league's actual averages
q2 = a.predict(p, "NewA", "NewB", allow_new_teams=True)
print(f"2) two prior-only teams: expected goals {q2['lambda_home']} - {q2['lambda_away']}  (league actual {df.FTHG.mean():.3f} - {df.FTAG.mean():.3f})")
assert abs(q2["lambda_home"] / df.FTHG.mean() - 1) < 0.05 and abs(q2["lambda_away"] / df.FTAG.mean() - 1) < 0.05
# (an earlier version of this prior averaged the LOG strengths and failed check 2: 1.358-1.101 vs 1.455-1.246)
# 3) never crashes and never produces an invalid matrix: new team vs EVERY fitted team, both venues, 30 leagues
n = clipped = 0
for seed in range(30):
    d, tm, *_ = make(200 + seed, n_matches=450, promoted_matches=30)
    pp = a.fit_model(d, xi=0.0018, reg=1.0, verbose=False, live=True)
    for t in pp["teams"]:
        for pair in (("Fresh", t), (t, "Fresh")):
            r = a.predict(pp, *pair, allow_new_teams=True); n += 1; clipped += r["rho_clipped_for_pair"]
            assert (r["matrix"] >= 0).all() and abs(r["matrix"].sum() + r["tail_probability"] - 1) < 1e-12
print(f"3) {n} new-team pairings across 30 leagues: 0 errors, rho had to be clipped for {clipped} of them")
# 4) the typed-name API: typo -> error with suggestions; genuine new team (listed by the data source) -> prior
m = a.ALEA(data=df, xi=0.0018, reg=1.0)
import pandas as pd
m.known_teams |= {"Newcomers"}                      # as if the fixture list contained them
r = m.predict("Newcomers", teams[1]); assert r["prior_only_teams"] == ["Newcomers"]
txt = a.explain(r); assert "NO matches in the training data" in txt and "league-average prior" in txt
print("4) explain():", txt[-160:])
try: m.predict(teams[0] + "x", teams[1]); raise SystemExit("FAIL: typo accepted as a new team")
except ValueError as e: print("   typo ->", str(e)[:75])
# 5) backtests include prior-only predictions by default and COUNT them; 'skip' reproduces the old behaviour
d, *_ = make(9, n_matches=700, promoted_matches=40)
d.loc[d.index[-60:], "HomeTeam"] = "Promoted United"        # a team that first appears late
rep_p, *_ = a.walk_forward_backtest(d, min_train_matches=300, step_days=21, verbose=False, tune_each_fold=False)
rep_s, *_ = a.walk_forward_backtest(d, min_train_matches=300, step_days=21, verbose=False, tune_each_fold=False, new_teams="skip")
print(f"5) backtest: prior mode scored {rep_p['n_predictions']} matches ({rep_p['n_predictions_with_prior_only_team']} prior-only); "
      f"skip mode scored {rep_s['n_predictions']} and skipped {rep_s['n_skipped_team_not_in_training']}")
assert rep_p["n_predictions_with_prior_only_team"] > 0 and rep_s["n_skipped_team_not_in_training"] > 0
assert rep_p["n_predictions"] == rep_s["n_predictions"] + rep_s["n_skipped_team_not_in_training"]
assert "model_rps_excluding_prior_only" in rep_p        # honest split: results with and without prior-only teams
print("PASS")
