"""Tests for BinderScore unified scoring — no GPU."""

import pytest

from bindmaster.scoring.unified import BinderScore, ToolOrigin, from_pxdesign_record, from_rfaa_result


def test_composite_all_metrics():
    score = BinderScore(
        design_id="test_001",
        origin=ToolOrigin.PXDESIGN,
        pdb_path="test.cif",
        target_name="PDL1",
        binder_length=80,
        iptm=0.87,
        plddt_binder=0.91,
        ipae=5.1,
    )
    assert score.composite_score is not None
    assert 0.0 < score.composite_score < 1.0


def test_composite_missing_ipae():
    """Should still compute composite without ipAE (weights redistributed)."""
    score = BinderScore(
        design_id="test_002",
        origin=ToolOrigin.PXDESIGN,
        pdb_path="test.cif",
        target_name="PDL1",
        binder_length=80,
        iptm=0.87,
        plddt_binder=0.91,
    )
    assert score.composite_score is not None


def test_composite_no_metrics():
    """RFAA backbones have no score — should return None."""
    score = BinderScore(
        design_id="rfaa_001",
        origin=ToolOrigin.RFAA,
        pdb_path="rfaa_out.pdb",
        target_name="7v11",
        binder_length=150,
        ligand_ccd_code="OQO",
    )
    assert score.composite_score is None


def test_from_pxdesign_record():
    record = {
        "af2_iptm": 0.72,
        "af2_ipae": 5.1,
        "af2_plddt": 0.91,
        "ptx_iptm": 0.87,
        "ptx_ptm": 0.89,
        "passes_protenix_strict": True,
        "passes_af2ig_strict": True,
    }
    score = from_pxdesign_record(record, "pxd_001", "PDL1", 80, "design.cif")
    assert score.origin == ToolOrigin.PXDESIGN
    assert score.passes_any_filter() is True
    assert score.composite_score is not None


def test_composite_ordering():
    """Better metrics -> higher composite."""
    good = BinderScore(
        design_id="good",
        origin=ToolOrigin.PXDESIGN,
        pdb_path="",
        target_name="T",
        binder_length=80,
        iptm=0.90,
        plddt_binder=0.95,
        ipae=3.0,
    )
    bad = BinderScore(
        design_id="bad",
        origin=ToolOrigin.PXDESIGN,
        pdb_path="",
        target_name="T",
        binder_length=80,
        iptm=0.50,
        plddt_binder=0.70,
        ipae=15.0,
    )
    assert good.composite_score > bad.composite_score
