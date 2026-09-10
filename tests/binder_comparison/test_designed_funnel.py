"""The generation funnel banner: generated → passed the tool's own filter → refold pool.

The banner used to state only "designed in total N → M in the ranked pool". On
CALCA that is 37,863 → 350, a 1-in-108 drop with no named intermediate step, so
the reader cannot tell how much of the reduction was each tool's own filtering
and how much was our top-N cut. These tests pin the middle rung.
"""

import pandas as pd
import pytest
from binder_comparison.visualization.report import _designed_funnel_html


@pytest.fixture
def pool():
    # 4 designs in the refold pool, two tools.
    return pd.DataFrame({"source_tool": ["bindcraft", "bindcraft", "boltzgen", "boltzgen"]})


def test_no_meta_renders_nothing(pool):
    assert _designed_funnel_html(pool, {}) == ""
    assert _designed_funnel_html(pool, None) == ""


def test_generated_total_is_summed_across_tools(pool):
    html = _designed_funnel_html(pool, {"bindcraft": {"total": "12270"}, "boltzgen": {"total": "9873"}})
    assert "22,143" in html  # 12270 + 9873
    assert "12,270" in html and "9,873" in html


def test_filtered_rung_is_summed_and_labelled(pool):
    html = _designed_funnel_html(
        pool,
        {
            "bindcraft": {"total": "12270", "filtered": "568"},
            "boltzgen": {"total": "9873", "filtered": "4561"},
        },
    )
    assert "5,129" in html  # 568 + 4561 — the middle rung
    assert "passed the tool" in html.lower()


def test_pool_size_is_the_last_rung(pool):
    html = _designed_funnel_html(pool, {"bindcraft": {"total": "10"}, "boltzgen": {"total": "10"}})
    # 4 rows in the pool
    assert ">4<" in html or "4</b>" in html


def test_tool_without_filter_is_marked_not_dropped(pool):
    """A tool that ranks but does not filter must still appear, with the middle
    rung shown as absent — not silently omitted, and not counted as zero."""
    html = _designed_funnel_html(
        pool, {"bindcraft": {"total": "12270", "filtered": "568"}, "boltzgen": {"total": "9873"}}
    )
    assert "BoltzGen" in html
    assert "568" in html
    # the summed middle rung covers only the tool that declared one
    assert "5,129" not in html


def test_filtered_without_total_is_ignored(pool):
    """`filtered` alone is meaningless without its denominator."""
    assert _designed_funnel_html(pool, {"bindcraft": {"filtered": "568"}}) == ""


def test_non_numeric_meta_is_skipped(pool):
    html = _designed_funnel_html(pool, {"bindcraft": {"total": "lots"}, "boltzgen": {"total": "9873"}})
    assert "9,873" in html
    assert "lots" not in html


# --- last rung: refolded designs vs collapsed backbones -----------------------
#
# The frame the HTML renderer gets is representatives-only (MPNN/cycle siblings
# collapsed to one row per backbone), so on CALCA it holds 334 rows while 350
# designs were actually refolded. Reporting 334 as "refolded" understates the
# work by every sibling that was folded; reporting 350 as the row count would
# not match the table below it. The banner states both.


def test_refold_count_comes_from_full_df_when_given(pool):
    full = pd.DataFrame({"source_tool": ["bindcraft"] * 6 + ["boltzgen"] * 2})
    html = _designed_funnel_html(pool, {"bindcraft": {"total": "12270"}, "boltzgen": {"total": "9873"}}, full_df=full)
    assert "8</b> designs refolded" in html or "<b>8</b>" in html
    # and the collapse is named, not silently dropped
    assert "4" in html and "backbone" in html.lower()


def test_no_collapse_note_when_counts_match(pool):
    html = _designed_funnel_html(pool, {"bindcraft": {"total": "10"}, "boltzgen": {"total": "10"}}, full_df=pool)
    assert "backbone" not in html.lower()


def test_full_df_absent_falls_back_to_pool(pool):
    html = _designed_funnel_html(pool, {"bindcraft": {"total": "10"}, "boltzgen": {"total": "10"}})
    assert "backbone" not in html.lower()
