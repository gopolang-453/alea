"""Stage 12 — artifact integrity, backup/restore and operational checks."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ReliabilityError(ValueError):
    pass


def sha256_file(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise ReliabilityError(f"file does not exist: {file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: str | Path, expected: str) -> bool:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(expected)):
        raise ReliabilityError("expected SHA-256 must be 64 hexadecimal characters")
    try:
        return sha256_file(path).lower() == expected.lower()
    except ReliabilityError:
        return False


def backup_artifact(source: str | Path, backup_dir: str | Path) -> Dict[str, Any]:
    source_path = Path(source)
    digest = sha256_file(source_path)
    target_dir = Path(backup_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / f"{source_path.name}.{digest[:16]}.bak"
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(source_path, temporary)
        if sha256_file(temporary) != digest:
            temporary.unlink(missing_ok=True)
            raise ReliabilityError("backup checksum did not match source")
        os.replace(temporary, destination)
    manifest = {
        "source_name": source_path.name,
        "backup_name": destination.name,
        "sha256": digest,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = destination.with_suffix(destination.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def restore_backup(
    backup_path: str | Path,
    destination: str | Path,
    expected_sha256: str,
) -> Path:
    backup = Path(backup_path)
    target = Path(destination)
    if not verify_sha256(backup, expected_sha256):
        raise ReliabilityError("backup artifact failed SHA-256 verification")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".restore.tmp")
    shutil.copy2(backup, temporary)
    if not verify_sha256(temporary, expected_sha256):
        temporary.unlink(missing_ok=True)
        raise ReliabilityError("restored temporary file failed SHA-256 verification")
    os.replace(temporary, target)
    return target


def data_freshness(
    latest_available_at: Optional[datetime],
    now: Optional[datetime] = None,
    *,
    max_age_hours: float = 72.0,
) -> Dict[str, Any]:
    if latest_available_at is None:
        return {"status": "missing", "age_hours": None}
    current = now or datetime.now(timezone.utc)
    if (
        latest_available_at.tzinfo is None or latest_available_at.utcoffset() is None
        or current.tzinfo is None or current.utcoffset() is None
    ):
        raise ReliabilityError("freshness timestamps must be timezone-aware")
    if not math.isfinite(max_age_hours) or max_age_hours <= 0:
        raise ReliabilityError("max_age_hours must be finite and positive")
    age = (current - latest_available_at).total_seconds() / 3600.0
    if age < 0:
        raise ReliabilityError("latest data availability timestamp is in the future")
    return {
        "status": "fresh" if age <= max_age_hours else "stale",
        "age_hours": age,
        "max_age_hours": float(max_age_hours),
    }


_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH) PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"""(?i)\b(?:api_key|secret_key|access_token)\s*=\s*['"][A-Za-z0-9_./+-]{24,}['"]"""),
]


def scan_repository_for_secrets(root: str | Path) -> List[Dict[str, Any]]:
    """Find high-confidence secret patterns in working-tree text files.

    This scans the current filesystem only, not Git history or remote secrets.
    """
    base = Path(root)
    findings: List[Dict[str, Any]] = []
    skip = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}
    for path in base.rglob("*"):
        if not path.is_file() or any(part in skip for part in path.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            for pattern in _SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append({
                        "path": str(path.relative_to(base)),
                        "line": line_number,
                        "pattern": pattern.pattern,
                    })
    return findings
