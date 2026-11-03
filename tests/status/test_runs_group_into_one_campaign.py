"""One campaign can span several run directories, and must read as one block.

TfR1 ended up as four runs -- the first RFD3 batch, a larger second batch, RFD4,
and BindCraft 2 -- because RFD3 has no resume and each tool was sized separately.
Rendered per run directory that is four headings with one arm each, and the
question the page exists to answer ("how is the campaign doing") gets no answer
anywhere on it.

Grouping comes from a `campaigns` map in the document (run -> label), the same
mechanism as `deadlines`: the probe cannot know which runs belong together, and
guessing from a shared name prefix would silently merge unrelated runs.
"""

from status.render_term import render


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


def _doc(campaigns=None):
    return {
        "generated_at": "now",
        "campaigns": campaigns or {},
        "hosts": {
            "host-a": {
                "reachable": True,
                "runs": {
                    "tfr1_apical": {"tools": {"rfd3": _arm("running", 10, 50)}},
                    "tfr1_rfd4": {"tools": {"rfd4": _arm("done", 50, 50)}},
                },
            },
            "host-d": {
                "reachable": True,
                "runs": {"tfr1_bc2": {"tools": {"bindcraft2": _arm("running", 0, 50)}}},
            },
        },
    }


def _headings(out):
    return [ln for ln in out.splitlines() if ln and not ln.startswith(" ") and "campaign status" not in ln]


def test_mapped_runs_render_under_one_heading():
    labels = {"tfr1_apical": "TfR1", "tfr1_rfd4": "TfR1", "tfr1_bc2": "TfR1"}
    assert _headings(render(_doc(labels))) == ["TfR1"]


def test_the_grouped_total_adds_every_run_up():
    labels = {"tfr1_apical": "TfR1", "tfr1_rfd4": "TfR1", "tfr1_bc2": "TfR1"}
    out = render(_doc(labels))
    foot = next(ln for ln in out.splitlines() if "designs banked" in ln)
    assert "60 designs banked" in foot, foot
    assert "2 running" in foot, foot
    assert "3 arms" in foot, foot


def test_an_unmapped_run_still_renders_under_its_own_name():
    heads = _headings(render(_doc({"tfr1_apical": "TfR1"})))
    assert "TfR1" in heads
    assert "tfr1_bc2" in heads, heads


def test_the_same_tool_in_two_runs_of_one_campaign_shows_twice():
    doc = _doc({"a": "C", "b": "C"})
    doc["hosts"]["host-a"]["runs"] = {"a": {"tools": {"rfd3": _arm("done", 50, 50)}}}
    doc["hosts"]["host-d"]["runs"] = {"b": {"tools": {"rfd3": _arm("running", 7, 350)}}}
    lines = [ln for ln in render(doc).splitlines() if "rfd3" in ln]
    assert len(lines) == 2, lines


def test_a_queued_second_run_is_not_eaten_by_the_running_first_one():
    """The case that actually bites, and the reason dedup keys on the RUN.

    TfR1 has RFD3 round 1 running and round 2 queued behind it in the same
    campaign. Round 2 has no output, no settings and no process, so it has no
    evidence — and the evidence filter exists to drop exactly that. Keyed on the
    campaign, the two runs share one bucket, round 1's evidence wins it, and the
    350-design round 2 disappears from the view entirely: the largest piece of
    work scheduled would be invisible.
    """
    doc = _doc({"r1": "C", "r2": "C"})
    doc["hosts"]["host-a"]["runs"] = {
        "r1": {"tools": {"rfd3": _arm("running", 10, 50)}},
        "r2": {"tools": {"rfd3": dict(_arm("queued", 0, 350), started=False)}},
    }
    doc["hosts"]["host-d"]["runs"] = {}

    lines = [ln for ln in render(doc).splitlines() if "rfd3" in ln]
    assert len(lines) == 2, lines
    assert any("10/50" in ln for ln in lines), lines
    assert any("0/350" in ln for ln in lines), "the queued round-2 run vanished"
