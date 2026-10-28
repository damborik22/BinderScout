"""`--uninstall` must dispatch to every tool its installer can install.

A tool the installer can create an environment for but that `--uninstall` never
reaches leaves the env, its weights and its marker behind while reporting success.
The user's next `install --tool <that one>` then sees a half-state nobody wrote.

This was live on aarch64 at 1.0.6: `install_aarch.sh` installs RFD3 through the
documented opt-in `--tool rfd3`, and `uninstall_tool` has an `rfd3` branch, but
the dispatch block had no `DO_RFD3` line — so `--uninstall --tool rfd3` there
printed its banner, removed nothing, and exited 0. x86_64 had the line.

Derived from the installers rather than hand-listed: a hand-maintained list is
how the aarch64 one fell behind in the first place.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALLERS = {
    "install.sh": (REPO / "install" / "install.sh").read_text(),
    "install_aarch.sh": (REPO / "install" / "install_aarch.sh").read_text(),
}

# `--tool x` sets DO_X=true; the uninstall block tests the same DO_X flags.
_SETS_FLAG = re.compile(r"\b(DO_[A-Z0-9_]+)=true")
_UNINSTALL_DISPATCH = re.compile(r'\[\[\s*"\$\{(DO_[A-Z0-9_]+)\}"\s*==\s*true\s*\]\]\s*&&\s*\{\s*uninstall_tool')

# Not tools: these gate install *behaviour*, so they are never uninstalled.
_NOT_A_TOOL = {"DO_INSTALL", "DO_UNINSTALL", "DO_ALL", "DO_EXAMPLES", "DO_STANDALONE"}


def _installable(text: str) -> set[str]:
    return {f for f in _SETS_FLAG.findall(text) if f not in _NOT_A_TOOL}


def _uninstallable(text: str) -> set[str]:
    return set(_UNINSTALL_DISPATCH.findall(text))


@pytest.mark.parametrize("name", sorted(INSTALLERS))
def test_every_installable_tool_is_also_uninstallable(name):
    text = INSTALLERS[name]
    missing = _installable(text) - _uninstallable(text)
    assert not missing, (
        f"{name}: {sorted(missing)} can be installed but `--uninstall` never dispatches them, "
        "so the env and its marker survive an uninstall that reports success"
    )


@pytest.mark.parametrize("name", sorted(INSTALLERS))
def test_uninstall_never_dispatches_a_tool_it_cannot_install(name):
    """The mirror case: a dispatch line for a flag no `--tool` ever sets is dead code."""
    text = INSTALLERS[name]
    orphaned = _uninstallable(text) - _installable(text)
    assert not orphaned, f"{name}: uninstall dispatches {sorted(orphaned)}, which no --tool sets"


def test_rfd3_specifically_is_uninstallable_on_both_arches():
    """The regression that was live. Named, because a generic test can go green by
    accident if the flag-discovery regex stops matching."""
    for name, text in INSTALLERS.items():
        assert "DO_RFD3" in _uninstallable(text), f"{name}: --uninstall --tool rfd3 is a silent no-op"
