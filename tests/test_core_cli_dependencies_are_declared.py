"""A core command's mandatory output must not need an undeclared package.

`binder-compare hits` is the wet-lab handoff — the last step before genes are
ordered — and its `--output XLSX` is `required=True`. It writes through
`pd.ExcelWriter(engine="openpyxl")`, and openpyxl was declared nowhere: not in
pyproject, not in any env spec, not in any of the nine built environments. So
the fully installed `binder-eval` env printed a success-looking selection line
and then died with a traceback, writing no file.

That combination — core command, mandatory output, undeclared dependency — is
the shape worth guarding, not openpyxl specifically.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = REPO / "Evaluator" / "pyproject.toml"


def _declared() -> str:
    """Everything pyproject declares, dependencies and extras alike."""
    return PYPROJECT.read_text()


@pytest.mark.parametrize(
    ("package", "why"),
    [
        ("openpyxl", "cli/hits.py writes the wet-lab workbook via pd.ExcelWriter(engine='openpyxl')"),
        ("pandas", "every comparison module"),
        ("numpy", "PAE and scoring maths"),
        ("requests", "refolding/target_msa.py imports it at module level"),
    ],
)
def test_runtime_dependency_is_declared(package, why):
    assert re.search(rf'"{package}\b', _declared()), f"{package} is undeclared but required: {why}"


def test_openpyxl_is_a_hard_dependency_not_an_extra():
    """`hits --output` is required=True, so the workbook is not optional.

    Putting openpyxl behind an extra would leave the default install unable to
    run a documented core command — the state this test exists to prevent.
    """
    text = _declared()
    deps_block = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "openpyxl" in deps_block, "openpyxl must sit in the base dependencies, not an optional extra"


def test_hits_still_requires_its_workbook_output():
    """If --output ever becomes optional this guard's premise changes; fail so
    someone re-reads it rather than leaving a stale rationale behind."""
    hits = (REPO / "Evaluator" / "binder_comparison" / "cli" / "hits.py").read_text()
    assert "required=True" in hits.split('"--output"', 1)[1][:400], (
        "hits --output is no longer required — revisit whether openpyxl is still a hard dependency"
    )
