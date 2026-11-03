"""A page served from a file must not claim to be fresh after its generator dies.

The artifact page is pushed by an agent, so its freshness bar can be computed at
push time -- the push IS the moment. A file served by a static web server is the
opposite: it keeps being served, unchanged, for as long as the browser keeps
asking, and a band baked in at render time reads "fresh" forever. The failure it
would hide is the one the page exists to catch: the generator stopped and the
fleet's real state is now unknown.

So the band is recomputed in the browser from the document's own stamp. These
tests pin that: the stamp is in the page, the recompute runs, and no literal
band is written into the markup for the browser to inherit.
"""

import re

from status.render_html import render

_DOC = {
    "generated_at": "2026-10-31T07:10:56Z",
    "campaigns": {"r1": "A campaign"},
    "hosts": {
        "host-a": {
            "reachable": True,
            "runs": {
                "r1": {
                    "tools": {
                        "rfd3": {
                            "state": "running",
                            "done": 10,
                            "total": 50,
                            "started": True,
                            "warnings": [],
                            "eta_s": 3600,
                            "output_age_s": 120,
                            "proc": {"alive": True, "gpu_mem_mib": 8192},
                        }
                    }
                }
            },
        }
    },
}


def test_the_stamp_the_browser_reads_is_on_the_page():
    page = render(_DOC)
    assert '<span class="stamp">2026-10-31T07:10:56Z</span>' in page


def test_the_band_is_recomputed_from_the_stamp_not_baked_in():
    page = render(_DOC)
    # The script must read the stamp and set the band from it.
    assert "Date.parse" in page
    assert "dataset.age" in page
    # And it must keep doing so while the tab stays open: a page left up
    # overnight is exactly when a dead generator matters.
    assert "setInterval" in page


def test_a_long_dead_document_is_not_rendered_as_fresh():
    """Server-side, an unknown age is stale -- never fresh.

    `render` is called with no age by the CLI, so whatever it writes into the
    markup is what a browser with JavaScript disabled will show. That default
    must err toward "do not trust this", not toward "all good".
    """
    page = render(_DOC)
    band = re.search(r'class="age" data-age="([a-z]+)"', page)
    assert band, "the freshness element must carry a band for the no-script case"
    assert band.group(1) == "stale"

    # And an explicitly fresh age still renders fresh, so the parameter works.
    assert 'data-age="fresh"' in render(_DOC, age_s=10)
