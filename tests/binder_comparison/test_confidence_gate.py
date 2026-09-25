"""BindCraft's confidence filters, ported to our refold columns.

BindCraft gates its own designs on a conjunctive panel, and the confidence half
of it needs no Rosetta at all -- it is arithmetic on columns we already have.
Porting it is worthwhile because those thresholds are tuned on de novo
minibinders of exactly this class, and RFD3 emits no quality score of its own.

Three things make it more than copying numbers across, and each fails quietly:

* **i_pAE is NORMALISED in BindCraft and raw Angstroms here.** ColabDesign
  divides PAE by 31.0 (``colabdesign/af/loss.py:252``), so BindCraft's 0.35
  is 10.85 A. The mapping is an identity, not an approximation: BindCraft
  symmetrises the PAE matrix and means it over the full binder x target block,
  which is exactly ``(pae_bt_mean + pae_tb_mean) / 2``.
* **ESMFold2's scalar ``iptm`` is the wrong quantity.** Its own refold script
  says so: the scalar "is chain-averaged and can be diluted", while
  ``pair_chains_iptm``'s off-diagonal "is the meaningful interface number for a
  binder". On the six real designs in the golden pool the scalar runs +0.137 to
  +0.239 above the pair value, so using it would inflate the gate by ~0.19 on
  one engine.
* **Boltz-2 emits no complex pTM.** Its only pTM-family column is the binder
  MONOMER pTM, a different quantity, so the pTM check covers two engines.

SHADOW MODE (the 2.0 rule): this annotates ``would_exclude_confidence`` and
excludes nothing. It must not reorder, drop, or decide which designs get
measured by anything else -- using a flag to select what gets scored is
selection, not annotation.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.confidence_gate import (  # noqa: E402
    BINDCRAFT_IPAE_NORMALISED,
    IPAE_MAX_ANGSTROM,
    PAE_NORMALISER,
    annotate_confidence_gate,
)


def _row(**over):
    """A design that clears every threshold on all three engines."""
    base = {
        "binder_id": "d1",
        "boltz_iptm": 0.95,
        "af3_iptm": 0.92,
        "esmfold2_iptm_pair": 0.75,
        "esmfold2_iptm": 0.89,  # the diluted scalar — must NOT be used
        "boltz_plddt_binder_mean": 0.96,
        "af3_plddt_binder_mean": 0.98,
        "esmfold2_plddt_binder_mean": 0.90,
        "boltz_pae_bt_mean": 4.0,
        "boltz_pae_tb_mean": 4.0,
        "af3_pae_bt_mean": 5.0,
        "af3_pae_tb_mean": 5.0,
        "esmfold2_pae_bt_mean": 6.0,
        "esmfold2_pae_tb_mean": 6.0,
    }
    base.update(over)
    return base


def test_the_conversion_constant_is_exact():
    """0.35 normalised x 31.0 = 10.85 A. Not 31.75 — that is the last PAE bin
    centre, not ColabDesign's divisor."""
    assert PAE_NORMALISER == 31.0
    assert BINDCRAFT_IPAE_NORMALISED == 0.35
    assert pytest.approx(10.85) == IPAE_MAX_ANGSTROM


def test_a_good_design_passes_every_check():
    out = annotate_confidence_gate(pd.DataFrame([_row()]))
    assert bool(out.loc[0, "passes_confidence_gate"]) is True
    assert bool(out.loc[0, "would_exclude_confidence"]) is False
    assert out.loc[0, "confidence_fail_reasons"] in ("", None) or pd.isna(out.loc[0, "confidence_fail_reasons"])


def test_ipae_is_the_mean_of_the_two_directions_in_angstroms():
    out = annotate_confidence_gate(pd.DataFrame([_row(boltz_pae_bt_mean=8.0, boltz_pae_tb_mean=12.0)]))
    # (8 + 12) / 2 = 10.0 A, still under 10.85
    assert out.loc[0, "boltz_ipae_ang"] == pytest.approx(10.0)
    assert bool(out.loc[0, "passes_confidence_gate"]) is True


def test_ipae_just_over_the_threshold_fails():
    out = annotate_confidence_gate(pd.DataFrame([_row(af3_pae_bt_mean=11.0, af3_pae_tb_mean=11.0)]))
    assert bool(out.loc[0, "passes_confidence_gate"]) is False
    assert "ipae" in str(out.loc[0, "confidence_fail_reasons"]).lower()


def test_uses_the_esmfold2_interface_iptm_not_the_diluted_scalar():
    """The scalar would pass; the interface value must be what is tested."""
    row = _row(esmfold2_iptm_pair=0.40, esmfold2_iptm=0.89)
    out = annotate_confidence_gate(pd.DataFrame([row]))
    assert bool(out.loc[0, "passes_confidence_gate"]) is False, (
        "esmfold2_iptm_pair=0.40 is below the 0.5 gate; reading the diluted scalar "
        "esmfold2_iptm=0.89 instead would wrongly pass this design"
    )
    assert "iptm" in str(out.loc[0, "confidence_fail_reasons"]).lower()


def test_chain_iptm_interface_is_accepted_when_iptm_pair_is_absent():
    row = _row()
    row.pop("esmfold2_iptm_pair")
    row["esmfold2_chain_iptm_interface"] = 0.40
    out = annotate_confidence_gate(pd.DataFrame([row]))
    assert bool(out.loc[0, "passes_confidence_gate"]) is False


def test_low_plddt_fails():
    out = annotate_confidence_gate(pd.DataFrame([_row(esmfold2_plddt_binder_mean=0.55)]))
    assert bool(out.loc[0, "passes_confidence_gate"]) is False
    assert "plddt" in str(out.loc[0, "confidence_fail_reasons"]).lower()


def test_no_engine_columns_at_all_is_NA_not_a_failure():
    """Absence of evidence. A design nothing refolded must not be reported as
    having failed a threshold it was never measured against."""
    out = annotate_confidence_gate(pd.DataFrame([{"binder_id": "d1"}]))
    assert pd.isna(out.loc[0, "passes_confidence_gate"])
    assert bool(out.loc[0, "would_exclude_confidence"]) is False, "an unmeasured design is never excluded"
    assert out.loc[0, "confidence_n_engines"] == 0


def test_partial_coverage_is_scored_on_what_exists():
    """One engine present is still a real measurement — it is just narrower, and
    confidence_n_engines records that."""
    row = {k: v for k, v in _row().items() if not k.startswith(("af3_", "esmfold2_"))}
    out = annotate_confidence_gate(pd.DataFrame([row]))
    assert out.loc[0, "confidence_n_engines"] == 1
    assert bool(out.loc[0, "passes_confidence_gate"]) is True


def test_shadow_mode_excludes_nothing_and_preserves_order():
    df = pd.DataFrame([_row(binder_id="good"), _row(binder_id="bad", af3_pae_bt_mean=30.0, af3_pae_tb_mean=30.0)])
    out = annotate_confidence_gate(df)
    assert out["binder_id"].tolist() == ["good", "bad"], "must not reorder"
    assert len(out) == 2, "must not drop"
    assert bool(out.loc[1, "would_exclude_confidence"]) is True
    assert bool(out.loc[1, "passes_confidence_gate"]) is False


def test_it_does_not_touch_the_ranking():
    """The 2.0 rule: an advisory column may never move `rank`."""
    from binder_comparison.comparison import scoring

    df = pd.DataFrame(
        [
            {"binder_id": "a", "consensus_iptm_mean": 0.9, "consensus_iptm_n": 3, "consensus_iptm": 0.95},
            {"binder_id": "b", "consensus_iptm_mean": 0.8, "consensus_iptm_n": 3, "consensus_iptm": 0.85},
        ]
    )
    before = scoring.rank_designs(df.copy()).sort_values("rank")["binder_id"].tolist()
    annotated = annotate_confidence_gate(df.copy())
    after = scoring.rank_designs(annotated.drop(columns=["rank"], errors="ignore")).sort_values("rank")
    assert after["binder_id"].tolist() == before


def test_a_missing_interface_iptm_is_not_a_silent_pass():
    """DEFECT 1. esmfold2_iptm_pair is NaN whenever the model returns no
    pair_chains_iptm, and `esmfold2_chain_iptm_interface` does not exist yet when
    the gate runs (report.py builds it later). So the iPTM test was skipped
    entirely while the engine still counted as measured -- an interface iPTM of
    0.12 passed a 0.5 gate with no reason recorded.

    An engine that contributed pLDDT and PAE but no interface iPTM has NOT been
    checked against the iPTM threshold, and must not report a clean pass.
    """
    row = {
        "sequence": "AAA",
        "esmfold2_iptm": 0.12,  # the diluted scalar — deliberately not consulted
        "esmfold2_plddt_binder_mean": 0.91,
        "esmfold2_pae_bt_mean": 4.0,
        "esmfold2_pae_tb_mean": 4.0,
    }
    out = annotate_confidence_gate(pd.DataFrame([row]))
    assert out.loc[0, "confidence_missing"] != "", "the un-checked iPTM must be recorded"
    assert "iptm" in str(out.loc[0, "confidence_missing"]).lower()
    assert out.loc[0, "passes_confidence_gate"] is not True, (
        "a design whose interface iPTM was never measured must not report a clean pass"
    )


def test_a_blank_numeric_cell_does_not_crash():
    """DEFECT 3. pd.notna("") is True, so an empty string reached float()."""
    row = {"sequence": "AAA", "boltz_iptm": "", "boltz_plddt_binder_mean": "0.9"}
    out = annotate_confidence_gate(pd.DataFrame([row]))
    assert out.loc[0, "confidence_n_engines"] == 1


def test_a_duplicate_index_does_not_smear_values_across_rows():
    """Latent, and exactly this codebase's characteristic failure: `.loc[row.name]`
    writes to EVERY row sharing a label, so two rows with index 0 both got the
    last one's value. Not reachable through the report today (the merge yields a
    RangeIndex) but one refactor away, and silent when it happens."""
    df = pd.DataFrame(
        [
            {"sequence": "A", "boltz_pae_bt_mean": 4.0, "boltz_pae_tb_mean": 6.0, "boltz_iptm": 0.9},
            {"sequence": "B", "boltz_pae_bt_mean": 20.0, "boltz_pae_tb_mean": 20.0, "boltz_iptm": 0.2},
        ],
        index=[0, 0],
    )
    out = annotate_confidence_gate(df)
    assert list(out["boltz_ipae_ang"]) == [5.0, 20.0], "the two rows must keep their own i_pAE"
