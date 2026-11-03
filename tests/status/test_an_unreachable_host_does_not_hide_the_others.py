"""One host is offline (2026-10-30). One dead host must not blank the view.

A monitor that aborts when any host times out is useless precisely when a box has
gone down -- which is when you most need to see the arms that are still alive.
"""

from status.remote import merge_host_results
from status.render_term import render


def _ok_host():
    return {
        "reachable": True,
        "runs": {
            "pmhc_g12d_t1": {
                "n_designs": 50,
                "tools": {
                    "rfd3": {
                        "state": "done",
                        "done": 50,
                        "total": 50,
                        "warnings": [],
                        "eta_s": None,
                        "proc": {"alive": False},
                    }
                },
            }
        },
    }


def test_a_timing_out_host_is_recorded_not_raised():
    merged = merge_host_results(
        {
            "host-a": _ok_host(),
            "host-e": {"reachable": False, "error": "timeout after 10s"},
        }
    )
    assert merged["hosts"]["host-e"]["reachable"] is False
    assert merged["hosts"]["host-a"]["reachable"] is True


def test_the_live_host_still_renders_beside_the_dead_one():
    merged = merge_host_results({"host-a": _ok_host(), "host-e": {"reachable": False, "error": "timeout after 10s"}})
    out = render(merged)
    assert "rfd3" in out
    assert "50/50" in out
    assert "host-e" in out
    assert "unreachable" in out.lower()


def test_every_host_down_still_renders_something():
    merged = merge_host_results({"host-e": {"reachable": False, "error": "no route"}})
    out = render(merged)
    assert "host-e" in out
    assert out.strip(), "an all-down fleet must still say so, not print nothing"
