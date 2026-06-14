"""Tests for the wet-lab advisor core (biophysics, assay selection, codon-opt, plan)."""

import pytest
from binder_comparison.comparison.wetlab import (
    WetLabConfig,
    codon_optimize,
    recommend_assay,
    sequence_properties,
    wetlab_plan_markdown,
)

# --- sequence_properties ------------------------------------------------------


def test_extinction_is_pace_gill_reduced():
    # 1 Trp (5500) + 1 Tyr (1490) = 6990; other residues contribute 0.
    assert sequence_properties("WYAAA")["extinction_280"] == 6990


def test_molecular_weight_single_glycine():
    # residue mass 57.0519 + one water 18.01528.
    assert sequence_properties("G")["molecular_weight"] == pytest.approx(75.07, abs=0.05)


def test_pi_acidic_vs_basic():
    acidic = sequence_properties("DDDEEE")["isoelectric_point"]
    basic = sequence_properties("KKKRRR")["isoelectric_point"]
    assert acidic < 5.0 < 9.0 < basic


def test_gravy_all_isoleucine_is_max_hydrophobic():
    assert sequence_properties("IIII")["gravy"] == pytest.approx(4.5)


def test_aromatic_fraction_and_nonstandard():
    p = sequence_properties("FWYA")
    assert p["aromatic_fraction"] == pytest.approx(0.75)
    p2 = sequence_properties("AXZ")  # only A is standard
    assert p2["length"] == 1 and p2["nonstandard"] == 2


def test_empty_sequence_is_zeroed():
    assert sequence_properties("")["length"] == 0


# --- recommend_assay ----------------------------------------------------------


def test_assay_high_throughput_above_50():
    assert "NanoBiT" in recommend_assay(80)["screen"]


def test_assay_bli_at_or_below_50():
    assert "BLI" in recommend_assay(30)["screen"]


def test_assay_tight_budget_downgrades_to_cheap_screen():
    assert "NanoBiT" in recommend_assay(30, budget_usd=1000)["screen"]


def test_assay_always_recommends_spr_for_leads():
    assert "SPR" in recommend_assay(10)["lead_characterization"]


# --- codon_optimize -----------------------------------------------------------


def test_codon_length_is_three_per_residue_plus_stop():
    dna = codon_optimize("MKV")
    assert len(dna) == 3 * 3 + 3 and dna.endswith("TAA")


def test_codon_start_methionine():
    assert codon_optimize("M", add_stop=False) == "ATG"


def test_codon_rejects_nonstandard():
    with pytest.raises(ValueError):
        codon_optimize("MXV")


# --- wetlab_plan_markdown -----------------------------------------------------


def test_plan_has_required_sections_and_fasta():
    designs = [
        {"binder_id": "d1", "sequence": "MAEVKLSYWY"},
        {"binder_id": "d2", "sequence": "GGSAHHWQTT"},
    ]
    md = wetlab_plan_markdown(designs, WetLabConfig(budget_usd=8000, top_n=10))
    for section in (
        "# Wet-lab plan",
        "## 1. Gene synthesis",
        "## 2. Expression",
        "## 3. Screening",
        "## 5. Controls",
        "### FASTA",
    ):
        assert section in md
    assert ">d1" in md and "MAEVKLSYWY" in md


def test_plan_respects_top_n():
    designs = [{"binder_id": f"d{i}", "sequence": "MKV"} for i in range(10)]
    md = wetlab_plan_markdown(designs, WetLabConfig(top_n=3))
    assert md.count(">d") == 3
