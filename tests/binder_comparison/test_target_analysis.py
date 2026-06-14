"""Tests for the target-analysis core (difficulty score + suggestions + geometry)."""

import numpy as np
from binder_comparison.comparison.target_analysis import (
    classify_difficulty,
    difficulty_score,
    flat_surface_fraction,
    neighbor_counts,
    pick_hotspots,
    suggest_binder_length,
    suggest_campaign,
)

# --- geometry -----------------------------------------------------------------


def test_neighbor_counts():
    coords = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [100, 0, 0]], float)
    counts = neighbor_counts(coords, radius=5.0)
    assert counts.tolist() == [2, 2, 2, 0]


def test_flat_surface_fraction():
    assert flat_surface_fraction([2, 2, 2, 20], exposed_max=9) == 0.75


# --- difficulty ---------------------------------------------------------------


def test_difficulty_min_and_max():
    assert difficulty_score(length=100) == 0.0
    assert difficulty_score(length=400, disorder_fraction=1.0, flat_fraction=1.0) == 1.0


def test_difficulty_length_only_midpoint():
    # length 250 → f_len 0.5 → 0.45*0.5 = 0.225
    assert difficulty_score(length=250) == 0.225


def test_classify_bands():
    assert classify_difficulty(0.3) == "easy"
    assert classify_difficulty(0.5) == "medium"
    assert classify_difficulty(0.7) == "medium"  # boundary inclusive → medium
    assert classify_difficulty(0.8) == "hard"


# --- suggestions --------------------------------------------------------------


def test_suggest_campaign_easy_vs_hard():
    easy = suggest_campaign(0.2)
    hard = suggest_campaign(0.9)
    assert easy["n_target"] == 250 and easy["gate_tier"] == "strict"
    assert hard["n_target"] == 50 and hard["gate_tier"] == "permissive"
    assert len(hard["add_tools"]) > len(easy["add_tools"])  # harder → more diversity


def test_suggest_binder_length_grows_with_difficulty():
    assert suggest_binder_length(0.2) == (60, 100)
    assert suggest_binder_length(0.9) == (80, 160)


# --- hotspots -----------------------------------------------------------------


def test_pick_hotspots_in_pocket_band_most_concave_first():
    counts = [5, 12, 17, 25, 14]  # band [10,18] → resids B(12), C(17), E(14)
    resids = ["A", "B", "C", "D", "E"]
    picked = pick_hotspots(counts, resids, n=2)
    assert picked == ["C", "E"]  # 17 then 14 (most concave first)


def test_pick_hotspots_respects_n():
    counts = [11, 12, 13, 14]
    assert len(pick_hotspots(counts, ["a", "b", "c", "d"], n=2)) == 2
