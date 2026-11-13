"""TEST 12b (regression of review test 03) - the bug found in v2.3 (fixed in v2.4).
In v2.3 the ridge penalty included the MEAN of the defence parameters, which is the model's
league-average goal level (it acts as the intercept). Strong shrinkage therefore dragged
predicted goals toward 1.0. PASS = in v2.4, mean predicted away goals match the actual
mean within 1% at every reg value. If the v2.3 file is present, its bias is printed for comparison."""
import numpy as np, pandas as pd
import _paths
import alea_predictor_v2_4_1 as fixed
old = _paths.optional_import("alea_predictor_v2_3")

def make_big_intercept(seed, base=0.30, n_teams=20, n=900):
    rng = np.random.default_rng(seed); teams = [f"T{i:02d}" for i in range(n_teams)]
    att = rng.normal(0, .25, n_teams); att -= att.mean(); dfn = rng.normal(0, .2, n_teams); dfn -= dfn.mean()
    rows = []; d0 = pd.Timestamp("2024-08-01")
    for k in range(n):
        h, aw = rng.choice(n_teams, 2, replace=False)
        rows.append((d0 + pd.Timedelta(days=int(k * 0.6)), teams[h], teams[aw],
                     rng.poisson(np.exp(base + 0.25 + att[h] + dfn[aw])), rng.poisson(np.exp(base + att[aw] + dfn[h]))))
    return pd.DataFrame(rows, columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]).drop_duplicates(
        subset=["Date", "HomeTeam", "AwayTeam"]).reset_index(drop=True)      # v2.4 refuses duplicate fixtures

def mean_pred_away(mod, reg):
    pa, ra = [], []
    for s in range(8):
        df = make_big_intercept(s); p = mod.fit_model(df, xi=0.0, reg=reg, verbose=False, **({"live": True} if mod is fixed else {})); T = p["teams"]
        pa += [np.exp(p["attack"][w] + p["defence"][h]) for h in T for w in T if h != w]; ra.append(df.FTAG.mean())
    return np.mean(pa), np.mean(ra)

print(f"{'reg':>5} {'v2.4 pred':>12} {'actual':>8} {'bias':>7}" + (f" {'v2.3 pred':>10} {'bias':>7}" if old else ""))
for reg in (0.0, 1.0, 3.0, 8.0):
    p1, act = mean_pred_away(fixed, reg); line = f"{reg:5.1f} {p1:12.3f} {act:8.3f} {p1/act-1:+7.1%}"
    assert abs(p1 / act - 1) < 0.01, f"v2.4 still biased at reg={reg}"
    if old:
        p0, _ = mean_pred_away(old, reg); line += f" {p0:10.3f} {p0/act-1:+7.1%}"
    print(line)
print("PASS")
