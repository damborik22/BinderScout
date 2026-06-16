"""Tests for the two-stage ranking and chain-iPTM derivation — no GPU, no refold.

Covers the report's default ranking path (rank_by_two_stage) and the canonical
ESMFold2 interface chain-pair iPTM derivation (add_chain_iptm_interface), which the
ESMFold2 autosize gate will also consume.
"""

import pytest

pytest.importorskip("pandas")
import pandas as pd
from binder_comparison.comparison.scoring import (
    add_chain_iptm_interface,
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
    while design C has a higher MEAN but a low MAX (fails screen)."""
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
    screen survivor (B, mean 0.425) outranks a non-survivor (C, mean 0.60)."""
    out = rank_by_two_stage(_two_engine_df(), screen_frac=0.5)
    order = out.sort_values("two_stage_rank")["id"].tolist()
    assert order == ["A", "B", "C", "D"]
    rank = dict(zip(out["id"], out["two_stage_rank"]))
    assert rank["B"] < rank["C"]  # survivor beats higher-mean non-survivor


def test_two_stage_screen_keeps_top_frac_by_max():
    out = rank_by_two_stage(_two_engine_df(), screen_frac=0.5)
    passed = set(out.loc[out["passes_max_screen"], "id"])
    assert passed == {"A", "B"}


def test_two_stage_screen_metric_mean_changes_survivors():
    """screen_metric='mean' screens on consensus_iptm_mean, not max — so design C
    (mean 0.60) is kept over design B (mean 0.425), the reverse of the max screen."""
    out = rank_by_two_stage(_two_engine_df(), screen_frac=0.5, screen_metric="mean")
    passed = set(out.loc[out["passes_max_screen"], "id"])
    assert passed == {"A", "C"}  # top-2 by mean = {A 0.90, C 0.60}; not B (0.425)


def test_two_stage_default_screen_metric_is_max():
    """Omitting screen_metric must reproduce the shipped max-screen exactly."""
    default = rank_by_two_stage(_two_engine_df(), screen_frac=0.5)
    explicit = rank_by_two_stage(_two_engine_df(), screen_frac=0.5, screen_metric="max")
    assert default["two_stage_rank"].tolist() == explicit["two_stage_rank"].tolist()
    assert set(default.loc[default["passes_max_screen"], "id"]) == {"A", "B"}


def test_two_stage_handles_nan_consensus_rows():
    """A design with no engine iPTMs (all NaN) must sort last, not crash."""
    df = _two_engine_df()
    df.loc[len(df)] = {"id": "E", "boltz_pae_iptm": float("nan"), "af3_pae_iptm": float("nan")}
    out = rank_by_two_stage(df, screen_frac=0.5)
    last_id = out.sort_values("two_stage_rank")["id"].tolist()[-1]
    assert last_id == "E"
    assert not bool(out.loc[out["id"] == "E", "passes_max_screen"].iloc[0])
