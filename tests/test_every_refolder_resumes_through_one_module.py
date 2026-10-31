"""No refolder may carry a private answer to "what counts as already done".

Six copies of this logic existed: one inline in each of the three engine scripts
and one ``_load_completed_indices`` in each of the three runners. They drifted,
and both directions of drift shipped:

  - the positional key, which on 2026-10-28 let a shared CWD-relative CSV mark
    all 65 designs of a PD-L1 pool complete -- Boltz-2 folded 0 and exited 0;
  - the missing score gate, which on 2026-10-31 would have stopped a retry from
    repairing 92 blank rows left by a partial OOM.

They are now one module, ``refolding/resume.py``. Its behaviour is tested in
tests/test_resume_is_keyed_on_the_sequence.py; this file pins that every entry
point actually reaches it, because a correct shared helper nothing calls is
still six different behaviours.

Static by necessity: these scripts import gemmi / torch / jax, which live only
in the per-engine envs, so they cannot be imported here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "Evaluator" / "scripts"
RUNNERS = REPO / "Evaluator" / "binder_comparison" / "refolding"

ENTRY_POINTS = [
    SCRIPTS / "refold_af3.py",
    SCRIPTS / "refold_esmfold2.py",
    RUNNERS / "af3_runner.py",
    RUNNERS / "esmfold2_runner.py",
    RUNNERS / "boltz2_runner.py",
]


def _ids(p: Path) -> str:
    return p.name


@pytest.mark.parametrize("path", ENTRY_POINTS, ids=_ids)
def test_it_calls_the_shared_resume(path):
    tree = ast.parse(path.read_text())
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "resume_plan" in calls, (
        f"{path.name} never calls resume_plan(). Its resume path is not the shared one, so it can "
        "disagree with the other engines about what 'completed' means."
    )


@pytest.mark.parametrize("path", ENTRY_POINTS, ids=_ids)
def test_the_name_it_calls_is_the_one_it_imported(path):
    """Matching the call text alone is not enough.

    `from .resume import resume_plan as _unused` leaves every `resume_plan(...)`
    call site intact and reaching nothing -- a NameError at runtime, and invisible
    to a test that only looks for the call. Pin the import binding too.
    """
    tree = ast.parse(path.read_text())
    bound = {
        (alias.asname or alias.name)
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("resume")
        for alias in n.names
    }
    assert "resume_plan" in bound, (
        f"{path.name} calls resume_plan() but never binds that name from the resume module "
        f"(bound instead: {sorted(bound) or 'nothing'}). The call would raise NameError."
    )


@pytest.mark.parametrize("path", ENTRY_POINTS, ids=_ids)
def test_it_keeps_no_private_resume_implementation(path):
    src = path.read_text()
    assert "_load_completed_indices" not in src, f"{path.name} reintroduced a private resume helper"
    assert "_completed_indices" not in src, f"{path.name} reintroduced a private resume helper"


@pytest.mark.parametrize("path", ENTRY_POINTS, ids=_ids)
def test_it_does_not_build_a_skip_set_from_the_row_index(path):
    """The positional key, banned at the source.

    Any `skip.add(...)` / `indices.add(...)` inside a resume path is the shape of
    the bug: a set of row positions standing in for a set of designs.
    """
    tree = ast.parse(path.read_text())
    adds = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id in {"skip", "skip_indices", "indices"}
    ]
    assert not adds, (
        f"{path.name} builds its skip set element by element ({len(adds)} .add call(s)). "
        "The skip set must come from resume_plan(), which keys on the binder sequence."
    )
