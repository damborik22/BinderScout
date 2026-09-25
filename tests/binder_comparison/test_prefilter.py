"""Tests for `binder-compare prefilter` — fold-back ranking for tools (RFD3)
that have no native interface metric.

Covers the pure ranking/formatting logic (build_selection) and the FASTA
metadata parser; the PAE recompute is exercised end-to-end elsewhere.
"""

import pytest

pd = pytest.importorskip("pandas")
from binder_comparison.cli.prefilter import _fasta_metadata, build_selection  # noqa: E402


def _df():
    # two distinct designs + a duplicate sequence of the best one (worse score)
    return pd.DataFrame(
        {
            "run_id": ["h1", "h2", "h3"],
            "sequence": ["AAAA", "BBBB", "AAAA"],
            "binder_length": [40, 60, 40],
            "boltz_pae_ipsae_min": [0.30, 0.50, 0.10],
            "boltz_pae_iptm": [0.6, 0.8, 0.4],
        }
    )


def test_build_selection_ranks_best_first_and_dedups():
    out = build_selection(_df(), "boltz_pae_ipsae_min", None, tool="rfd3", top=None)
    # best-first, and the duplicate AAAA collapses to its best (0.30) row
    assert list(out["sequence"]) == ["BBBB", "AAAA"]
    assert list(out["native_value"]) == [0.5, 0.3]
    assert (out["native_metric"] == "boltz_pae_ipsae_min").all()
    assert (out["tool"] == "rfd3").all()
    # no FASTA → design_id falls back to run_id
    assert list(out["design_id"]) == ["h2", "h1"]


def test_build_selection_top_n():
    out = build_selection(_df(), "boltz_pae_ipsae_min", None, tool="rfd3", top=1)
    assert len(out) == 1 and out["sequence"].iloc[0] == "BBBB"


def test_build_selection_uses_fasta_metadata():
    meta = {
        "AAAA": {"binder_id": "rfd3_design_7", "source_tool": "rfd3"},
        "BBBB": {"binder_id": "rfd3_design_2", "source_tool": "rfd3"},
    }
    out = build_selection(_df(), "boltz_pae_ipsae_min", meta, tool="ignored", top=None)
    assert list(out["design_id"]) == ["rfd3_design_2", "rfd3_design_7"]
    assert list(out["tool"]) == ["rfd3", "rfd3"]


def test_build_selection_iptm_metric():
    out = build_selection(_df(), "boltz_pae_iptm", None, tool="rfd3", top=None)
    assert list(out["sequence"]) == ["BBBB", "AAAA"]
    assert list(out["native_value"]) == [0.8, 0.6]


def test_fasta_metadata_parses_source_tag(tmp_path):
    fa = tmp_path / "x.fasta"
    fa.write_text(">rfd3_d1  source=rfd3  length=53\nAAAA\n>rfd3_d2  source=rfd3\nBBBB\n")
    meta = _fasta_metadata(str(fa))
    assert meta["AAAA"] == {"binder_id": "rfd3_d1", "source_tool": "rfd3"}
    assert meta["BBBB"]["binder_id"] == "rfd3_d2"


# --------------------------------------------------------------------------
# Restricting the selection to one tool.
#
# prefilter's docstring recipe assumes an RFD3-ONLY FASTA. In the real pipeline
# the Boltz-2 results cover every tool's designs, and `report --tool-csv
# rfd3=<file>` takes the WHOLE file as RFD3's list -- it does not filter on the
# `tool` column. So handing it an unfiltered selection would put every tool's
# designs into RFD3's native block, ranked by Boltz-2, under RFD3's name.
# --------------------------------------------------------------------------


def _mixed_df():
    return pd.DataFrame(
        {
            "run_id": ["r1", "m1", "r2"],
            "sequence": ["AAAA", "CCCC", "BBBB"],
            "binder_length": [40, 50, 60],
            "boltz_pae_ipsae_min": [0.30, 0.90, 0.50],
        }
    )


_MIXED_META = {
    "AAAA": {"binder_id": "rfd3_a", "source_tool": "rfd3"},
    "CCCC": {"binder_id": "mosaic_c", "source_tool": "mosaic"},
    "BBBB": {"binder_id": "rfd3_b", "source_tool": "rfd3"},
}


def test_only_tool_keeps_just_that_tools_designs():
    out = build_selection(_mixed_df(), "boltz_pae_ipsae_min", _MIXED_META, tool="rfd3", top=None, only_tool="rfd3")
    assert list(out["sequence"]) == ["BBBB", "AAAA"], "the mosaic design scores best and must still be excluded"
    assert (out["tool"] == "rfd3").all()


def test_without_only_tool_everything_is_kept():
    """Unchanged default — the flag is opt-in, not a behaviour change."""
    out = build_selection(_mixed_df(), "boltz_pae_ipsae_min", _MIXED_META, tool="rfd3", top=None)
    assert list(out["sequence"]) == ["CCCC", "BBBB", "AAAA"]


def test_only_tool_applies_before_top_n():
    """Otherwise --top would be spent on designs that are about to be dropped."""
    out = build_selection(_mixed_df(), "boltz_pae_ipsae_min", _MIXED_META, tool="rfd3", top=1, only_tool="rfd3")
    assert list(out["sequence"]) == ["BBBB"], "top-1 of RFD3, not top-1 of the pool then filtered"


def test_only_tool_with_no_matching_designs_is_empty_not_everything():
    out = build_selection(_mixed_df(), "boltz_pae_ipsae_min", _MIXED_META, tool="x", top=None, only_tool="bindcraft")
    assert len(out) == 0
