"""The probe is shipped over stdin to boxes we do not control. Two guarantees.

1. STDLIB ONLY. remote.py pipes the probe source into `ssh <host> python3 -`, so
   it must run on a box with no checkout, no conda env and nothing pip-installed.
   An import of pandas (which the Evaluator's extractors pull in) would make the
   probe work on the dev box and fail on every other one.

2. NO `pgrep -f`. It matches its own command line -- recorded in CLAUDE.local.md
   and the reason tfr1_queue.sh waits with `kill -0`. A liveness check that
   matches itself reports every arm as running, including the dead ones, which
   silently defeats the entire module.
"""

import ast
import pathlib

STATUS_DIR = pathlib.Path(__file__).resolve().parents[2] / "status"

# Modules that must survive being piped into a bare `python3 -`.
SHIPPED = ("schema.py", "probes.py", "liveness.py", "collect.py")

STDLIB_ALLOWED = {
    "argparse",
    "collections",
    "concurrent",
    "csv",
    "dataclasses",
    "datetime",
    "glob",
    "gzip",
    "itertools",
    "json",
    "math",
    "os",
    "pathlib",
    "re",
    "shutil",
    "socket",
    "statistics",
    "string",
    "subprocess",
    "sys",
    "time",
    "typing",
}


def _imports(path):
    tree = ast.parse(path.read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_the_shipped_probe_imports_only_the_stdlib():
    for name in SHIPPED:
        path = STATUS_DIR / name
        assert path.is_file(), f"{name} is missing"
        outside = {m for m in _imports(path) if m not in STDLIB_ALLOWED and m != "status"}
        assert not outside, f"{name} imports {sorted(outside)} -- it cannot run on a bare python3"


def test_no_module_reaches_for_pandas_or_the_evaluator_package():
    for path in STATUS_DIR.glob("*.py"):
        found = _imports(path)
        for banned in ("pandas", "numpy", "binder_comparison", "matplotlib"):
            assert banned not in found, f"{path.name} imports {banned}"


def _string_constants(path):
    """Every string literal in the module except its docstrings.

    Comments are absent from the AST, so this lets the module DOCUMENT the trap
    by name while still failing if anything ever tries to invoke it.
    """
    tree = ast.parse(path.read_text())
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docstrings
    ]


def test_liveness_never_shells_out_to_the_self_matching_matcher():
    for literal in _string_constants(STATUS_DIR / "liveness.py"):
        assert "pgrep" not in literal, f"liveness must scan /proc itself, found {literal!r}"
