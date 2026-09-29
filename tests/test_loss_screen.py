"""The CPU loss-term screen must flag the term that was actually wrong.

`tools/loss_screen.py` exists because a Mosaic design-loss arm costs a campaign plus two
refolds, while the defects that matter are visible in the gradient in seconds. The test
that earns its keep is therefore not "does the harness run" but **does it reject the real
candidate we rejected, and accept the replacement we derived** -- so both are rebuilt here
as fixtures with the same shape as the upstream code.

Background: upstream Mosaic's ``UnigramExcess`` is ``sum(relu(empirical - natural)**2)``
over amino-acid frequencies. Being one-sided ABOVE the natural marginal makes it inert on
exactly the residues hallucination over-produces, and active only on the eight sitting
below it -- five of which are hydrophobic. The replacement is a one-sided hydrophobic
*deficit* hinge, which is silent while composition is fine and pulls the right way when it
is not.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import loss_screen as ls

# Swiss-Prot / UniProt average residue frequencies. Used to give the fixtures a REALISTIC
# SHAPE, not because the third decimal matters: what the tests depend on is which residues
# fall below 1/20, because that is what the one-sided relu keys off.
NATURAL = {
    "A": 0.0826,
    "R": 0.0553,
    "N": 0.0406,
    "D": 0.0546,
    "C": 0.0138,
    "Q": 0.0393,
    "E": 0.0674,
    "G": 0.0708,
    "H": 0.0227,
    "I": 0.0591,
    "L": 0.0966,
    "K": 0.0582,
    "M": 0.0241,
    "F": 0.0386,
    "P": 0.0472,
    "S": 0.0661,
    "T": 0.0535,
    "W": 0.0109,
    "Y": 0.0292,
    "V": 0.0686,
}

_NAT = np.array([NATURAL[a] for a in ls.ALPHABET], dtype=float)
_HYD = np.array([1.0 if a in ls.HYDROPHOBIC else 0.0 for a in ls.ALPHABET], dtype=float)


def unigram_excess(pssm):
    """The upstream shape: penalise only frequencies ABOVE the natural marginal."""
    emp = np.asarray(pssm).mean(axis=0)
    return float((np.maximum(emp - _NAT, 0.0) ** 2).sum())


def hydrophobic_deficit(pssm, target=0.38):
    """The replacement: penalise only a SHORTFALL in hydrophobic fraction."""
    hf = float((np.asarray(pssm) @ _HYD).mean())
    return float(max(target - hf, 0.0) ** 2)


# ── the fixtures the harness exists to tell apart ────────────────────────────────


def test_the_natural_marginals_have_the_shape_the_relu_keys_off():
    """Guards the fixture: the one-sided relu is active only below 1/20, and hydrophobics
    are over-represented there.

    That over-representation is the whole mechanism -- it is why a penalty that looks
    composition-neutral lands on the hydrophobic core. (The exact letter set depends on the
    marginal source: these Swiss-Prot averages put P below 1/20 as well, where the
    UniRef50-derived set bundled with Mosaic does not. The property below holds either way,
    and the property is what the tests rest on.)
    """
    below = [a for a in ls.ALPHABET if NATURAL[a] < 0.05]
    hyd_below = [a for a in below if a in ls.HYDROPHOBIC]
    assert len(hyd_below) >= 5, hyd_below
    # over-represented: a larger share of the active set than of the alphabet
    assert len(hyd_below) / len(below) > len(ls.HYDROPHOBIC) / len(ls.ALPHABET), (
        f"{len(hyd_below)}/{len(below)} of the active residues are hydrophobic, vs "
        f"{len(ls.HYDROPHOBIC)}/{len(ls.ALPHABET)} of the alphabet — the fixture does not "
        "reproduce the mechanism under test"
    )


def test_it_flags_the_unigram_penalty_for_pushing_the_wrong_way():
    """The headline. At a uniform PSSM this term suppresses hydrophobics."""
    c = ls.check_direction(unigram_excess, intent="promote")
    assert not c.passed, f"the harness passed a term that suppresses hydrophobics: {c.detail}"
    assert c.numbers["inside"] > 0, "gradient on hydrophobics should be positive (suppressive)"
    assert "WRONG SIGN" in c.detail


def test_it_measures_that_the_suppression_lands_on_hydrophobics_hardest():
    """Not just 'wrong sign somewhere' -- concentrated on the class we care about."""
    c = ls.check_direction(unigram_excess, intent="promote")
    assert c.numbers["inside"] > c.numbers["outside"] > 0, (
        f"expected more suppressive gradient inside the hydrophobic class than outside: {c.numbers}"
    )


def test_the_default_length_mode_catches_an_extensive_term():
    """The common real length bug: `sum` where `mean` was meant.

    This is what the DEFAULT (exact-frequency) mode is for. It is the design-time regime:
    a loss sees a soft PSSM, so its value is a smooth function of composition, and a term
    that scales with L penalises long binders for no compositional reason.
    """

    def extensive(pssm):  # sums over positions instead of averaging
        return float((np.asarray(pssm) @ _HYD).sum())

    def intensive(pssm):
        return float((np.asarray(pssm) @ _HYD).mean())

    bad = ls.check_length_invariance(extensive, freqs=NATURAL)
    good = ls.check_length_invariance(intensive, freqs=NATURAL)
    assert not bad.passed, f"an extensive term must be flagged: {bad.detail}"
    assert bad.numbers["ratio"] > 6, bad.numbers
    assert good.passed, f"an intensive term must pass: {good.detail}"


def test_the_sampled_mode_is_about_scoring_not_design_and_says_so():
    """Both a wrongly-shaped and a correctly-shaped one-sided term look confounded here,
    because both fire only on finite-sample excursions. That is why sampling is not the
    default -- it answers a question about scoring a finished sequence, not about steering
    a design, and reading it as the latter would reject the correct term too.
    """
    bad = ls.check_length_invariance(unigram_excess, freqs=NATURAL, sampled=True, n_samples=24)
    good = ls.check_length_invariance(hydrophobic_deficit, freqs=NATURAL, sampled=True, n_samples=24)
    for c in (bad, good):
        assert not c.passed, f"expected both to look confounded in sampled mode: {c.detail}"
        assert c.numbers[30] > c.numbers[200], "noise excursions must shrink with length"


def test_it_passes_the_replacement_deficit_hinge():
    """The good term must survive all three checks, or the harness is just a rejector."""
    poor = {**{a: 0.0 for a in ls.ALPHABET}, "E": 0.25, "K": 0.25, "S": 0.25, "T": 0.25}
    s = ls.screen_composition_term(
        hydrophobic_deficit,
        name="HydrophobicDeficit(0.38)",
        intent="promote",
        natural_freqs=NATURAL,
        satisfied_freqs=NATURAL,
        probe_freqs=poor,
    )
    assert s.ok, "the correct term was flagged:\n" + s.report()


def test_the_deficit_hinge_is_exactly_inert_when_composition_is_fine():
    c = ls.check_silence_when_satisfied(hydrophobic_deficit, satisfied_freqs=NATURAL)
    assert c.passed and c.numbers["max_grad"] == 0.0, c.detail


def test_probing_a_one_sided_hinge_at_uniform_is_reported_not_silently_passed():
    """A uniform PSSM has hydrophobic fraction 0.45, above the 0.38 target, so the hinge is
    inert there. The harness must say so and point at probe_freqs rather than either
    passing it blindly or calling it wrongly-signed."""
    c = ls.check_direction(hydrophobic_deficit, intent="promote")
    assert not c.passed
    assert "probe_freqs" in c.detail and "one-sided hinge" in c.detail


def test_order_check_calls_a_composition_term_order_blind():
    seq = "AAKEWLNQRQISFVKSHFSRQLEERLGA" * 3
    c = ls.check_order_sensitivity(unigram_excess, sequence=seq)
    assert not c.passed, "a unigram term cannot read order; the check must say so"
    assert "shuffle noise" in c.detail


def test_a_genuinely_order_sensitive_term_is_recognised():
    """Guards the order check against being a constant 'no'."""

    def adjacent_repeats(pssm):
        p = np.asarray(pssm)
        return float((p[:-1] * p[1:]).sum())

    seq = "AAAAAAAAAAAAAAGGGGGGGGGGGGGG"
    c = ls.check_order_sensitivity(adjacent_repeats, sequence=seq)
    assert c.passed, f"an order-sensitive term must be recognised as such: {c.detail}"


# ── harness mechanics ────────────────────────────────────────────────────────────


def test_report_names_the_verdict_and_every_check():
    s = ls.screen_composition_term(unigram_excess, name="UnigramExcess", intent="promote", natural_freqs=NATURAL)
    r = s.report()
    assert r.startswith("FLAG"), r
    assert "direction" in r and "length" in r


def test_intent_is_validated():
    with pytest.raises(ValueError, match=r"promote|suppress"):
        ls.check_direction(unigram_excess, intent="maximise")


def test_the_finite_difference_backend_agrees_with_an_analytic_gradient():
    """The whole harness rests on _grad being right. Check it against a closed form."""

    def quad(pssm):
        return float((np.asarray(pssm) ** 2).sum())

    p = ls.uniform_pssm(5)
    got = ls._grad(quad, p)
    np.testing.assert_allclose(got, 2.0 * p, rtol=1e-4, atol=1e-6)


def test_silence_flags_a_two_sided_penalty_that_pulls_when_nothing_is_wrong():
    """The distinction the check exists to draw: one-sided hinge vs two-sided penalty.

    A two-sided term keeps pulling at a satisfying composition, so it distorts every design
    it touches -- and invisibly, because its own reported value looks small and reasonable.
    Without this case the check could be hard-wired to pass and no test would notice.
    """

    def two_sided(pssm, target=0.38):
        hf = float((np.asarray(pssm) @ _HYD).mean())
        return float((hf - target) ** 2)  # no relu: active in both directions

    c = ls.check_silence_when_satisfied(two_sided, satisfied_freqs=NATURAL)
    assert not c.passed, f"a two-sided penalty must be flagged: {c.detail}"
    assert c.numbers["max_grad"] > 0
    assert "still pulling" in c.detail

    # ...and the one-sided version of the same idea must still pass, so the check is
    # discriminating rather than simply strict.
    ok = ls.check_silence_when_satisfied(hydrophobic_deficit, satisfied_freqs=NATURAL)
    assert ok.passed, ok.detail
