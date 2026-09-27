"""The two installers must offer the same tools.

`binderscout install` dispatches by platform (`binderscout.py:124` picks
`install_aarch.sh` on aarch64, and `install.sh` now refuses there rather than
warning). But **one entry point is not one implementation**: the aarch64 script
is a separate ~3,000-line file with its own `install_*` functions, not a wrapper
that reuses x86 logic with different wheel pins.

So every tool has to be written twice, and the evidence is that the second copy
gets forgotten. Measured on 2026-09-26: TmProt had 59 references in `install.sh`
and **zero** in `install_aarch.sh` — it simply could not be installed on Spark —
and Proteina-Complexa had no install function there at all. Neither was a
decision; both were oversights that survived because nothing compared the two.

This makes that comparison a test. It deliberately checks the *surface* — the
`--tool` vocabulary, the `install_*` functions and the `DO_*` flags — not the
bodies, which genuinely differ (cu121 vs cu130 indexes, conda vs pip PyRosetta,
source builds). A tool present on one platform and absent on the other is the
defect; implementing it differently is the point.

Where a tool truly cannot work on a platform, add it to `_PLATFORM_EXEMPT` with
the reason. An exemption is a claim, so each is asserted to still hold.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
X86 = REPO / "install" / "install.sh"
ARM = REPO / "install" / "install_aarch.sh"

# Tools legitimately absent from one platform, with why. Empty today: every tool
# this project installs is offered on both.
_PLATFORM_EXEMPT: dict[str, str] = {}


def _tool_names(path: Path) -> set[str]:
    """Labels of the `--tool` case block — the vocabulary a user can type."""
    text = path.read_text()
    marker = 'case "${2,,}" in'
    assert marker in text, f"{path.name} no longer parses --tool with that case block"
    block = text.split(marker, 1)[1].split("esac", 1)[0]
    names: set[str] = set()
    for m in re.finditer(r"^\s*([a-z0-9|_-]+)\)", block, re.M):
        names.update(p.strip() for p in m.group(1).split("|"))
    names.discard("*")
    assert names, f"parsed no tool names from {path.name}"
    return names


def _install_functions(path: Path) -> set[str]:
    return set(re.findall(r"^(install_[a-z0-9_]+)\s*\(\)", path.read_text(), re.M))


def _do_flags(path: Path) -> set[str]:
    return set(re.findall(r"^(DO_[A-Z0-9_]+)=", path.read_text(), re.M))


@pytest.mark.parametrize(
    ("what", "extract"),
    [
        ("--tool names", _tool_names),
        ("install_* functions", _install_functions),
        ("DO_* flags", _do_flags),
    ],
)
def test_the_installers_offer_the_same_tools(what, extract):
    x86, arm = extract(X86), extract(ARM)
    missing_on_arm = sorted(x86 - arm - set(_PLATFORM_EXEMPT))
    missing_on_x86 = sorted(arm - x86 - set(_PLATFORM_EXEMPT))
    assert not missing_on_arm and not missing_on_x86, (
        f"{what} drifted between the installers.\n"
        f"  in install.sh but NOT install_aarch.sh: {missing_on_arm or '-'}\n"
        f"  in install_aarch.sh but NOT install.sh: {missing_on_x86 or '-'}\n"
        "Port it, or add it to _PLATFORM_EXEMPT with the reason it cannot work there."
    )


@pytest.mark.parametrize("tool", sorted(_PLATFORM_EXEMPT))
def test_each_exemption_still_applies(tool):
    """An exemption is a claim about a platform. If the tool is now on both, the
    claim is stale and the exemption hides the next real drift."""
    on_x86 = tool in _tool_names(X86) or tool in _install_functions(X86) or tool in _do_flags(X86)
    on_arm = tool in _tool_names(ARM) or tool in _install_functions(ARM) or tool in _do_flags(ARM)
    assert not (on_x86 and on_arm), (
        f"{tool} is present in BOTH installers — remove it from _PLATFORM_EXEMPT: {_PLATFORM_EXEMPT[tool]}"
    )


def test_a_dispatched_tool_is_actually_called():
    """A DO_ flag that nothing calls is a --tool that silently does nothing.

    Both scripts set the flag in one place and act on it in another, so this
    checks the second half exists for every install function.
    """
    problems = []
    for path in (X86, ARM):
        text = path.read_text()
        for fn in sorted(_install_functions(path)):
            total = len(re.findall(rf"\b{re.escape(fn)}\b", text))
            # Definitions sit at column 0; every call site is indented inside the
            # dispatcher. Subtracting the definitions leaves the calls.
            definitions = len(re.findall(rf"^{re.escape(fn)}\s*\(\)", text, re.M))
            if total - definitions < 1:
                problems.append(f"{path.name}: {fn} is defined but never called")
    assert not problems, "\n".join(problems)


# The primary spelling of every tool either installer can install. Aliases
# (bc2, complexa, phunter, esm, tm, ...) are deliberately excluded: the message
# is there to teach a user the name to type, not to enumerate every synonym.
_CANONICAL_TOOLS = (
    "all",
    "bindcraft",
    "bindcraft2",
    "boltzgen",
    "mosaic",
    "evaluator",
    "pxdesign",
    "proteina-complexa",
    "protein-hunter",
    "rfd3",
    "af3",
    "esmfold2",
    "soluprot",
    "tmprot",
)


def _advertised_tool_names(path: Path) -> set[str]:
    """The names the `--tool` rejection message tells the user to use."""
    m = re.search(r"Must be one of: ([^$\"]+)", path.read_text())
    assert m, f"{path.name} no longer prints a 'Must be one of:' list for --tool"
    return {p.strip() for p in m.group(1).split(",") if p.strip()}


@pytest.mark.parametrize("path", [X86, ARM], ids=lambda p: p.name)
def test_the_rejection_message_lists_every_tool(path):
    """A tool the installer accepts but never advertises is undiscoverable.

    Measured 2026-09-27: `tmprot` was missing from both messages and
    `proteina-complexa` from the aarch64 one, so a user who mistyped was told
    those tools did not exist — months after both were added.
    """
    missing = sorted(set(_CANONICAL_TOOLS) - _advertised_tool_names(path))
    assert not missing, (
        f"{path.name} accepts {missing} but its --tool rejection message never names them. "
        "Add them to the 'Must be one of:' list."
    )


@pytest.mark.parametrize("path", [X86, ARM], ids=lambda p: p.name)
def test_the_rejection_message_invents_nothing(path):
    """The mirror check: a name in the message that the parser rejects sends the
    user straight back to the same error."""
    unknown = sorted(_advertised_tool_names(path) - _tool_names(path))
    assert not unknown, f"{path.name} advertises {unknown}, which its own --tool parser rejects."


# Checks whose bodies must be IDENTICAL in both installers. Unlike the install_*
# functions -- which genuinely differ (cu121 vs cu130 indexes, conda vs pip
# PyRosetta, source builds) -- a verifier only reads paths and env names that both
# files define identically, so there is nothing to fork. Forking one anyway is how
# the aarch64 copy of a check rots, and `install_aarch.sh` had no verifier at all
# until 2026-09-27: `--verify` dispatches there on aarch64 and exited 1 with
# "Unknown option", leaving Spark as the only platform that could not be audited.
_SHARED_VERIFY_FUNCTIONS = ("_env_python_ok", "_env_refold_cli_ok", "_af3_ccd_built", "_count_glob", "verify_tool")


def _function_body(path: Path, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n", path.read_text(), re.S | re.M)
    assert m, f"{path.name} does not define {name}()"
    return m.group(1)


@pytest.mark.parametrize("fn", _SHARED_VERIFY_FUNCTIONS)
def test_the_verify_checks_are_identical_in_both_installers(fn):
    x86, arm = _function_body(X86, fn), _function_body(ARM, fn)
    assert x86 == arm, (
        f"{fn}() has drifted between install.sh and install_aarch.sh.\n"
        "These are meant to be byte-identical copies: they only read paths and conda "
        "env names that both files define the same way. Port the change to both, or "
        "if a platform genuinely needs a different check, split it out explicitly "
        "rather than editing one copy."
    )


@pytest.mark.parametrize("path", [X86, ARM], ids=lambda p: p.name)
def test_both_installers_accept_verify(path):
    """`binderscout install --verify` dispatches by platform, so an installer
    without the flag makes the documented audit impossible on that hardware."""
    text = path.read_text()
    assert "VERIFY_ONLY=false" in text, f"{path.name} has no --verify mode flag"
    assert re.search(r"^\s+--verify\)", text, re.M), f"{path.name} does not parse --verify"
    assert "verify_selected_tools" in text, f"{path.name} never runs the verification"
