"""A design demoted by the cross-engine gate must say so in the operator's notes.

`rank_designs` puts gate failures last *regardless of score*, which makes the gate
the only criterion in the report that actually reorders the table. So a gate
failure is the single most important thing to explain, and it was the one thing
`annotate_wetlab_recommended` did not mention.

Measured 2026-09-27 on an 8-tool pool: the PXDesign design had the pool's best
`consensus_iptm_mean` (0.9646) and was correctly ranked 8/8 for having only two
engines — with an empty `Notes` cell, while all seven designs that *passed* the
gate carried "agreement 0 < 2". An operator reading that table would conclude the
best-scoring design was inexplicably last.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.scoring import annotate_wetlab_recommended  # noqa: E402


def _pool() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sequence": ["AAAA", "CCCC", "GGGG"],
            "consensus_iptm_mean": [0.96, 0.82, 0.70],
            "consensus_iptm_n": [2, 3, 3],
            "passes_engine_gate": [False, True, True],
        }
    )


def test_the_gate_failure_is_named_in_the_reason():
    out = annotate_wetlab_recommended(_pool())
    reason = str(out.loc[0, "wetlab_reason"])
    assert "gate" in reason.lower(), f"gate failure left unexplained: {reason!r}"
    assert "2" in reason, f"the reason should name the engine count it actually had: {reason!r}"


def test_designs_that_pass_the_gate_are_not_blamed_for_it():
    out = annotate_wetlab_recommended(_pool())
    for i in (1, 2):
        assert "gate" not in str(out.loc[i, "wetlab_reason"]).lower(), (
            "a design that cleared the gate must not carry a gate reason"
        )


def test_an_unassessed_gate_blames_nobody():
    """NaN means the gate was not evaluated, which is not a defect in the design.
    This mirrors the NaN policy the rest of the function follows."""
    df = _pool()
    df["passes_engine_gate"] = [None, None, None]
    out = annotate_wetlab_recommended(df)
    for i in range(3):
        assert "gate" not in str(out.loc[i, "wetlab_reason"]).lower()


def test_it_survives_a_pool_with_no_engine_count():
    """consensus_iptm_n is not guaranteed present; the reason must still be given."""
    df = _pool().drop(columns=["consensus_iptm_n"])
    out = annotate_wetlab_recommended(df)
    assert "gate" in str(out.loc[0, "wetlab_reason"]).lower()
