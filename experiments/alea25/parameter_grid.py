"""Parameter sensitivity and alternative time-decay / regularisation experiments.

This module never imports or modifies the frozen champion source. It re-uses
the public fit_model / predict API from alea_predictor_v2_4_1 so that every
candidate is evaluated under the same numerical implementation and the same
cutoff discipline.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from alea_predictor_v2_4_1 import (
    fit_model,
    predict,
    walk_forward_backtest,
    XI as CHAMPION_XI,
    REG as CHAMPION_REG,
)

XI_CANDIDATES: Tuple[float, ...] = (0.0008, 0.0012, 0.0018, 0.0025, 0.0035, 0.0050)
REG_CANDIDATES: Tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0)
JOINT_GRID: Tuple[Tuple[float, float], ...] = tuple(
    (xi, reg) for xi in (0.0012, 0.0018, 0.0025, 0.0035) for reg in (0.5, 1.0, 2.0)
)


@dataclass(frozen=True)
class CandidateSpec:
    model_id: str
    xi: float
    reg: float
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def make_xi_candidates() -> List[CandidateSpec]:
    return [
        CandidateSpec(
            model_id=f"dc-xi-{xi:.4f}-reg-{CHAMPION_REG}",
            xi=xi,
            reg=CHAMPION_REG,
            description=f"Dixon-Coles with xi={xi}, champion reg={CHAMPION_REG}",
        )
        for xi in XI_CANDIDATES
    ]


def make_reg_candidates() -> List[CandidateSpec]:
    return [
        CandidateSpec(
            model_id=f"dc-xi-{CHAMPION_XI}-reg-{reg}",
            xi=CHAMPION_XI,
            reg=reg,
            description=f"Dixon-Coles with champion xi={CHAMPION_XI}, reg={reg}",
        )
        for reg in REG_CANDIDATES
    ]


def make_joint_candidates() -> List[CandidateSpec]:
    return [
        CandidateSpec(
            model_id=f"dc-xi-{xi:.4f}-reg-{reg}",
            xi=xi,
            reg=reg,
            description=f"Dixon-Coles joint (xi={xi}, reg={reg})",
        )
        for xi, reg in JOINT_GRID
    ]


def fit_candidate(
    data: pd.DataFrame,
    spec: CandidateSpec,
    *,
    as_of_date: Optional[date | datetime] = None,
    live: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    params = fit_model(
        data,
        xi=spec.xi,
        reg=spec.reg,
        verbose=verbose,
        as_of_date=as_of_date,
        live=live,
    )
    params["experiment_model_id"] = spec.model_id
    params["experiment_spec"] = spec.to_dict()
    return params


def predict_candidate(params: Dict[str, Any], home: str, away: str) -> Dict[str, Any]:
    return predict(params, home, away)


def _summarise_backtest(report: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"model_id": model_id}
    for key in ("log_loss", "brier", "rps", "accuracy", "n_matches", "n_folds"):
        if key in report:
            out[key] = report[key]
    if "metrics" in report and isinstance(report["metrics"], dict):
        for key in ("log_loss", "brier", "rps", "accuracy"):
            if key in report["metrics"]:
                out[key] = report["metrics"][key]
    if "n" in report:
        out["n_matches"] = report["n"]
    for nested_key in ("summary", "overall", "aggregate"):
        if nested_key in report and isinstance(report[nested_key], dict):
            for key in ("log_loss", "brier", "rps", "accuracy"):
                if key in report[nested_key]:
                    out[key] = report[nested_key][key]
    return out


def run_parameter_sensitivity(
    data: pd.DataFrame,
    candidates: Sequence[CandidateSpec],
    *,
    min_train_matches: int = 380,
    step_days: int = 14,
    verbose: bool = True,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {
        "milestone": "ALEA-2.5",
        "experiment": "parameter_sensitivity",
        "champion_xi": CHAMPION_XI,
        "champion_reg": CHAMPION_REG,
        "min_train_matches": min_train_matches,
        "step_days": step_days,
        "candidates": [],
        "notes": [
            "All candidates use the same fit_model / predict implementation as the champion.",
            "Cutoffs are enforced inside fit_model; no future information is used.",
            "Promotion is never automatic; results are for research only.",
        ],
    }

    if verbose:
        print("=== Champion baseline (xi=0.0018, reg=1.0) ===")
    champ_report = walk_forward_backtest(
        data,
        xi=CHAMPION_XI,
        reg=CHAMPION_REG,
        min_train_matches=min_train_matches,
        step_days=step_days,
        verbose=verbose,
        tune_each_fold=False,
    )
    results["champion"] = _summarise_backtest(champ_report, "champion")
    results["champion_raw_keys"] = list(champ_report.keys()) if isinstance(champ_report, dict) else []

    for spec in candidates:
        if verbose:
            print(f"=== Candidate {spec.model_id} ===")
        try:
            cand_report = walk_forward_backtest(
                data,
                xi=spec.xi,
                reg=spec.reg,
                min_train_matches=min_train_matches,
                step_days=step_days,
                verbose=verbose,
                tune_each_fold=False,
            )
            summary = _summarise_backtest(cand_report, spec.model_id)
            summary["spec"] = spec.to_dict()
            if "log_loss" in results["champion"] and "log_loss" in summary:
                summary["log_loss_diff_vs_champion"] = (
                    summary["log_loss"] - results["champion"]["log_loss"]
                )
            results["candidates"].append(summary)
        except Exception as exc:
            results["candidates"].append({
                "model_id": spec.model_id,
                "error": str(exc),
                "spec": spec.to_dict(),
            })

    return results
