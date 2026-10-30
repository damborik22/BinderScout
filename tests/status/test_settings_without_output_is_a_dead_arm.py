"""A tool directory holding settings.json and nothing else means it DIED.

Every run script writes settings.json BEFORE the design step (the per-run
reproducibility convention in CLAUDE.md). So settings-without-designs is not
"queued" -- it is a tool that started and exited in seconds. That is exactly the
EnvironmentNameNotFound and argument-discarding-wrapper class in
CLAUDE.local.md 6.2/6.3, which cost a campaign round its PXDesign arm and looked
identical to a fast crash in sacct.

Conflating it with "queued" is the expensive mistake: a queued arm is left alone,
a dead one is relaunched.
"""

import json

from status.collect import classify, probe_started
from status.schema import DEAD, QUEUED


def test_settings_present_but_no_designs_is_dead(tmp_path):
    tool_dir = tmp_path / "pxdesign"
    tool_dir.mkdir()
    (tool_dir / "settings.json").write_text(json.dumps({"tool": "pxdesign"}))

    assert probe_started(tool_dir) is True
    assert classify(done=0, total=50, proc_alive=False, started=True) == DEAD


def test_a_bare_directory_is_only_queued(tmp_path):
    tool_dir = tmp_path / "pxdesign"
    tool_dir.mkdir()

    assert probe_started(tool_dir) is False
    assert classify(done=0, total=50, proc_alive=False, started=False) == QUEUED


def test_a_missing_directory_is_queued(tmp_path):
    assert probe_started(tmp_path / "never_ran") is False
