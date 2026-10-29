"""Every lock captured in install/locks/ must actually reach a package manager.

`install/locks/` exists because every dependency outage this repo has had came from a
distribution install.sh never names: BUG-14 (pyrosetta 2026.29), BUG-20 (atomworks 3.0.0),
the RUF071 CI failure. A lock only protects an env if pip is handed it, and failing to hand
it over is silent in exactly the way this repo's bugs are: the file exists, EVIDENCE.md lists
it, a test reads `atomworks==2.2.1` out of it, CI is green -- and the env installs unpinned.
EVIDENCE.md finding 1 is the same shape ("a pin can be a lie": `torch==2.5.1+cu121` sat in
install.sh while the editable install on the next line upgraded straight over it).

tests/test_pinned_versions.py checks one direction only -- every `_constraints "<env>"` call
names a file that exists -- and counts `${CONSTRAINTS[@]}` splices across the whole file
(>= 8). Two ways to lose a lock slip between those:

* Delete a call. `_constraints "binder-eval-esmfold2"` goes, the remaining names still
  resolve, and the splices stay put (install_esmfold2 still reads the array three times).
  Nothing fails.
* `CONSTRAINTS` is ONE global array that only `_constraints` resets. A function that splices
  it without its own call does not fail; it reuses whatever the previous install_* left.
  Under `--tool all` ESMFold2 runs after AF3 (no lock, no call), which runs after
  Protein-Hunter, so ESMFold2's three pip lines would be constrained by Protein-Hunter's ~150
  pins instead of its own. Run alone, it is simply unpinned.

So these tests execute the real install_* functions instead of reading them. The technique is
the one test_install_markers.py uses (real bash extracted from install.sh), taken a step
further: PATH is emptied so no external command can run, and every command a function
launches is recorded instead. "Does the lock reach pip" is then answered by what pip was
actually handed -- which a regex over the source cannot see when a call sits after the first
pip line, or a splice sits in a branch that never runs. (install_aarch.sh applies no locks at
all, by design: the captures are x86_64-only and `_constraints` refuses them elsewhere.)

Two locks are not applied today (see KNOWN_UNAPPLIED). They are marked `xfail(strict=True)`
rather than skipped or special-cased in the assertion: the check stays exactly as strict for
them as for every other lock, the gap shows up as "2 xfailed" in every run, and wiring one
turns it into a failure that says to delete its entry (`pytest --runxfail` shows the failure
itself). Deleting one is caught too, and so is wiring it somewhere the sandbox cannot see.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

REPO = Path(__file__).resolve().parents[1]
INSTALL_TEXT = (REPO / "install" / "install.sh").read_text()
LOCKS = REPO / "install" / "locks"

# What main() dispatches, in `--tool all` order. Derived, so a tool added later is checked
# without anyone remembering to list it here.
INSTALL_FUNCTIONS = re.findall(r"_install_step \w+ (install_\w+)", INSTALL_TEXT)
LOCK_STEMS = sorted(p.stem for p in LOCKS.glob("*.txt"))

# Captured, documented as applied (README: "fed back to pip as a constraints file on
# reinstall"; CLAUDE.md: "`_constraints()` splices them into each pip call"), read by tests
# -- and handed to nothing. Every other lock is applied. Wire these two or delete them and
# the EVIDENCE.md rows that imply they are in force; that is the maintainer's call, so this
# table records the debt instead of deciding it.
KNOWN_UNAPPLIED = {
    "proteina-complexa": (
        "install_proteina_complexa builds the venv with upstream's env/build_uv_env.sh and applies "
        "no lock to it, then re-pins atomworks and dm-haiku by hand with `uv pip install` and no "
        "-c; the rest of the ~220 versions the lock records are left to upstream's script and to "
        "whatever PyPI serves that day. If this XPASSes the lock is now wired: delete its entry "
        "from KNOWN_UNAPPLIED."
    ),
    "binder-eval-soluprot": (
        "install_soluprot builds its env with `conda env create -f binder-eval-soluprot.yml` and "
        "never runs pip, so there is nothing for -c to attach to; conda resolves everything but "
        "python, scikit-learn and biopython afresh. If this XPASSes the lock is now wired: "
        "delete its entry from KNOWN_UNAPPLIED."
    ),
}

# Stands in for whatever the previous install_* left in the global CONSTRAINTS array.
LEFTOVER_LOCK = "/leftover-from-the-previous-tool.txt"


def bash_function(name: str) -> str:
    """Extract `name() { ... }` from install.sh by its column-zero braces."""
    match = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}$", INSTALL_TEXT, re.S | re.M)
    assert match, f"{name}() not found in install.sh"
    return match.group(0)


# Every top-level path constant the installer defines (`FOO_DIR="${BINDMASTER_DIR}/foo"`),
# replayed under the sandbox's own BINDMASTER_DIR so nothing a function writes can land in
# the real checkout -- and so a path constant added later is sandboxed without an edit here.
PATH_CONSTANTS = "\n".join(re.findall(r'^[A-Z][A-Z0-9_]*="\$\{[A-Z0-9_]+\}[^"$`]*"[ \t]*$', INSTALL_TEXT, re.M))

# PATH is emptied first thing, so bash cannot find a single external command (git, conda,
# pip, curl, rm, sed ...) and hands each one to command_not_found_handle, which records its
# argv and reports success. Nothing is installed, downloaded or deleted; what runs is the
# shell logic of the function, end to end. Helpers that are not defined here fall through to
# the same handler, so a function that gains a new helper call still runs. The few defined
# below are the ones whose default would be wrong: the output helpers (kept quiet),
# run_logged / smoke_test (their first argument is a label, not a command), env_exists
# ("success" would mean the env is already there) and uv (probed with `command -v`).
SANDBOX_HEAD = r"""
exec </dev/null
PATH=/nonexistent
HOME="${SANDBOX_DIR}/home"
ARCH=x86_64
BINDMASTER_DIR="${SANDBOX_DIR}"
CONDA_BASE="${SANDBOX_DIR}/conda"
CONDA_CMD=conda
CUDA_VERSION=12.4
FORCE=false
AUTO_YES=true
SKIP_EXAMPLES=true
"""

SANDBOX_TAIL = r"""
LOCKS_DIR="${REAL_LOCKS_DIR}"

command_not_found_handle() {
    printf '%s\0' "$@" >> "${CALL_LOG}"
    printf '\036' >> "${CALL_LOG}"
}
print_step() { :; }
print_ok() { :; }
print_warn() { :; }
print_fail() { echo "FAIL: $*" >&2; }
env_exists() { return 1; }  # a fresh box: every env has to be created
run_logged() { [[ "$1" == --retries ]] && shift 2; shift; "$@"; }  # [--retries N] <label> <command...>
smoke_test() { shift; "$@"; }                                        # <label> <command...>
uv() { command_not_found_handle uv "$@"; }                           # `command -v uv` must succeed
"""


class Run(NamedTuple):
    returncode: int
    stderr: str
    commands: list[str]


def run_install_function(name: str, sandbox: Path, *, source: str | None = None) -> Run:
    """Execute install.sh's real *name*() with every launched command recorded.

    The global CONSTRAINTS array is pre-loaded with a stand-in for the previous tool's lock,
    which a correct function overwrites with its own before its first pip line.
    *source* substitutes the text of the function, for the sandbox self-test below.
    """
    (sandbox / "home").mkdir()
    (sandbox / "bin").mkdir()
    shutil.copytree(REPO / "Evaluator" / "envs", sandbox / "Evaluator" / "envs")
    calls = sandbox / "calls.log"
    calls.touch()
    script = "\n".join(
        [
            SANDBOX_HEAD,
            PATH_CONSTANTS,
            SANDBOX_TAIL,
            bash_function("_constraints"),
            bash_function(name) if source is None else source,
            f"CONSTRAINTS=(-c {LEFTOVER_LOCK})",
            name,
            "exit $?",
        ]
    )
    # A bare environment: nothing from the developer's shell (PIP_CONSTRAINT, CONDA_PREFIX,
    # BASH_ENV ...) may change which branch a function takes. PATH is only for finding bash;
    # the script discards it before running anything.
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "SANDBOX_DIR": str(sandbox),
        "REAL_LOCKS_DIR": str(LOCKS),
        "CALL_LOG": str(calls),
    }
    proc = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, errors="replace", timeout=60)
    raw = calls.read_bytes().decode(errors="replace")
    commands = [" ".join(chunk.split("\0")[:-1]) for chunk in raw.split("\x1e") if chunk]
    return Run(proc.returncode, proc.stderr, commands)


# How a lock reaches a package manager: pip's / uv's `-c FILE` or `--constraint FILE`, or the
# PIP_CONSTRAINT / UV_CONSTRAINT environment variable (how install_bindcraft hands it to
# BindCraft's own installer, whose pip calls we cannot edit).
CONSTRAINT = re.compile(r"""(?:(?<![\w-])-c |--constraints?[ =]|\b(?:PIP|UV)_CONSTRAINT=)['"]?([^\s'"]+\.txt)""")


def applied_locks(commands: list[str]) -> set[str]:
    """Stems of the install/locks/*.txt files that appear as a constraint in *commands*."""
    return {
        Path(path).stem for command in commands for path in CONSTRAINT.findall(command) if Path(path).parent == LOCKS
    }


@pytest.fixture(scope="module")
def installer_runs(tmp_path_factory) -> dict[str, Run]:
    return {name: run_install_function(name, tmp_path_factory.mktemp(name)) for name in INSTALL_FUNCTIONS}


@pytest.fixture(scope="module")
def applied(installer_runs) -> set[str]:
    return set().union(*(applied_locks(run.commands) for run in installer_runs.values()))


def lock_param(stem: str):
    if stem not in KNOWN_UNAPPLIED:
        return pytest.param(stem, id=stem)
    mark = pytest.mark.xfail(strict=True, raises=AssertionError, reason=KNOWN_UNAPPLIED[stem])
    return pytest.param(stem, id=stem, marks=mark)


def test_the_installer_still_has_locks_and_install_functions_to_check():
    """Parametrising over an empty list skips instead of failing."""
    assert LOCK_STEMS, "install/locks/ holds no *.txt constraints files"
    assert INSTALL_FUNCTIONS, "no `_install_step <key> install_<tool>` dispatch found in main()"


@pytest.mark.parametrize("stem", [lock_param(s) for s in LOCK_STEMS])
def test_the_captured_lock_reaches_a_package_manager(stem, applied):
    assert stem in applied, (
        f"install/locks/{stem}.txt is captured, but no command any install_* function launches "
        "carries it -- so that env installs unpinned while the README and CLAUDE.md say every "
        "captured env is pinned. Wire it (call `_constraints` with the env name before the pip "
        'lines and splice "${CONSTRAINTS[@]}", or export PIP_CONSTRAINT as install_bindcraft does) '
        "or delete the file and the EVIDENCE.md row that implies it is in force. If you did not "
        "touch the wiring, check that the installer function still gets to its pip lines in the "
        "sandbox: run_install_function(name, tmp_path) returns .commands (what it launched), .stderr and "
        ".returncode."
    )


def test_the_known_unapplied_table_lists_only_locks_that_still_exist():
    """Deleting a lock is the other way out of the gap; it must not leave a stale entry behind."""
    stale = sorted(set(KNOWN_UNAPPLIED) - set(LOCK_STEMS))
    assert not stale, f"install/locks/ no longer holds {stale}: delete their entries from KNOWN_UNAPPLIED"


@pytest.mark.parametrize("stem", sorted(KNOWN_UNAPPLIED))
def test_a_known_unapplied_lock_is_not_referenced_anywhere_in_the_installer(stem):
    """Second line of defence for the xfail above.

    The sandbox only sees what an install_* function itself launches. Wiring a lock inside a
    helper that needs a real venv to get as far as its pip line (`_pin_complexa_atomworks`
    is the obvious place) would leave the xfail failing for the wrong reason, and the entry
    would never be asked to go. Any code reference to the lock is enough to ask.
    """
    code = "\n".join(line for line in INSTALL_TEXT.splitlines() if not line.lstrip().startswith("#"))
    wired = re.search(rf'_constraints "{re.escape(stem)}"|{re.escape(stem)}\.txt', code)
    assert not wired, (
        f"install.sh now refers to {wired.group(0)!r}. If that applies install/locks/{stem}.txt, delete "
        "its entry from KNOWN_UNAPPLIED -- and make sure the sandbox can see the pip line it reaches."
    )


@pytest.mark.parametrize("name", INSTALL_FUNCTIONS)
def test_an_install_function_never_inherits_the_previous_tools_constraints(name, installer_runs):
    leaked = [command for command in installer_runs[name].commands if LEFTOVER_LOCK in command]
    assert not leaked, (
        f"{name} handed a package manager a constraints file it never chose: {leaked[0]!r}. "
        "CONSTRAINTS is one global array that only `_constraints` resets, so a function that splices "
        '"${CONSTRAINTS[@]}" without its own `_constraints` call -- or before it -- applies whatever '
        "the previous install_* left behind: another env's lock under `--tool all`, nothing when run alone."
    )


def probe(first_line: str) -> str:
    """A stand-in install function with the shape every real one has: a call, then a splice."""
    return (
        "install_probe() {\n"
        f"    {first_line}\n"
        '    run_logged "probe" conda run -n BoltzGen pip install -q "${CONSTRAINTS[@]}" requests\n'
        "}"
    )


def test_the_sandbox_sees_a_lock_vanish_when_the_constraints_call_is_missing(tmp_path_factory):
    """The lock and leak checks above only mean something if the sandbox can fail.

    Run the same function with and without its `_constraints` call. A sandbox that stopped
    recording, or one that no longer propagates the global array between statements, turns
    this red instead of turning every check above into a vacuous pass.
    """
    with_call = run_install_function(
        "install_probe", tmp_path_factory.mktemp("with_call"), source=probe('_constraints "BoltzGen"')
    )
    without = run_install_function("install_probe", tmp_path_factory.mktemp("without"), source=probe(":"))

    assert applied_locks(with_call.commands) == {"BoltzGen"}
    assert not any(LEFTOVER_LOCK in command for command in with_call.commands)
    assert applied_locks(without.commands) == set()
    assert any(LEFTOVER_LOCK in command for command in without.commands)
