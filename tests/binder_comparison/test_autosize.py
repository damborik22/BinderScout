"""Tests for the ESMFold2-gated autosize core (decision + independence counting)."""

import pytest
from binder_comparison.comparison.autosize import (
    MIN_PROBE,
    autosize_decision,
    count_independent_passers,
    run_autosize_loop,
)


class _FakePool:
    """Simulates a tool: generate(n) grows the pool; score_pool() reports
    (passers, n_independent) at a fixed per-design yield."""

    def __init__(self, yield_rate):
        self.total = 0
        self.yield_rate = yield_rate

    def generate(self, n):
        self.total += n

    def score(self):
        return round(self.total * self.yield_rate), self.total


# --- autosize_decision (pure, no pandas) --------------------------------------


def test_complete_when_target_reached():
    v = autosize_decision(have=50, n_independent=400, n_target=50)
    assert v.complete and v.stop_reason == "complete" and v.next_batch == 0


def test_complete_when_target_exceeded():
    v = autosize_decision(have=55, n_independent=400, n_target=50)
    assert v.complete and v.next_batch == 0


def test_continue_sizes_next_batch_from_yield():
    # yield = 10/100 = 0.1; remaining = 40; next = ceil(40/0.1 * 1.2) = 480
    v = autosize_decision(have=10, n_independent=100, n_target=50, margin=1.2)
    assert v.stop_reason == "continue"
    assert v.yield_per_design == pytest.approx(0.1)
    assert v.next_batch == 480


def test_budget_stop_reports_shortfall():
    v = autosize_decision(have=10, n_independent=100, n_target=50, budget_spent=100.0, budget_cap=100.0)
    assert not v.complete and v.stop_reason == "budget" and v.next_batch == 0
    assert v.have == 10  # shortfall visible


def test_zero_yield_explores_min_probe():
    # no passers yet, but only 5 designs seen → explore at least MIN_PROBE more
    v = autosize_decision(have=0, n_independent=5, n_target=50)
    assert v.stop_reason == "continue" and v.next_batch == MIN_PROBE


def test_zero_yield_explores_groups_seen_when_larger():
    v = autosize_decision(have=0, n_independent=200, n_target=50)
    assert v.next_batch == 200  # max(n_independent, MIN_PROBE)


def test_empty_pool_does_not_crash():
    v = autosize_decision(have=0, n_independent=0, n_target=50)
    assert v.stop_reason == "continue" and v.next_batch == MIN_PROBE


# --- run_autosize_loop (pure orchestration, no pandas) ------------------------


def test_loop_converges_to_complete():
    pool = _FakePool(yield_rate=0.5)
    history = run_autosize_loop(generate=pool.generate, score_pool=pool.score, n_target=10)
    assert history[-1].stop_reason == "complete"
    assert history[-1].have >= 10


def test_loop_cold_start_explores_then_grows():
    """First score sees an empty pool (0,0); the loop must seed generation, not stall."""
    pool = _FakePool(yield_rate=0.2)
    history = run_autosize_loop(generate=pool.generate, score_pool=pool.score, n_target=5)
    assert history[0].n_independent == 0  # cold start
    assert history[0].next_batch == MIN_PROBE
    assert history[-1].complete


def test_loop_stops_on_budget_without_reaching_target():
    pool = _FakePool(yield_rate=0.0)  # tool never produces a passer
    history = run_autosize_loop(
        generate=pool.generate,
        score_pool=pool.score,
        n_target=50,
        budget_cap=10.0,
        gpu_h_per_design=1.0,  # MIN_PROBE designs = 50 GPU-h, blows the 10 h cap next round
    )
    assert history[-1].stop_reason == "budget"
    assert history[-1].have < 50


def test_loop_max_rounds_guard_prevents_infinite_loop():
    pool = _FakePool(yield_rate=0.0)  # never converges, no budget cap
    history = run_autosize_loop(generate=pool.generate, score_pool=pool.score, n_target=50, max_rounds=4)
    assert len(history) == 4
    assert history[-1].stop_reason == "continue"


# --- count_independent_passers (independence dedup, needs pandas) --------------

pd = pytest.importorskip("pandas")


def test_collapses_sequences_to_one_backbone():
    """Three MPNN sequences of one backbone count as ONE independent design."""
    pool = pd.DataFrame(
        {
            "design_group": ["bb1", "bb1", "bb1"],
            "chain_iptm_interface": [0.62, 0.81, 0.40],  # best of the group = 0.81
        }
    )
    passers, n_indep = count_independent_passers(pool, threshold=0.7, score_col="chain_iptm_interface")
    assert (passers, n_indep) == (1, 1)


def test_counts_passers_across_groups():
    pool = pd.DataFrame(
        {
            "design_group": ["a", "a", "b", "c"],
            "chain_iptm_interface": [0.90, 0.10, 0.50, 0.75],  # a->0.90 pass, b->0.50 fail, c->0.75 pass
        }
    )
    passers, n_indep = count_independent_passers(pool, threshold=0.7, score_col="chain_iptm_interface")
    assert (passers, n_indep) == (2, 3)


def test_coerces_string_scores():
    pool = pd.DataFrame({"design_group": ["a", "b"], "chain_iptm_interface": ["0.80", "0.50"]})
    passers, n_indep = count_independent_passers(pool, threshold=0.7, score_col="chain_iptm_interface")
    assert (passers, n_indep) == (1, 2)


def test_missing_columns_return_zero():
    assert count_independent_passers(pd.DataFrame(), threshold=0.7, score_col="x") == (0, 0)
    pool = pd.DataFrame({"design_group": ["a"]})  # no score col
    assert count_independent_passers(pool, threshold=0.7, score_col="chain_iptm_interface") == (0, 0)
