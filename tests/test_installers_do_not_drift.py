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
