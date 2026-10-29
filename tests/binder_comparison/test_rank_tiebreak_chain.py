"""The tiebreak chain under ``consensus_iptm_mean``: engine count, ``consensus_iptm``, then binder pLDDT.

``rank_designs`` sorts on ``passes_engine_gate``, ``consensus_iptm_mean``,
``consensus_iptm_n``, ``consensus_iptm`` and, last, binder pLDDT, every key descending.
The chain is written down twice (the ``rank_designs`` docstring and the "Rank" paragraph
of CLAUDE.md). At this commit no link of it is pinned by a test: flipping the direction
of any key below the mean, or dropping it, leaves the whole suite green.

The first link only looks pinned. ``test_scoring.test_engine_count_breaks_ties_toward_more_evidence``
feeds it 0.80s, which average to 0.8000000000000002 over three engines and to exactly 0.8
over two, so the MEAN puts the three-engine row first and the engine-count key is never
consulted. The last two links, and the ``plddt_binder_mean`` / ``boltz_plddt_binder_mean``
lookup that feeds the final one, run in every ranking test and are asserted by none.

This is not a regression test for a known shipped defect; it pins a documented contract.
What it guards against has the shape of the failures this project has shipped before:
exit 0, a complete ``metrics.csv`` and Top-30, and on every tie the worse design on top.

Reaching these keys is the hard part, which is why the fixtures look odd. They only
decide the order when the keys above them tie EXACTLY, and float iPTMs do not tie by
accident. (0.70, 0.70, 0.70) against (0.90, 0.60, 0.60) reads like a tie but is not one:
pandas 2.3.3 (the CI pin) computes those means as 0.6999999999999998 and
0.7000000000000001, so the mean itself decides the order and a test built on them passes
whatever the tiebreak does. The values below are halves and quarters, which are exact in
binary, and every test asserts on the ranked output that the keys above the one under
test really are equal. Someone "tidying" 0.75 / 0.25 into 0.9 / 0.6 then gets a loud
failure here instead of a test that has quietly stopped pinning anything.

``sort_values`` is stable, so a tiebreak that has been dropped leaves tied rows in the
order they were given. Each case therefore runs with the pair in both orders: whichever
way round the literal is written, one of the two runs puts the expected winner second,
and that is the run a dropped key fails.
"""

import pandas as pd
import pytest
from binder_comparison.comparison.scoring import MIN_ENGINES_DEFAULT, rank_designs

_BOTH_ROW_ORDERS = pytest.mark.parametrize("reverse_input", [False, True], ids=["rows_as_written", "rows_reversed"])


def _ranked(df: pd.DataFrame, reverse_input: bool, min_engines: int = MIN_ENGINES_DEFAULT) -> pd.DataFrame:
    """``rank_designs`` best first, fed the rows in either order (default gate unless told otherwise)."""
    out = rank_designs(df.iloc[::-1] if reverse_input else df, min_engines=min_engines)
    return out.sort_values("rank")


def _assert_tied_through(out: pd.DataFrame, *keys: str) -> None:
    """Fail loudly unless both rows tie EXACTLY on every key above the one under test.

    ``nunique() == 1`` is an exact float comparison, which is the point: ``approx`` here
    would wave through the one-ulp near-miss that makes a seemingly tied fixture vacuous.
    """
    assert out["passes_engine_gate"].all(), "both rows must clear the gate, or the gate orders them, not the tiebreak"
    for key in keys:
        assert out[key].nunique() == 1, (
            f"the fixture no longer ties on {key} ({out[key].tolist()}), so the tiebreak under test is never "
            f"reached and this test would pass whatever that tiebreak does"
        )


@_BOTH_ROW_ORDERS
def test_a_tie_on_the_mean_goes_to_more_engines_even_against_a_higher_consensus_iptm(reverse_input):
    """Equal mean: the design more engines back ranks first, and that beats a higher best-engine iPTM.

    fewer_engines: 0.75 / 0.25 / (none)  -> mean 0.5, 2 engines, max 0.75
    more_engines:  0.50 / 0.50 / 0.50    -> mean 0.5, 3 engines, max 0.50

    The higher max sits on the row with FEWER engines, so this one fixture pins the
    direction of the engine-count key, its presence, and its priority over
    ``consensus_iptm``: flip it, drop it or swap the two and ``fewer_engines`` wins.
    Both means are bit-identical (1.0 / 2 and 1.5 / 3 are exactly 0.5), unlike the
    0.80s in ``test_scoring``. Two engines clear the gate only at ``min_engines=2``.
    """
    nan = float("nan")
    df = pd.DataFrame(
        {
            "id": ["fewer_engines", "more_engines"],
            "boltz_pae_iptm": [0.75, 0.50],
            "af3_pae_iptm": [0.25, 0.50],
            "esmfold2_pae_iptm": [nan, 0.50],
        }
    )
    out = _ranked(df, reverse_input, min_engines=2)
    _assert_tied_through(out, "consensus_iptm_mean")
    assert out["id"].tolist() == ["more_engines", "fewer_engines"], (
        "on an exact tie of consensus_iptm_mean the design backed by more engines must win, "
        "even against a higher consensus_iptm"
    )


@_BOTH_ROW_ORDERS
def test_a_tie_on_mean_and_engine_count_goes_to_the_higher_consensus_iptm(reverse_input):
    """Equal mean, equal engine count: the design whose best engine is more confident ranks first.

    lower_max:  0.50 / 0.50 / 0.50  -> mean 0.5, max 0.50
    higher_max: 0.75 / 0.25 / 0.50  -> mean 0.5, max 0.75

    Both triples sum to exactly 1.5 in binary, so the two means are bit-identical.
    """
    df = pd.DataFrame(
        {
            "id": ["lower_max", "higher_max"],
            "boltz_pae_iptm": [0.50, 0.75],
            "af3_pae_iptm": [0.50, 0.25],
            "esmfold2_pae_iptm": [0.50, 0.50],
        }
    )
    out = _ranked(df, reverse_input)
    _assert_tied_through(out, "consensus_iptm_mean", "consensus_iptm_n")
    assert out["id"].tolist() == ["higher_max", "lower_max"], (
        "on an exact tie of consensus_iptm_mean and consensus_iptm_n the higher consensus_iptm must win"
    )


@pytest.mark.parametrize("plddt_col", ["plddt_binder_mean", "boltz_plddt_binder_mean"])
@_BOTH_ROW_ORDERS
def test_binder_plddt_breaks_a_tie_on_everything_above_it_and_higher_wins(plddt_col, reverse_input):
    """Identical engine scores in both rows, so only binder pLDDT can separate them.

    The report's frame carries both columns (``compute_ensemble_metrics`` copies
    ``boltz_plddt_binder_mean`` into ``plddt_binder_mean``); a library caller that ranks a
    merged frame directly carries only the prefixed one. Each must work on its own.
    """
    df = pd.DataFrame(
        {
            "id": ["weaker_fold", "stronger_fold"],
            "boltz_pae_iptm": [0.70, 0.70],
            "af3_pae_iptm": [0.70, 0.70],
            "esmfold2_pae_iptm": [0.70, 0.70],
            plddt_col: [0.55, 0.92],
        }
    )
    out = _ranked(df, reverse_input)
    _assert_tied_through(out, "consensus_iptm_mean", "consensus_iptm_n", "consensus_iptm")
    assert out["id"].tolist() == ["stronger_fold", "weaker_fold"], (
        f"with everything above it tied, the higher {plddt_col} must win"
    )


@_BOTH_ROW_ORDERS
def test_consensus_iptm_is_consulted_before_binder_plddt(reverse_input):
    """The chain's order, not only its members: a better fold must not leapfrog a higher best-engine iPTM.

    Same exact tie on mean and engine count as above, but now binder pLDDT points the
    OTHER way. Putting pLDDT ahead of ``consensus_iptm`` (or in place of it) hands the
    win to ``lower_max_better_fold``.
    """
    df = pd.DataFrame(
        {
            "id": ["lower_max_better_fold", "higher_max_worse_fold"],
            "boltz_pae_iptm": [0.50, 0.75],
            "af3_pae_iptm": [0.50, 0.25],
            "esmfold2_pae_iptm": [0.50, 0.50],
            "plddt_binder_mean": [0.95, 0.40],
        }
    )
    out = _ranked(df, reverse_input)
    _assert_tied_through(out, "consensus_iptm_mean", "consensus_iptm_n")
    assert out["id"].tolist() == ["higher_max_worse_fold", "lower_max_better_fold"], (
        "consensus_iptm is consulted before binder pLDDT: the higher consensus_iptm must win even against "
        "a better-folded binder"
    )
