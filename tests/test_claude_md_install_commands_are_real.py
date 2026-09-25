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
# BOTH installers: CLAUDE.md documents `install_aarch.sh --tool ...` invocations
# too, and the aarch64 one was never parsed.
INSTALLERS = (REPO / "install" / "install.sh", REPO / "install" / "install_aarch.sh")


def _accepted_tool_names() -> set[str]:
    """The labels of every installer's `--tool` case block."""
    marker = 'case "${2,,}" in'
    names: set[str] = set()
    for installer in INSTALLERS:
        if not installer.is_file():
            continue
        text = installer.read_text()
        assert marker in text, f"{installer.name} no longer parses --tool with that case block"
        block = text.split(marker, 1)[1].split("esac", 1)[0]
        for m in re.finditer(r"^\s*([a-z0-9|_-]+)\)", block, re.M):
            names.update(part.strip() for part in m.group(1).split("|"))
    assert names, "parsed no tool names out of the installers"
    return names


def _documented_tool_names() -> set[str]:
    """Every `--tool NAME` CLAUDE.md shows, whatever precedes it.

    The old pattern required `binderscout install --tool` adjacently, so it
    missed both `binderscout install --uninstall --tool X` (a form CLAUDE.md
    documents) and every `bash install/install_aarch.sh --tool X`.
    """
    text = CLAUDE.read_text()
    names: set[str] = set()
    for line in text.splitlines():
        if not re.search(r"(binderscout install|install(_aarch)?\.sh)", line):
            continue
        names.update(re.findall(r"--tool +([a-z0-9_-]+)", line))
    return names


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
