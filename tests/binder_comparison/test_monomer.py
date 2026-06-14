"""Tests for monomer validation (Kabsch RMSD + Cα parsing)."""

import numpy as np
import pytest
from binder_comparison.comparison.monomer import (
    ca_coords_from_pdb,
    classify_fold_robustness,
    kabsch_rmsd,
)


def _ca_line(serial, chain, resseq, x, y, z):
    s = [" "] * 80
    s[0:6] = "ATOM  "
    s[6:11] = f"{serial:>5}"
    s[12:16] = "CA  "
    s[17:20] = "ALA"
    s[21] = chain
    s[22:26] = f"{resseq:>4}"
    s[30:38] = f"{x:>8.3f}"
    s[38:46] = f"{y:>8.3f}"
    s[46:54] = f"{z:>8.3f}"
    return "".join(s)


# --- kabsch_rmsd --------------------------------------------------------------


def test_identical_coords_zero_rmsd():
    p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    assert kabsch_rmsd(p, p) == pytest.approx(0.0, abs=1e-9)


def test_rigid_motion_is_removed():
    """A pure rotation + translation must give ~0 RMSD."""
    rng = np.random.default_rng(0)
    p = rng.normal(size=(8, 3))
    theta = 0.7
    rot = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])
    q = p @ rot.T + np.array([10.0, -5.0, 2.0])
    assert kabsch_rmsd(p, q) == pytest.approx(0.0, abs=1e-9)


def test_deformation_gives_positive_rmsd():
    p = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
    q = p.copy()
    q[3] = [0, 0, 3]  # move one atom out of place — not a rigid motion
    assert kabsch_rmsd(p, q) > 0.5


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        kabsch_rmsd(np.zeros((3, 3)), np.zeros((4, 3)))


# --- classify_fold_robustness -------------------------------------------------


def test_robust_below_threshold_inclusive():
    assert classify_fold_robustness(2.0) is True
    assert classify_fold_robustness(3.0) is True  # boundary inclusive
    assert classify_fold_robustness(4.0) is False


# --- ca_coords_from_pdb -------------------------------------------------------


def test_parses_ca_and_filters_chain():
    pdb = "\n".join(
        [
            _ca_line(1, "A", 1, 0.0, 0.0, 0.0),
            _ca_line(2, "A", 2, 1.0, 2.0, 3.0),
            _ca_line(3, "B", 1, 9.0, 9.0, 9.0),
            "HETATM 4  O   HOH A   3       5.0   5.0   5.0",  # ignored (not ATOM/CA)
        ]
    )
    all_ca = ca_coords_from_pdb(pdb)
    assert all_ca.shape == (3, 3)
    chain_a = ca_coords_from_pdb(pdb, chain="A")
    assert chain_a.shape == (2, 3)
    assert chain_a[1].tolist() == [1.0, 2.0, 3.0]


def test_no_match_returns_empty():
    assert ca_coords_from_pdb("REMARK nothing here").shape == (0, 3)
