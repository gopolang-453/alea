"""Scoring of the prospective ledger: champion vs registered challengers.

Only forecasts with status ``settled`` (see ``ProspectiveLedger.fixture_status``)
are scored. Champion metrics carry ISO-week block-bootstrap confidence
intervals; challengers are compared on the paired subset of fixtures that
both models forecast before kickoff. Promotion follows the pre-registered
rule in ``config/model_registry.json`` and is never automatic.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from stages.stage9.candidates import paired_block_bootstrap, scores
from stages.stage9.prospective_ledger import ProspectiveLedger, split_fixture_key

BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 20261124
_EPS = 1e-15


def _metric_rows(p: np.ndarray, y: np.ndarray) -> Dict[str, np.ndarray]:
    one_hot = np.eye(3)[y]
    cum_p, cum_o = np.cumsum(p, axis=1)[:, :2], np.cumsum(one_hot, axis=1)[:, :2]
    return {
        "log_loss": -np.log(np.clip(p[np.arange(len(y)), y], _EPS, 1.0)),
        "brier": np.sum((p - one_hot) ** 2, axis=1),
        "rps": np.sum((cum_p - cum_o) ** 2, axis=1) / 2.0,
        "accuracy": (np.argmax(p, axis=1) == y).astype(float),
    }


def block_bootstrap_ci(p: np.ndarray, outcomes: List[str], dates: List[Any], *,
                       samples: int = BOOTSTRAP_SAMPLES, seed: int = BOOTSTRAP_SEED) -> Dict[str, Any]:
    """95% CIs for mean LL / Brier / RPS / accuracy, resampling ISO-week blocks."""
    y = np.asarray(["HDA".index(o) for o in outcomes])
    per_row = _metric_rows(p, y)
    groups: Dict[tuple, List[int]] = {}
    for i, d in enumerate(dates):
        iso = pd.Timestamp(d).isocalendar()
        groups.setdefault((int(iso.year), int(iso.week)), []).append(i)
    blocks = [np.asarray(g) for g in groups.values()]
    out: Dict[str, Any] = {"n_week_blocks": len(blocks)}
    if len(blocks) < 2:
        for name in per_row:
            out[f"{name}_ci95"] = None
        out["note"] = "fewer than two ISO-week blocks: no confidence interval"
        return out
    rng = np.random.default_rng(seed)
    boot = {name: np.empty(samples) for name in per_row}
    for s in range(samples):
        chosen = np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))])
        for name, values in per_row.items():
            boot[name][s] = values[chosen].mean()
    for name in per_row:
        out[f"{name}_ci95"] = [float(np.quantile(boot[name], 0.025)), float(np.quantile(boot[name], 0.975))]
    return out


def evaluate_ledger(ledger: ProspectiveLedger, registry: Dict[str, Any], now: datetime, *,
                    grace_hours: float = 60.0) -> Dict[str, Any]:
    now = now.astimezone(timezone.utc)
    champion_version = registry["champion"]["model_version"]
    rule = registry["promotion_rule"]
    preds = ledger.predictions()
    statuses = {p["fixture_key"]: ledger.fixture_status(p["fixture_key"], now, grace_hours=grace_hours)
                for p in preds}
    by_status: Dict[str, int] = {}
    for s in statuses.values():
        by_status[s.status] = by_status.get(s.status, 0) + 1

    foreign = sorted({p["model_version"] for p in preds} - {champion_version})
    settled_rows, outstanding = [], []
    for p in preds:
        st = statuses[p["fixture_key"]]
        day, home, away = split_fixture_key(p["fixture_key"])
        base = {"fixture_key": p["fixture_key"], "date": day.isoformat(), "home": home, "away": away,
                "kickoff_at": p["kickoff_at"], "predicted_at": p["predicted_at"],
                "model_version": p["model_version"], "data_snapshot_hash": p["data_snapshot_hash"],
                "p_home": p["p_home"], "p_draw": p["p_draw"], "p_away": p["p_away"],
                "status": st.status, "reason": st.reason}
        if st.scorable and p["model_version"] == champion_version:
            settled_rows.append({**base, "home_goals": st.home_goals, "away_goals": st.away_goals,
                                 "outcome": st.outcome})
        elif not st.scorable:
            outstanding.append(base)

    result: Dict[str, Any] = {
        "generated_at_utc": now.isoformat(),
        "champion_model_version": champion_version,
        "ledger_fingerprint": ledger.fingerprint(),
        "counts": {"champion_forecasts": len(preds), "by_status": by_status,
                   "scored": len(settled_rows), "challenger_forecasts": len(ledger.challenger_predictions())},
        "foreign_model_versions_in_champion_table": foreign,
        "settled": settled_rows,
        "outstanding": outstanding,
        "data_quality_issues": ledger.issues(),
        "events": ledger.events(),
        "promotion_rule": rule,
    }

    if settled_rows:
        p = np.array([[r["p_home"], r["p_draw"], r["p_away"]] for r in settled_rows])
        outcomes = [r["outcome"] for r in settled_rows]
        dates = [r["date"] for r in settled_rows]
        result["champion"] = {**scores(p, outcomes), **block_bootstrap_ci(p, outcomes, dates)}
    else:
        result["champion"] = {"n": 0, "note": "no settled forecasts yet"}

    settled_by_key = {r["fixture_key"]: r for r in settled_rows}
    champion_by_key = {p["fixture_key"]: p for p in preds}
    run_training = {}
    for r in ledger.runs():
        try:
            run_training[r["run_id"]] = json.loads(r["summary_json"]).get("training_matches")
        except (TypeError, ValueError):
            pass
    comparisons = {}
    for challenger in registry.get("challengers", []):
        model_id = challenger["model_id"]
        recorded = ledger.challenger_predictions(model_id)
        rows, excluded = [], {}
        for c in recorded:
            if c["fixture_key"] not in settled_by_key:
                continue
            reason = _pairing_exclusion(c, champion_by_key[c["fixture_key"]], challenger["model_version"],
                                        ledger, run_training)
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
            else:
                rows.append(c)
        entry: Dict[str, Any] = {"model_version": challenger["model_version"], "n_paired": len(rows),
                                 "forecasts_recorded": len(recorded), "settled_but_not_paired": excluded}
        if rows:
            keyed = [settled_by_key[c["fixture_key"]] for c in rows]
            pc = np.array([[c["p_home"], c["p_draw"], c["p_away"]] for c in rows])
            ph = np.array([[k["p_home"], k["p_draw"], k["p_away"]] for k in keyed])
            outcomes = [k["outcome"] for k in keyed]
            dates = [k["date"] for k in keyed]
            entry["challenger"] = scores(pc, outcomes)
            entry["champion_same_fixtures"] = scores(ph, outcomes)
            y = np.asarray(["HDA".index(o) for o in outcomes])
            entry["rps_diff"] = float(_metric_rows(pc, y)["rps"].mean() - _metric_rows(ph, y)["rps"].mean())
            if len({tuple(pd.Timestamp(d).isocalendar()[:2]) for d in dates}) >= 2:
                entry["paired"] = paired_block_bootstrap(pc, ph, outcomes, dates,
                                                         samples=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED)
            else:
                entry["paired"] = {"log_loss_diff": float(_metric_rows(pc, y)["log_loss"].mean()
                                                          - _metric_rows(ph, y)["log_loss"].mean()),
                                   "log_loss_ci95": None, "note": "fewer than two ISO-week blocks"}
        entry["decision"] = promotion_decision(entry, rule)
        comparisons[model_id] = entry
    result["challengers"] = comparisons
    return result


def _training_matches(row: Dict[str, Any], run_training: Dict[str, Any]) -> Optional[int]:
    try:
        extra = json.loads(row["payload_json"]).get("extra", {})
    except (TypeError, ValueError):
        return None
    if extra.get("training_matches") is not None:
        return int(extra["training_matches"])
    value = run_training.get(extra.get("run_id"))
    return int(value) if value is not None else None


def _pairing_exclusion(c: Dict[str, Any], champ: Dict[str, Any], version: str,
                       ledger: ProspectiveLedger, run_training: Dict[str, Any]) -> Optional[str]:
    """Why a settled challenger forecast may not be paired with the champion (None = eligible).

    Pairing requires the registered challenger version, a forecast made
    before the effective (possibly rescheduled) kickoff, and an information
    set no larger than the champion's (same number of training matches).
    """
    if c["model_version"] != version:
        return "model_version_differs_from_registry"
    kickoff = datetime.fromisoformat(c["kickoff_at"])
    resched = [e for e in ledger.events(c["fixture_key"]) if e["event_type"] == "RESCHEDULED"]
    if resched and resched[-1].get("new_kickoff_at"):
        kickoff = min(kickoff, datetime.fromisoformat(resched[-1]["new_kickoff_at"]))
    if datetime.fromisoformat(c["predicted_at"]) >= kickoff:
        return "challenger_forecast_not_before_kickoff"
    n_ch, n_champ = _training_matches(c, run_training), _training_matches(champ, run_training)
    if n_ch is None or n_champ is None:
        return "information_set_unverifiable"
    if n_ch != n_champ:
        return "information_set_differs_from_champion"
    return None


def promotion_decision(entry: Dict[str, Any], rule: Dict[str, Any]) -> str:
    n = entry.get("n_paired", 0)
    if n < rule["min_paired_settled_fixtures"]:
        return f"insufficient data ({n} of {rule['min_paired_settled_fixtures']} paired settled fixtures)"
    paired = entry.get("paired") or {}
    ci = paired.get("log_loss_ci95")
    if ci and ci[1] < 0 and paired.get("brier_diff", 1) <= 0:
        return "meets pre-registered rule: eligible for human review (no automatic promotion)"
    return "does not meet pre-registered rule: champion retained"


def _label(key: str) -> str:
    day, home, away = key.split("|")
    return f"{day} {home} v {away}"


def _fmt_ci(ci: Optional[List[float]]) -> str:
    return "n/a" if not ci else f"[{ci[0]:.4f}, {ci[1]:.4f}]"


def render_markdown(ev: Dict[str, Any], *, run: Optional[Dict[str, Any]] = None) -> str:
    lines = ["# ALEA prospective forecast report", "",
             f"Generated: {ev['generated_at_utc']}  ",
             f"Champion: `{ev['champion_model_version']}`  ",
             f"Ledger fingerprint (champion forecasts): `{ev['ledger_fingerprint']}`", ""]
    if run:
        lines += ["## This run", "", f"- Run id: `{run.get('run_id')}`", f"- Status: **{run.get('status')}**"]
        if run.get("reason"):
            lines.append(f"- Reason: {run['reason']}")
        for key in ("forecasts_recorded", "forecasts_already_in_ledger", "challenger_forecasts_recorded",
                    "outcomes_settled", "too_close_to_kickoff"):
            if key in run:
                value = run[key]
                lines.append(f"- {key.replace('_', ' ')}: {len(value) if isinstance(value, list) else value}")
        src = run.get("sources", {})
        if src.get("wikipedia_attribution"):
            lines.append(f"- {src['wikipedia_attribution']}")
        lines.append("")
        if run.get("forecasts"):
            lines += ["### Forecasts in this window", "",
                      "| Kickoff (listed, UTC) | Home | Away | H | D | A | Status |", "|---|---|---|---|---|---|---|"]
            for f in run["forecasts"]:
                lines.append(f"| {f['kickoff_utc'][:16]} | {f['home']} | {f['away']} | {f['p_home']:.3f} | "
                             f"{f['p_draw']:.3f} | {f['p_away']:.3f} | {f['status']} |")
            lines.append("")
    c = ev["counts"]
    lines += ["## Ledger summary", "",
              f"- Champion forecasts: {c['champion_forecasts']} (challenger rows: {c['challenger_forecasts']})",
              f"- By status: " + (", ".join(f"{k} {v}" for k, v in sorted(c["by_status"].items())) or "none"),
              f"- Scored (settled, champion version): {c['scored']}", ""]
    if ev["foreign_model_versions_in_champion_table"]:
        lines += [f"**WARNING:** champion table contains other model versions: "
                  f"{ev['foreign_model_versions_in_champion_table']}", ""]
    ch = ev["champion"]
    lines += ["## Champion performance (settled forecasts only)", ""]
    if ch.get("n", 0) == 0:
        lines += ["No settled forecasts yet.", ""]
    else:
        lines += ["| Metric | Value | 95% CI (ISO-week block bootstrap) |", "|---|---|---|"]
        for m in ("log_loss", "brier", "rps", "accuracy"):
            lines.append(f"| {m} | {ch[m]:.4f} | {_fmt_ci(ch.get(f'{m}_ci95'))} |")
        lines += ["", f"n = {ch['n']}, week blocks = {ch.get('n_week_blocks')}, "
                      f"mean p(draw) {ch['mean_p_draw']:.3f} vs draw rate {ch['actual_draw_rate']:.3f}", ""]
    lines += ["## Registered challengers (paired, settled fixtures)", "",
              "| Challenger | n paired | LL diff | LL diff 95% CI | Brier diff | RPS diff | Decision |",
              "|---|---|---|---|---|---|---|"]
    for model_id, e in ev["challengers"].items():
        paired = e.get("paired") or {}
        ll = paired.get("log_loss_diff")
        lines.append(f"| {model_id} | {e['n_paired']} | {'n/a' if ll is None else f'{ll:+.4f}'} | "
                     f"{_fmt_ci(paired.get('log_loss_ci95'))} | "
                     f"{'n/a' if paired.get('brier_diff') is None else format(paired['brier_diff'], '+.4f')} | "
                     f"{'n/a' if e.get('rps_diff') is None else format(e['rps_diff'], '+.4f')} | {e['decision']} |")
    lines += ["", "Differences are challenger minus champion; negative favours the challenger.", ""]
    lines += ["## Outstanding forecasts", ""]
    if ev["outstanding"]:
        lines += ["| Fixture | Kickoff (listed) | Status | Note |", "|---|---|---|---|"]
        for o in ev["outstanding"]:
            lines.append(f"| {_label(o['fixture_key'])} | {o['kickoff_at'][:16]} | {o['status']} | {o['reason']} |")
    else:
        lines.append("None.")
    lines += ["", "## Settled forecasts", ""]
    if ev["settled"]:
        lines += ["| Fixture | H | D | A | Score | Outcome |", "|---|---|---|---|---|---|"]
        for s in ev["settled"]:
            lines.append(f"| {_label(s['fixture_key'])} | {s['p_home']:.3f} | {s['p_draw']:.3f} | {s['p_away']:.3f} | "
                         f"{s['home_goals']}-{s['away_goals']} | {s['outcome']} |")
    else:
        lines.append("None yet.")
    lines += ["", "## Data-quality issues", ""]
    if ev["data_quality_issues"]:
        lines += ["| When | Severity | Code | Fixture | Detail |", "|---|---|---|---|---|"]
        for i in ev["data_quality_issues"][-50:]:
            lines.append(f"| {i['recorded_at'][:16]} | {i['severity']} | {i['code']} | {_label(i['fixture_key']) if i['fixture_key'] else ''} | "
                         f"{i['detail'][:140].replace('|', '/')} |")
    else:
        lines.append("None recorded.")
    if ev["events"]:
        lines += ["", "## Fixture events", "", "| Fixture | Event | Source | New kickoff | Detail |",
                  "|---|---|---|---|---|"]
        for e in ev["events"]:
            lines.append(f"| {_label(e['fixture_key'])} | {e['event_type']} | {e['source']} | {e['new_kickoff_at'] or ''} | "
                         f"{e['detail']} |")
    lines += ["", "## Data sources and licences", "",
              "- Forecast probabilities: ALEA model output.",
              "- Match results: Wikipedia contributors, \"2026\u201327 Premier League\" "
              "(the revision used by each run is recorded in `runs/` and in the ledger), licensed under "
              "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Result observations "
              "redistributed in this ledger remain under CC BY-SA 4.0.",
              "- Fixtures and historical results: [OpenFootball football.json]"
              "(https://github.com/openfootball/football.json), CC0 1.0.",
              "- Licensing assessment: `docs/DATA_SOURCES_AND_LICENSING.md` (not legal advice).", ""]
    return "\n".join(lines)


def dumps(ev: Dict[str, Any]) -> str:
    return json.dumps(ev, indent=2, sort_keys=True, default=str) + "\n"
