"""Every `uv venv` in an installer must pass --clear, or re-install is impossible.

`uv venv` REFUSES when the target directory already holds a venv:

    error: Failed to create virtual environment
      Caused by: A virtual environment already exists at `.venv`. Use `--clear` to replace it

It exits non-zero, so the installer's `|| { print_fail ...; return 1; }` fires and the whole
tool install fails at its first step -- leaving the OLD venv in place and reporting failure.

Measured on BM5, 2026-10-03. Proteina-Complexa's aarch64 install was fixed on 2026-09-26 to
use `jax[cuda12]==0.6.2` instead of the CPU-only `jax[cpu]==0.4.29`, because 0.4.x cannot
compile an AF2-class graph for sm_121. That fix never reached BM5: the box already had a
pre-0.6.2 venv, so the installer refused, and the env sat on `jax 0.4.29 / backend cpu` --
exactly the configuration whose cost ("~130x too slow", "1.7 years") the deprecation rests on.
A tool documented as "installable on aarch64" was only installable on a machine that had
never installed it.

This is a static check on purpose. The real thing needs uv, a network and ~8 GB per venv, so
it cannot run in CI -- but the defect is visible in the call site, and that is where it was
introduced three times.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALLERS = ["install/install.sh", "install/install_aarch.sh"]

# A real `uv venv ...` INVOCATION, to the end of its logical line.
#
# The lookahead is what makes this usable. Both installers are full of the string
# "uv venv" in prose: menu descriptions ("...(uv venv)"), comments, `run_logged`
# labels ("Creating uv venv (python 3.12)") and `print_fail "uv venv failed"`. A
# plain \buv\s+venv\b matched nine such strings and three real calls, so the test
# reported six phantom offenders. An invocation is always followed by a flag or a
# path, and prose never is.
_CALL = re.compile(r"""(?:\buv|\$\{UV\}|'\$\{UV\}')\s+venv(?=\s+(?:--|-\w|[./$'"]))[^\n]*(?:\\\n[^\n]*)*""")


def _calls(text: str) -> list[str]:
    return [m.group(0) for m in _CALL.finditer(text)]


@pytest.mark.parametrize("rel", INSTALLERS)
def test_every_uv_venv_call_passes_clear(rel: str) -> None:
    path = REPO / rel
    assert path.is_file(), f"{rel} is missing"
    calls = _calls(path.read_text(encoding="utf-8"))
    offenders = [c for c in calls if "--clear" not in c]
    assert not offenders, (
        f"{rel} has {len(offenders)} `uv venv` call(s) without --clear, so re-installing that "
        "tool on a machine that already has its venv fails at the first step and silently "
        "leaves the old environment in place:\n  " + "\n  ".join(" ".join(c.split())[:140] for c in offenders)
    )


def test_the_matcher_actually_finds_the_calls() -> None:
    """Guard against the regex quietly matching nothing, which would pass vacuously.

    Both installers create venvs; if this count ever drops to zero the test above becomes
    an assertion about an empty list.
    """
    per = {rel: len(_calls((REPO / rel).read_text(encoding="utf-8"))) for rel in INSTALLERS}
    total = sum(per.values())
    assert total >= 3, f"expected at least 3 `uv venv` invocations across the installers, found {per}"
    # And it must not have gone loose again: every installer mentions "uv venv" in prose
    # far more often than it invokes it, so a big count means the lookahead broke.
    assert total <= 8, f"matcher looks loose -- it is probably catching prose again: {per}"


def test_proteina_complexa_aarch64_still_pins_the_gpu_jax() -> None:
    """The fix that --clear was blocking: PC's AF2 reward must not be CPU-only jax.

    jax 0.4.x cannot compile an AF2-class graph for sm_121 (`LLVM ERROR: Unsupported rounding
    mode for conversion`), which is what put the reward on the CPU and made the MCTS recipe
    unaffordable. BindCraft's env on the same box proves 0.6.2 works there.
    """
    text = (REPO / "install/install_aarch.sh").read_text(encoding="utf-8")
    assert "jax[cuda12]==0.6.2" in text
    # The manual Blackwell port's CPU pin must not be what PC installs.
    pc = text[text.index("install_proteina_complexa") :]
    assert 'jax[cpu]==0.4.29"' not in pc.replace(" ", ""), (
        "Proteina-Complexa's aarch64 install appears to pin jax[cpu]==0.4.29 again; that is the "
        "CPU-bound reward the deprecation was about."
    )
