"""Tests for the two-stage ranking and chain-iPTM derivation — no GPU, no refold.

Covers the report's default ranking path (rank_by_two_stage) and the canonical
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
    rank_by_two_stage,
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


# --- rank_by_two_stage --------------------------------------------------------


def _two_engine_df():
    """Four designs with two engine iPTMs each. Crafted so the max-screen and the
    mean-rank disagree: design B has a high MAX (passes screen) but a low MEAN,
    while design C has a higher MEAN but a low MAX (fails screen).

    Only two engines, so callers pass min_engines=2 to isolate the screen mechanics
    from the cross-engine support gate (which defaults to 3)."""
    return pd.DataFrame(
        {
            "id": ["A", "B", "C", "D"],
            "boltz_pae_iptm": [0.90, 0.85, 0.60, 0.50],
            "af3_pae_iptm": [0.90, 0.00, 0.60, 0.50],
        }
    )
    # max:  A 0.90, B 0.85, C 0.60, D 0.50   → top-2 screen = {A, B}
    # mean: A 0.90, B 0.425, C 0.60, D 0.50


def test_two_stage_survivors_rank_above_nonsurvivors_despite_lower_mean():
    """The load-bearing property: passes_max_screen is the PRIMARY sort key, so a
    max-screen survivor (B, mean 0.425) outranks a non-survivor (C, mean 0.60)."""
    out = rank_by_two_stage(_two_engine_df(), screen_frac=0.5, screen_metric="max", min_engines=2)
    order = out.sort_values("two_stage_rank")["id"].tolist()
    assert order == ["A", "B", "C", "D"]
    rank = dict(zip(out["id"], out["two_stage_rank"]))
    assert rank["B"] < rank["C"]  # survivor beats higher-mean non-survivor


def test_two_stage_screen_keeps_top_frac_by_max():
    out = rank_by_two_stage(_two_engine_df(), screen_frac=0.5, screen_metric="max", min_engines=2)
    passed = set(out.loc[out["passes_max_screen"], "id"])
    assert passed == {"A", "B"}


def test_two_stage_screen_metric_mean_differs_from_default_max():
    """screen_metric='mean' screens on consensus_iptm_mean, keeping C (high mean, low
    max); the default max-screen keeps B instead — the two screens are genuinely different."""
    out = rank_by_two_stage(_two_engine_df(), screen_frac=0.5, screen_metric="mean", min_engines=2)
    passed = set(out.loc[out["passes_max_screen"], "id"])
    assert passed == {"A", "C"}  # top-2 by mean = {A 0.90, C 0.60}; not B (0.425)


def test_two_stage_default_screen_metric_is_max():
    """Omitting screen_metric uses the default max-screen (lenient recall): top-2 by
    max = {A 0.90, B 0.85}, so B (high max, low mean) is kept over C; Stage 2 then
    ranks the survivors by mean."""
    default = rank_by_two_stage(_two_engine_df(), screen_frac=0.5, min_engines=2)
    explicit = rank_by_two_stage(_two_engine_df(), screen_frac=0.5, screen_metric="max", min_engines=2)
    assert default["two_stage_rank"].tolist() == explicit["two_stage_rank"].tolist()
    assert set(default.loc[default["passes_max_screen"], "id"]) == {"A", "B"}


def test_two_stage_handles_nan_consensus_rows():
    """A design with no engine iPTMs (all NaN) must sort last, not crash."""
    df = _two_engine_df()
    df.loc[len(df)] = {"id": "E", "boltz_pae_iptm": float("nan"), "af3_pae_iptm": float("nan")}
    out = rank_by_two_stage(df, screen_frac=0.5, min_engines=2)
    last_id = out.sort_values("two_stage_rank")["id"].tolist()[-1]
    assert last_id == "E"
    assert not bool(out.loc[out["id"] == "E", "passes_max_screen"].iloc[0])


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


def test_single_engine_design_cannot_pass_the_screen():
    """Regression: consensus_iptm_mean skips missing engines, so a design only
    Boltz-2 refolded used to compete against 3-engine means on the same scale —
    and for a Mosaic design that engine is its own designer."""
    out = rank_by_two_stage(_mixed_coverage_df(), min_engines=MIN_ENGINES_DEFAULT)
    passed = set(out.loc[out["passes_max_screen"], "id"])
    assert "S" not in passed
    assert passed == {"F"}  # only the 3-engine design is eligible


def test_gate_of_two_admits_the_two_engine_design():
    out = rank_by_two_stage(_mixed_coverage_df(), min_engines=2)
    eligible = set(out.loc[out["passes_max_screen"], "id"])
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
    out = rank_by_two_stage(df, min_engines=2)
    rank = dict(zip(out["id"], out["two_stage_rank"]))
    assert rank["three"] < rank["two"]


def test_min_engines_below_floor_is_rejected():
    with pytest.raises(ValueError, match="below the floor"):
        rank_by_two_stage(_mixed_coverage_df(), min_engines=1)


def test_warns_when_the_gate_empties_the_screen():
    """A pool that no engine trio covers must say so, not silently report that
    nothing is good enough."""
    df = pd.DataFrame({"id": ["A"], "boltz_pae_iptm": [0.9], "af3_pae_iptm": [float("nan")]})
    with pytest.warns(UserWarning, match="no design was refolded by 3"):
        out = rank_by_two_stage(df, min_engines=3)
    assert not out["passes_max_screen"].any()


# --- Stage-1 screen size (ceil, not banker's rounding) ------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (10, 5)],
)
def test_screen_keeps_ceil_half_of_the_eligible_pool(n, expected):
    """round() is banker's rounding: round(1*0.5) == 0 kept NOTHING for a single
    design, and n=5 kept 2 (40%) rather than 3."""
    df = pd.DataFrame(
        {
            "id": [f"d{i}" for i in range(n)],
            "boltz_pae_iptm": [0.9 - i * 0.01 for i in range(n)],
            "af3_pae_iptm": [0.9 - i * 0.01 for i in range(n)],
        }
    )
    out = rank_by_two_stage(df, screen_frac=0.5, min_engines=2)
    assert int(out["passes_max_screen"].sum()) == expected
    assert expected == math.ceil(n * 0.5)
