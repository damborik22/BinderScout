"""A live arm was reported DEAD when HOME or the checkout was reached through a symlink.

Liveness matches process command lines against the run directory, and generated run
scripts bake the RESOLVED path while the probe built its needle from the path as it
was spelled -- so a home that is a symlink to other storage made every running arm look dead, and the
campaign's response to "dead" is to relaunch it. The second leak: ``home_relative``
only compared against the unresolved home, so a resolved checkout path was published
whole, account name included.
"""

import json

import pytest

from status import liveness
from status.collect import collect_local, home_relative
from status.schema import RUNNING


@pytest.fixture
def linked_home(tmp_path, monkeypatch):
    real = tmp_path / "data" / "acct"
    real.mkdir(parents=True)
    link = tmp_path / "home" / "acct"
    link.parent.mkdir()
    link.symlink_to(real)
    monkeypatch.setenv("HOME", str(link))
    return real, link


def test_a_process_with_the_resolved_path_is_found_through_the_symlinked_spelling(linked_home):
    real, link = linked_home
    (real / "ck" / "runs" / "r1" / "rfd3").mkdir(parents=True)
    table = {4242: f"rfd3 design out_dir={real}/ck/runs/r1/rfd3/diffusion"}

    got = liveness.tool_alive("rfd3", link / "ck" / "runs" / "r1", table=table, gpu_mem={})

    assert got["alive"] is True and got["pid"] == 4242


def test_the_unresolved_spelling_still_matches(linked_home):
    real, link = linked_home
    (real / "ck" / "runs" / "r1").mkdir(parents=True)
    table = {7: f"rfd3 design out_dir={link}/ck/runs/r1/rfd3/diffusion"}
    assert liveness.tool_alive("rfd3", link / "ck" / "runs" / "r1", table=table, gpu_mem={})["alive"] is True


def test_the_prefix_trap_survives_the_second_spelling(linked_home):
    real, link = linked_home
    (real / "ck" / "runs" / "r1").mkdir(parents=True)
    table = {9: f"bindcraft design out={real}/ck/runs/r1/bindcraft2/x"}
    assert liveness.tool_alive("bindcraft", link / "ck" / "runs" / "r1", table=table, gpu_mem={})["alive"] is False


def test_collect_local_reports_a_running_arm_through_a_symlinked_home(linked_home, monkeypatch):
    real, link = linked_home
    run = real / "ck" / "runs" / "r1"
    (run / "rfd3").mkdir(parents=True)
    (run / "config.json").write_text(json.dumps({"n_designs": 50, "tools_enabled": {"rfd3": True}}))
    (run / "rfd3" / "settings.json").write_text("{}")
    monkeypatch.setattr(liveness, "process_table", lambda: {31337: f"rfd3 design out_dir={run}/rfd3/diffusion"})
    monkeypatch.setattr(liveness, "gpu_memory_by_pid", dict)
    monkeypatch.setattr(liveness, "gpus", list)

    arm = collect_local(repo_root=link / "ck", host="h")["runs"]["r1"]["tools"]["rfd3"]

    assert arm["state"] == RUNNING, f"a live arm was classed {arm['state']}"


def test_a_resolved_checkout_path_is_still_published_home_relative(linked_home):
    real, link = linked_home
    assert home_relative(real / "ck") == "~/ck"
    assert home_relative(link / "ck") == "~/ck"
    assert home_relative(link) == "~"
