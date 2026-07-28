"""Tests for the ranking and chain-iPTM derivation — no GPU, no refold.

Covers the report's ranking path (rank_designs) and the canonical
ESMFold2 interface chain-pair iPTM derivation (add_chain_iptm_interface), which the
ESMFold2 autosize gate will also consume.
"""

import pytest

pytest.importorskip("pandas")
import math

import pandas as pd
from binder_comparison.comparison.scoring import (
    MIN_ENGINES_DEFAULT,
    MIN_ENGINES_FLOOR,
    add_chain_iptm_interface,
    compute_consensus_ipsae,
    compute_consensus_iptm,
    rank_designs,
)

# --- add_chain_iptm_interface -------------------------------------------------


def test_chain_iptm_prefixed_is_mean_of_pair_and_pair_min():
    df = pd.DataFrame({"esmfold2_iptm_pair": [0.8, 0.6], "esmfold2_iptm_pair_min": [0.6, 0.4]})
    out = add_chain_iptm_interface(df, prefix="esmfold2")
    assert out["esmfold2_chain_iptm_interface"].tolist() == [0.7, 0.5]


def test_chain_iptm_raw_prefix_for_loop_gate():
    """prefix='' serves the raw refold CSV the autosize loop reads."""
    df = pd.DataFrame({"iptm_pair": [0.9], "iptm_pair_min": [0.5]})
    out = add_chain_iptm_interface(df, prefix="")
    assert out["chain_iptm_interface"].tolist() == [0.7]


def test_chain_iptm_coerces_string_csv_values():
    """A raw CSV gives strings; the derivation must coerce, not concatenate."""
    df = pd.DataFrame({"iptm_pair": ["0.6"], "iptm_pair_min": ["0.4"]})
    out = add_chain_iptm_interface(df, prefix="")
    assert out["chain_iptm_interface"].tolist() == [0.5]


def test_chain_iptm_noop_when_pair_columns_absent():
    df = pd.DataFrame({"x": [1]})
    out = add_chain_iptm_interface(df, prefix="esmfold2")
    assert "esmfold2_chain_iptm_interface" not in out.columns


# --- rank_designs --------------------------------------------------------


def _two_engine_df():
    """Four designs with two engine iPTMs each. Crafted so a max-ordering and the
    mean-ordering disagree: design B has a high MAX but a low MEAN, while design C
    has a higher MEAN but a low MAX.

    Only two engines, so callers pass min_engines=2 to isolate the ranking from the
    cross-engine gate (which defaults to 3)."""
    return pd.DataFrame(
        {
            "id": ["A", "B", "C", "D"],
            "boltz_pae_iptm": [0.90, 0.85, 0.60, 0.50],
            "af3_pae_iptm": [0.90, 0.00, 0.60, 0.50],
        }
    )
    # max:  A 0.90, B 0.85, C 0.60, D 0.50
    # mean: A 0.90, B 0.425, C 0.60, D 0.50


def test_rank_is_consensus_iptm_mean_descending():
    """Part U: the ranking is the mean, full stop. C (mean 0.60) outranks B
    (mean 0.425) even though B has the higher max — no screen intervenes."""
    out = rank_designs(_two_engine_df(), min_engines=2)
    assert out.sort_values("rank")["id"].tolist() == ["A", "C", "D", "B"]


def test_rank_column_is_named_rank_and_is_the_only_one():
    """The three legacy rank columns were removed in Part U — a clean break."""
    out = rank_designs(_two_engine_df(), min_engines=2)
    assert "rank" in out.columns
    for gone in ("two_stage_rank", "adaptyv_rank", "consensus_rank", "active_rank", "passes_max_screen"):
        assert gone not in out.columns, f"{gone} should have been removed in Part U"


def test_rank_is_dense_and_starts_at_one():
    out = rank_designs(_two_engine_df(), min_engines=2)
    assert out["rank"].tolist() == [1, 2, 3, 4]


def test_gate_failures_rank_last_but_are_not_dropped():
    """Nothing disappears silently: an ineligible design is ranked, just last."""
    df = _two_engine_df()
    df.loc[len(df)] = {"id": "S", "boltz_pae_iptm": 0.99, "af3_pae_iptm": float("nan")}
    out = rank_designs(df, min_engines=2)
    assert len(out) == 5  # kept
    assert out.sort_values("rank")["id"].tolist()[-1] == "S"  # but last
    assert not bool(out.loc[out["id"] == "S", "passes_engine_gate"].iloc[0])


def test_handles_nan_consensus_rows():
    """A design with no engine iPTMs (all NaN) must sort last, not crash."""
    df = _two_engine_df()
    df.loc[len(df)] = {"id": "E", "boltz_pae_iptm": float("nan"), "af3_pae_iptm": float("nan")}
    out = rank_designs(df, min_engines=2)
    assert out.sort_values("rank")["id"].tolist()[-1] == "E"
    assert not bool(out.loc[out["id"] == "E", "passes_engine_gate"].iloc[0])


# --- consensus_iptm_spread / consensus_ipsae_min_spread (Item 4) -------------


def test_consensus_iptm_spread_is_max_minus_min():
    """The per-row spread surfaced as the engine-disagreement signal must equal max − min."""
    df = pd.DataFrame(
        {
            "boltz_pae_iptm": [0.90, 0.85, 0.50],  # spreads: 0.05, 0.45, 0.00
            "af3_pae_iptm": [0.88, 0.40, 0.50],
            "esmfold2_pae_iptm": [0.85, 0.42, 0.50],
        }
    )
    out = compute_consensus_iptm(df)
    spreads = out["consensus_iptm_spread"].round(2).tolist()
    assert spreads == [0.05, 0.45, 0.00]


def test_consensus_iptm_spread_is_nan_when_single_engine():
    """A row with only one engine present has no measurable disagreement."""
    df = pd.DataFrame({"boltz_pae_iptm": [0.9, 0.8], "af3_pae_iptm": [0.85, float("nan")]})
    out = compute_consensus_iptm(df)
    # Row 0: 2 engines → spread defined; Row 1: 1 engine → spread NaN
    assert math.isfinite(out["consensus_iptm_spread"].iloc[0])
    assert math.isnan(out["consensus_iptm_spread"].iloc[1])


def test_consensus_ipsae_min_spread_added():
    """ipSAE_min spread mirrors the iPTM spread for the engine-disagreement flag."""
    df = pd.DataFrame(
        {
            "boltz_pae_ipsae_min": [0.85, 0.30],
            "af3_ipsae_min": [0.82, 0.80],
        }
    )
    out = compute_consensus_ipsae(df)
    assert "consensus_ipsae_min_spread" in out.columns
    spreads = out["consensus_ipsae_min_spread"].round(2).tolist()
    assert spreads == [0.03, 0.50]


def test_consensus_iptm_spread_empty_when_no_engines_present():
    """Defensive: even with zero engine columns the spread column is initialised."""
    df = pd.DataFrame({"id": ["a", "b"]})
    out = compute_consensus_iptm(df)
    assert "consensus_iptm_spread" in out.columns
    assert out["consensus_iptm_spread"].isna().all()


# --- Cross-engine support gate (min_engines) ----------------------------------


def _mixed_coverage_df():
    """Three designs with DIFFERENT engine coverage.

    S is refolded by one engine only and has the single highest value; M by two;
    F by all three but with the lowest numbers. Without the gate, S wins outright
    because consensus_iptm_mean skips NaN and therefore equals S's lone value.
    """
    nan = float("nan")
    return pd.DataFrame(
        {
            "id": ["S", "M", "F"],
            "boltz_pae_iptm": [0.95, 0.80, 0.70],
            "af3_pae_iptm": [nan, 0.80, 0.70],
            "esmfold2_pae_iptm": [nan, nan, 0.70],
        }
    )


def test_default_min_engines_is_three():
    assert MIN_ENGINES_DEFAULT == 3
    assert MIN_ENGINES_FLOOR == 2


def test_single_engine_design_cannot_clear_the_gate():
    """Regression: consensus_iptm_mean skips missing engines, so a design only
    Boltz-2 refolded used to compete against 3-engine means on the same scale —
    and for a Mosaic design that engine is its own designer."""
    out = rank_designs(_mixed_coverage_df(), min_engines=MIN_ENGINES_DEFAULT)
    passed = set(out.loc[out["passes_engine_gate"], "id"])
    assert "S" not in passed
    assert passed == {"F"}  # only the 3-engine design is eligible


def test_gate_of_two_admits_the_two_engine_design():
    out = rank_designs(_mixed_coverage_df(), min_engines=2)
    eligible = set(out.loc[out["passes_engine_gate"], "id"])
    assert "S" not in eligible
    assert eligible <= {"M", "F"} and eligible


def test_engine_count_breaks_ties_toward_more_evidence():
    """Equal means must resolve toward the design more engines agree on."""
    df = pd.DataFrame(
        {
            "id": ["two", "three"],
            "boltz_pae_iptm": [0.80, 0.80],
            "af3_pae_iptm": [0.80, 0.80],
            "esmfold2_pae_iptm": [float("nan"), 0.80],
        }
    )
    out = rank_designs(df, min_engines=2)
    rank = dict(zip(out["id"], out["rank"]))
    assert rank["three"] < rank["two"]


def test_min_engines_below_floor_is_rejected():
    with pytest.raises(ValueError, match="below the floor"):
        rank_designs(_mixed_coverage_df(), min_engines=1)


def test_warns_when_the_gate_admits_nothing():
    """A pool that no engine trio covers must say so, not silently report that
    nothing is good enough."""
    df = pd.DataFrame({"id": ["A"], "boltz_pae_iptm": [0.9], "af3_pae_iptm": [float("nan")]})
    with pytest.warns(UserWarning, match="no design was refolded by 3"):
        out = rank_designs(df, min_engines=3)
    assert not out["passes_engine_gate"].any()


# --- Report truthfulness -------------------------------------------------------


def test_wetlab_not_blocked_by_unassessable_agreement():
    """Regression: agreement_count cannot exceed the engines that ran, so on a
    single-engine install the >=2 rule failed EVERY design for a reason no design
    change could fix, making the column uninformative."""
    from binder_comparison.comparison.scoring import annotate_wetlab_recommended

    df = pd.DataFrame(
        {
            "id": ["A", "B"],
            "agreement_count": [1, 1],
            "consensus_iptm_n": [1, 1],
            "plddt_binder_min": [0.90, 0.85],
        }
    )
    with pytest.warns(UserWarning, match="could not be assessed"):
        out = annotate_wetlab_recommended(df)
    assert out["wetlab_recommended"].all(), "a 1-engine run must not fail every design"


def test_wetlab_still_blocks_real_disagreement():
    """With enough engines present, a genuinely low agreement_count must still block."""
    from binder_comparison.comparison.scoring import annotate_wetlab_recommended

    df = pd.DataFrame(
        {
            "id": ["good", "lonely"],
            "agreement_count": [3, 1],
            "consensus_iptm_n": [3, 3],
            "plddt_binder_min": [0.90, 0.90],
        }
    )
    out = annotate_wetlab_recommended(df)
    rec = dict(zip(out["id"], out["wetlab_recommended"]))
    assert rec["good"] is True or rec["good"]
    assert not rec["lonely"]
    assert "agreement 1 < 2" in out.loc[out["id"] == "lonely", "wetlab_reason"].iloc[0]
