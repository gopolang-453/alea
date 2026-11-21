"""Stage 10 regression suite — registry gates and champion comparison.

All data used here is SYNTHETIC. Results must not be reported as real
Premier League validation.
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stages.stage10.automation import ModelRegistry, RegistryError
from stages.stage10.champion_comparison import (
    ComparisonError,
    HeadToHeadResult,
    compare_candidate_to_champion,
)


def _make_artifact(path: Path, content: bytes = b"synthetic-model-artifact-v1") -> Path:
    path.write_bytes(content)
    return path


def _valid_metrics(n=120, ll=0.94, base_ll=0.96, ci_upper=-0.01, brier=0.57, base_brier=0.58):
    return {
        "n_holdout": float(n),
        "holdout_log_loss": float(ll),
        "baseline_holdout_log_loss": float(base_ll),
        "log_loss_diff_ci_upper": float(ci_upper),
        "holdout_brier": float(brier),
        "baseline_holdout_brier": float(base_brier),
        "brier_diff_ci_upper": float(brier - base_brier),
    }


def test_register_and_verify(tmp_path):
    reg = ModelRegistry(tmp_path)
    art = _make_artifact(tmp_path / "m1.bin")
    rec = reg.register("cand-1", art, _valid_metrics(), metadata={"comparison_baseline_version": "none"})
    assert reg.verify("cand-1") is True
    assert rec["sha256"]


def test_promote_rejects_missing_metrics(tmp_path):
    reg = ModelRegistry(tmp_path)
    art = _make_artifact(tmp_path / "m1.bin")
    reg.register("cand-1", art, {"n_holdout": 50.0}, metadata={})
    with pytest.raises(RegistryError, match="missing metrics"):
        reg.promote("cand-1")


def test_promote_rejects_too_few_samples(tmp_path):
    reg = ModelRegistry(tmp_path)
    art = _make_artifact(tmp_path / "m1.bin")
    metrics = _valid_metrics(n=10)
    base_art = _make_artifact(tmp_path / "base.bin", b"base")
    reg.register("base-1", base_art, _valid_metrics(n=150, ll=0.96), metadata={})
    data = reg._read()
    data["champion"] = "base-1"
    reg._write(data)
    reg.register("cand-1", art, metrics, metadata={"comparison_baseline_version": "base-1"})
    with pytest.raises(RegistryError, match="too small"):
        reg.promote("cand-1", min_holdout_samples=100)


def test_promote_rejects_when_ci_includes_zero(tmp_path):
    reg = ModelRegistry(tmp_path)
    base_art = _make_artifact(tmp_path / "base.bin", b"base")
    reg.register("base-1", base_art, _valid_metrics(n=150, ll=0.96), metadata={})
    data = reg._read()
    data["champion"] = "base-1"
    reg._write(data)
    art = _make_artifact(tmp_path / "m1.bin")
    metrics = _valid_metrics(n=120, ll=0.94, base_ll=0.96, ci_upper=0.01)
    reg.register("cand-1", art, metrics, metadata={"comparison_baseline_version": "base-1"})
    with pytest.raises(RegistryError, match="has not proven a log-loss improvement"):
        reg.promote("cand-1")


def test_promote_rejects_when_worse_than_champion_baseline(tmp_path):
    reg = ModelRegistry(tmp_path)
    base_art = _make_artifact(tmp_path / "base.bin", b"base")
    reg.register("base-1", base_art, _valid_metrics(n=150, ll=0.94), metadata={})
    data = reg._read()
    data["champion"] = "base-1"
    reg._write(data)
    art = _make_artifact(tmp_path / "m1.bin")
    metrics = _valid_metrics(n=120, ll=0.97, base_ll=0.94, ci_upper=-0.01)
    reg.register("cand-1", art, metrics, metadata={"comparison_baseline_version": "base-1"})
    with pytest.raises(RegistryError, match="does not beat its baseline"):
        reg.promote("cand-1")


def test_promote_rejects_wrong_baseline_version(tmp_path):
    reg = ModelRegistry(tmp_path)
    base_art = _make_artifact(tmp_path / "base.bin", b"base")
    reg.register("base-1", base_art, _valid_metrics(n=150), metadata={})
    other_art = _make_artifact(tmp_path / "other.bin", b"other")
    reg.register("other-1", other_art, _valid_metrics(n=150), metadata={})
    data = reg._read()
    data["champion"] = "base-1"
    reg._write(data)
    art = _make_artifact(tmp_path / "m1.bin")
    metrics = _valid_metrics(n=120)
    reg.register("cand-1", art, metrics, metadata={"comparison_baseline_version": "other-1"})
    with pytest.raises(RegistryError, match="must be compared against the current champion"):
        reg.promote("cand-1")


def test_promote_rejects_tampered_artifact(tmp_path):
    reg = ModelRegistry(tmp_path)
    base_art = _make_artifact(tmp_path / "base.bin", b"base")
    reg.register("base-1", base_art, _valid_metrics(n=150), metadata={})
    data = reg._read()
    data["champion"] = "base-1"
    reg._write(data)
    art = _make_artifact(tmp_path / "m1.bin")
    metrics = _valid_metrics(n=120)
    reg.register("cand-1", art, metrics, metadata={"comparison_baseline_version": "base-1"})
    (tmp_path / "models" / "cand-1" / art.name).write_bytes(b"TAMPERED")
    with pytest.raises(RegistryError, match="SHA-256"):
        reg.promote("cand-1")


def test_valid_promotion_succeeds(tmp_path):
    reg = ModelRegistry(tmp_path)
    base_art = _make_artifact(tmp_path / "base.bin", b"base")
    base_metrics = _valid_metrics(n=150, ll=0.96, brier=0.58, base_ll=0.96, base_brier=0.58)
    reg.register("base-1", base_art, base_metrics, metadata={})
    data = reg._read()
    data["champion"] = "base-1"
    reg._write(data)

    art = _make_artifact(tmp_path / "m1.bin")
    metrics = _valid_metrics(n=120, ll=0.94, base_ll=0.96, ci_upper=-0.015, brier=0.57, base_brier=0.58)
    reg.register("cand-1", art, metrics, metadata={"comparison_baseline_version": "base-1"})
    outcome = reg.promote("cand-1", min_holdout_samples=100)
    assert outcome["champion"] == "cand-1"
    assert outcome["previous_champion"] == "base-1"
    assert reg.champion()["version"] == "cand-1"


def test_rollback_restores_previous(tmp_path):
    reg = ModelRegistry(tmp_path)
    base_art = _make_artifact(tmp_path / "base.bin", b"base")
    base_metrics = _valid_metrics(n=150, ll=0.96, brier=0.58, base_ll=0.96, base_brier=0.58)
    reg.register("base-1", base_art, base_metrics, metadata={})
    data = reg._read()
    data["champion"] = "base-1"
    reg._write(data)

    art = _make_artifact(tmp_path / "m1.bin")
    metrics = _valid_metrics(n=120, ll=0.94, base_ll=0.96, ci_upper=-0.02, brier=0.57, base_brier=0.58)
    reg.register("cand-1", art, metrics, metadata={"comparison_baseline_version": "base-1"})
    reg.promote("cand-1")
    assert reg.champion()["version"] == "cand-1"

    rolled = reg.rollback()
    assert rolled["champion"] == "base-1"
    assert reg.champion()["version"] == "base-1"


def test_head_to_head_result_gate_logic():
    good = HeadToHeadResult(
        n_shared_fixtures=100,
        champion_log_loss=0.96,
        candidate_log_loss=0.94,
        champion_brier=0.58,
        candidate_brier=0.57,
        champion_rps=0.20,
        candidate_rps=0.19,
        paired_log_loss_diff_mean=-0.02,
        paired_log_loss_diff_ci_low=-0.04,
        paired_log_loss_diff_ci_high=-0.01,
        includes_zero=False,
    )
    assert good.passes_promotion_gate() is True

    tied = HeadToHeadResult(
        n_shared_fixtures=100,
        champion_log_loss=0.95,
        candidate_log_loss=0.95,
        champion_brier=0.58,
        candidate_brier=0.58,
        champion_rps=0.20,
        candidate_rps=0.20,
        paired_log_loss_diff_mean=0.0,
        paired_log_loss_diff_ci_low=-0.01,
        paired_log_loss_diff_ci_high=0.01,
        includes_zero=True,
    )
    assert tied.passes_promotion_gate() is False


def test_comparison_rejects_insufficient_fixtures():
    rng = np.random.default_rng(0)
    rows = []
    for i in range(10):
        rows.append({
            "Date": f"2024-01-{i+1:02d}",
            "HomeTeam": "A",
            "AwayTeam": "B",
            "FTHG": int(rng.integers(0, 4)),
            "FTAG": int(rng.integers(0, 4)),
        })
    df = pd.DataFrame(rows)
    with pytest.raises(ComparisonError, match="post-cutoff|shared"):
        compare_candidate_to_champion(
            df,
            {"as_of_date": "2023-12-01"},
            min_shared_fixtures=50,
        )


def test_failed_register_does_not_create_champion(tmp_path):
    reg = ModelRegistry(tmp_path)
    art = _make_artifact(tmp_path / "m1.bin")
    with pytest.raises(RegistryError):
        reg.register("bad version!", art, _valid_metrics())
    assert reg.champion() is None
