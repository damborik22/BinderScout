"""AF3's --resume must re-run a design whose previous row came back blank.

A failed design still gets a row. ``_empty_row()`` writes its ``idx`` and its
sequence with every score column empty, so the CSV's row count says 450 while
the scored count says 100. Keying resume on ``idx`` alone therefore skips
exactly the designs a resume exists to repair: the retry after a partial OOM
reproduces the gap byte for byte, prints "skipping 450 already-completed
binders", and exits 0.

That is not hypothetical. On 2026-10-31 an ESMFold2 run on the TfR1 pool OOMed
from binder #12 and wrote 92 blank rows; ESMFold2's resume re-ran them because
it keys on the score. AF3's did not have that fix, and the only reason it did no
damage that day is that the pool happened to be appended to rather than
reordered. The comment on the ESMFold2 version records the same bug being fixed
there once already.

The script cannot be imported in the test env -- it needs gemmi, which lives
only in binder-eval-af3 -- so this extracts the one function and executes it.
That is a real behavioural test, not a text match: it fails if the gate is
removed, whatever the surrounding source looks like. A second test pins the call
site, because a helper that nothing calls is still a bug.
"""

from __future__ import annotations

import ast
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "Evaluator" / "scripts" / "refold_af3.py"
HELPER = "_completed_indices"


def _load_helper():
    """Compile just `_completed_indices` out of the script and return it.

    It needs only `csv` and `Path`, both of which this test already has, so the
    function runs here exactly as it runs inside the refolder.
    """
    tree = ast.parse(SCRIPT.read_text())
    fn = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == HELPER),
        None,
    )
    assert fn is not None, (
        f"refold_af3.py has no {HELPER}(). The resume skip-set must live in one "
        "named function so it can be tested without a GPU; inline in main() it cannot be."
    )
    ns: dict = {"csv": csv, "Path": Path}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SCRIPT), "exec"), ns)
    return ns[HELPER]


def _write_csv(path: Path, rows: list[dict]) -> Path:
    cols = ["idx", "run_id", "sequence", "iptm", "ptm"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


def test_a_scored_row_is_skipped(tmp_path):
    fn = _load_helper()
    p = _write_csv(tmp_path / "af3.csv", [{"idx": 0, "sequence": "AAA", "iptm": "0.83", "ptm": "0.9"}])
    done, blank = fn(p)
    assert done == {0}
    assert blank == 0


def test_a_blank_row_is_NOT_skipped(tmp_path):
    """The whole point: a row with no score is unfinished work, not finished work."""
    fn = _load_helper()
    p = _write_csv(tmp_path / "af3.csv", [{"idx": 7, "sequence": "AAA", "iptm": "", "ptm": ""}])
    done, blank = fn(p)
    assert done == set(), (
        "a blank row was treated as completed. A retry would skip it forever, so a pool "
        "that lost designs to an OOM can never be repaired and reports itself clean."
    )
    assert blank == 1


def test_a_partially_scored_pool_reruns_exactly_the_blanks(tmp_path):
    """The real shape of the failure: 100 scored, 350 blank, out of 450 rows."""
    fn = _load_helper()
    rows = [{"idx": i, "sequence": "AAA", "iptm": "0.7" if i < 100 else "", "ptm": ""} for i in range(450)]
    done, blank = fn(_write_csv(tmp_path / "af3.csv", rows))
    assert done == set(range(100))
    assert blank == 350
    assert len(done) != len(rows), "every row was skipped -- this is the bug, not the fix"


def test_whitespace_is_not_a_score(tmp_path):
    fn = _load_helper()
    p = _write_csv(tmp_path / "af3.csv", [{"idx": 3, "sequence": "AAA", "iptm": "   ", "ptm": ""}])
    done, blank = fn(p)
    assert done == set()
    assert blank == 1


def test_an_unparsable_idx_is_ignored_not_crashed_on(tmp_path):
    fn = _load_helper()
    rows = [
        {"idx": "", "sequence": "AAA", "iptm": "0.8"},
        {"idx": "nope", "sequence": "BBB", "iptm": "0.8"},
        {"idx": 5, "sequence": "CCC", "iptm": "0.8"},
    ]
    done, _ = fn(_write_csv(tmp_path / "af3.csv", rows))
    assert done == {5}


def _entrypoint():
    """The `if __name__ == "__main__":` block -- this script has no main()."""
    tree = ast.parse(SCRIPT.read_text())
    for n in tree.body:
        if (
            isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "__name__"
        ):
            return n
    raise AssertionError('refold_af3.py has no `if __name__ == "__main__":` block')


def test_the_entrypoint_actually_calls_the_helper():
    """A helper nothing calls is still a bug.

    Pins the call site as well as the function, so deleting the call -- leaving a
    correct, tested, unused helper and the old inline skip-set behind -- fails.
    """
    entry = _entrypoint()
    calls = [
        n for n in ast.walk(entry) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == HELPER
    ]
    assert calls, f"the entrypoint never calls {HELPER}() -- the resume path is not using the tested logic"


def test_no_ungated_skip_set_survives_alongside_it():
    """Two paths means the wrong one can be reached."""
    entry = _entrypoint()
    bare = [
        n
        for n in ast.walk(entry)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "skip"
    ]
    assert not bare, (
        "the entrypoint still builds the resume skip-set inline with skip.add(...). That is "
        "the ungated path this fix removes."
    )
