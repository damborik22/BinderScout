"""There is exactly one labelled-pool registry, and it is `binder_comparison.benchmarks`.

The 2.0 plan had Y and AG both creating `binder_comparison/benchmarks.py`, with AG
additionally creating `comparison/benchmark.py` (the plan's own §159-160 flags this).
Y shipped first, so the duplicate is settled by precedence — but the second module
was never settled, and it blocked AG and AH from starting.

**Decision, 2026-09-28.** Reading what each actually needs narrows the conflict:

* `benchmarks.py` is a **registry** -- `list_benchmarks`, `load_manifest`,
  `store_root`, `labels_path`, `load_labels`. It answers "which labelled pools exist
  and what are their rows", and `load_labels` returns a checksum-verified DataFrame,
  which is precisely what AG needs to join a ranking against. AG must **import it,
  not recreate it**.
* AG's `comparison/benchmark.py` is **not a duplicate** of that. There is no
  label-based scoring anywhere in the shipped tree (no `roc_auc`, no `macro_auc`,
  no precision-at-k over labels), so Part U's numbers came from analysis that never
  landed as library code. AG writing the first of it is legitimately new work.

So the rule is not "one module" bluntly -- it is **one registry**, plus a scoring
module whose name cannot be mistaken for it. `benchmarks.py` and
`comparison/benchmark.py` differ by one character and a directory, which is how a
reader imports the wrong one; that specific name is therefore refused. Call the
scoring module something that says what it does (`label_scoring.py`), and have it
import the registry.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "Evaluator" / "binder_comparison"
REGISTRY = PKG / "benchmarks.py"

#: The registry's public surface. A second module offering these is a second registry.
_REGISTRY_FUNCTIONS = {"list_benchmarks", "load_manifest", "load_labels", "labels_path", "store_root"}


def _module_level_defs(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text())
    except (SyntaxError, UnicodeDecodeError):
        return set()
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def test_the_registry_is_where_we_decided_it_is():
    assert REGISTRY.is_file(), (
        "binder_comparison/benchmarks.py is the single labelled-pool registry (Y shipped it). "
        "If it moved, update this test and every part that imports it -- do not leave two homes."
    )
    defined = _module_level_defs(REGISTRY)
    missing = sorted(_REGISTRY_FUNCTIONS - defined)
    assert not missing, f"the registry lost {missing} — AG and AH import these"


def test_the_confusable_name_is_not_used():
    """`comparison/benchmark.py` is refused on naming grounds, not on scope grounds.

    AG does need a scoring module. It must not be one character away from the
    registry, because that is how the wrong import happens.
    """
    forbidden = PKG / "comparison" / "benchmark.py"
    assert not forbidden.exists(), (
        f"{forbidden.relative_to(REPO)} exists. Label-based scoring is welcome, but not under a "
        "name one character from binder_comparison/benchmarks.py — call it label_scoring.py and "
        "import the registry rather than re-deriving it."
    )


def test_no_second_registry_appeared_anywhere():
    """The substantive guard: any other module offering the registry's surface is a
    second source of truth for which pools exist and what their labels are."""
    offenders = {}
    for path in sorted(PKG.rglob("*.py")):
        if path == REGISTRY:
            continue
        overlap = _module_level_defs(path) & _REGISTRY_FUNCTIONS
        if overlap:
            offenders[str(path.relative_to(REPO))] = sorted(overlap)
    assert not offenders, (
        "a second labelled-pool registry appeared: "
        + "; ".join(f"{k} defines {v}" for k, v in offenders.items())
        + ". Import binder_comparison.benchmarks instead — two registries means two answers "
        "to 'which pools exist', and the labels decide every number computed from them."
    )
