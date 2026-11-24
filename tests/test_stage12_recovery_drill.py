import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.recovery_drill import FROZEN_SHA, run_drill


def test_drill_passes_on_frozen_baseline_and_leaves_it_untouched(tmp_path):
    artifact = ROOT / "alea_predictor_v2_4_1.py"
    report = run_drill(artifact, FROZEN_SHA, tmp_path)
    assert report["passed"], report["checks"]
    assert len(report["checks"]) == 6
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == FROZEN_SHA


def test_drill_fails_when_source_does_not_match(tmp_path):
    artifact = tmp_path / "model.py"
    artifact.write_text("print('x')\n")
    report = run_drill(artifact, "0" * 64, tmp_path / "scratch")
    assert not report["passed"]
    assert report["checks"]["source_integrity"] is False
