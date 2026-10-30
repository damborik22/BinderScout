"""The box you are standing on is a campaign box too.

Found on the live fleet: with --hosts naming the four remote boxes, the local box
was excluded to avoid double-counting -- and the local box held a FINISHED RFD3
arm (50/50) plus a BindCraft arm that had just been launched. Both vanished from
the view, and the finished arm re-rendered as `queued` from another box's empty
directory. Hiding completed work is the worst failure this renderer can have.
"""

from status.cli import build_document


def test_the_local_box_is_probed_alongside_the_remote_ones(monkeypatch):
    monkeypatch.setattr(
        "status.cli.probe_hosts", lambda hosts, t: {h: {"reachable": False, "error": "x"} for h in hosts}
    )
    monkeypatch.setattr("status.cli.collect_local", lambda host="local": {"reachable": True, "host": host, "runs": {}})

    doc = build_document(["bm1", "bm2"], timeout_s=5)
    assert "local" in doc["hosts"], "the box we are standing on must appear"
    assert doc["hosts"]["local"]["reachable"] is True
    assert set(doc["hosts"]) == {"local", "bm1", "bm2"}


def test_a_local_only_run_still_works(monkeypatch):
    monkeypatch.setattr("status.cli.collect_local", lambda host="local": {"reachable": True, "host": host, "runs": {}})
    doc = build_document([], timeout_s=5)
    assert set(doc["hosts"]) == {"local"}
