"""Self-consistency RMSD: did the refold put the binder where the design did?

Every published RFdiffusion-family gate couples an interface-confidence term with
a self-consistency RMSD between the design model and its refold — RFD3's own gate
uses target-aligned binder Cα-RMSD < 2.5 Å, Bennett 2023 uses
``af2_complex_rmsd < 5``. We compute no such term at all, so our gate has only
one of the field's two axes.

**The alignment is the whole point, and getting it wrong is silent.** Superposing
the binder onto itself measures whether it has the same FOLD. Superposing on the
TARGET — the one molecule that is the same in both structures — measures whether
the binder is in the same PLACE relative to it. A design whose binder folds
perfectly but docks on the wrong face scores ~0 Å the first way and large the
second, and it is the second number that says whether the prediction reproduces
the designed complex. ``test_a_correctly_folded_binder_docked_elsewhere_*`` pins
exactly that difference.

BindCraft's own 3.5 Å threshold is deliberately NOT ported: it computes RMSD
without superposition, on sub-poses in the trajectory frame, so its number does
not sit on the same scale as anything we can reproduce. RFD3's 2.5 Å is
target-aligned and is the one that transfers.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from binder_comparison.comparison.self_consistency import (  # noqa: E402
    SELF_CONSISTENCY_RMSD_MAX,
    target_aligned_rmsd,
)

# A small L-shaped "target" (asymmetric, so superposition is well determined)
# and a compact "binder" sitting beside it.
TARGET = np.array(
    [[0.0, 0.0, 0.0], [3.8, 0.0, 0.0], [7.6, 0.0, 0.0], [7.6, 3.8, 0.0], [7.6, 7.6, 0.0]],
    dtype=float,
)
BINDER = np.array([[0.0, 6.0, 0.0], [3.8, 6.0, 0.0], [3.8, 9.8, 0.0]], dtype=float)


def _rotation_z(deg: float) -> np.ndarray:
    t = np.radians(deg)
    return np.array([[np.cos(t), -np.sin(t), 0.0], [np.sin(t), np.cos(t), 0.0], [0.0, 0.0, 1.0]])


def test_identical_structures_are_zero():
    assert target_aligned_rmsd(TARGET, BINDER, TARGET, BINDER) == pytest.approx(0.0, abs=1e-6)


def test_a_rigid_move_of_the_whole_complex_is_zero():
    """Both structures are in arbitrary frames — the target superposition must
    remove any rigid motion applied to the complex as a whole."""
    shift = np.array([17.0, -4.0, 9.0])
    rot = _rotation_z(37.0)
    moved_target = TARGET @ rot.T + shift
    moved_binder = BINDER @ rot.T + shift
    assert target_aligned_rmsd(TARGET, BINDER, moved_target, moved_binder) == pytest.approx(0.0, abs=1e-6)


def test_binder_displaced_relative_to_the_target_is_that_displacement():
    """Target unchanged, binder moved 2 Å along x: every Cα is 2 Å off."""
    assert target_aligned_rmsd(TARGET, BINDER, TARGET, BINDER + np.array([2.0, 0.0, 0.0])) == pytest.approx(2.0)


def test_a_correctly_folded_binder_docked_elsewhere_scores_badly():
    """THE case this metric exists for. The binder's internal geometry is
    untouched — only its placement relative to the target changed."""
    docked_elsewhere = BINDER @ _rotation_z(180.0).T + np.array([7.6, 0.0, 0.0])
    rmsd = target_aligned_rmsd(TARGET, BINDER, TARGET, docked_elsewhere)
    assert rmsd > SELF_CONSISTENCY_RMSD_MAX, f"a wrongly-docked binder scored {rmsd:.2f} A — it must fail the gate"


def test_a_correctly_folded_binder_docked_elsewhere_looks_perfect_to_a_free_superposition():
    """The control that makes the previous test meaningful: aligning the binder
    on ITSELF reports ~0, because the fold really is identical. That is the
    number we must not be computing."""
    from binder_comparison.comparison.monomer import kabsch_rmsd

    docked_elsewhere = BINDER @ _rotation_z(180.0).T + np.array([7.6, 0.0, 0.0])
    assert kabsch_rmsd(docked_elsewhere, BINDER) == pytest.approx(0.0, abs=1e-6)


def test_mismatched_binder_lengths_are_not_a_number():
    """A truncated or extended binder has no 1:1 Cα correspondence. NaN, never a
    coincidental value from a partial comparison."""
    assert np.isnan(target_aligned_rmsd(TARGET, BINDER, TARGET, BINDER[:2]))


def test_mismatched_target_lengths_are_not_a_number():
    assert np.isnan(target_aligned_rmsd(TARGET, BINDER, TARGET[:3], BINDER))


def test_empty_input_is_not_a_number():
    empty = np.zeros((0, 3))
    assert np.isnan(target_aligned_rmsd(TARGET, BINDER, empty, BINDER))
    assert np.isnan(target_aligned_rmsd(TARGET, BINDER, TARGET, empty))


def test_the_threshold_is_rfd3s_and_is_documented_as_borrowed():
    """RFD3's gate, which is itself inherited rather than calibrated -- the
    preprint says 'cutoffs from [ref]'. Recorded so nobody cites it as
    RFD3-validated."""
    assert SELF_CONSISTENCY_RMSD_MAX == 2.5
