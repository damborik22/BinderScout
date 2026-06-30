"""Tests for the advisory SoluProt + qc-annotate report integration.

Both are ADVISORY: surfaced as columns, never used to reorder or drop designs.
"""

import pytest

pd = pytest.importorskip("pandas")
from binder_comparison.cli.report import _attach_qc_results  # noqa: E402
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


def test_screening_summary_intro_two_stage_combined_table():
    """Item 12: two_stage shows a single combined table with iPTM + ipSAE bands side-by-side.

    The previous design had two paragraph blocks which read as duplication
    (same 4 colored bands, slightly different thresholds). Folded into one
    table with a shared tier label.
    """
    html = _screening_summary_intro_html("two_stage")
    # One combined block, not two duplicate paragraphs.
    assert "Threshold bands" in html
    assert "iPTM band" in html and "ipSAE_min band" in html
    # The active ranking metric is named so the reader knows which is the ranking key.
    assert "consensus_iptm_mean" in html
    # No leftover "iPTM tiers" / "ipSAE_min tiers" duplicate paragraph headings.
    assert "ipSAE_min tiers" not in html


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
