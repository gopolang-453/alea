"""TEST 11 (regression of review test 01) - the 'Invalid Dixon-Coles score matrix' failure.
Claim: v2.2 can fit a model that is invalid for some team pairing that never occurred;
v2.4 cannot, because rho is constrained for EVERY pairing and verified after each fit.
Same 40 synthetic datasets for both versions. PASS = v2.4 has 0 invalid fits."""
import itertools
import _paths
import alea_predictor_v2_4_1 as new
from _common import make
old = _paths.optional_import("alea_predictor_v2_2")

def all_pairings_ok(mod, params):
    T = params["teams"]
    for h in T:
        for a_ in T:
            if h != a_:
                try: mod._predict_outcome_probs(params, h, a_)
                except ValueError: return False
    return True

N = 40; bad_old = bad_new = 0
for s in range(N):
    df, *_ = make(s)
    if old is not None:
        bad_old += (not all_pairings_ok(old, old.fit_model(df, xi=0.0018, verbose=False)))
    pn = new.fit_model(df, xi=0.0018, reg=1.0, verbose=False, live=True)
    bad_new += (not all_pairings_ok(new, pn))
    T = pn["teams"]
    for h, a_ in itertools.islice(itertools.permutations(T, 2), 0, 400, 7):
        P = new.predict(pn, h, a_)["matrix"]
        assert (P >= 0).all() and abs(P.sum() + new.tail_probability(*new._lam_mu(pn, h, a_, False)[:2]) - 1) < 1e-12
print(f"v2.2   fits with >=1 invalid pairing: {bad_old}/{N}" if old else "v2.2 file not found - comparison skipped")
print(f"v2.4 fits with >=1 invalid pairing: {bad_new}/{N}")
assert bad_new == 0
print("PASS")
