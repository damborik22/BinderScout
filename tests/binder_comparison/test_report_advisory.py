"""Tests for the advisory SoluProt + qc-annotate report integration.

Both are ADVISORY: surfaced as columns, never used to reorder or drop designs.
"""

import pytest

pd = pytest.importorskip("pandas")
from binder_comparison.cli.report import (  # noqa: E402
    _attach_affinity_results,
    _attach_monomer_results,
    _attach_qc_results,
)
from binder_comparison.visualization.report import (  # noqa: E402
    _advisory_legend_html,
    _benchmark_provenance_html,
    _df_to_html,
    _qc_rules_html,
    _screening_summary_intro_html,
    _select_display_cols,
    _top_table_legend_html,
)


def _metrics_df():
    return pd.DataFrame(
        {
            "binder_id": ["d1", "d2", "d3"],
            "source_tool": ["mosaic", "bindcraft", "rfd3"],
            "two_stage_rank": [1, 2, 3],
            "consensus_iptm": [0.9, 0.8, 0.7],
            "consensus_iptm_mean": [0.85, 0.75, 0.65],
        }
    )


def test_attach_qc_results_joins_by_binder_id(tmp_path):
    qc = pd.DataFrame(
        {
            "binder_id": ["d1", "d3"],  # only a shortlist annotated
            "qc_pass": [True, False],
            "qc_fail_reasons": ["", "dG>0.0;sc<0.55"],
            "interface_dG": [-25.0, 3.0],
            "interface_sc": [0.71, 0.40],
        }
    )
    p = tmp_path / "qc.csv"
    qc.to_csv(p, index=False)
    out = _attach_qc_results(_metrics_df(), str(p))
    # advisory: NO rows dropped, NO reordering
    assert out["binder_id"].tolist() == ["d1", "d2", "d3"]
    # annotated rows carry the panel; the un-annotated one stays NaN
    assert bool(out.loc[out.binder_id == "d1", "qc_pass"].iloc[0]) is True
    assert out.loc[out.binder_id == "d2", "qc_pass"].isna().iloc[0]
    assert out.loc[out.binder_id == "d3", "interface_dG"].iloc[0] == 3.0


def test_attach_qc_results_missing_file_is_noop():
    df = _metrics_df()
    out = _attach_qc_results(df, "/nonexistent/qc.csv")
    assert "qc_pass" not in out.columns
    assert out["binder_id"].tolist() == df["binder_id"].tolist()


def test_display_cols_include_advisory_when_present():
    df = _metrics_df()
    df["native_soluprot_score"] = [0.7, 0.6, 0.5]
    df["qc_pass"] = [True, False, True]
    df["interface_dG"] = [-25.0, 3.0, -10.0]
    primary, secondary = _select_display_cols(df, rank_method="two_stage")
    assert "native_soluprot_score" in primary
    assert "qc_pass" in primary
    assert "interface_dG" in secondary


def test_display_cols_omit_advisory_when_absent():
    primary, _secondary = _select_display_cols(_metrics_df(), rank_method="two_stage")
    assert "native_soluprot_score" not in primary
    assert "qc_pass" not in primary


def test_advisory_legend_present_only_with_columns():
    assert _advisory_legend_html(_metrics_df()) == ""
    df = _metrics_df()
    df["native_soluprot_score"] = 0.5
    df["qc_pass"] = True
    legend = _advisory_legend_html(df)
    assert "soluprot_score" in legend and "qc_pass" in legend


# --- Phase 1 additions (Items 4, 7, 12, 15) -----------------------------------


def test_top_table_legend_two_stage_calls_iptm_primary():
    """The Top-30 legend under two-stage ranking must NOT label ipSAE_min as primary."""
    df = _metrics_df()
    df["passes_max_screen"] = [True, True, False]
    df["consensus_iptm_mean"] = df["consensus_iptm_mean"]  # already in fixture
    html = _top_table_legend_html("two_stage", df)
    assert "Primary ranking metric" in html
    # The "Primary ranking metric" label must be attached to consensus_iptm_mean,
    # not ipsae_min — this is the bug the maintainer flagged.
    primary_idx = html.index("Primary ranking metric")
    iptm_mean_idx = html.index("consensus_iptm_mean")
    assert iptm_mean_idx < primary_idx + 200  # within the same row


def test_top_table_legend_adaptyv_still_calls_ipsae_primary():
    """The adaptyv ranking path keeps ipSAE_min as primary — the rewrite is rank-aware."""
    df = _metrics_df()
    df["ipsae_min"] = [0.85, 0.82, 0.45]
    html = _top_table_legend_html("adaptyv", df)
    assert "Primary ranking metric" in html
    # Under adaptyv, the primary label sits next to ipsae_min, not consensus_iptm_mean.
    ipsae_idx = html.index("ipsae_min")
    primary_idx = html.index("Primary ranking metric")
    assert ipsae_idx < primary_idx + 200


def test_screening_summary_intro_two_stage_single_ipsae_tier():
    """Item 12: two_stage shows ONE tier system (ipSAE_min) matching the single tier-count table.

    iPTM is the ranking metric but is continuous, not tier-banded — there is no
    iPTM tier-count table, so rendering a parallel iPTM tier legend just reads as a
    confusing second tier system. iPTM is named in prose; only ipSAE_min is banded.
    """
    html = _screening_summary_intro_html("two_stage")
    # The active ranking metric is named so the reader knows the ranking key.
    assert "consensus_iptm_mean" in html
    # No second, parallel iPTM tier band/table.
    assert "iPTM band" not in html
    # The single ipSAE_min tier band is present.
    assert "High" in html and "Reject" in html


def test_binding_map_link_renders_only_when_provided():
    from binder_comparison.visualization.report import _binding_map_link_html

    assert _binding_map_link_html(None) == ""
    assert _binding_map_link_html("") == ""
    html = _binding_map_link_html("2VDY_CBG_binding_map.html")
    assert "Target binding map" in html
    assert "href='2VDY_CBG_binding_map.html'" in html
    assert 'target="_blank"' in html or "target='_blank'" in html


def test_screening_summary_intro_adaptyv_only_ipsae_legend():
    """Under adaptyv, ipSAE IS the ranking metric — show just the single ipSAE band."""
    html = _screening_summary_intro_html("adaptyv")
    assert "ipSAE_min tiers" in html
    # No iPTM band table in adaptyv mode (iPTM isn't the ranking key here).
    assert "iPTM band" not in html


def test_qc_rules_html_lists_all_five_default_thresholds():
    """Item 15: the QC details block must surface every BindCraft default threshold."""
    html = _qc_rules_html()
    for needle in (
        "interface_dG",
        "interface_sc",
        "interface_interface_hbonds",
        "interface_delta_unsat_hbonds",
        "interface_nres",
    ):
        assert needle in html, f"QC threshold missing from rules block: {needle}"
    assert "Advisory only" in html  # the never-auto-drop disclaimer


def test_benchmark_provenance_html_cites_both_benchmarks_and_caveat():
    """Item 7: provenance block must cite Adaptyv + ProteinBase AUCs and the serpin caveat."""
    html = _benchmark_provenance_html()
    assert "Adaptyv" in html
    assert "ProteinBase" in html
    assert "0.710" in html and "0.689" in html
    assert "Transferability caveat" in html
    assert "serpins" in html


def test_df_to_html_disagreement_flag_fires_when_agreement_low():
    """Item 4: ⚠ icon appears when agreement_count drops below 2."""
    df = pd.DataFrame(
        {
            "two_stage_rank": [1, 2, 3],
            "binder_id": ["a", "b", "c"],
            "agreement_count": [3, 1, 3],  # row b should trigger
            "consensus_iptm_spread": [0.05, 0.05, 0.05],
        }
    )
    html = _df_to_html(df, flag_disagreement=True, rank_col="two_stage_rank")
    assert html.count("⚠") == 1


def test_df_to_html_disagreement_flag_fires_when_spread_high():
    """Item 4: ⚠ icon also appears when per-engine iPTM spread > 0.3."""
    df = pd.DataFrame(
        {
            "two_stage_rank": [1, 2],
            "binder_id": ["a", "b"],
            "agreement_count": [3, 3],
            "consensus_iptm_spread": [0.05, 0.45],  # row b should trigger
        }
    )
    html = _df_to_html(df, flag_disagreement=True, rank_col="two_stage_rank")
    assert html.count("⚠") == 1


def test_df_to_html_disagreement_flag_off_by_default():
    """Default rendering MUST NOT add warning markers — only opt-in for Top-30."""
    df = pd.DataFrame(
        {
            "two_stage_rank": [1],
            "binder_id": ["a"],
            "agreement_count": [1],
            "consensus_iptm_spread": [0.9],
        }
    )
    html = _df_to_html(df, flag_disagreement=False)
    assert "⚠" not in html


def test_select_display_cols_two_stage_promotes_agreement_and_spread():
    """Item 4 part 2: agreement_count + consensus_iptm_spread must be in PRIMARY now."""
    df = _metrics_df()
    df["passes_max_screen"] = True
    df["agreement_count"] = [3, 2, 1]
    df["consensus_iptm_spread"] = [0.05, 0.15, 0.40]
    primary, _secondary = _select_display_cols(df, rank_method="two_stage")
    assert "agreement_count" in primary
    assert "consensus_iptm_spread" in primary


# --- Part X: newly-wired advisory panels (affinity, monomer, beta) ------------


def test_attach_affinity_results_joins_by_binder_id(tmp_path):
    """affinity CSV surfaces affinity_energy_density + passes_affinity_gate; advisory (no drop/reorder)."""
    aff = pd.DataFrame(
        {
            "binder_id": ["d1", "d3"],
            "affinity_energy_density": [0.42, 0.11],
            "passes_affinity_gate": [True, False],
        }
    )
    p = tmp_path / "affinity.csv"
    aff.to_csv(p, index=False)
    out = _attach_affinity_results(_metrics_df(), str(p))
    assert out["binder_id"].tolist() == ["d1", "d2", "d3"]  # no reorder/drop
    assert out.loc[out.binder_id == "d1", "affinity_energy_density"].iloc[0] == 0.42
    assert out.loc[out.binder_id == "d2", "affinity_energy_density"].isna().iloc[0]


def test_attach_affinity_results_missing_file_is_noop():
    out = _attach_affinity_results(_metrics_df(), "/nonexistent/affinity.csv")
    assert "affinity_energy_density" not in out.columns


def test_attach_monomer_results_joins_design_id_to_binder_id(tmp_path):
    """monomer CSV keys by design_id; must join onto binder_id and add monomer_rmsd + fold_robust."""
    mono = pd.DataFrame(
        {
            "design_id": ["d1", "d2"],
            "monomer_rmsd": [1.2, 5.6],
            "fold_robust": [True, False],
        }
    )
    p = tmp_path / "monomer.csv"
    mono.to_csv(p, index=False)
    out = _attach_monomer_results(_metrics_df(), str(p))
    assert out["binder_id"].tolist() == ["d1", "d2", "d3"]
    assert bool(out.loc[out.binder_id == "d1", "fold_robust"].iloc[0]) is True
    assert out.loc[out.binder_id == "d2", "monomer_rmsd"].iloc[0] == 5.6
    assert out.loc[out.binder_id == "d3", "fold_robust"].isna().iloc[0]  # unannotated stays blank


def test_new_advisory_cols_in_secondary_when_present():
    """affinity / monomer / beta columns must reach the Top-30 detailed (secondary) display set."""
    df = _metrics_df()
    df["passes_max_screen"] = True
    df["affinity_energy_density"] = [0.4, 0.3, 0.2]
    df["fold_robust"] = [True, True, False]
    df["monomer_rmsd"] = [1.0, 2.0, 4.0]
    df["beta_intercalates"] = ["false", "false", "true"]
    df["esmfold2_chain_iptm_interface"] = [0.7, 0.6, 0.5]
    _primary, secondary = _select_display_cols(df, rank_method="two_stage")
    for col in (
        "affinity_energy_density",
        "fold_robust",
        "monomer_rmsd",
        "beta_intercalates",
        "esmfold2_chain_iptm_interface",
    ):
        assert col in secondary, f"{col} missing from two-stage secondary display set"


def test_advisory_legend_covers_beta_affinity_monomer():
    df = _metrics_df()
    df["beta_intercalates"] = "false"
    df["affinity_energy_density"] = 0.3
    df["fold_robust"] = True
    legend = _advisory_legend_html(df)
    assert "beta_intercalates" in legend
    assert "affinity_energy_density" in legend
    assert "fold_robust" in legend


def _pdb_atom(serial, chain, resnum, x, y, z):
    """One fixed-width Cα ATOM record the epitope parser can read."""
    return (
        "ATOM  "
        + f"{serial:>5}"
        + "  CA  "
        + "ALA "
        + chain
        + f"{resnum:>4}"
        + "    "
        + f"{x:>8.3f}"
        + f"{y:>8.3f}"
        + f"{z:>8.3f}"
        + "  1.00  0.00           C"
    )


def test_primary_structure_col_picks_engine_and_chain():
    from binder_comparison.cli.report import _primary_structure_col

    df = pd.DataFrame({"esmfold2_pdb": ["/x.pdb"], "boltz_pdb": ["/y.pdb"]})
    assert _primary_structure_col(df, "esmfold2") == ("esmfold2_pdb", "B")
    assert _primary_structure_col(df, "boltz") == ("boltz_pdb", "A")
    # fallback to any engine when the requested one is absent
    df2 = pd.DataFrame({"boltz_pdb": ["/y.pdb"]})
    assert _primary_structure_col(df2, "af3") == ("boltz_pdb", "A")


def test_compute_epitope_inline_scores_from_structure(tmp_path):
    """Inline epitope reads the refolded structure and scores hotspot recall (advisory)."""
    from binder_comparison.cli.report import _compute_epitope_inline

    pdb = "\n".join(
        [
            _pdb_atom(1, "A", 1, 0, 0, 0),  # binder
            _pdb_atom(2, "A", 2, 3, 0, 0),  # binder
            _pdb_atom(3, "B", 10, 1, 1, 1),  # target, ~1.7 Å from binder → interface
            _pdb_atom(4, "B", 99, 50, 50, 50),  # target, far → not interface
        ]
    )
    p = tmp_path / "d1.pdb"
    p.write_text(pdb)
    df = pd.DataFrame({"binder_id": ["d1"], "sequence": ["AA"], "boltz_pdb": [str(p)]})
    out = _compute_epitope_inline(
        df,
        hotspots_spec="10,99",
        structure_col="boltz_pdb",
        binder_chain="A",
        cutoff=8.0,
        flag_threshold=0.30,
        base_dir=None,
    )
    assert out.loc[0, "epitope_n_interface"] == 1  # only B10 contacts the binder
    assert out.loc[0, "epitope_match_fraction"] == 0.5  # 1 of 2 hotspots (10) landed; numeric, not str
    assert out.loc[0, "epitope_status"] == "OK"  # 0.5 >= 0.30 flag threshold


def test_compute_epitope_inline_missing_structure_marks_no_structure(tmp_path):
    from binder_comparison.cli.report import _compute_epitope_inline

    df = pd.DataFrame({"binder_id": ["d1"], "boltz_pdb": ["/does/not/exist.pdb"]})
    out = _compute_epitope_inline(
        df,
        hotspots_spec="10",
        structure_col="boltz_pdb",
        binder_chain="A",
        cutoff=8.0,
        flag_threshold=0.30,
        base_dir=None,
    )
    assert out.loc[0, "epitope_status"] == "NO_STRUCTURE"
    assert pd.isna(out.loc[0, "epitope_match_fraction"])


def test_engine_radar_uses_real_pae_mean_columns():
    """Regression: the AF3 radar referenced non-existent af3_pae_bt/tb (the real
    merged columns are *_pae_bt_mean). ESMFold2 (default engine) must now have a radar panel.

    Protenix was in this list until its refolding was removed (see CHANGELOG,
    "Protenix refolding removed; AF3 is the 2nd engine") — it has no radar to check."""
    from binder_comparison.visualization.plots import _ENGINE_RADAR_METRICS, _ENGINE_RANK_COLS

    for engine in ("af3", "esmfold2"):
        cols = {c for c, _lbl, _dir in _ENGINE_RADAR_METRICS[engine]}
        assert f"{engine}_pae_bt_mean" in cols, f"{engine} radar must use {engine}_pae_bt_mean"
        assert f"{engine}_pae_tb_mean" in cols
        assert f"{engine}_pae_bt" not in cols  # the bare (non-existent) column must be gone
    assert _ENGINE_RANK_COLS["esmfold2"] == "esmfold2_ipsae_min"


# --- Methodology text must describe the ranking that actually ran (F32) --------


class TestTwoStageMethodologyText:
    """Regression: the blurb was a fixed string. Commit 5769064 flipped the screen
    default mean -> max and updated CHANGELOG, CLAUDE.md, cli/report.py, scoring.py
    and test_scoring.py — but not visualization/report.py. Every report afterwards
    ran a max screen while telling the reader it had run a mean screen, called mean
    "the default" and called max "legacy"."""

    def _render(self, screen_metric, min_engines=3):
        from binder_comparison.visualization.report import _two_stage_methodology_html

        return _two_stage_methodology_html(screen_metric, min_engines, "ipsae-link")

    def test_max_screen_names_the_column_it_diagnoses(self):
        html = self._render("max")
        assert "<code>consensus_iptm</code>" in html
        assert "no longer affects the ranking" in html

    def test_max_screen_does_not_claim_mean_is_the_default(self):
        html = self._render("max")
        assert "Mean was selected as default" not in html
        assert "legacy max-screen" not in html

    def test_mean_screen_names_the_column_it_diagnoses(self):
        html = self._render("mean")
        assert "<code>consensus_iptm_mean</code>) as a" in html
        assert "no longer affects the ranking" in html

    def test_blurb_does_not_claim_the_screen_still_ranks(self):
        """Part U retired Stage 1. The blurb must not tell a reader that a screen
        selects a 'binder-likely pool' or that Stage 2 ranks only 'survivors'."""
        for metric in ("max", "mean"):
            html = self._render(metric)
            assert "binder-likely" not in html
            assert "survivors are ordered" not in html

    def test_blurb_states_the_calibrated_enrichment(self):
        """A reader must not take the top-N as a verdict — Part U measured ~1.5-2x."""
        html = self._render("max")
        assert "triage filter" in html
        assert "6 of 12 targets" in html

    def test_the_two_screens_render_differently(self):
        assert self._render("max") != self._render("mean")

    def test_engine_gate_is_stated_from_the_argument(self):
        assert "at least <b>3</b>" in self._render("max", min_engines=3)
        assert "at least <b>2</b>" in self._render("max", min_engines=2)


class TestVendoredNglIsInlined:
    """Regression (F20): report.html <script src>'d unpkg.com, so the 3D viewer was a
    blank black box on air-gapped nodes — the environment this pipeline otherwise
    engineers around carefully. cli/epitope_map.py already inlined the vendored copy."""

    def test_script_tag_is_inline_not_cdn(self):
        from binder_comparison.visualization.report import _ngl_script_tag

        tag = _ngl_script_tag()
        assert tag.startswith("<script>")
        assert "unpkg.com" not in tag
        assert len(tag) > 100_000, "should carry the real vendored library, not a stub"
