"""TEST 06 - score grid size and monitoring (updated for v2.4.1's exact probabilities).
v2.3.1: 0..8 grid, tail silently renormalised away (up to ~2%). v2.4: 0..15 grid, tail reported but still renormalised.
v2.4.1: 0..15 grid, tail reported and NEVER redistributed; markets do not depend on the grid at all."""
import _paths
import numpy as np
import alea_predictor_v2_4_1 as a
from _common import make
old = _paths.optional_import("alea_predictor_v2_3_1")
assert a.MAX_GOALS == 15
print(f"{'lam':>5} {'mu':>4} | tail cap8 {'':3} tail cap15 | grid sum cap15 | markets depend on grid size?")
for lam, mu in [(1.4, 1.1), (2.5, 1.0), (3.5, 0.8), (4.0, 1.5)]:
    rho = -0.10; t8, t15 = a.tail_probability(lam, mu, 8), a.tail_probability(lam, mu, 15)
    s15 = a.score_matrix(lam, mu, rho, 15).sum()
    m_small, m_big = a.exact_markets(lam, mu, rho), a.exact_markets(lam, mu, rho)       # exact_markets has no grid argument
    print(f"{lam:5.1f} {mu:4.1f} | {t8:9.2e}  {t15:11.2e} | {s15:14.12f} | no (closed form)")
    assert m_small == m_big and abs(s15 + t15 - 1) < 1e-14 and t15 < 1e-5
    if old is not None and lam >= 3.5:
        Po = old.score_matrix(lam, mu, rho, 8)                  # v2.3.1 renormalised: sums to 1 although 1-2% is missing
        assert abs(Po.sum() - 1) < 1e-12 and a.score_matrix(lam, mu, rho, 8).sum() < 0.995
df, *_ = make(5, n_matches=500); p = a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, live=True); T = p["teams"]
q = a.predict(p, T[0], T[1]); assert q["matrix"].shape == (16, 16) and q["tail_probability"] < 1e-6 and q["grid_warning"] is None
q3 = a.predict(p, T[0], T[1], max_goals=3)
assert q3["grid_warning"] and q3["tail_probability"] > a.TRUNC_WARN and "NOT redistributed" in q3["grid_warning"]
print("predict(max_goals=3) ->", q3["grid_warning"][:120], "...")
for h, w in [(T[0], T[1]), (T[2], T[3]), (T[4], T[5])]:
    big, small = a.predict(p, h, w, max_goals=30), a.predict(p, h, w)
    for k in ("p_home_win", "p_draw", "p_away_win", "p_over_2.5", "p_over_3.5", "p_btts_yes"):
        assert big[k] == small[k], k                            # identical, not merely close
print("PASS")
