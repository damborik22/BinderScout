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


# --------------------------------------------------------------------------
# Resolving which chain is the binder.
#
# Chain conventions differ per producer -- Boltz-2 puts the binder in A,
# AF3/ESMFold2 in B, and a tool's own design structure uses whatever it wrote.
# CLAUDE.md already lists that mismatch as a bug source, so the binder is found
# by SEQUENCE rather than by a hardcoded letter. Pure PDB text: gemmi is
# deliberately not a binder-eval dependency.
# --------------------------------------------------------------------------

from binder_comparison.comparison.self_consistency import split_target_binder  # noqa: E402

_BINDER_SEQ = "AGV"  # ALA GLY VAL
_TARGET_SEQ = "MKSE"


def _pdb(chains: dict[str, tuple[str, list]]) -> str:
    """chains = {chain_id: (three_letter_codes_str, [(x,y,z), ...])}"""
    three = {"A": "ALA", "G": "GLY", "V": "VAL", "M": "MET", "K": "LYS", "S": "SER", "E": "GLU"}
    lines, n = [], 0
    for cid, (seq, coords) in chains.items():
        for i, (aa, xyz) in enumerate(zip(seq, coords, strict=True), start=1):
            n += 1
            lines.append(
                f"ATOM  {n:>5}  CA  {three[aa]} {cid}{i:>4}    {xyz[0]:>8.3f}{xyz[1]:>8.3f}{xyz[2]:>8.3f}  1.00  0.00"
            )
    return "\n".join(lines) + "\n"


def test_finds_the_binder_by_sequence_in_chain_B():
    text = _pdb({"A": (_TARGET_SEQ, TARGET[:4]), "B": (_BINDER_SEQ, BINDER)})
    tgt, bnd = split_target_binder(text, "AGV")
    assert len(bnd) == 3 and len(tgt) == 4
    assert np.allclose(bnd, BINDER)


def test_finds_the_binder_by_sequence_in_chain_A():
    """The Boltz-2 layout. Same call, no flag, no convention."""
    text = _pdb({"A": (_BINDER_SEQ, BINDER), "B": (_TARGET_SEQ, TARGET[:4])})
    tgt, bnd = split_target_binder(text, "AGV")
    assert len(bnd) == 3 and len(tgt) == 4
    assert np.allclose(bnd, BINDER)


def test_every_other_chain_becomes_the_target():
    """A multi-chain target must not be truncated to one chain."""
    text = _pdb({"A": ("MK", TARGET[:2]), "B": (_BINDER_SEQ, BINDER), "C": ("SE", TARGET[2:4])})
    tgt, bnd = split_target_binder(text, "AGV")
    assert len(bnd) == 3
    assert len(tgt) == 4, "chains A and C together are the target"


def test_no_matching_chain_returns_empty():
    text = _pdb({"A": (_TARGET_SEQ, TARGET[:4]), "B": (_BINDER_SEQ, BINDER)})
    tgt, bnd = split_target_binder(text, "WWWWWW")
    assert len(bnd) == 0 and len(tgt) == 0


def test_the_whole_comparison_end_to_end():
    """design vs refold, opposite chain conventions, binder shifted 2 A."""
    design = _pdb({"A": (_TARGET_SEQ, TARGET[:4]), "B": (_BINDER_SEQ, BINDER)})
    refold = _pdb({"A": (_BINDER_SEQ, BINDER + np.array([2.0, 0.0, 0.0])), "B": (_TARGET_SEQ, TARGET[:4])})

    d_t, d_b = split_target_binder(design, "AGV")
    r_t, r_b = split_target_binder(refold, "AGV")
    assert target_aligned_rmsd(d_t, d_b, r_t, r_b) == pytest.approx(2.0)


# --------------------------------------------------------------------------
# The report annotation.
# --------------------------------------------------------------------------

from binder_comparison.comparison.self_consistency import annotate_self_consistency  # noqa: E402

pd = pytest.importorskip("pandas")


def _write_complex(path, binder_coords, target_coords, binder_chain="B"):
    tgt_chain = "A" if binder_chain == "B" else "B"
    chains = {tgt_chain: (_TARGET_SEQ, target_coords), binder_chain: (_BINDER_SEQ, binder_coords)}
    # keep deterministic order: target first
    ordered = {k: chains[k] for k in sorted(chains)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pdb(ordered))


def test_annotates_rmsd_against_each_engine(tmp_path):
    design_dir = tmp_path / "design_structures" / "rfd3"
    _write_complex(design_dir / "design_0000.pdb", BINDER, TARGET[:4])
    (design_dir.parent / "rfd3" / "manifest.csv").write_text("sequence,path\nAGV,design_0000.pdb\n")

    # Boltz-2 layout (binder in A) and shifted 2 A; AF3 layout, exact.
    _write_complex(tmp_path / "b.pdb", BINDER + np.array([2.0, 0.0, 0.0]), TARGET[:4], binder_chain="A")
    _write_complex(tmp_path / "a.pdb", BINDER, TARGET[:4], binder_chain="B")

    df = pd.DataFrame([{"binder_id": "d1", "sequence": "AGV", "boltz_pdb": "b.pdb", "af3_pdb": "a.pdb"}])
    out = annotate_self_consistency(df, design_root=tmp_path / "design_structures", base_dir=tmp_path)

    assert out.loc[0, "boltz_self_consistency_rmsd"] == pytest.approx(2.0)
    assert out.loc[0, "af3_self_consistency_rmsd"] == pytest.approx(0.0, abs=1e-6)
    # best agreement across engines
    assert out.loc[0, "self_consistency_rmsd"] == pytest.approx(0.0, abs=1e-6)
    assert bool(out.loc[0, "passes_self_consistency"]) is True


def test_no_design_structure_is_NA_not_a_failure(tmp_path):
    df = pd.DataFrame([{"binder_id": "d1", "sequence": "AGV", "boltz_pdb": "missing.pdb"}])
    out = annotate_self_consistency(df, design_root=tmp_path / "nope", base_dir=tmp_path)
    assert pd.isna(out.loc[0, "self_consistency_rmsd"])
    assert pd.isna(out.loc[0, "passes_self_consistency"])
    assert bool(out.loc[0, "would_exclude_self_consistency"]) is False, "unmeasured is never excluded"


def test_a_wrongly_docked_design_is_flagged(tmp_path):
    design_dir = tmp_path / "design_structures" / "rfd3"
    _write_complex(design_dir / "design_0000.pdb", BINDER, TARGET[:4])
    (design_dir / "manifest.csv").write_text("sequence,path\nAGV,design_0000.pdb\n")

    docked_elsewhere = BINDER @ _rotation_z(180.0).T + np.array([7.6, 0.0, 0.0])
    _write_complex(tmp_path / "b.pdb", docked_elsewhere, TARGET[:4], binder_chain="A")

    df = pd.DataFrame([{"binder_id": "d1", "sequence": "AGV", "boltz_pdb": "b.pdb"}])
    out = annotate_self_consistency(df, design_root=tmp_path / "design_structures", base_dir=tmp_path)

    assert out.loc[0, "self_consistency_rmsd"] > SELF_CONSISTENCY_RMSD_MAX
    assert bool(out.loc[0, "passes_self_consistency"]) is False
    assert bool(out.loc[0, "would_exclude_self_consistency"]) is True
