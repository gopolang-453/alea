"""Stage 12 reliability and security regression tests."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage12.reliability import (
    ReliabilityError,
    backup_artifact,
    data_freshness,
    restore_backup,
    scan_repository_for_secrets,
    sha256_file,
    verify_sha256,
)


def test_backup_restore_and_checksum_verification(tmp_path):
    original = tmp_path / "model.json"
    original.write_text('{"model":"known-good"}', encoding="utf-8")
    manifest = backup_artifact(original, tmp_path / "backups")
    backup = tmp_path / "backups" / manifest["backup_name"]
    assert verify_sha256(backup, manifest["sha256"])

    original.write_text("corrupted", encoding="utf-8")
    restored = restore_backup(backup, original, manifest["sha256"])
    assert restored.read_text(encoding="utf-8") == '{"model":"known-good"}'
    assert sha256_file(original) == manifest["sha256"]


def test_restore_refuses_corrupted_backup(tmp_path):
    backup = tmp_path / "bad.bak"
    backup.write_text("bad", encoding="utf-8")
    with pytest.raises(ReliabilityError, match="failed SHA-256"):
        restore_backup(backup, tmp_path / "restore.json", "0" * 64)


def test_data_freshness_reports_missing_fresh_and_stale():
    now = datetime(2024, 1, 10, tzinfo=timezone.utc)
    assert data_freshness(None, now)["status"] == "missing"
    assert data_freshness(now - timedelta(hours=2), now)["status"] == "fresh"
    assert data_freshness(now - timedelta(days=5), now)["status"] == "stale"
    with pytest.raises(ReliabilityError, match="future"):
        data_freshness(now + timedelta(hours=1), now)


def test_secret_scanner_reports_location_without_echoing_secret(tmp_path):
    (tmp_path / "safe.py").write_text('API_KEY = os.environ.get("API_KEY")\n', encoding="utf-8")
    (tmp_path / "unsafe.py").write_text('TOKEN = "ghp_' + "A" * 40 + '"\n', encoding="utf-8")
    findings = scan_repository_for_secrets(tmp_path)
    assert len(findings) == 1
    assert findings[0]["path"] == "unsafe.py"
    assert findings[0]["line"] == 1
    assert "A" * 40 not in str(findings)
