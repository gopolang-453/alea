"""TEST 14 - HISTORICAL CUTOFF ENFORCED INSIDE fit_model (v2.4.1, correction 1).
BEFORE (v2.4): fit_model had no cutoff: it trained on whatever it was given, so a historical prediction could silently
use matches played AFTER the prediction date (only the backtest wrappers protected against it).
AFTER (v2.4.1): fit_model / tune_params / fit_corner_rates require an explicit cutoff (as_of_date=... or live=True),
reject any match not earlier than it, cannot be told to skip the check, and every backtest fold passes its own cutoff.
Covers the six required checks + the mandatory-ness itself + a perturbation ('canary') leakage test."""
import inspect
import _paths
import numpy as np, pandas as pd
import alea_predictor_v2_4_1 as a
from _common import make_matchday_league
prev = _paths.optional_import("alea_predictor_v2_4")           # the previous implementation (baseline/)

df, *_ = make_matchday_league(7, n_weeks=60, reschedule_prob=0.10)
day = df.Date.dt.normalize()
C = day.iloc[400]                                            # the prediction date
eligible = df[day < C].reset_index(drop=True)
future = df[day >= C].reset_index(drop=True)
print(f"data: {len(df)} matches; cutoff {C.date()}: {len(eligible)} eligible (before it), {len(future)} on/after it")

# ---- 0. the cutoff is MANDATORY and unambiguous
for kw, why in (({}, "neither as_of_date nor live"), ({"as_of_date": C, "live": True}, "both")):
    try: a.fit_model(eligible, verbose=False, **kw); raise SystemExit(f"FAIL: accepted {why}")
    except ValueError as e: assert "cutoff" in str(e).lower() or "either" in str(e).lower()
print("0) neither / both cutoff arguments -> ValueError (a historical fit cannot forget its cutoff)")

# ---- 1. only eligible historical matches -> passes, and the cutoff is recorded
p = a.fit_model(eligible, xi=0.0018, reg=1.0, verbose=False, as_of_date=C)
assert p["cutoff_mode"] == "historical" and p["as_of_date"] == str(C) and p["same_day_policy"] == "exclude"
assert pd.Timestamp(p["data_through"]) < C and p["n_matches_trained"] == len(eligible)
print(f"1) eligible matches only -> accepted; model records as_of_date={p['as_of_date']}, data_through={p['data_through']}")

# ---- 2. a match after the cutoff -> refused
if prev is not None:
    pl = prev.fit_model(df, xi=0.0018, reg=1.0, verbose=False)                      # BEFORE
    n_leak = int((day >= C).sum())
    print(f"BEFORE v2.4:   fit_model(all {len(df)} matches) ACCEPTED, silently using {n_leak} matches dated on/after {C.date()}")
try: a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, as_of_date=C); raise SystemExit("FAIL: future matches accepted")
except a.FutureDataError as e: print("AFTER  v2.4.1: fit_model(all matches, as_of_date) REFUSED ->", str(e)[:110], "...")
one = pd.concat([eligible, future.iloc[[-1]]], ignore_index=True)                   # a single match far in the future
try: a.fit_model(one, xi=0.0018, reg=1.0, verbose=False, as_of_date=C); raise SystemExit("FAIL")
except a.FutureDataError: print("2) a single post-cutoff match is enough to refuse the fit")

# ---- 3. same-day policy (documented): default 'exclude'; opt-in 'timestamp'
same = future.iloc[[0]].copy(); same["Date"] = C                                     # a match ON the cutoff date
with_same = pd.concat([eligible, same], ignore_index=True)
try: a.fit_model(with_same, xi=0.0018, reg=1.0, verbose=False, as_of_date=C); raise SystemExit("FAIL")
except a.FutureDataError: print("3a) same_day='exclude' (default): a match ON the cutoff date is refused")
day_before = same.copy(); day_before["Date"] = C - pd.Timedelta(days=1)
a.fit_model(pd.concat([eligible, day_before], ignore_index=True), xi=0.0018, reg=1.0, verbose=False, as_of_date=C)
print("3b) a match the day before is accepted")
asof = C + pd.Timedelta(hours=14, minutes=30)                                         # 14:30 on the cutoff date
def with_time(t): x = same.copy(); x["Time"] = t; e = eligible.copy(); e["Time"] = "15:00"; return pd.concat([e, x], ignore_index=True)
a.fit_model(with_time("12:00"), xi=0.0018, reg=1.0, verbose=False, as_of_date=asof, same_day="timestamp")
print(f"3c) same_day='timestamp': kickoff 12:00 + {a.MATCH_COMPLETION_MINUTES} min = 14:30 <= as_of 14:30 -> accepted (boundary inclusive)")
for t in ("12:01", "15:00", None):
    try: a.fit_model(with_time(t), xi=0.0018, reg=1.0, verbose=False, as_of_date=asof, same_day="timestamp"); raise SystemExit(f"FAIL: kickoff {t}")
    except a.FutureDataError: pass
print("3d) kickoff 12:01 / 15:00 / unknown time -> refused (cannot prove it had finished)")
tomorrow = same.copy(); tomorrow["Date"] = C + pd.Timedelta(days=1); tomorrow["Time"] = "12:00"
e = eligible.copy(); e["Time"] = "15:00"
try: a.fit_model(pd.concat([e, tomorrow], ignore_index=True), xi=0.0018, reg=1.0, verbose=False, as_of_date=asof, same_day="timestamp"); raise SystemExit("FAIL")
except a.FutureDataError: print("3e) 'timestamp' policy never admits a match dated AFTER the cutoff date")
try: a.fit_model(eligible, verbose=False, as_of_date=C, same_day="timestamp"); raise SystemExit("FAIL")
except ValueError: print("3f) 'timestamp' policy needs an as_of_date with a time of day")
try: a.fit_model(eligible, verbose=False, as_of_date=C, same_day="whenever"); raise SystemExit("FAIL")
except ValueError: pass

# ---- 4. nothing can bypass it
names = set(inspect.signature(a.fit_model).parameters)
assert names == {"data", "xi", "reg", "verbose", "as_of_date", "live", "same_day"}, names
for kw in ({"fail_closed": False}, {"strict": False}, {"validate": False}, {"skip_cutoff": True}, {"enforce": False},
           {"max_reject_fraction": 1.0}, {"today": "2100-01-01"}):
    try: a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, as_of_date=C, **kw); raise SystemExit(f"FAIL: {kw} accepted")
    except TypeError: pass
print("4) fail_closed=False and six other would-be switches -> TypeError (no such parameter exists); signature:", sorted(names))
cl, _ = a.clean_matches(df, max_reject_fraction=1.0, verbose=False)                    # loosest cleaning possible
try: a.fit_model(cl, xi=0.0018, reg=1.0, verbose=False, as_of_date=C); raise SystemExit("FAIL")
except a.FutureDataError: print("   loosest possible clean_matches(max_reject_fraction=1.0) does not remove the cutoff protection")
try: a.assert_training_data_valid(df, today="2100-01-01")         # the 'is it in the future of NOW' check can be moved...
except Exception: pass
try: a.fit_model(df, xi=0.0018, reg=1.0, verbose=False, as_of_date=C); raise SystemExit("FAIL")
except a.FutureDataError: print("   ...but that is a different check; the cutoff check inside fit_model is unaffected")
for fn, kw in ((a.tune_params, {}), (a.fit_corner_rates, {})):
    d2 = df.assign(HC=5.0, AC=4.0)
    try: fn(d2, as_of_date=C, **kw); raise SystemExit(f"FAIL: {fn.__name__} accepted future data")
    except a.FutureDataError: pass
    try: fn(eligible.assign(HC=5.0, AC=4.0)); raise SystemExit(f"FAIL: {fn.__name__} ran without a cutoff")
    except ValueError: pass
print("   tune_params and fit_corner_rates enforce the same mandatory cutoff")

# ---- 5. every backtest fold / tuning split / ALEA fit respects its own cutoff
calls = []; real = a.fit_model
def spy(train, *args, **kw):
    calls.append((train.copy(), kw)); return real(train, *args, **kw)
a.fit_model = spy
try:
    calls.clear()
    rep, *_ = a.walk_forward_backtest(df, min_train_matches=250, step_days=21, verbose=False, tune_each_fold=False)
    folds = {f["cutoff"]: f for f in rep["fold_log"]}
    assert len(calls) == len(folds) > 5
    for tr, kw in calls:
        asof_k = pd.Timestamp(kw["as_of_date"])
        assert str(asof_k.date()) in folds and tr["Date"].max().normalize() < asof_k.normalize() and "live" not in kw
    assert all(f["as_of_date_used_for_fit"] == f"{f['cutoff']} 00:00:00" for f in rep["fold_log"])
    print(f"5a) walk-forward: {len(calls)}/{len(calls)} fold fits passed as_of_date == the fold's own cutoff, newest training match earlier")
    calls.clear()
    a.walk_forward_backtest(df.iloc[:520], min_train_matches=300, step_days=45, verbose=False, tune_each_fold=True)   # tuning inside folds
    assert len(calls) > 20 and all("as_of_date" in kw and tr["Date"].max().normalize() < pd.Timestamp(kw["as_of_date"]).normalize() for tr, kw in calls)
    print(f"5b) walk-forward WITH per-fold tuning: all {len(calls)} fits (tuning candidates + final fits) carried a cutoff that every training row precedes")
    calls.clear()
    arep, *_ = a.aligned_market_backtest(make_matchday_league(21, n_weeks=45, with_odds=True)[0], min_train_matches=250,
                                         retune_every=10**6, verbose=False, n_boot=100)
    infos = {f["info_date"] for f in arep["fold_log"]}
    ok = [kw for tr, kw in calls if str(pd.Timestamp(kw["as_of_date"]).date()) in infos]
    assert len(ok) >= len(infos) and all(tr["Date"].max().normalize() < pd.Timestamp(kw["as_of_date"]).normalize() for tr, kw in calls)
    print(f"5c) aligned odds backtest: all {len(calls)} fits carried the odds-observation date as cutoff")
    calls.clear()
    m = a.ALEA(data=df, as_of_date=C, xi=0.0018, reg=1.0)
    assert m.params["as_of_date"] == str(C) and m.params["cutoff_mode"] == "historical"
    assert m.data["Date"].max() < C and len(m.data) == len(eligible) and calls[0][1]["as_of_date"] == C
    live = a.ALEA(data=eligible, xi=0.0018, reg=1.0)
    assert live.params["cutoff_mode"] == "live" and calls[-1][1].get("live") is True
    print(f"5d) ALEA(as_of_date=C): trained on {len(m.data)} matches before C ({len(df)-len(m.data)} later ones excluded); ALEA() = live mode")
finally:
    a.fit_model = real

# ---- 6. no future information enters training: perturb every result on/after T, nothing before T may change
T = day.iloc[430]
df2 = df.copy(); fut = df2["Date"].dt.normalize() >= T
rng = np.random.default_rng(3)
df2.loc[fut, "FTHG"] = rng.integers(0, 7, fut.sum()); df2.loc[fut, "FTAG"] = rng.integers(0, 7, fut.sum())
m1 = a.ALEA(data=df, as_of_date=T)                       # includes automatic (xi, reg) tuning
m2 = a.ALEA(data=df2, as_of_date=T)
assert (m1.xi, m1.reg) == (m2.xi, m2.reg)
for t in m1.params["teams"]:
    assert m1.params["attack"][t] == m2.params["attack"][t] and m1.params["defence"][t] == m2.params["defence"][t]
assert m1.params["rho"] == m2.params["rho"] and m1.params["home_adv"] == m2.params["home_adv"]
print(f"6a) ALEA(as_of_date=T) with tuning: scrambling all {int(fut.sum())} results on/after T leaves parameters IDENTICAL (xi, reg, attack, defence, rho, home advantage)")
m3 = a.ALEA(data=df, as_of_date=T + pd.Timedelta(days=60), xi=m1.xi, reg=m1.reg)
m4 = a.ALEA(data=df2, as_of_date=T + pd.Timedelta(days=60), xi=m1.xi, reg=m1.reg)
assert any(m3.params["attack"][t] != m4.params["attack"][t] for t in m3.params["attack"])
print("    control: with the cutoff moved 60 days later the same perturbation DOES change the model (so the test has power)")
r1, p1, _ = a.walk_forward_backtest(df, min_train_matches=250, step_days=14, verbose=False, tune_each_fold=False)
r2, p2, _ = a.walk_forward_backtest(df2, min_train_matches=250, step_days=14, verbose=False, tune_each_fold=False)
off = same_n = diff_n = 0
for f1, f2 in zip(r1["fold_log"], r2["fold_log"]):
    sl = slice(off, off + f1["n_test"]); off += f1["n_test"]
    if pd.Timestamp(f1["test_max_date"]) < T:
        assert np.array_equal(p1[sl], p2[sl]); same_n += f1["n_test"]
    elif pd.Timestamp(f1["cutoff"]) > T:
        diff_n += int(not np.array_equal(p1[sl], p2[sl]))
print(f"6b) walk-forward: {same_n} predictions for matches before T are bit-identical after scrambling the future; later folds change (as they should)")
assert same_n > 100 and diff_n > 0
od, *_ = make_matchday_league(21, n_weeks=60, with_odds=True, reschedule_prob=0.1); od2 = od.copy()
f2 = od2["Date"].dt.normalize() >= T; od2.loc[f2, "FTHG"] = 9 - od2.loc[f2, "FTHG"].clip(0, 9); od2.loc[f2, "FTAG"] = 7
ra, mpa, _, _ = a.aligned_market_backtest(od, min_train_matches=250, retune_every=10**6, verbose=False, n_boot=50)
rb, mpb, _, _ = a.aligned_market_backtest(od2, min_train_matches=250, retune_every=10**6, verbose=False, n_boot=50)
off = n_ok = 0
for fa in ra["fold_log"]:
    sl = slice(off, off + fa["n_scored"]); off += fa["n_scored"]
    if pd.Timestamp(fa["info_date"]) <= T:
        assert np.array_equal(mpa[sl], mpb[sl]); n_ok += fa["n_scored"]
print(f"6c) aligned odds backtest: {n_ok} model predictions with odds-date <= T are bit-identical after scrambling later results")
assert n_ok > 50
print("PASS")
