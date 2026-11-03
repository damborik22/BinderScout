"""docker-entrypoint.sh's fallback HOME is private to the run, not a fixed shared /tmp path.

When neither $HOME nor /home/binderscout-user can be created (a container run with a host UID),
the entrypoint fell back to `/tmp/binderscout-home` -- the same directory for every user and every
container sharing that /tmp, which anyone can pre-create or symlink. It is `mktemp -d` now.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import REPO  # noqa: E402

ENTRYPOINT = REPO / "docker-entrypoint.sh"


def _home_chosen(tmp_path: Path) -> str:
    r = subprocess.run(
        ["bash", str(ENTRYPOINT), "sh", "-c", 'printf %s "$HOME"'],
        capture_output=True,
        text=True,
        env={"HOME": "/", "PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path)},
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.skipif(
    os.geteuid() == 0 or Path("/home/binderscout-user").exists(), reason="the primary home would be creatable"
)
def test_the_fallback_home_is_a_fresh_private_directory(tmp_path):
    first, second = _home_chosen(tmp_path), _home_chosen(tmp_path)
    assert first != second, "two runs share one fallback HOME"
    assert first != "/tmp/binderscout-home"
    assert Path(first).is_dir() and Path(first).parent == tmp_path, "the fallback is not a mktemp directory"
    assert oct(Path(first).stat().st_mode & 0o777) == "0o700"


def test_no_fixed_tmp_path_remains_in_the_entrypoint():
    assert "/tmp/binderscout" not in ENTRYPOINT.read_text()
