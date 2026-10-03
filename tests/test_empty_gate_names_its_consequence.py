"""When the cross-engine gate empties, say what that DOES to the ordering.

Measured 2026-10-03: with `min_engines` above the number of engines actually present,
nothing clears the gate, `passes_engine_gate` becomes constant and stops discriminating,
and the sort falls through to `consensus_iptm_mean` alone — so a design scored by ONE
engine outranks a design scored by three. That is precisely the single-engine
designer-bias failure the gate exists to prevent (Mosaic games `boltz_iptm` by
construction; BindCraft and BindCraft 2 game AF2's i_pTM the same way).

The warning already existed and already named the fix. What it did not say is the
consequence, and the consequence is the part an operator would act on: a top-10 read off
that list is not a shortlist. Deliberately a MESSAGE change, not a ranking change —
reordering the fallback would itself be an unvalidated ranking change, and Part U measured
that searching for a better ranking on our data made it worse.
"""

from __future__ import annotations

import warnings

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison import scoring  # noqa: E402


def _pool():
    """One design with 1 engine and a high mean, one with 3 engines and a lower mean."""
    return pd.DataFrame(
        {
            "sequence": ["A" * 30, "C" * 30],
            "boltz_pae_iptm": [0.99, 0.60],
            "af3_pae_iptm": [None, 0.60],
            "esmfold2_pae_iptm": [None, 0.60],
        }
    )


def test_the_inversion_is_real_and_is_what_the_warning_is_about():
    """Establish the behaviour the message has to describe, so the test is not circular."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = scoring.rank_designs(_pool(), min_engines=4)
    top = out.sort_values("rank").iloc[0]
    assert int(top["consensus_iptm_n"]) == 1, (
        f"expected the 1-engine design to be promoted to rank 1 once the gate empties; got n={top['consensus_iptm_n']}"
    )
    assert not out["passes_engine_gate"].any()


def test_the_warning_names_the_consequence_not_just_the_shortfall():
    with pytest.warns(UserWarning) as rec:
        scoring.rank_designs(_pool(), min_engines=4)
    msg = " ".join(str(w.message) for w in rec).lower()

    # the shortfall, which it always said
    assert "no design cleared" in msg
    # ...and the consequence, which it did not
    assert "outrank" in msg, f"the warning does not say a 1-engine design can outrank a 3-engine one: {msg}"
    assert "designer-bias" in msg or "designer bias" in msg, (
        "the warning should connect this to the bias the gate exists to prevent"
    )
    assert "shortlist" in msg, "the warning should tell the operator not to read the top as a shortlist"


def test_a_satisfiable_gate_stays_quiet():
    """Or the warning is noise on every well-formed run."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        out = scoring.rank_designs(_pool(), min_engines=3)
    assert out["passes_engine_gate"].sum() == 1
