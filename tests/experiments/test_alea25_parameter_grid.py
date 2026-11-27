"""Unit tests for ALEA 2.5 parameter-grid helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.alea25.parameter_grid import (
    make_xi_candidates,
    make_reg_candidates,
    make_joint_candidates,
    CandidateSpec,
    CHAMPION_XI,
    CHAMPION_REG,
)


def test_xi_candidates_include_champion_value():
    cands = make_xi_candidates()
    assert any(abs(c.xi - CHAMPION_XI) < 1e-9 for c in cands)
    assert all(c.reg == CHAMPION_REG for c in cands)
    assert all(c.xi > 0 for c in cands)


def test_reg_candidates_include_champion_value():
    cands = make_reg_candidates()
    assert any(abs(c.reg - CHAMPION_REG) < 1e-9 for c in cands)
    assert all(c.xi == CHAMPION_XI for c in cands)


def test_joint_grid_unique_ids():
    cands = make_joint_candidates()
    ids = [c.model_id for c in cands]
    assert len(ids) == len(set(ids))
    assert all(isinstance(c, CandidateSpec) for c in cands)


def test_candidate_spec_immutable():
    c = CandidateSpec(model_id="test", xi=0.002, reg=1.5)
    with pytest.raises(Exception):
        c.xi = 0.003  # type: ignore
