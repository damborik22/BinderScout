"""`consensus_iptm_mean` must be the plain mean over the engines that scored each design.

It is the one number the ranking sorts on (Part U: a cross-engine gate, then
`consensus_iptm_mean`), and the case for it is a property, not a convenience. iPTM is
gameable by the engine that designed the binder - Mosaic *is* Boltz-2 gradient
hallucination - so a design one engine loves and another rejects has to be DEMOTED
(CLAUDE.md, "Critical domain facts"). The mean does that. The median, the tempting
"robust" aggregate, does not: with three engines it is just the middle value, blind to
how badly the odd one out rejects the design. (0.95, 0.90, 0.10) and (0.95, 0.90, 0.85)
have the same median, so a design Boltz-2 and AF3 like and ESMFold2 rejects would head
the Top-30 over a design all three agree on.

Nothing pinned that VALUE. The ranking tests in `test_scoring.py` drive the aggregation
with exactly two engines (where mean and median are the same number), with three
IDENTICAL values (where every aggregator is), or assert only the spread, the engine
count or the resulting order, and no other test computes the mean at all - they hand
`consensus_iptm_mean` in as a literal column. Until this file, swapping
`numeric.mean(axis=1)` for `numeric.median(axis=1)` in `compute_consensus_iptm` left
every test green. What it leaves behind is the shape of every bug this project has
shipped: exit 0, a full metrics.csv, a populated `rank` column, every guard passing, the
gate still reporting three engines - and a different design at the top.

Which aggregator ranks is not settled by inertia. The CHANGELOG records the ranking's
screen metric being flipped between mean and max, and a stretch in which every report
described a mean-iPTM screen while the code ran a max one. And "the mean skips the
engines that never folded the design" is the premise the cross-engine gate is built on
(CLAUDE.md, Stage 0), so a change to NaN handling (`skipna=False`, a fixed divide by
three) breaks the same thing from the other side.

So these tests use three engines and rows chosen to tell the aggregators apart, assert
the number itself, and then assert the consequence the number exists for.
"""

import statistics

import pytest

pytest.importorskip("pandas")
import pandas as pd
from binder_comparison.comparison.scoring import (
    MIN_ENGINES_DEFAULT,
    compute_consensus_iptm,
    rank_designs,
)

_NAN = float("nan")

# (boltz, af3, esmfold2) PAE-recomputed ipTM per design. Each row earns its place:
#
#   spiky   Boltz-2 and AF3 love it, ESMFold2 rejects it.
#           mean 0.65  |  median 0.90  |  max 0.95  |  min 0.10
#   flat    all three agree, nothing spectacular. mean = median = max = 0.70, so every
#           aggregator scores this row correctly - which is what makes it the foil.
#   partial ESMFold2 never folded it. The mean is over the TWO engines that did: 0.72.
#           skipna=False would make it NaN; a fixed divide-by-3 would drag it to 0.48.
_SPIKY = (0.95, 0.90, 0.10)
_FLAT = (0.70, 0.70, 0.70)
_PARTIAL = (0.84, 0.60, _NAN)


def _frame(designs: dict[str, tuple[float, float, float]]) -> pd.DataFrame:
    """One row per design, one `<engine>_pae_iptm` column per engine, in the order given."""
    return pd.DataFrame(
        {
            "id": list(designs),
            "boltz_pae_iptm": [t[0] for t in designs.values()],
            "af3_pae_iptm": [t[1] for t in designs.values()],
            "esmfold2_pae_iptm": [t[2] for t in designs.values()],
        }
    )


def test_consensus_iptm_mean_is_the_arithmetic_mean_of_the_engines_that_scored_each_design():
    out = compute_consensus_iptm(_frame({"spiky": _SPIKY, "flat": _FLAT, "partial": _PARTIAL}))

    expected = [(0.95 + 0.90 + 0.10) / 3, 0.70, (0.84 + 0.60) / 2]
    assert out["consensus_iptm_mean"].tolist() == pytest.approx(expected), (
        "must be the arithmetic mean over the engines that scored the design - "
        "not a median, a trimmed mean or a blend, and not a sum divided by a fixed three"
    )

    # The denominator is the engines that contributed, and consensus_iptm_n is what the
    # cross-engine gate reads: the two have to agree about which engines those were.
    assert out["consensus_iptm_n"].tolist() == [3, 3, 2]


def test_a_design_two_engines_love_and_one_rejects_ranks_below_one_all_three_agree_on():
    """The property the ranking exists for, through the two calls `binder-compare report` makes.

    Both designs clear the default three-engine gate, so the order below can only come
    from the mean. The spiky design wins under every aggregator that cannot see the
    rejection - max (which Part U retired) and median - which is what makes this pair a
    test of the mean and not just of the sort.
    """
    scored = compute_consensus_iptm(_frame({"spiky": _SPIKY, "flat": _FLAT}))
    out = rank_designs(scored, min_engines=MIN_ENGINES_DEFAULT)

    assert out["passes_engine_gate"].all(), "the order must be decided by the mean, not by the gate"

    # Guards the guard: if the foil stopped beating flat under max and median, the
    # ordering assertion below would prove nothing.
    by_id = out.set_index("id")
    assert by_id.loc["spiky", "consensus_iptm"] > by_id.loc["flat", "consensus_iptm"], "max would put spiky first"
    assert statistics.median(_SPIKY) > statistics.median(_FLAT), "and so would the median"

    assert out.sort_values("rank")["id"].tolist() == ["flat", "spiky"]
