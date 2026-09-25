"""Every `--tool` name CLAUDE.md documents must be one the installer accepts.

CLAUDE.md is this project's canonical description of itself, and its Commands
section is the first thing anyone runs. A name that the parser rejects sends a
reader to `Unknown tool` on their first command.

Static by design: it reads `install/install.sh`'s own `case` block rather than
invoking anything, so it works in CI, which installs the test dependencies but
not the `binderscout` CLI or the Evaluator package.

Sibling guards, each from a real defect found the same way:
`test_referenced_conda_envs_exist.py` (a docstring naming an env that has never
existed) and `test_readme_documents_the_cli.py` (evaluate.sh flags).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLAUDE = REPO / "CLAUDE.md"
INSTALLER = REPO / "install" / "install.sh"


def _accepted_tool_names() -> set[str]:
    """The labels of the installer's `--tool` case block."""
    text = INSTALLER.read_text()
    marker = 'case "${2,,}" in'
    assert marker in text, "install.sh no longer parses --tool with that case block — update this test"
    block = text.split(marker, 1)[1].split("esac", 1)[0]
    names: set[str] = set()
    for m in re.finditer(r"^\s*([a-z0-9|_-]+)\)", block, re.M):
        names.update(part.strip() for part in m.group(1).split("|"))
    assert names, "parsed no tool names out of install.sh"
    return names


def _documented_tool_names() -> set[str]:
    return set(re.findall(r"binderscout install --tool ([a-z0-9_-]+)", CLAUDE.read_text()))


def test_every_documented_tool_name_is_accepted():
    documented = _documented_tool_names()
    assert documented, "CLAUDE.md documents no --tool commands — did the Commands section move?"
    unknown = sorted(documented - _accepted_tool_names())
    assert not unknown, (
        f"CLAUDE.md documents `--tool {', '.join(unknown)}`, which install.sh rejects. "
        "Either the installer lost the name or the docs invented it."
    )


def test_the_installer_still_advertises_the_core_tools():
    """A canary: if this drops to a handful, the case block was restructured and
    the parse above is silently matching the wrong thing."""
    accepted = _accepted_tool_names()
    for core in ("all", "bindcraft", "boltzgen", "mosaic", "rfd3", "evaluator"):
        assert core in accepted, f"install.sh no longer accepts --tool {core}"
