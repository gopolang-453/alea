"""Stage 10 registry safety tests."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage10.automation import ModelRegistry, RegistryError


GOOD_METRICS = {
    "n_holdout": 500,
    "holdout_log_loss": 0.95,
    "baseline_holdout_log_loss": 1.00,
    "log_loss_diff_ci_upper": -0.01,
    "holdout_brier": 0.56,
    "baseline_holdout_brier": 0.57,
    "brier_diff_ci_upper": -0.001,
}


def artifact(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_registry_registers_verifies_promotes_and_rolls_back(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(
        "baseline", artifact(tmp_path, "baseline.json", '{"base":true}'),
        {"holdout_log_loss": 1.0, "holdout_brier": 0.57},
    )
    first = registry.register(
        "model-1", artifact(tmp_path, "m1.json", '{"a":1}'), GOOD_METRICS,
        {"comparison_baseline_version": "baseline"},
    )
    assert registry.verify("model-1")
    assert registry.promote("model-1")["champion"] == "model-1"

    second_metrics = dict(
        GOOD_METRICS,
        holdout_log_loss=0.90,
        baseline_holdout_log_loss=0.95,
        holdout_brier=0.54,
        baseline_holdout_brier=0.56,
    )
    second = registry.register(
        "model-2", artifact(tmp_path, "m2.json", '{"a":2}'), second_metrics,
        {"comparison_baseline_version": "model-1"},
    )
    assert registry.verify("model-2")
    assert registry.promote("model-2")["previous_champion"] == "model-1"
    assert registry.champion()["version"] == "model-2"

    assert registry.rollback()["champion"] == "model-1"
    assert registry.champion()["version"] == "model-1"


def test_registry_refuses_candidate_without_strong_holdout_evidence(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(
        "baseline", artifact(tmp_path, "baseline.json", "baseline"),
        {"holdout_log_loss": 1.0, "holdout_brier": 0.57},
    )
    weak = dict(GOOD_METRICS, log_loss_diff_ci_upper=0.01)
    registry.register(
        "weak", artifact(tmp_path, "weak.json", "model"), weak,
        {"comparison_baseline_version": "baseline"},
    )
    with pytest.raises(RegistryError, match="CI includes zero"):
        registry.promote("weak")


def test_registry_detects_artifact_tampering(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register(
        "baseline", artifact(tmp_path, "baseline.json", "baseline"),
        {"holdout_log_loss": 1.0, "holdout_brier": 0.57},
    )
    record = registry.register(
        "model-1", artifact(tmp_path, "model.json", "original"), GOOD_METRICS,
        {"comparison_baseline_version": "baseline"},
    )
    (tmp_path / "registry" / record["artifact"]).write_text("tampered", encoding="utf-8")
    assert registry.verify("model-1") is False
    with pytest.raises(RegistryError, match="SHA-256"):
        registry.promote("model-1")


def test_registry_requires_evidence_and_valid_version(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    with pytest.raises(RegistryError, match="unsupported characters"):
        registry.register("../bad", artifact(tmp_path, "bad.json", "x"), GOOD_METRICS)
    registry.register(
        "baseline", artifact(tmp_path, "baseline.json", "base"),
        {"holdout_log_loss": 1.0, "holdout_brier": 0.57},
    )
    registry.register(
        "no-evidence", artifact(tmp_path, "candidate.json", "x"), {},
        {"comparison_baseline_version": "baseline"},
    )
    with pytest.raises(RegistryError, match="missing metrics"):
        registry.promote("no-evidence")
