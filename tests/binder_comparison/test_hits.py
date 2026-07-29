"""Tests for the wet-lab Selected Hits builder (comparison/hits.py).

The selection is two numbers — top-N per tool, then top-M NEW off our ranking —
plus one piece of bookkeeping that is easy to get wrong: a refold pick already
covered by a per-tool block is still listed (so the reader can see it was
accounted for) but must NOT consume one of the M slots.
"""

import pytest

pd = pytest.importorskip("pandas")
from binder_comparison.comparison.hits import (  # noqa: E402
    _tool_key,
    code_slug,
    hits_summary,
    select_hits,
)


def _candidates():
    """Two tools; the refold block's top pick is already in a native block."""
    native = [
        ("Native top-20", "BindCraft", 1, 10, "AAAA"),
        ("Native top-20", "BindCraft", 2, 40, "BBBB"),
        ("Native top-20", "BindCraft", 3, 50, "CCCC"),
        ("Protein Hunter", "Protein Hunter", 1, 20, "PPPP"),
        ("Native top-20", "Protein Hunter", 2, 60, "QQQQ"),
    ]
    refold = [
        ("Refold top-50", "BindCraft", 1, 10, "AAAA"),  # already covered by native #1
        ("Refold top-50", "Protein Hunter", 1, 20, "PPPP"),  # already covered
        ("Refold top-50", "BindCraft", 9, 30, "ZZZZ"),  # new
        ("Refold top-50", "BindCraft", 3, 50, "CCCC"),  # already covered
        ("Refold top-50", "Protein Hunter", 8, 70, "YYYY"),  # new
    ]
    rows = [
        {
            "Set": s if s.startswith(("Native", "Refold")) else "Native top-20",
            "Method": m,
            "Ranking native": nr,
            "Ranking refolded": rr,
            "Mean_ipTM": 0.9,
            "Mean_ipSAE_min": 0.8,
            "Solubility SoluProt": 0.7,
            "Length": len(seq),
            "Primary sequence": seq,
        }
        for s, m, nr, rr, seq in native + refold
    ]
    return pd.DataFrame(rows)


def test_section_a_is_top_n_per_tool_in_the_tools_own_order():
    h = select_hits(_candidates(), target="T", per_tool=2, refolded=1)
    a = h[h.Section == "per-tool"]
    assert list(a["Primary sequence"]) == ["AAAA", "BBBB", "PPPP", "QQQQ"]  # 2 per tool
    assert list(a["Ranking native"]) == [1, 2, 1, 2]  # the tool's own order


def test_already_covered_refold_picks_are_listed_but_do_not_consume_a_slot():
    # asking for 2 new must walk past AAAA and PPPP (both already in section A)
    h = select_hits(_candidates(), target="T", per_tool=2, refolded=2)
    b = h[h.Section != "per-tool"]
    assert list(b.Section) == [
        "already covered above",  # AAAA, refold rank 10 — native #1, in section A
        "already covered above",  # PPPP, rank 20 — native #1, in section A
        "refolded",  # ZZZZ, rank 30 -> new #1
        "refolded",  # CCCC, rank 50 -> new #2 (BindCraft native #3, so per_tool=2 excluded it)
    ]
    s = hits_summary(h)
    assert s["refolded_new"] == 2
    assert s["already_covered"] == 2
    # a design is only counted once toward what the lab actually orders
    assert s["distinct_designs_to_test"] == 6  # 4 per-tool + ZZZZ + CCCC


def test_section_b_stops_as_soon_as_the_target_is_met():
    h = select_hits(_candidates(), target="T", per_tool=2, refolded=1)
    b = h[h.Section != "per-tool"]
    assert list(b.Section)[-1] == "refolded"  # never trails already-covered rows
    assert hits_summary(h)["refolded_new"] == 1


def test_extra_slots_apply_to_the_named_tool_only():
    h = select_hits(_candidates(), target="T", per_tool=2, refolded=1, extra={"bindcraft": 1})
    a = h[h.Section == "per-tool"]
    assert (a.Method == "BindCraft").sum() == 3  # 2 + 1
    assert (a.Method == "Protein Hunter").sum() == 2


def test_extra_accepts_the_display_name_too():
    """`RFDiffusion3` does not contain its key `rfd3`, so a prefix match is not enough."""
    assert _tool_key("RFDiffusion3") == "rfd3"
    assert _tool_key("rfd3") == "rfd3"
    assert _tool_key("Protein Hunter") == "protein_hunter"
    assert _tool_key("Proteina-Complexa") == "proteina_complexa"
    assert _tool_key("BoltzGen (protein)") == "boltzgen_protein"


def test_codes_always_split_into_target_tool_number():
    """The hand-built sheets produced `CALCAProtein Hunter-03` and a bare `Proteina`
    prefix, because the tool names contain a space and a hyphen."""
    h = select_hits(_candidates(), target="CALCA", per_tool=2, refolded=1)
    for code in h["Code"]:
        parts = str(code).split("-")
        assert len(parts) == 3, code
        assert parts[0] == "CALCA"
        assert " " not in code
    assert code_slug("Protein Hunter") == "ProteinHunter"
    assert code_slug("Proteina-Complexa") == "ProteinaComplexa"
    # section B is coded against the pipeline, not one tool
    assert any(c.startswith("CALCA-BinderScout-") for c in h["Code"])


def test_numbering_is_dense_and_per_tool():
    h = select_hits(_candidates(), target="T", per_tool=2, refolded=2)
    assert list(h["No"]) == list(range(1, len(h) + 1))
    bc = [c for c in h["Code"] if "BindCraft" in c]
    assert bc[:2] == ["T-BindCraft-01", "T-BindCraft-02"]
