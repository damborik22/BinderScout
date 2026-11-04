"""`settings.json` recorded `binderscout_git_branch: HEAD` whenever the checkout was a detached tag.

`git rev-parse --abbrev-ref HEAD` prints the literal word HEAD there, which reads like a branch name
and says nothing. Every generated script (and each shipped template) now asks for the branch, falls
back to the exact tag, and says "detached" when it is neither.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "configurator" / "configurator.py", *sorted((ROOT / "binderscout_examples").glob("*.template"))]
LINE = re.compile(r"^GIT_BRANCH=\$\(.*\)$", re.M)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "ck"
    (r / "a" / "b").mkdir(parents=True)
    _git(r, "init", "-q", "-b", "work")
    (r / "f").write_text("x")
    _git(r, "add", "f")
    _git(r, "commit", "-q", "-m", "c")
    _git(r, "tag", "v9.9.9")
    return r


def _branch(line: str, repo: Path) -> str:
    out = subprocess.run(
        ["bash", "-c", f'set -euo pipefail\n{line}\necho -n "$GIT_BRANCH"'],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
            "BINDERSCOUT_DIR": str(repo),
            "BMDIR": str(repo),
            "RUN_DIR": str(repo / "a" / "b"),
        },
        check=True,
    )
    return out.stdout


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.name)
def test_every_source_has_the_line(src):
    assert LINE.search(src.read_text()), f"{src.name} no longer sets GIT_BRANCH"


@pytest.mark.parametrize("src", SOURCES, ids=lambda p: p.name)
def test_branch_tag_and_unnamed_head(src, repo):
    line = LINE.search(src.read_text()).group(0)
    assert _branch(line, repo) == "work"
    _git(repo, "checkout", "-q", "--detach", "v9.9.9")
    assert _branch(line, repo) == "v9.9.9", "a detached tag must be recorded by name, not as HEAD"
    (repo / "f").write_text("y")
    _git(repo, "commit", "-q", "-am", "d")
    assert _branch(line, repo) == "detached"
    (repo / "a" / "b").rename(repo / "a" / "c")
    assert _branch(line, repo) in {"detached", "unknown"}, "a bad directory must not kill a set -e script"
