"""The golden synthetic pool, re-slotted from AF3 to Protenix, ranks exactly as the AF3 pool does.

The ranking is a function of the three engines' ``*_pae_iptm`` columns alone; which engine holds the
second slot must not change it. This pins that end to end through the real report CLI, with the order
as a literal taken from the pre-Part-2 tree (the same list ``test_report_second_engine`` pins for the
AF3 default), so a change to the registry, the merger or scoring that reorders either slot fails here.

The re-slot helper is the one ``tests/binder_comparison/test_report_second_engine.py`` uses (the PAE is
saved binder-first, as the second-engine adapters save it); it is imported, not copied.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pandas")
import synthetic_pool

from tests.binder_comparison.test_report_second_engine import _base, _reslot_to_protenix, _run

# binder_id (which carries |source_tool), ranks 1-10, taken from the pre-change AF3 run.
_PINNED_RANK_ORDER = [
    "d01_mpnn1|bindcraft",
    "d05|rfd3",
    "d02|mosaic",
    "d08|rfd3",
    "d04_c1|protein_hunter",
    "d01_mpnn2|bindcraft",
    "d03|boltzgen",
    "d04_c2|protein_hunter",
    "d07|mosaic",
    "d06|pxdesign",
]


@pytest.fixture(scope="module")
def protenix_report(tmp_path_factory):
    root = tmp_path_factory.mktemp("protenix_pinned")
    pool = synthetic_pool.build(root / "pool")
    csv_path = _reslot_to_protenix(pool, root)
    return _run(
        root / "rep",
        [*_base(pool), "--second-engine", "protenix", "--second-results", str(csv_path)],
    )


def test_rank_order_is_the_pinned_af3_order(protenix_report):
    ordered = protenix_report.sort_values("rank")
    assert list(ordered["binder_id"]) == _PINNED_RANK_ORDER
    assert list(ordered["rank"].astype(int)) == list(range(1, 11))


def test_the_panel_is_recorded_on_every_row(protenix_report):
    assert set(protenix_report["panel"]) == {"boltz+protenix+esmfold2"}
    assert set(protenix_report["second_engine"]) == {"protenix"}
    assert len(protenix_report) == 10


def test_no_af3_column_feeds_the_consensus(protenix_report):
    cols = list(protenix_report.columns)
    assert not [c for c in cols if c.startswith("af3_") or "_af3_" in c]
    assert "passes_af3_filter" not in cols
    # The pool has three engines for 8 designs, two for d06 and one for d07; an AF3 column read as a
    # fourth engine would show up as n = 4.
    n = dict(zip(protenix_report["binder_id"], protenix_report["consensus_iptm_n"].astype(int), strict=True))
    assert max(n.values()) == 3
    assert n["d06|pxdesign"] == 2
    assert n["d07|mosaic"] == 1
    assert sorted(n.values()) == [1, 2, 3, 3, 3, 3, 3, 3, 3, 3]
