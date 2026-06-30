"""Tests for the advisory SoluProt + qc-annotate report integration.

Both are ADVISORY: surfaced as columns, never used to reorder or drop designs.
"""

import pytest

pd = pytest.importorskip("pandas")
from binder_comparison.cli.report import _attach_qc_results  # noqa: E402
from binder_comparison.visualization.report import (  # noqa: E402
    _advisory_legend_html,
    _select_display_cols,
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
