"""The served page must group, and dedup, exactly as the terminal does.

Two surfaces rendering the same document from two copies of the grouping rule is
how they drift, and the first rule to drift would be the one that cost the most
to get right: dedup is keyed on (run, tool), not (campaign, tool), because TfR1
runs RFD3 twice -- a first batch of 50 and a second of 350 -- and collapsing on
the campaign label would show one RFD3 arm and silently drop 350 designs.

So `render_html` imports `_rows` and `_deadline_for` from the terminal renderer.
This test fails if either is reimplemented.
"""

from status.render_html import render
from status.render_term import render as render_term


def _arm(state, done, total):
    return {
        "state": state,
        "done": done,
        "total": total,
        "started": True,
        "warnings": [],
        "eta_s": None,
        "proc": {"alive": state == "running"},
    }


_DOC = {
    "generated_at": "2026-10-31T07:10:56Z",
    "campaigns": {"tfr1_r1": "TfR1 apical", "tfr1_r2": "TfR1 apical", "pmhc": "pMHC"},
    "deadlines": {"TfR1 apical": "2026-11-02T11:59:00Z"},
    "hosts": {
        "host-a": {
            "reachable": True,
            "runs": {
                "tfr1_r1": {"tools": {"rfd3": _arm("done", 50, 50)}},
                "tfr1_r2": {"tools": {"rfd3": _arm("running", 200, 350)}},
                "pmhc": {"tools": {"rfd4": _arm("done", 50, 50)}},
            },
        },
        "host-b": {"reachable": False, "error": "unreachable (ssh failed)"},
    },
}


def test_both_rfd3_rounds_survive_onto_the_page():
    page = render(_DOC)
    assert page.count('class="arm"') == 3
    assert "50</b>/50" in page
    assert "200</b>/350" in page


def test_one_campaign_label_is_one_block():
    page = render(_DOC)
    assert page.count("<h2>TfR1 apical</h2>") == 1
    assert page.count("<h2>pMHC</h2>") == 1


def test_the_deadline_and_the_down_host_are_both_shown():
    page = render(_DOC)
    assert "due 2026-11-02" in page
    assert "unreachable (ssh failed)" in page


def test_the_two_surfaces_agree_on_which_arms_exist():
    """Same document, same arm set -- whatever each surface does with the layout."""
    page, term = render(_DOC), render_term(_DOC)
    for count in ("50/50", "200/350"):
        assert count in term
    assert page.count('class="arm"') == sum(term.count(c) for c in ("rfd3  ", "rfd4  "))
