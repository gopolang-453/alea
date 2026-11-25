#!/usr/bin/env python3
"""Task 7: frozen champion vs bookmaker closing market on identical fixtures.

Joins the champion's leakage-free walk-forward predictions
(results/stage9_mle/predictions.csv, frozen params xi=0.0018 reg=1.0) with a
user-supplied, locally held file of devigged market probabilities passed via
``--odds`` (columns: date, home, away, p_market_home, p_market_draw,
p_market_away, y_home, y_draw, y_away). No odds file is shipped with the repository: bookmaker odds
from football-data.co.uk are for the user's own personal/academic use and must
not be committed, uploaded as CI artifacts or otherwise redistributed. Keep the
file outside the repository or under the git-ignored ``data/`` directory.

Reports paired differences (champion - market; negative = champion better) in
log loss, Brier and RPS with ISO-week block-bootstrap 95% CIs, per season, by
favourite strength, and a reliability (calibration) table for both.

Only aggregates are written; no odds or per-match rows are redistributed.
Market probabilities are a benchmark only; they are never used as a feature.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage1.data_store import canonical_team  # noqa: E402

SAMPLES, SEED = 2000, 20261124
ODDS_COLUMNS = ("date", "home", "away", "p_market_home", "p_market_draw", "p_market_away",
                "y_home", "y_draw", "y_away")


def _season(d: pd.Timestamp) -> str:
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def per_row(p: np.ndarray, y: np.ndarray) -> dict:
    onehot = np.eye(3)[y]
    cum_p, cum_y = np.cumsum(p, 1)[:, :2], np.cumsum(onehot, 1)[:, :2]
    return {"log_loss": -np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1)),
            "brier": ((p - onehot) ** 2).sum(1),
            "rps": ((cum_p - cum_y) ** 2).sum(1) / 2}


def paired(df: pd.DataFrame) -> dict:
    y = df["y"].to_numpy()
    a = per_row(df[["c_h", "c_d", "c_a"]].to_numpy(), y)
    b = per_row(df[["m_h", "m_d", "m_a"]].to_numpy(), y)
    iso = pd.to_datetime(df["date"]).dt.isocalendar()
    keys = list(zip(iso["year"], iso["week"]))
    groups = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    blocks = [np.asarray(g) for g in groups.values()]
    rng = np.random.default_rng(SEED)
    out = {"n": int(len(df)), "n_week_blocks": len(blocks)}
    for m in a:
        diff = a[m] - b[m]
        out[f"champion_{m}"] = float(a[m].mean())
        out[f"market_{m}"] = float(b[m].mean())
        out[f"diff_{m}"] = float(diff.mean())
        if len(blocks) >= 2:
            boot = [diff[np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))])].mean()
                    for _ in range(SAMPLES)]
            out[f"diff_{m}_ci95"] = [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))]
    out["champion_accuracy"] = float((df[["c_h", "c_d", "c_a"]].to_numpy().argmax(1) == y).mean())
    out["market_accuracy"] = float((df[["m_h", "m_d", "m_a"]].to_numpy().argmax(1) == y).mean())
    return out


def reliability(df: pd.DataFrame, cols, bins=10) -> list:
    p = df[cols].to_numpy().ravel()
    hit = np.eye(3)[df["y"].to_numpy()].ravel()
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    rows = []
    for b in range(bins):
        mask = idx == b
        if mask.sum():
            rows.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(mask.sum()),
                         "mean_forecast": float(p[mask].mean()), "observed_freq": float(hit[mask].mean())})
    ece = sum(r["n"] * abs(r["mean_forecast"] - r["observed_freq"]) for r in rows) / len(p)
    return {"bins": rows, "expected_calibration_error": float(ece)}


def build(champion_csv: Path, odds_csv: Path) -> pd.DataFrame:
    c = pd.read_csv(champion_csv)
    c = c.assign(home=c.home_team.map(canonical_team), away=c.away_team.map(canonical_team))
    o = pd.read_csv(odds_csv)
    o = o.assign(home=o.home.map(canonical_team), away=o.away.map(canonical_team))
    sums = o[["p_market_home", "p_market_draw", "p_market_away"]].sum(axis=1)
    if ((sums - 1).abs() > 1e-6).any():
        raise SystemExit(f"{int(((sums - 1).abs() > 1e-6).sum())} odds rows are not devigged "
                         "probabilities summing to 1; refusing")
    o["y"] = np.where(o.y_home == 1, 0, np.where(o.y_draw == 1, 1, 2))
    m = c.merge(o[["date", "home", "away", "p_market_home", "p_market_draw", "p_market_away", "y"]],
                on=["date", "home", "away"], how="inner", validate="one_to_one")
    m["y_c"] = m.actual.map({"H": 0, "D": 1, "A": 2})
    if (m.y_c != m.y).any():
        raise SystemExit(f"{int((m.y_c != m.y).sum())} result disagreements between files; refusing")
    m = m.rename(columns={"p_home": "c_h", "p_draw": "c_d", "p_away": "c_a", "p_market_home": "m_h",
                          "p_market_draw": "m_d", "p_market_away": "m_a"})
    m["season"] = pd.to_datetime(m.date).map(_season)
    m["fav"] = m[["m_h", "m_d", "m_a"]].max(axis=1)
    return m


def run(champion_csv: Path, odds_csv: Path) -> dict:
    m = build(champion_csv, odds_csv)
    n_odds = len(pd.read_csv(odds_csv))
    res = {"description": __doc__.strip().splitlines()[0], "joined_fixtures": int(len(m)),
           "odds_file_rows": n_odds, "unmatched_odds_rows": int(n_odds - len(m)),
           "model_version": sorted(m.model_version.unique().tolist()),
           "sign_convention": "diff = champion - market; negative favours the champion",
           "overall": paired(m),
           "by_season": {s: paired(g) for s, g in m.groupby("season")},
           "by_period": {s: paired(g) for s, g in m.groupby("period")}}
    bands = pd.cut(m.fav, [0, 0.5, 0.65, 1.0], labels=["max_p<0.50 (open)", "0.50-0.65", ">=0.65 (strong fav)"])
    res["by_market_favourite_strength"] = {str(k): paired(g) for k, g in m.groupby(bands, observed=True)}
    res["calibration"] = {"champion": reliability(m, ["c_h", "c_d", "c_a"]),
                          "market": reliability(m, ["m_h", "m_d", "m_a"])}
    return res


def render(res: dict) -> str:
    def row(name, r):
        ci = r.get("diff_log_loss_ci95")
        cis = f"[{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else "n/a"
        bci = r.get("diff_brier_ci95")
        bcis = f"[{bci[0]:+.4f}, {bci[1]:+.4f}]" if bci else "n/a"
        return (f"| {name} | {r['n']} | {r['champion_log_loss']:.4f} | {r['market_log_loss']:.4f} | "
                f"{r['diff_log_loss']:+.4f} {cis} | {r['diff_brier']:+.4f} {bcis} | {r['diff_rps']:+.4f} |")
    head = ("| Slice | n | Champion LL | Market LL | LL diff [95% CI] | Brier diff [95% CI] | RPS diff |\n"
            "|---|---:|---:|---:|---:|---:|---:|")
    lines = ["# Champion vs closing market (Task 7)", "",
             f"Joined fixtures: {res['joined_fixtures']} (odds rows {res['odds_file_rows']}, "
             f"unmatched {res['unmatched_odds_rows']}). Model: {', '.join(res['model_version'])}.",
             f"Sign: {res['sign_convention']}. CIs: ISO-week block bootstrap, {SAMPLES} resamples.", "",
             head, row("All", res["overall"])]
    lines += [row(f"Season {k}", v) for k, v in res["by_season"].items()]
    lines += [row(f"Period {k}", v) for k, v in res["by_period"].items()]
    lines += [row(f"Fav {k}", v) for k, v in res["by_market_favourite_strength"].items()]
    lines += ["", "## Calibration (all three outcomes pooled)", "",
              f"Expected calibration error: champion {res['calibration']['champion']['expected_calibration_error']:.4f}, "
              f"market {res['calibration']['market']['expected_calibration_error']:.4f}.", "",
              "| Bin | n | Champion mean p | Champion freq | Market n | Market mean p | Market freq |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    cb = {b["bin"]: b for b in res["calibration"]["champion"]["bins"]}
    mb = {b["bin"]: b for b in res["calibration"]["market"]["bins"]}
    for k in sorted(set(cb) | set(mb)):
        c, m = cb.get(k), mb.get(k)
        f = lambda d, key: f"{d[key]:.3f}" if d else "-"
        lines.append(f"| {k} | {c['n'] if c else 0} | {f(c,'mean_forecast')} | {f(c,'observed_freq')} | "
                     f"{m['n'] if m else 0} | {f(m,'mean_forecast')} | {f(m,'observed_freq')} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--champion", default=str(ROOT / "results/stage9_mle/predictions.csv"))
    ap.add_argument("--odds", required=True,
                    help="local CSV of devigged market probabilities (never committed or uploaded)")
    ap.add_argument("--out-dir", default=str(ROOT / "results/stage9_market"))
    a = ap.parse_args(argv)
    odds = Path(a.odds)
    if not odds.is_file():
        print(f"BLOCKED: odds file {odds} not found. Supply your own locally held file with --odds; "
              "none is distributed with ALEA (football-data.co.uk odds are personal/academic use only).",
              file=sys.stderr)
        return 2
    if not Path(a.champion).is_file():
        print(f"BLOCKED: champion predictions {a.champion} not found (run the Stage 9 backtest first).",
              file=sys.stderr)
        return 2
    header = set(pd.read_csv(odds, nrows=0).columns)
    missing = sorted(set(ODDS_COLUMNS) - header)
    if missing:
        print(f"BLOCKED: odds file {odds} lacks required columns {missing}", file=sys.stderr)
        return 2
    res = run(Path(a.champion), odds)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "champion_vs_market.json").write_text(json.dumps(res, indent=2) + "\n")
    (out / "champion_vs_market.md").write_text(render(res))
    print(render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
