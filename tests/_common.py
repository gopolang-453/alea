"""Synthetic league generator shared by the tests (fixed seeds => repeatable)."""
import numpy as np, pandas as pd

def make(seed, n_teams=22, n_matches=420, promoted_matches=6, start="2023-08-01", spacing=0.8):
    """Independent-Poisson league with known true strengths. The LAST team is 'newly promoted':
    only `promoted_matches` of its matches are kept. Returns (df, team_names, true_attack, true_defence)."""
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(n_teams)]
    att = rng.normal(0, 0.30, n_teams); att -= att.mean()
    dfn = rng.normal(0, 0.25, n_teams)
    rows = []; d0 = pd.Timestamp(start)
    for k in range(n_matches):
        h, aw = rng.choice(n_teams, 2, replace=False)
        rows.append((d0 + pd.Timedelta(days=int(k * spacing)), teams[h], teams[aw],
                     rng.poisson(np.exp(0.1 + 0.25 + att[h] + dfn[aw])),
                     rng.poisson(np.exp(0.1 + att[aw] + dfn[h]))))
    df = pd.DataFrame(rows, columns=["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"])
    df = df.drop_duplicates(subset=["Date", "HomeTeam", "AwayTeam"]).reset_index(drop=True)   # same fixture twice is not valid data
    t = teams[-1]; idx = df.index[(df.HomeTeam == t) | (df.AwayTeam == t)]
    df = df.drop(idx[promoted_matches:]).reset_index(drop=True)
    return df, teams, att, dfn


def make_matchday_league(seed, n_teams=20, n_weeks=76, start="2023-08-12", with_odds=False,
                         market="truth", noise=0.35, margin=0.05, strength_sd=(0.30, 0.25), reschedule_prob=0.0):
    """League with a REALISTIC weekly structure: each week every team plays once, 5 matches on
    Saturday, 4 on Sunday, 1 on Monday (so matchdays span several dates). True strengths are
    known. If with_odds, adds B365H/B365D/B365A (early odds) generated from the TRUE
    probabilities (market='truth') or from the truth plus log-odds noise (market='noisy'),
    with a proportional bookmaker margin. Returns (df, teams, att, dfn)."""
    from scipy.stats import poisson
    rng = np.random.default_rng(seed)
    teams = [f"Club{i:02d}" for i in range(n_teams)]
    att = rng.normal(0, strength_sd[0], n_teams); att -= att.mean()
    dfn = rng.normal(0, strength_sd[1], n_teams)
    offsets = [0] * 5 + [1] * 4 + [2]               # Sat, Sun, Mon
    rows = []; d0 = pd.Timestamp(start)
    goals = np.arange(16)
    for wk in range(n_weeks):
        order = rng.permutation(n_teams)
        for k in range(n_teams // 2):
            h, a_ = order[2 * k], order[2 * k + 1]
            if rng.random() < 0.5: h, a_ = a_, h
            lam = np.exp(0.1 + 0.25 + att[h] + dfn[a_]); mu = np.exp(0.1 + att[a_] + dfn[h])
            move = int(rng.integers(3, 11)) if rng.random() < reschedule_prob else 0   # postponed / midweek
            row = {"Date": d0 + pd.Timedelta(weeks=wk, days=offsets[k] + move), "HomeTeam": teams[h], "AwayTeam": teams[a_],
                   "FTHG": int(rng.poisson(lam)), "FTAG": int(rng.poisson(mu))}
            if with_odds:
                P = np.outer(poisson.pmf(goals, lam), poisson.pmf(goals, mu))
                tp = np.array([np.tril(P, -1).sum(), np.trace(P), np.triu(P, 1).sum()]); tp /= tp.sum()
                if market == "noisy":
                    z = np.log(tp) + rng.normal(0, noise, 3); tp = np.exp(z) / np.exp(z).sum()
                od = 1.0 / (tp * (1 + margin))
                row.update({"B365H": round(float(od[0]), 3), "B365D": round(float(od[1]), 3), "B365A": round(float(od[2]), 3)})
            rows.append(row)
    df = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    return df, teams, att, dfn
