"""End-of-input at a wizard prompt must not read as "the software is broken".

Any non-interactive stdin reaches `ask()`'s `input()` as EOFError: a piped answer
file, a redirect, `ssh host 'binderscout configure'` inside a script, or a
fat-fingered Ctrl-D. The exit code was already a correct 1, so only the
presentation was wrong -- but a Python traceback with a file path and a line
number is what a non-programmer reads as a crash, where Ctrl-C in the same place
printed a friendly "Interrupted.".

EOFError then shared that "Interrupted." message, which told this user nothing:
they did not interrupt anything, and the one thing they need to know is that this
path has a non-interactive equivalent (`--config`).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATOR = ROOT / "configurator" / "configurator.py"


def _run_with_closed_stdin(tmp_path):
    return subprocess.run(
        [sys.executable, str(CONFIGURATOR)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "NO_COLOR": "1"},
    )


def test_closed_stdin_exits_1_without_a_traceback(tmp_path):
    proc = _run_with_closed_stdin(tmp_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, f"expected a clean exit 1, got {proc.returncode}"
    assert "Traceback (most recent call last)" not in combined, combined[-800:]
    assert "EOFError" not in combined, combined[-800:]


def test_the_message_names_the_non_interactive_path(tmp_path):
    """The user who hits this is precisely the user who wants --config."""
    out = _run_with_closed_stdin(tmp_path).stdout
    assert "No more input" in out
    assert "interactive terminal" in out
    assert "configure --config" in out, "point them at the path that works unattended"


def test_it_is_not_reported_as_an_interruption(tmp_path):
    """Shared with Ctrl-C, "Interrupted." was wrong: nothing was interrupted."""
    out = _run_with_closed_stdin(tmp_path).stdout
    assert "Interrupted." not in out
