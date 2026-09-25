"""An optional dependency must not be able to kill a command that runs without it.

``Evaluator/pyproject.toml`` deliberately leaves gemmi and biopython out of the
dependencies, on a stated contract: they are "imported inside functions, behind
guards that keep their modules importable without them". The four conda
environments exist precisely so that distinction matters — the Evaluator's own
``binder-eval`` has neither package.

``structures.py`` did not hold that contract, and the cost was concrete: wiring
``extract --collect-structures`` into the generated pipeline turned an unguarded
``import gemmi`` into a crash that killed every run *after* it had successfully
extracted the sequences. Nothing caught it, because the import is lazy — the
module imports fine, the CLI's ``--help`` works, and only the real path fails.

So this test is structural rather than behavioural: any in-function import of an
optional dependency must sit under ``try:``, and a new unguarded one fails here.
``_ALLOWED`` records the sites deliberately left to raise, each with a reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "Evaluator" / "binder_comparison"

# Import names worth checking. A name is OPTIONAL only when pyproject does not
# declare it -- derived below rather than hand-listed, so adding a dependency
# automatically stops it being treated as optional (matplotlib IS declared, and
# was wrongly listed here at first).
_CANDIDATES = {
    "gemmi": "gemmi",
    "Bio": "biopython",
    "scipy": "scipy",
    "sklearn": "scikit-learn",
    "torch": "torch",
    "jax": "jax",
    "matplotlib": "matplotlib",
}
_PYPROJECT = (Path(__file__).resolve().parents[1] / "Evaluator" / "pyproject.toml").read_text()
OPTIONAL = {imp for imp, dist in _CANDIDATES.items() if f'"{dist}' not in _PYPROJECT}

# Sites that may raise, with the reason each is acceptable.
_ALLOWED = {
    # Dead code: no caller anywhere in the package, and its docstring documents
    # the ImportError as the contract. Flagged here rather than deleted.
    ("io/read.py", "convert_cif_to_pdb"),
}


def _enclosing_function(tree: ast.Module, node: ast.stmt) -> str | None:
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and fn.lineno <= node.lineno:
            end = getattr(fn, "end_lineno", fn.lineno)
            if node.lineno <= end:
                return fn.name
    return None


def _guarded(tree: ast.Module, node: ast.stmt) -> bool:
    """True when the import sits inside a try block."""
    for parent in ast.walk(tree):
        if isinstance(parent, ast.Try):
            for stmt in parent.body:
                for inner in ast.walk(stmt):
                    if inner is node:
                        return True
    return False


def _optional_imports() -> list[tuple[str, str, int, str]]:
    """(relpath, function, lineno, package) for every in-function optional import."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        rel = path.relative_to(PACKAGE).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            pkgs = OPTIONAL.intersection(names)
            if not pkgs:
                continue
            if _guarded(tree, node):
                continue
            # A module-level optional import is WORSE, not exempt: it breaks the
            # module for every caller, not just the one code path. Skipping it
            # left the guard blind in structures.py -- the very file whose
            # breakage this test's docstring cites.
            fn = _enclosing_function(tree, node) or "<module level>"
            found.append((rel, fn, node.lineno, sorted(pkgs)[0]))
    return found


def test_no_new_unguarded_optional_import():
    offenders = [(rel, fn, line, pkg) for rel, fn, line, pkg in _optional_imports() if (rel, fn) not in _ALLOWED]
    assert not offenders, (
        "in-function imports of an optional dependency must sit under `try:` so the module stays usable "
        "without it — this is the contract pyproject.toml states, and the one structures.py broke:\n"
        + "\n".join(f"  {rel}:{line} in {fn}() imports {pkg}" for rel, fn, line, pkg in offenders)
    )


@pytest.mark.parametrize(("rel", "fn"), sorted(_ALLOWED))
def test_the_allowlist_is_not_stale(rel, fn):
    """An exemption that no longer applies should be removed, not left to rot."""
    assert (PACKAGE / rel).exists(), f"{rel} is gone — drop it from _ALLOWED"
    assert any(r == rel and f == fn for r, f, _line, _pkg in _optional_imports()), (
        f"{rel}:{fn}() no longer has an unguarded optional import — remove it from _ALLOWED"
    )
