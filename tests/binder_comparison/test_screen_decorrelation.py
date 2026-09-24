"""The harness that answers "is this screen redundant with SoluProt?" (item D3).

Validated end to end against real data before these unit tests were written: on
the 2VDY/CBG archive it reproduces Spearman -0.090 for TmProt vs SoluProt over
436 deduplicated designs, matching a hand computation done independently. These
tests pin the edges that real data happened not to exercise.
"""

import pandas as pd
import pytest
from binder_comparison.comparison.screen_decorrelation import (
    compare_screens,
    format_report,
    load_screen,
)

SEQS = [f"SEQ{i:03d}" for i in range(20)]


def _screen(col, values):
    return pd.DataFrame({"sequence": SEQS, col: values})


def _only(pairs):
    assert len(pairs) == 1, f"expected one column pair, got {[(p.left, p.right) for p in pairs]}"
    return pairs[0]


def test_a_screen_that_restates_another_is_redundant():
    a = _screen("score_a", list(range(20)))
    b = _screen("score_b", [v * 3 + 1 for v in range(20)])  # monotone in a
    p = _only(compare_screens(a, b))
    assert p.spearman == pytest.approx(1.0)
    assert p.verdict == "redundant"


def test_an_inverted_restatement_is_also_redundant():
    """Sign does not matter: a screen that is the negative of another carries
    no new information."""
    a = _screen("score_a", list(range(20)))
    b = _screen("score_b", list(range(20))[::-1])
    p = _only(compare_screens(a, b))
    assert p.spearman == pytest.approx(-1.0)
    assert p.verdict == "redundant"


def test_an_uncorrelated_screen_is_independent():
    a = _screen("score_a", [0, 1] * 10)
    b = _screen("score_b", [0, 0, 1, 1] * 5)
    assert _only(compare_screens(a, b)).verdict == "independent"


def test_every_reduction_is_compared_in_one_pass():
    """AggreProt emits several candidate reductions; D3 must be answerable for
    all of them from a single run, not one run per reduction."""
    a = pd.DataFrame(
        {
            "sequence": SEQS,
            "aggreprot_max": list(range(20)),
            "aggreprot_apr_fraction": [v % 5 for v in range(20)],
        }
    )
    b = _screen("soluprot_score", [v * 0.5 for v in range(20)])
    pairs = compare_screens(a, b)
    assert {p.left for p in pairs} == {"aggreprot_max", "aggreprot_apr_fraction"}


def test_duplicate_sequences_are_dropped_on_load(tmp_path):
    """Real screen outputs carry repeats -- both files in the 2VDY archive hold
    3 -- and a merge on a duplicated key silently weights those designs more
    heavily in the correlation."""
    p = tmp_path / "s.csv"
    pd.DataFrame({"sequence": ["A", "A", "B"], "score": [1.0, 2.0, 3.0]}).to_csv(p, index=False)
    loaded = load_screen(p)
    assert len(loaded) == 2
    assert loaded.loc[loaded.sequence == "A", "score"].item() == 1.0, "must keep the first"


def test_a_screen_without_a_sequence_column_is_refused(tmp_path):
    p = tmp_path / "s.csv"
    pd.DataFrame({"binder_id": ["a"], "score": [1.0]}).to_csv(p, index=False)
    with pytest.raises(ValueError, match="sequence"):
        load_screen(p)


def test_constant_columns_are_skipped_not_reported_as_nan():
    """soluprot_passes is often all-1 on a filtered pool; a correlation against
    a constant is undefined and must not appear as a spurious NaN row."""
    a = _screen("score_a", list(range(20)))
    b = _screen("all_same", [1] * 20)
    assert compare_screens(a, b) == []


def test_report_sorts_by_absolute_correlation():
    a = pd.DataFrame({"sequence": SEQS, "weak": [v % 3 for v in range(20)], "strong": list(range(20))})
    b = _screen("ref", list(range(20)))
    text = format_report(compare_screens(a, b))
    assert text.index("strong vs ref") < text.index("weak vs ref")
