"""Every box carries the run directory, but each arm runs on exactly one of them.

Found running the monitor against the live fleet: a pMHC run directory exists on
every box, so a per-host rendering showed ten `queued` rows per box for arms that
were finished or running elsewhere. That buries the two lines that matter.

The rule: an arm with evidence somewhere (started, has output, or has a live
process) is shown only where that evidence is. An arm with evidence NOWHERE is
genuinely not started yet, and is shown once.
"""

from status.render_term import render


def _doc(hosts):
    return {"generated_at": "now", "hosts": hosts}


def _arm(state, done=0, total=50, started=False):
    return {
        "state": state,
        "done": done,
        "total": total,
        "started": started,
        "warnings": [],
        "eta_s": None,
        "proc": {"alive": state == "running"},
    }


def _host(tools):
    return {"reachable": True, "runs": {"camp": {"n_designs": 50, "tools": tools}}}


def test_the_box_without_the_arm_is_not_listed_for_it():
    out = render(
        _doc(
            {
                "host-a": _host({"rfd3": _arm("done", done=50, started=True)}),
                "host-c": _host({"rfd3": _arm("queued")}),
            }
        )
    )
    rfd3_lines = [ln for ln in out.splitlines() if "rfd3" in ln]
    assert len(rfd3_lines) == 1, rfd3_lines
    assert "host-a" in rfd3_lines[0]
    assert "host-c" not in rfd3_lines[0]


def test_a_running_arm_wins_over_an_empty_directory_elsewhere():
    out = render(
        _doc(
            {
                "host-b": _host({"boltzgen": _arm("running", done=7, started=True)}),
                "host-c": _host({"boltzgen": _arm("queued")}),
            }
        )
    )
    lines = [ln for ln in out.splitlines() if "boltzgen" in ln]
    assert len(lines) == 1 and "host-b" in lines[0] and "running" in lines[0]


def test_an_arm_started_nowhere_is_still_shown_once():
    out = render(
        _doc(
            {
                "host-a": _host({"bindcraft": _arm("queued")}),
                "host-c": _host({"bindcraft": _arm("queued")}),
            }
        )
    )
    lines = [ln for ln in out.splitlines() if "bindcraft" in ln]
    assert len(lines) == 1, lines
    assert "queued" in lines[0]


def test_a_dead_arm_is_never_hidden_by_an_empty_directory():
    # The expensive case: hiding a crash behind another box's empty dir.
    out = render(
        _doc(
            {
                "host-c": _host({"protein_hunter": _arm("dead", done=1, started=True)}),
                "host-a": _host({"protein_hunter": _arm("queued")}),
            }
        )
    )
    lines = [ln for ln in out.splitlines() if "protein_hunter" in ln]
    assert len(lines) == 1 and "host-c" in lines[0] and "DEAD" in lines[0]
