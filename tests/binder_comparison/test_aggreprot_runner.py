"""AggreProt screen: reduce a per-residue aggregation profile to comparable columns.

AggreProt (Loschmidt Lab, NAR 2024 52(W1):W159) predicts aggregation-prone
regions with an ensemble of five DNNs and outputs a **per-residue profile**, not
a score. Item D3's test — "rank correlation vs soluprot_score" — is therefore
not executable as written: a profile cannot be rank-correlated against a scalar
until it has been reduced, and *which* reduction is an open design decision the
assessment never names.

So this module emits every defensible reduction rather than choosing one, and
these tests pin their behaviour. The choice of which to present is deliberately
left downstream.

The reductions are pure arithmetic over a list of floats, so they are fully
specified and fully testable here — unlike the parser and the tool invocation,
which cannot be validated until the group supplies the model.
"""

import pytest
from binder_comparison.refolding.aggreprot_runner import (
    APR_THRESHOLD,
    reduce_profile,
)

# A profile with one clear aggregation-prone region: residues 3-7 above 0.5.
PROFILE = [0.1, 0.2, 0.1, 0.8, 0.9, 0.7, 0.85, 0.6, 0.2, 0.1]
FLAT_LOW = [0.1] * 10
ALL_HIGH = [0.9] * 10


def test_reduces_to_every_defensible_statistic():
    r = reduce_profile(PROFILE)
    for key in (
        "aggreprot_max",
        "aggreprot_mean",
        "aggreprot_apr_fraction",
        "aggreprot_apr_count",
        "aggreprot_apr_longest",
    ):
        assert key in r, f"{key} missing — the reduction choice must stay open"


def test_max_and_mean():
    r = reduce_profile(PROFILE)
    assert r["aggreprot_max"] == pytest.approx(0.9)
    assert r["aggreprot_mean"] == pytest.approx(sum(PROFILE) / len(PROFILE))


def test_apr_fraction_counts_residues_over_the_threshold():
    r = reduce_profile(PROFILE)
    # 0.8, 0.9, 0.7, 0.85, 0.6 -> 5 of 10
    assert r["aggreprot_apr_fraction"] == pytest.approx(0.5)


def test_apr_count_is_regions_not_residues():
    """Five contiguous hot residues are ONE region, not five.

    This is the distinction that makes count and fraction different signals:
    a protein with one long sticky patch and one with five scattered hot spots
    can share a fraction and mean very different things for engineering.
    """
    assert reduce_profile(PROFILE)["aggreprot_apr_count"] == 1
    scattered = [0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1]
    assert reduce_profile(scattered)["aggreprot_apr_count"] == 5
    assert reduce_profile(scattered)["aggreprot_apr_fraction"] == pytest.approx(0.5)


def test_apr_longest_is_the_longest_run():
    assert reduce_profile(PROFILE)["aggreprot_apr_longest"] == 5
    assert reduce_profile([0.9, 0.9, 0.1, 0.9, 0.1])["aggreprot_apr_longest"] == 2


def test_no_apr_at_all():
    r = reduce_profile(FLAT_LOW)
    assert r["aggreprot_apr_count"] == 0
    assert r["aggreprot_apr_fraction"] == 0.0
    assert r["aggreprot_apr_longest"] == 0


def test_entirely_aggregation_prone():
    r = reduce_profile(ALL_HIGH)
    assert r["aggreprot_apr_count"] == 1
    assert r["aggreprot_apr_fraction"] == pytest.approx(1.0)
    assert r["aggreprot_apr_longest"] == 10


def test_threshold_is_explicit_and_overridable():
    """The APR cutoff decides three of the five columns, so it must not be
    buried as a literal."""
    assert 0.0 < APR_THRESHOLD < 1.0
    loose = reduce_profile(PROFILE, threshold=0.05)
    assert loose["aggreprot_apr_fraction"] == pytest.approx(1.0)


def test_empty_profile_is_not_a_zero_score():
    """A sequence AggreProt did not score must be distinguishable from one it
    scored as perfectly soluble."""
    r = reduce_profile([])
    assert all(v is None for v in r.values()), f"expected all-None, got {r}"
