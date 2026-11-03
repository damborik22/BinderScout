"""`bindcraft` is a prefix of `bindcraft2`, and a substring match conflates them.

Found on the live fleet: an aarch64 box was running a BindCraft 2 campaign, and the monitor
reported BindCraft -- a tool not installed for that arm -- as `running` on that box,
because `BindCraft2/.venv/bin/bindcraft` contains the string `bindcraft`.

The consequence is the same shape as the self-matching trap: a dead or absent arm
reported as healthy. Matching is therefore on a word boundary.
"""

from status.liveness import tool_alive


def test_a_bindcraft2_process_is_not_reported_as_bindcraft(tmp_path):
    run_dir = tmp_path / "runs" / "camp"
    table = {4242: f"python {run_dir}/bindcraft2/.venv/bin/bindcraft --settings {run_dir}/bindcraft2/c.json"}
    assert tool_alive("bindcraft", run_dir, table=table, gpu_mem={})["alive"] is False
    assert tool_alive("bindcraft2", run_dir, table=table, gpu_mem={})["alive"] is True


def test_a_real_bindcraft_process_is_still_found(tmp_path):
    run_dir = tmp_path / "runs" / "camp"
    table = {777: f"python -u ./bindcraft.py --settings {run_dir}/bindcraft/target_settings.json"}
    assert tool_alive("bindcraft", run_dir, table=table, gpu_mem={})["alive"] is True
    assert tool_alive("bindcraft2", run_dir, table=table, gpu_mem={})["alive"] is False


def test_rfd3_and_rfd4_are_likewise_distinct(tmp_path):
    run_dir = tmp_path / "runs" / "camp"
    table = {9: f"rfd4-generate out={run_dir}/rfd4/generate"}
    assert tool_alive("rfd3", run_dir, table=table, gpu_mem={})["alive"] is False
    assert tool_alive("rfd4", run_dir, table=table, gpu_mem={})["alive"] is True
