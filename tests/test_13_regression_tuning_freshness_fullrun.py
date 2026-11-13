"""TEST 13 (regression of review test 04) - tuning, data-freshness and a full end-to-end run (all on MOCKED data, no network).
  a) tune_params skips ONE failing candidate and still finishes; fails loudly if ALL candidates fail
  b) load_from_openfootball flags a source that is behind real life (15 past-dated matches with no score)
  c) no warning when the source is current
  d) full ALEA() run with tuning ON, status(), explain() (must flag stale data), walk-forward backtest (0 failed folds)
The mock league has NO real skill, so the model is NOT expected to beat the baselines here -
this test checks that the machinery works, not that it predicts well."""
import sys, io, contextlib, time
import numpy as np, pandas as pd
import _paths
import alea_predictor_v2_4_1 as a
from _common import make

def section(n): print(f"\n--- {n} ---")

# ---- Test 2: one failing candidate must not abort tuning
section("tune_params skips a failing candidate")
df, *_ = make(7, n_matches=500)
real_fit = a.fit_model
def flaky(data, xi=a.XI, reg=a.REG, verbose=True, **kw):
    if abs(xi - 0.001) < 1e-12 and reg == 1.0:
        raise RuntimeError("simulated optimiser failure")
    return real_fit(data, xi=xi, reg=reg, verbose=verbose, **kw)
a.fit_model = flaky
bx, br, results, failed = a.tune_params(df, xi_candidates=[0.0, 0.001], reg_candidates=[0.0, 1.0], verbose=True, live=True)
a.fit_model = real_fit
assert len(failed) == 1 and len(results) == 3, (len(failed), len(results))
print("PASS: 1 candidate failed, 3 still scored, tuning completed ->", bx, br)

section("tune_params: all candidates failing raises clearly (no silent fallback)")
a.fit_model = lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    a.tune_params(df, xi_candidates=[0.0], reg_candidates=[0.0], verbose=False, live=True); raise SystemExit("should have raised")
except ValueError as e:
    print("PASS: raised ->", str(e)[:80])
a.fit_model = real_fit

# ---- Test 4: freshness warnings with a mocked stale source (as_of_date makes it deterministic)
section("freshness warning: source behind real life")
rng = np.random.default_rng(1)
teams = [f"Club{i:02d}" for i in range(12)]
def payload(season, start, n_played, n_past_missing, n_future):
    ms = []; base = pd.Timestamp(start)
    for i in range(n_played):
        h, aw = rng.choice(teams, 2, replace=False)
        ms.append({"round": f"MD{i}", "date": str((base + pd.Timedelta(days=i*2)).date()), "team1": h, "team2": aw,
                   "score": {"ft": [int(rng.poisson(1.4)), int(rng.poisson(1.1))]}})
    last = base + pd.Timedelta(days=n_played*2)
    for i in range(n_past_missing):   # dated in the past, no score in the source
        h, aw = rng.choice(teams, 2, replace=False)
        ms.append({"round": "late", "date": str((last + pd.Timedelta(days=i+1)).date()), "team1": h, "team2": aw})
    for i in range(n_future):
        h, aw = rng.choice(teams, 2, replace=False)
        ms.append({"round": "fut", "date": str((pd.Timestamp("2026-11-20") + pd.Timedelta(days=i)).date()), "team1": h, "team2": aw})
    return {"name": season, "matches": ms}
class R:
    def __init__(s, p): s.p = p
    def raise_for_status(s): pass
    def json(s): return s.p
def fake_get_stale(url, timeout=20):
    if "/2026-27/" in url: return R(payload("2026-27", "2026-08-22", 30, 25, 6))   # played to ~Oct 21; 25 past matches missing
    return R(payload(url.split("/")[-2], "2025-08-10" if "2025-26" in url else "2024-08-10", 180, 0, 0))
a.requests.get = fake_get_stale
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    data, fx = a.load_from_openfootball(as_of_date="2026-11-06")
out = buf.getvalue(); print(out)
fr = data.attrs["freshness"]
assert fr["past_without_result"] == 15 and len(fr["warnings"]) == 2, fr
assert "WARNING (data freshness)" in out
print("PASS: stale source detected and reported:", fr["newest_result"], f"({fr['age_days']} days), {fr['past_without_result']} past matches without result")

section("freshness OK when source is current")
def fake_get_ok(url, timeout=20):
    if "/2026-27/" in url: return R(payload("2026-27", "2026-08-22", 38, 0, 6))
    return fake_get_stale(url)
a.requests.get = fake_get_ok
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    data2, fx2 = a.load_from_openfootball(as_of_date="2026-11-06")
print(buf.getvalue().strip().splitlines()[-3:])
print("freshness:", data2.attrs["freshness"]["warnings"], "-> no warnings expected for a ~10 day gap")
assert not data2.attrs["freshness"]["warnings"]

# ---- Test 5: full ALEA on the mocked stale source, tuning ON, backtest, explain, status
section("full ALEA run (tuning on) with stale mock source")
a.requests.get = fake_get_stale
t = time.time()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    m = a.ALEA(seasons=("2024-25", "2025-26", "2026-27"))
print(buf.getvalue()[-900:])
print("init time %.1fs" % (time.time() - t))
m.status()
h, aw = m.params["teams"][0], m.params["teams"][1]
txt = a.explain(m.predict(h, aw)); print("\nEXPLAIN:", txt)
assert "Caution" in txt and "days old" in txt, "stale data must be flagged in explain()"
t = time.time()
rep = m.backtest(min_train_matches=250, step_days=14)
print("backtest time %.1fs" % (time.time() - t))
assert rep["n_folds_failed"] == 0
for k in ("model_rps", "baseline_train_rate_rps", "model_log_loss", "baseline_train_rate_log_loss"): print(k, round(rep[k], 4))
print("\nALL OK")
