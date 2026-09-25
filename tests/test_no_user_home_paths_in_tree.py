"""No tracked file may carry a real user's home directory.

This repo is public, and CLAUDE.md's rule is explicit: no Unix usernames, no
absolute ``/home/<user>`` paths. The rule was being broken while the file
claimed otherwise — it said "Scrubbed from tree and history 2026-09-22" while
six tracked files still carried one on 2026-09-25, because nothing checked.

``tests/test_script_hygiene.py`` catches this inside *shell scripts*. This
catches it across the whole tracked tree, which is where it actually went wrong:
a CHANGELOG entry, two investigation write-ups, a plan, a notebook and a test
fixture — none of them shell scripts.

Publishing is irreversible, so the guard is on the tree rather than on intent.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

USER_HOME_RE = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")

# Placeholders that name no real account. `<user>` cannot match the pattern at
# all; the rest are deliberate stand-ins, and each is a value no machine here uses.
ALLOWED = {
    "/home/user",
    "/home/olduser",  # test_script_hygiene fixture — must stay DETECTABLE to be a fixture
    "/home/someoneelse",  # PAE-path fixture: a path from "another machine", by construction
    "/home/binderscout-user",  # the Docker image's account, defined in Dockerfile.test
    "/home/runner",  # GitHub Actions
}

# Binaries whose build path is baked in by the compiler. Removing it needs a
# rebuild on that architecture, so it is recorded in CLAUDE.md rather than
# patched. Listed here so a NEW binary cannot join them unnoticed.
KNOWN_BINARY_OFFENDERS = {"tools/aarch64/dssp"}


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line.strip()]


def _offending_paths(text: str) -> set[str]:
    return {m for m in USER_HOME_RE.findall(text) if m not in ALLOWED}


def test_no_tracked_text_file_carries_a_user_home_path():
    offenders: dict[str, set[str]] = {}
    for rel in _tracked_files():
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binaries are covered by the test below
        found = _offending_paths(text)
        if found:
            offenders[rel] = found

    assert not offenders, (
        "tracked file(s) carry a real user's home directory on a PUBLIC repo — "
        "use /home/<user>, $HOME, or a repo-relative path:\n"
        + "\n".join(f"  {rel}: {', '.join(sorted(v))}" for rel, v in sorted(offenders.items()))
    )


def test_no_new_binary_carries_a_build_path():
    """A binary's path is baked in at compile time, so this pins the known set
    rather than demanding a rebuild — but a NEW one must not slip in quietly."""
    offenders = set()
    for rel in _tracked_files():
        path = REPO / rel
        if not path.is_file() or rel in KNOWN_BINARY_OFFENDERS:
            continue
        try:
            path.read_text(encoding="utf-8")
            continue  # it is text; the test above covers it
        except (UnicodeDecodeError, OSError):
            pass
        try:
            blob = path.read_bytes()
        except OSError:  # pragma: no cover
            continue
        if _offending_paths(blob.decode("latin-1")):
            offenders.add(rel)

    assert not offenders, f"new binary file(s) carry a build-time home path: {sorted(offenders)}"


@pytest.mark.parametrize("rel", sorted(KNOWN_BINARY_OFFENDERS))
def test_the_known_binary_exemption_is_not_stale(rel):
    """If the binary is rebuilt clean, drop it from the list rather than leaving
    an exemption that hides a future regression."""
    path = REPO / rel
    if not path.is_file():
        pytest.skip(f"{rel} is not present in this checkout")
    found = _offending_paths(path.read_bytes().decode("latin-1"))
    assert found, f"{rel} is now clean — remove it from KNOWN_BINARY_OFFENDERS"
