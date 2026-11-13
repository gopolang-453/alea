"""TEST 15 - EXACT SCORE PROBABILITIES (v2.4.1, correction 2).
BEFORE (v2.4): score_matrix() divided by P.sum(), silently spreading the omitted tail over the grid; 1X2, over/under and
BTTS were then read off that renormalised grid. AFTER (v2.4.1): the grid holds exact cell probabilities (sum = 1 - tail,
tail reported); markets are computed over the FULL distribution in closed form, so they do not depend on the grid size.
Independent references: (a) an mpmath (50-digit) summation over a 150-goal grid, (b) a 200-goal float grid, (c) hand derivation."""
import inspect
import _paths
import numpy as np
from scipy.stats import poisson
import mpmath as mp
import alea_predictor_v2_4_1 as a
import alea_value_engine_v0_2_1 as v
from _common import make
prev = _paths.optional_import("alea_predictor_v2_4")

mp.mp.dps = 50
def mp_reference(lam, mu, rho, N=150):
    """Exact (50-digit) market probabilities from a 150-goal grid; the neglected remainder is < 1e-90 for lam, mu <= 8."""
    lam, mu, rho = mp.mpf(lam), mp.mpf(mu), mp.mpf(rho)
    f = [mp.e ** -lam * lam ** k / mp.factorial(k) for k in range(N + 1)]
    g = [mp.e ** -mu * mu ** k / mp.factorial(k) for k in range(N + 1)]
    home = draw = away = o15 = o25 = o35 = btts = mp.mpf(0)
    for h in range(N + 1):
        for k in range(N + 1):
            c = f[h] * g[k]
            if h == 0 and k == 0: c *= 1 - lam * mu * rho
            elif h == 0 and k == 1: c *= 1 + lam * rho
            elif h == 1 and k == 0: c *= 1 + mu * rho
            elif h == 1 and k == 1: c *= 1 - rho
            if h > k: home += c
            elif h == k: draw += c
            else: away += c
            if h + k >= 2: o15 += c
            if h + k >= 3: o25 += c
            if h + k >= 4: o35 += c
            if h >= 1 and k >= 1: btts += c
    return {"home": home, "draw": draw, "away": away, "over_1_5": o15, "over_2_5": o25, "over_3_5": o35, "btts_yes": btts}

def mp_tail(lam, mu, N):
    lam, mu = mp.mpf(lam), mp.mpf(mu)
    F = lambda m: sum(mp.e ** -m * m ** k / mp.factorial(k) for k in range(N + 1))
    return 1 - F(lam) * F(mu)

CASES = [("ordinary", 1.4, 1.1, -0.10), ("low scoring", 0.7, 0.5, -0.08), ("strong home", 2.8, 0.7, -0.12),
         ("high", 4.0, 1.5, -0.10), ("very high", 5.5, 4.5, -0.02), ("lopsided", 0.15, 6.0, -0.05)]

# ---- 1. the grid is NOT renormalised
src = inspect.getsource(a.score_matrix)
import ast
tree = ast.parse(src)                                                     # inspect the CODE (docstrings are not code)
fn = tree.body[0]; body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) else fn.body
nodes = [n for stmt in body for n in ast.walk(stmt)]
assert not any(isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Div) for n in nodes), "score_matrix divides in place"
assert not any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("clip", "sum") for n in nodes), "score_matrix clips or sums"
lam, mu, rho, N = 4.0, 1.5, -0.10, 8                       # a fixture where the 0-8 grid is visibly too small
P = a.score_matrix(lam, mu, rho, N); tail = a.tail_probability(lam, mu, N)
assert abs(P.sum() + tail - 1) < 1e-15 and tail > 0.02
g = np.arange(N + 1); ref = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
d = a.dc_corrections(lam, mu, rho); ref[0, 0] += d[0]; ref[0, 1] += d[1]; ref[1, 0] += d[2]; ref[1, 1] += d[3]
assert np.array_equal(P, ref)
print(f"1) cap {N}, lam {lam}, mu {mu}: grid sums to {P.sum():.6f}, tail {tail:.6f}, sum + tail - 1 = {P.sum() + tail - 1:+.1e}; cells equal tau x Poisson x Poisson exactly")
if prev is not None:
    Pold = prev.score_matrix(lam, mu, rho, N)
    print(f"   BEFORE v2.4: the same grid summed to {Pold.sum():.6f} (cells inflated by x{1 / P.sum():.5f}: the {tail:.4f} tail spread over the grid); AFTER: not redistributed")
    assert abs(Pold.sum() - 1) < 1e-12 and np.allclose(Pold, P / P.sum(), rtol=1e-12, atol=0)
print("   source check (AST of the code, not the docstring): score_matrix has no in-place division, no clip, no sum")

# ---- 2-3. ordinary and unusually high expected goals: closed-form markets vs the 50-digit reference
print(f"\n2-3) {'case':12s} {'lam':>5} {'mu':>5}  max |exact_markets - 50-digit reference|   prev v2.4 (cap 15) error   v2.3.1 (cap 8) error")
for name, lam, mu, rho in CASES:
    mk = a.exact_markets(lam, mu, rho); ref = mp_reference(lam, mu, rho)
    err = max(abs(mk[k] - float(ref[k])) for k in ref)
    assert err < 1e-13, (name, err)
    e15 = e8 = float("nan")
    if prev is not None:
        P15 = prev.score_matrix(lam, mu, rho, 15); t = np.add.outer(np.arange(16), np.arange(16))
        old15 = {"home": np.tril(P15, -1).sum(), "draw": np.trace(P15), "away": np.triu(P15, 1).sum(), "over_2_5": P15[t >= 3].sum(), "btts_yes": P15[1:, 1:].sum()}
        e15 = max(abs(old15[k] - float(ref[k])) for k in old15)
        P8 = prev.score_matrix(lam, mu, rho, 8); t8 = np.add.outer(np.arange(9), np.arange(9))
        old8 = {"home": np.tril(P8, -1).sum(), "draw": np.trace(P8), "away": np.triu(P8, 1).sum(), "over_2_5": P8[t8 >= 3].sum(), "btts_yes": P8[1:, 1:].sum()}
        e8 = max(abs(old8[k] - float(ref[k])) for k in old8)
    print(f"     {name:12s} {lam:5.2f} {mu:5.2f}  {err:34.1e}   {e15:24.1e}   {e8:19.1e}")
print("     (the 'prev' columns are the OLD method's error against the same reference: removed by the new method)")

# ---- 4. the reported tail is correct (independent 50-digit computation), including when it is tiny
for name, lam, mu, rho in CASES:
    for N in (3, 8, 15):
        got = a.tail_probability(lam, mu, N); want = float(mp_tail(lam, mu, N))
        assert abs(got - want) <= 1e-13 * max(1.0, 1) and (want == 0 or abs(got / want - 1) < 1e-9), (name, N, got, want)
        P = a.score_matrix(lam, mu, rho, N)
        assert abs(P.sum() + got - 1) < 1e-14
print("4) tail_probability matches a 50-digit calculation to relative 1e-9 for 18 (case, grid size) combinations; grid + tail = 1 within 1e-14 every time")

# ---- 5-7. 1X2, over/under and BTTS cover the full distribution and ignore the grid size
df, *_ = make(5, n_matches=500); p = a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, live=True); T = p["teams"]
for N in (3, 8, 15, 40):
    q = a.predict(p, T[0], T[1], max_goals=N)
    mk = q["markets"]
    if N == 3: base = mk; assert q["grid_warning"] and q["tail_probability"] > 1e-3
    assert mk == base                                       # identical floats for any grid size
    assert abs(q["grid_sum"] + q["tail_probability"] - 1) < 1e-14 and q["probability_identity_error"] < 1e-14
print("5-7) predict(max_goals=3/8/15/40): markets are IDENTICAL floats; grid_sum + tail = 1 for each (tail at N=3 is large and reported, not redistributed)")
for name, lam, mu, rho in CASES:
    mk = a.exact_markets(lam, mu, rho)
    assert abs(mk["home"] + mk["draw"] + mk["away"] - 1) < 1e-14
    assert abs(mk["over_2_5"] + mk["under_2_5"] - 1) < 1e-14 and abs(mk["btts_yes"] + mk["btts_no"] - 1) < 1e-15
    # derive the same markets again from a 200-goal float grid (no renormalisation): independent route
    P = a.score_matrix(lam, mu, rho, 200); t = np.add.outer(np.arange(201), np.arange(201))
    assert abs(np.tril(P, -1).sum() - mk["home"]) < 1e-13 and abs(P[t >= 4].sum() - mk["over_3_5"]) < 1e-13 and abs(P[1:, 1:].sum() - mk["btts_yes"]) < 1e-13
print("     1X2 sums to 1, over+under = 1, BTTS yes+no = 1 (all within 1e-14), and agree with a 200-goal grid")

# ---- 8. validity and consistency over thousands of random fixtures; invalid correction raises, never silently fixed
rng = np.random.default_rng(1); bad = 0
for _ in range(3000):
    lam = float(np.exp(rng.uniform(np.log(0.05), np.log(6.0)))); mu = float(np.exp(rng.uniform(np.log(0.05), np.log(6.0))))
    lo = max(-0.98 / lam, -0.98 / mu, -0.3); hi = min(0.98 / (lam * mu), 0.98, 0.3); rho = float(rng.uniform(lo, hi))
    mk = a.exact_markets(lam, mu, rho); P = a.score_matrix(lam, mu, rho, 15)
    assert all(-1e-15 <= x <= 1 + 1e-15 for x in mk.values()) and (P >= 0).all()
    assert abs(mk["home"] + mk["draw"] + mk["away"] - 1) < 1e-13 and abs(P.sum() + a.tail_probability(lam, mu, 15) - 1) < 1e-13
for lam, mu, rho in ((3.6, 0.8, -0.30), (2.5, 2.0, 0.30), (1.0, 1.0, 1.5), (-1.0, 1.0, 0.0), (float("nan"), 1.0, 0.0)):
    for fn in (a.exact_markets, a.score_matrix):
        try: fn(lam, mu, rho); raise SystemExit(f"FAIL: {fn.__name__} accepted invalid ({lam},{mu},{rho})")
        except ValueError: bad += 1
print(f"8) 3000 random fixtures: every probability in [0,1], 1X2 sums to 1, grid + tail = 1; {bad} invalid inputs REFUSED (never clipped or rescaled)")

# ---- consumers: predict() output is mutually consistent and the value engine reads it correctly
q = a.predict(p, T[0], T[1])
assert abs(q["p_home_win"] + q["p_draw"] + q["p_away_win"] - 1) < 2e-4 and abs(q["p_over_2.5"] + q["p_under_2.5"] - 1) < 1.5e-4
assert abs(q["p_btts_yes"] + q["p_btts_no"] - 1) < 1.5e-4
P = q["matrix"]; assert all(abs(prob - P[int(s.split("-")[0]), int(s.split("-")[1])]) < 1e-15 for s, prob in q["top_scores"])
assert abs(P.sum() + q["p_other_scores"] - 1) < 1e-14
pr = v.probabilities_from_prediction(q); gr = v.probabilities_from_score_matrix(P.tolist(), q["tail_probability"])
assert abs(pr["over_2_5"] - gr["over_2_5"]) < 1e-12 and 0 <= pr["home"] - gr["home"] <= q["tail_probability"] + 1e-15
r = v.analyse_market({k: pr[k] for k in ("home", "draw", "away")}, {"home": 2.0, "draw": 3.5, "away": 4.0}); assert r["probability_sum_error"] < 1e-14
try: v.probabilities_from_score_matrix(a.score_matrix(4.0, 1.5, -0.1, 8).tolist(), 0.0); raise SystemExit("FAIL: grid without its tail accepted")
except ValueError: pass
try: v.probabilities_from_score_matrix(a.score_matrix(4.0, 1.5, -0.1, 8).tolist(), a.tail_probability(4.0, 1.5, 8)); raise SystemExit("FAIL: large tail accepted")
except ValueError: pass
print("   consumers: top scorelines equal the exact cells; value engine reads exact markets, refuses a grid whose tail it cannot assign")
print("PASS")
