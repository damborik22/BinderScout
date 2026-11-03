"""`status --json` must emit nothing but JSON.

The dispatcher prints a `BinderScout -> status` banner before exec'ing, which is
right for the human-readable view and fatal for the machine-readable one: the
first attempt to capture the document for the pushed page produced a file
starting with the banner's ANSI escape, and `json.load` failed at char 0.

The whole point of --json is that something else consumes it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_the_json_arm_prints_no_banner(tmp_path):
    env = {**os.environ, "BINDERSCOUT_FLEET": "", "HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, str(REPO / "binderscout.py"), "status", "--local", "--json"],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    doc = json.loads(proc.stdout)  # must parse with no stripping whatsoever
    assert doc["schema"] >= 1
    assert "hosts" in doc


def test_the_human_arm_still_announces_itself(tmp_path):
    env = {**os.environ, "BINDERSCOUT_FLEET": "", "HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, str(REPO / "binderscout.py"), "status", "--local"],
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
        cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    assert "status" in proc.stdout
