"""Tests for the maturation decision core (Kd / affinity-proxy → next round)."""

from binder_comparison.comparison.maturation import (
    DONE,
    MPNN_REDESIGN,
    MUTATION_SCAN,
    PARTIAL_DIFFUSION,
    decide_maturation_strategy,
    plan_maturation,
)

# --- decide_maturation_strategy -----------------------------------------------


def test_no_measurement_defaults_to_mpnn():
    strat, _ = decide_maturation_strategy(None)
    assert strat == MPNN_REDESIGN


def test_meeting_target_is_done():
    strat, _ = decide_maturation_strategy(5.0, target_affinity_nM=10.0)
    assert strat == DONE


def test_weak_binder_explores_backbone():
    strat, _ = decide_maturation_strategy(800.0)
    assert strat == PARTIAL_DIFFUSION


def test_moderate_binder_redesigns_sequence():
    strat, _ = decide_maturation_strategy(120.0)
    assert strat == MPNN_REDESIGN


def test_strong_binder_mutation_scan():
    strat, _ = decide_maturation_strategy(20.0)
    assert strat == MUTATION_SCAN


# --- plan_maturation ----------------------------------------------------------


def test_empty_affinities_is_cold_start():
    plan = plan_maturation({})
    assert plan.strategy == MPNN_REDESIGN and plan.parent_design_ids == []


def test_partial_diffusion_carries_top_k_parents_tightest_first():
    plan = plan_maturation({"d1": 1000.0, "d2": 600.0, "d3": 800.0}, top_k=2)
    assert plan.strategy == PARTIAL_DIFFUSION
    assert plan.parent_design_ids == ["d2", "d3"]  # 600 then 800
    assert plan.best_affinity_nM == 600.0


def test_mutation_scan_carries_only_the_single_best():
    plan = plan_maturation({"d1": 10.0, "d2": 30.0})
    assert plan.strategy == MUTATION_SCAN and plan.parent_design_ids == ["d1"]


def test_done_carries_no_parents():
    plan = plan_maturation({"d1": 5.0, "d2": 8.0}, target_affinity_nM=10.0)
    assert plan.strategy == DONE and plan.parent_design_ids == []


def test_expected_improvement_is_reported():
    plan = plan_maturation({"d1": 900.0})
    assert "backbone" in plan.expected_improvement
