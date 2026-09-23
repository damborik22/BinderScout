"""The Mosaic template must record the order designs were generated in.

2.0 Part AD needs a per-design `generation_index`: when a design was produced,
not how good it turned out. Mosaic is the tool where this is easiest to lose,
because `hallucinate_binderscout.py` appends candidates in generation order and
then sorts them by `ranking_loss` twice before anything is written — so the
`rank` column in designs.csv is quality order and carries no generation
information at all.

The fragile part is `_diversity_filter`: it destructures each candidate and
*rebuilds* a tuple, so any field added to the candidate silently disappears
there rather than raising.

These helpers are pure stdlib, but the module imports jax and mosaic at line 32
onward and those exist only in Mosaic/.venv — so the tests extract just the two
helpers rather than importing the module, and therefore run in CI too.
"""

import ast
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parents[1] / "binderscout_examples" / "hallucinate_binderscout.py"

_WANTED = {"_hamming_distance", "_diversity_filter"}


def _pure_helpers():
    tree = ast.parse(TEMPLATE.read_text())
    ns: dict = {}
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _WANTED:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(TEMPLATE), "exec"), ns)
            found.add(node.name)
    missing = _WANTED - found
    assert not missing, f"helpers missing from the template: {missing}"
    return ns


@pytest.fixture(scope="module")
def helpers():
    return _pure_helpers()


def test_diversity_filter_preserves_the_generation_index(helpers):
    """A candidate is (sequence, loss, generation_index). The filter selects
    candidates; it must not reshape them."""
    candidates = [
        ("AAAAAAAA", 0.1, 7),
        ("AAAAAAAT", 0.2, 3),  # 1 away from the first — dropped at min_hamming=4
        ("CCCCCCCC", 0.3, 0),  # far from both — kept
    ]
    kept = helpers["_diversity_filter"](candidates, min_hamming=4)

    assert [c[0] for c in kept] == ["AAAAAAAA", "CCCCCCCC"]
    assert all(len(c) == 3 for c in kept), (
        "_diversity_filter rebuilt the candidate tuple and dropped a field — "
        "generation_index would be silently lost before designs.csv is written"
    )
    assert [c[2] for c in kept] == [7, 0], "generation_index did not survive the filter"


def test_generation_index_is_written_to_designs_csv():
    """The column has to reach the CSV, or the extractor has nothing to read."""
    src = TEMPLATE.read_text()
    assert '"generation_index"' in src, "generation_index is never emitted"
    # It must be in the csv_columns list, not only in the row dict: DictWriter is
    # constructed with fieldnames=csv_columns, so a key absent from that list is
    # dropped (or raises), never written.
    columns_block = src.split("csv_columns = [", 1)
    assert len(columns_block) == 2, "csv_columns list not found"
    assert '"generation_index"' in columns_block[1].split("]", 1)[0], (
        "generation_index is in the row dict but not in csv_columns — DictWriter writes fieldnames only"
    )


def test_generation_index_is_captured_before_the_sort():
    """Captured at the append, not in the post-sort loop.

    The template sorts candidates by ranking_loss twice before the writing loop,
    so an index derived there would be rank, not generation order.
    """
    src = TEMPLATE.read_text()
    append_at = src.index("candidates.append(")
    first_sort_at = src.index("candidates = sorted(")
    assert append_at < first_sort_at, "candidates are sorted before the index is captured"
