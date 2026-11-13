"""TEST 12a (regression of review test 02) - does shrinkage help a team with very little data?
Ground truth is KNOWN (synthetic league), so error is measured against the true 1X2 probabilities.
PASS = at reg=3 the average |p_model - p_true| is lower than at reg=0, for fixtures of a 6-match team."""
import numpy as np
import _paths
import alea_predictor_v2_4_1 as a
from _common import make

def true_probs(att, dfn, i, j, home_adv=0.25):
    lam = np.exp(0.1 + home_adv + att[i] + dfn[j]); mu = np.exp(0.1 + att[j] + dfn[i])
    mk = a.exact_markets(lam, mu, 0.0)
    return np.array([mk["home"], mk["draw"], mk["away"]])

REGS = [0.0, 1.0, 3.0, 8.0]
res = {r: {"ll": [], "err": [], "top": []} for r in REGS}
for seed in range(30):
    df, teams, att, dfn = make(100 + seed, promoted_matches=6)
    rng = np.random.default_rng(5000 + seed); P = len(teams) - 1
    models = {r: a.fit_model(df, xi=0.0, reg=r, verbose=False, live=True) for r in REGS}
    for o in range(P):
        for i, j in ((P, o), (o, P)):
            tp = true_probs(att, dfn, i, j); out = rng.choice(3, p=tp)
            for r in REGS:
                p = a._predict_outcome_probs(models[r], teams[i], teams[j])
                res[r]["ll"].append(-np.log(p[out])); res[r]["err"].append(np.abs(p - tp).sum()); res[r]["top"].append(p.max())
print(f"{'reg':>5} {'log loss':>9} {'mean|p-p_true|':>15} {'mean top prob':>14}")
for r in REGS:
    print(f"{r:5.1f} {np.mean(res[r]['ll']):9.4f} {np.mean(res[r]['err']):15.4f} {np.mean(res[r]['top']):14.3f}")
assert np.mean(res[3.0]["err"]) < np.mean(res[0.0]["err"])
print("PASS")
