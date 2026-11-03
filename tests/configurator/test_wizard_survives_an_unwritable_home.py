"""The wizard must reach its first prompt when HOME cannot be written.

`wizard()` called `install_shortcut()` before anything else. That function writes
`~/.local/bin/binderscout-config` with an unguarded `mkdir` and `write_text`, so
on a box whose HOME is read-only (a container, a locked-down login node, a CI
sandbox) the interactive path died with a PermissionError traceback before its
first prompt. The `--config` replay path never calls it, which is why nothing
caught it: only the interactive wizard was affected.

The shortcut is a convenience, so failing to write it must degrade silently.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATOR = ROOT / "configurator" / "configurator.py"

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")


def _run_wizard_with_home(home: Path):
    return subprocess.run(
        [sys.executable, str(CONFIGURATOR)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=home,
        env={"PATH": "/usr/bin:/bin", "HOME": str(home), "NO_COLOR": "1"},
    )


def test_a_read_only_home_does_not_stop_the_wizard_before_its_first_prompt(tmp_path):
    home = tmp_path / "ro_home"
    home.mkdir()
    home.chmod(0o555)
    try:
        proc = _run_wizard_with_home(home)
    finally:
        home.chmod(0o755)
    combined = proc.stdout + proc.stderr
    assert "PermissionError" not in combined, combined[-800:]
    assert "Traceback (most recent call last)" not in combined, combined[-800:]
    # It got as far as the banner and the first prompt, then hit the closed stdin.
    assert "BinderScout Configurator" in proc.stdout, proc.stdout[-800:]
    assert "No more input" in proc.stdout, proc.stdout[-800:]
    assert not (home / ".local").exists(), "nothing should have been written to a read-only HOME"


def test_a_writable_home_still_gets_the_shortcut(tmp_path):
    """The guard must not turn the shortcut into dead code."""
    proc = _run_wizard_with_home(tmp_path)
    shortcut = tmp_path / ".local" / "bin" / "binderscout-config"
    assert shortcut.is_file(), (proc.stdout + proc.stderr)[-800:]
    assert str(CONFIGURATOR) in shortcut.read_text()
