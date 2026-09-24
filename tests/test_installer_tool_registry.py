"""The installer must enumerate its tools from exactly one list.

There used to be five hardcoded tool lists in install.sh and they had drifted
apart: ``print_tool_status`` carried 6 entries, ``select_tools_interactive`` 8,
``--tool all`` 11, and the dispatch and uninstall blocks 12. Only the 11 was
deliberate (AF3 is opt-in because its weights are gated).

The 8 was the damaging one. A user who ran the interactive menu could not
select ESMFold2 at all, and ESMFold2 is the *default* refold engine — so a
menu-driven install produced an evaluator that could not satisfy its own
default three-engine gate, and only said so at report time.

These tests fail if a new tool is added to one place and not the others.
"""

import re
from pathlib import Path

import pytest

INSTALLERS = [
    Path(__file__).resolve().parents[1] / "install" / "install.sh",
]


def _registry(src: str) -> list[tuple[str, str, str]]:
    block = re.search(r"TOOL_REGISTRY=\((.*?)\n\)", src, re.S)
    assert block, "TOOL_REGISTRY not found"
    rows = re.findall(r'"([^"|]+)\|([^"|]+)\|([^"|]+)"', block.group(1))
    assert rows, "TOOL_REGISTRY is empty"
    return rows


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_registry_covers_every_do_flag(path):
    """Every DO_<TOOL> flag the script declares must be in the registry."""
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    src = path.read_text()
    declared = set(re.findall(r"^(DO_[A-Z0-9_]+)=false", src, re.M))
    registered = {flag for flag, _, _ in _registry(src)}
    missing = declared - registered
    assert not missing, f"declared but not in TOOL_REGISTRY: {sorted(missing)}"


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_every_registry_entry_names_a_real_install_function(path):
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    src = path.read_text()
    for flag, tool, fn in _registry(src):
        assert re.search(rf"^{re.escape(fn)}\(\)", src, re.M), (
            f"TOOL_REGISTRY entry '{tool}' names {fn}(), which is not defined"
        )


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_every_registry_entry_has_a_verifier(path):
    """A tool with no verifier silently reports 'not installed' forever."""
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    src = path.read_text()
    body = re.search(r"^verify_tool\(\).*?\n}", src, re.S | re.M)
    assert body, "verify_tool() not found"
    arms = body.group(0)
    for _flag, tool, _fn in _registry(src):
        needle = tool.lower()
        assert needle in arms.lower(), f"verify_tool() has no arm for '{tool}'"


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_tool_status_is_not_a_second_hardcoded_list(path):
    """print_tool_status must derive from the registry, not its own list."""
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    src = path.read_text()
    body = re.search(r"^print_tool_status\(\).*?\n}", src, re.S | re.M)
    assert body, "print_tool_status() not found"
    assert "TOOL_REGISTRY" in body.group(0), (
        "print_tool_status() no longer reads TOOL_REGISTRY — it has grown its "
        "own tool list again, which is how six of twelve tools went missing"
    )


@pytest.mark.parametrize("path", INSTALLERS, ids=lambda p: p.name)
def test_weight_downloads_are_retried(path):
    """A transient DNS failure cost RFD3 its entire checkpoint on 2026-09-23.

    Every run_logged step whose label mentions downloading must carry --retries;
    build/compile steps deliberately must not, because retrying a deterministic
    compile failure only hides the error.
    """
    if not path.exists():
        pytest.skip(f"{path.name} not present")
    src = path.read_text()
    unretried = [
        line.strip()
        for line in src.splitlines()
        if "run_logged " in line and "--retries" not in line and re.search(r'"[^"]*[Dd]ownload', line)
    ]
    assert not unretried, "download steps without --retries:\n  " + "\n  ".join(unretried)
