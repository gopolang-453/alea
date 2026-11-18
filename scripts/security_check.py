#!/usr/bin/env python3
"""Fail CI when a high-confidence secret is present in the working tree."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.stage12.reliability import scan_repository_for_secrets


def main() -> int:
    findings = scan_repository_for_secrets(ROOT)
    if findings:
        for finding in findings:
            print(f"{finding['path']}:{finding['line']}: possible secret ({finding['pattern']})")
        return 1
    print("Secret scan passed: no high-confidence secret patterns found in working tree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
