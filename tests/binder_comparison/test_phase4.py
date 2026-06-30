"""Tests for Phase 4 — UX polish (Items 9 / 13 / 10 / lightweight)."""

import pytest

pytest.importorskip("pandas")
import pandas as pd
from binder_comparison.comparison.scoring import annotate_wetlab_recommended
from binder_comparison.visualization.plots import (
    plot_metric_correlation_heatmap,
    plot_pareto_front,
)
from binder_comparison.visualization.report import _df_to_html

# --- Item 9: wetlab_recommended annotation -----------------------------------


def _toy_df(**overrides):
    base = {
        "binder_id": ["a", "b", "c"],
        "source_tool": ["mosaic", "bindcraft", "mosaic"],
        "native_soluprot_passes": [True, False, True],
        "agreement_count": [3, 1, 2],
        "plddt_binder_min": [0.7, 0.6, 0.40],
        "consensus_ipsae_min_mean": [0.85, 0.80, 0.75],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_wetlab_recommended_passes_when_all_signals_clear():
    df = annotate_wetlab_recommended(_toy_df())
    # Design 'a': all pass.
    assert bool(df.loc[df.binder_id == "a", "wetlab_recommended"].iloc[0]) is True
    assert df.loc[df.binder_id == "a", "wetlab_reason"].iloc[0] == ""


def test_wetlab_recommended_flags_soluprot_fail():
    df = annotate_wetlab_recommended(_toy_df())
    # Design 'b': SoluProt fail + agreement 1.
    assert bool(df.loc[df.binder_id == "b", "wetlab_recommended"].iloc[0]) is False
    reason = df.loc[df.binder_id == "b", "wetlab_reason"].iloc[0]
    assert "SoluProt" in reason
    assert "agreement" in reason


def test_wetlab_recommended_flags_low_plddt_min():
    df = annotate_wetlab_recommended(_toy_df())
    # Design 'c': agreement 2 (just pass), pLDDT min 0.4 < 0.5.
    assert bool(df.loc[df.binder_id == "c", "wetlab_recommended"].iloc[0]) is False
    assert "pLDDT" in df.loc[df.binder_id == "c", "wetlab_reason"].iloc[0]


def test_wetlab_recommended_handles_missing_columns_gracefully():
    """When no advisory columns are present, recommend stays True (don't penalise unknowns)."""
    df = pd.DataFrame({"binder_id": ["x"], "source_tool": ["mosaic"]})
    out = annotate_wetlab_recommended(df)
    assert bool(out["wetlab_recommended"].iloc[0]) is True
    assert out["wetlab_reason"].iloc[0] == ""


def test_wetlab_recommended_flags_failed_run_convergence():
    """boltzgen_protein with mean ipSAE_min < 0.20 → FAILED RUN."""
    df = pd.DataFrame(
        {
            "binder_id": ["a", "b"],
            "source_tool": ["boltzgen_protein", "boltzgen_protein"],
            "consensus_ipsae_min_mean": [0.05, 0.10],
        }
    )
    out = annotate_wetlab_recommended(df)
    assert (out["wetlab_recommended"] == False).all()  # noqa: E712
    assert all("failed run" in r.lower() for r in out["wetlab_reason"])


# --- _df_to_html strike-through ---------------------------------------------


def test_df_to_html_strikes_through_when_recommended_false():
    df = pd.DataFrame(
        {
            "binder_id": ["a", "b"],
            "wetlab_recommended": [True, False],
        }
    )
    html = _df_to_html(df, strike_when_false_col="wetlab_recommended")
    assert "line-through" in html  # row b struck
    # Both rows present
    assert ">a<" in html and ">b<" in html


def test_df_to_html_no_strike_when_column_absent():
    df = pd.DataFrame({"binder_id": ["a"]})
    html = _df_to_html(df, strike_when_false_col="wetlab_recommended")
    assert "line-through" not in html


# --- Item 10 plots -----------------------------------------------------------


def test_correlation_heatmap_returns_figure_when_enough_metrics():
    df = pd.DataFrame(
        {
            "consensus_iptm": [0.9, 0.8, 0.7, 0.6, 0.5],
            "consensus_iptm_mean": [0.85, 0.75, 0.65, 0.55, 0.45],
            "agreement_count": [3, 2, 2, 1, 1],
            "ipsae_min": [0.8, 0.7, 0.6, 0.5, 0.4],
        }
    )
    fig = plot_metric_correlation_heatmap(df)
    assert fig is not None
    # Tear down so matplotlib doesn't leak Agg buffers between tests.
    import matplotlib.pyplot as plt

    plt.close(fig)


def test_correlation_heatmap_none_with_too_few_metrics():
    df = pd.DataFrame({"consensus_iptm": [0.9, 0.8]})
    assert plot_metric_correlation_heatmap(df) is None


def test_pareto_front_returns_figure():
    df = pd.DataFrame(
        {
            "binder_id": [f"d{i}" for i in range(8)],
            "source_tool": ["mosaic"] * 4 + ["bindcraft"] * 4,
            "consensus_iptm_mean": [0.9, 0.8, 0.7, 0.85, 0.6, 0.95, 0.5, 0.75],
            "native_soluprot_score": [0.4, 0.6, 0.8, 0.5, 0.9, 0.3, 0.95, 0.7],
        }
    )
    fig = plot_pareto_front(df, x="consensus_iptm_mean", y="native_soluprot_score", z=None)
    assert fig is not None
    import matplotlib.pyplot as plt

    plt.close(fig)


def test_pareto_front_none_when_columns_missing():
    df = pd.DataFrame({"x": [1, 2, 3]})
    assert plot_pareto_front(df, x="not_present", y="missing", z=None) is None


# --- Lightweight mode CLI flag is plumbed ------------------------------------


def test_lightweight_flag_in_report_cli_parser():
    """The --lightweight flag must be exposed by `binder-compare report`."""
    import argparse

    from binder_comparison.cli import report as report_cli

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    report_cli.add_parser(sub)
    parsed = parser.parse_args(["report", "--output", "/tmp/x", "--lightweight"])
    assert getattr(parsed, "lightweight", False) is True
