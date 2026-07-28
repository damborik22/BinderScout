"""The per-tool 'Top Designs per Tool' tables must show the TOOL's own ranking.

Regression for `a86839c` ("per-tool tables use the slim decision view too"), which
swapped those tables to the evaluator's ranking but left the section header count
and BOTH 3D viewers reading the native ordering. The result: the table and the
structures rendered directly beneath it were disjoint sets of designs.

The fix keeps the slim look but restores the native row order, so:
  * the table leads with `native_rank` (the tool's own order) and carries our `rank`
    alongside for comparison, and
  * the table, the header count and the viewers all describe the same designs.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
import re

from binder_comparison.visualization.top30_slim import slim_table_html


def _cells(html: str) -> list[list[str]]:
    rows = re.findall(r"<tr>(.*?)</tr>", html, flags=re.S)[1:]  # skip header row
    return [[re.sub("<.*?>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.S)] for r in rows]


def _headers(html: str) -> list[str]:
    return [re.sub("<.*?>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", html, flags=re.S)]


def _native_frame():
    """A tool whose native order is the exact reverse of the evaluator's ranking —
    so any accidental re-sort is immediately visible."""
    return pd.DataFrame(
        {
            "native_rank": [1, 2, 3, 4],
            "rank": [4, 3, 2, 1],
            "binder_id": ["d1", "d2", "d3", "d4"],
            "source_tool": ["mytool"] * 4,
            "consensus_iptm_mean": [0.64, 0.73, 0.82, 0.91],
        }
    )


def test_preserve_order_keeps_the_tools_own_ranking():
    """The whole point of the per-tool section: the tool's order, not ours."""
    html = slim_table_html(_native_frame(), top_n=4, table_id="t", preserve_order=True)
    assert [r[0] for r in _cells(html)] == ["1", "2", "3", "4"]  # native_rank ascending
    assert [r[2] for r in _cells(html)] == ["d1", "d2", "d3", "d4"]


def test_without_preserve_order_the_evaluator_ranking_wins():
    """The main Top-30 path is unchanged — it still sorts by our rank."""
    html = slim_table_html(_native_frame(), top_n=4, table_id="t")
    assert [r[2] for r in _cells(html)] == ["d4", "d3", "d2", "d1"]


def test_native_rank_column_leads_when_present():
    html = slim_table_html(_native_frame(), top_n=4, table_id="t", preserve_order=True)
    heads = _headers(html)
    assert heads[0] == "Native rank"
    assert "Rank" in heads  # our ranking is shown alongside, not replaced
    assert heads.index("Native rank") < heads.index("Rank")


def test_native_rank_column_absent_from_the_main_top30():
    """`native_rank` only exists in per-tool frames; the overall table must not grow
    an empty column because of it."""
    df = _native_frame().drop(columns=["native_rank"])
    assert "Native rank" not in _headers(slim_table_html(df, top_n=4, table_id="t"))


def test_table_and_viewer_show_the_same_designs():
    """The a86839c defect itself: the table was our-ranked while both 3D viewers
    walked the native order, so the structures did not match the rows above them."""
    native = _native_frame()
    top_n = 2
    table_ids = [r[2] for r in _cells(slim_table_html(native, top_n, "t", preserve_order=True))]
    # Both viewer paths take the first `top_n` of the native frame / native CSV.
    viewer_ids = native["binder_id"].head(top_n).tolist()
    assert table_ids == viewer_ids


def test_preserve_order_still_truncates_to_top_n():
    html = slim_table_html(_native_frame(), top_n=2, table_id="t", preserve_order=True)
    assert len(_cells(html)) == 2
