"""Stage 10 — candidate model registry with evidence-gated promotion and rollback."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class RegistryError(ValueError):
    pass


_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelRegistry:
    """Filesystem registry; artifacts are immutable once registered."""

    SCHEMA_VERSION = 1

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.models_dir = self.root / "models"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.root / "registry.json"
        if not self.registry_path.exists():
            self._write({
                "schema_version": self.SCHEMA_VERSION,
                "champion": None,
                "previous_champion": None,
                "models": {},
            })
        self._read()

    def _read(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"cannot read model registry: {exc}") from exc
        if data.get("schema_version") != self.SCHEMA_VERSION or not isinstance(data.get("models"), dict):
            raise RegistryError("unsupported or malformed model registry schema")
        return data

    def _write(self, data: Dict[str, Any]) -> None:
        temporary = self.registry_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.registry_path)

    def register(
        self,
        version: str,
        artifact_path: str | Path,
        metrics: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not _VERSION.fullmatch(version):
            raise RegistryError("version contains unsupported characters")
        source = Path(artifact_path)
        if not source.is_file() or source.stat().st_size == 0:
            raise RegistryError("model artifact must exist and be non-empty")
        data = self._read()
        if version in data["models"]:
            raise RegistryError(f"model version already registered: {version}")
        clean_metrics = {}
        for key, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise RegistryError(f"metric {key!r} must be a finite number")
            clean_metrics[key] = float(value)
        try:
            json.dumps(metadata or {})
        except (TypeError, ValueError) as exc:
            raise RegistryError("metadata must be JSON serialisable") from exc

        destination_dir = self.models_dir / version
        destination_dir.mkdir(parents=True, exist_ok=False)
        destination = destination_dir / source.name
        shutil.copy2(source, destination)
        record = {
            "version": version,
            "artifact": str(destination.relative_to(self.root)),
            "sha256": sha256_file(destination),
            "metrics": clean_metrics,
            "metadata": metadata or {},
            "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        data["models"][version] = record
        self._write(data)
        return record

    def verify(self, version: str) -> bool:
        data = self._read()
        if version not in data["models"]:
            raise RegistryError(f"unknown model version: {version}")
        record = data["models"][version]
        artifact = self.root / record["artifact"]
        return artifact.is_file() and sha256_file(artifact) == record["sha256"]

    def promote(
        self,
        version: str,
        *,
        min_holdout_samples: int = 100,
        brier_tolerance: float = 0.0,
    ) -> Dict[str, Any]:
        if min_holdout_samples < 1 or not math.isfinite(brier_tolerance) or brier_tolerance < 0:
            raise RegistryError("promotion thresholds must be finite and non-negative")
        data = self._read()
        if version not in data["models"]:
            raise RegistryError(f"unknown model version: {version}")
        if not self.verify(version):
            raise RegistryError("candidate artifact failed SHA-256 verification")
        metrics = data["models"][version]["metrics"]
        required = {
            "n_holdout", "holdout_log_loss", "log_loss_diff_ci_upper",
            "holdout_brier", "baseline_holdout_brier",
        }
        missing = sorted(required - set(metrics))
        if missing:
            raise RegistryError(f"promotion evidence missing metrics: {missing}")
        if metrics["n_holdout"] < min_holdout_samples:
            raise RegistryError("holdout sample is too small for promotion")
        if metrics["log_loss_diff_ci_upper"] >= 0:
            raise RegistryError("candidate has not proven a log-loss improvement (paired CI includes zero)")
        if metrics["holdout_brier"] > metrics["baseline_holdout_brier"] + brier_tolerance:
            raise RegistryError("candidate materially worsens Brier score")
        old_champion = data.get("champion")
        data["previous_champion"] = old_champion
        data["champion"] = version
        self._write(data)
        return {"champion": version, "previous_champion": old_champion}

    def rollback(self) -> Dict[str, Any]:
        data = self._read()
        previous = data.get("previous_champion")
        if not previous or previous not in data["models"]:
            raise RegistryError("no previous champion is available for rollback")
        if not self.verify(previous):
            raise RegistryError("previous champion artifact failed SHA-256 verification")
        current = data.get("champion")
        data["champion"] = previous
        data["previous_champion"] = current
        self._write(data)
        return {"champion": previous, "previous_champion": current}

    def champion(self) -> Optional[Dict[str, Any]]:
        data = self._read()
        version = data.get("champion")
        return None if version is None else data["models"][version]
