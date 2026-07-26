"""Tests for the two functions that produce every number this pipeline ranks on.

`compute_iptm_from_pae` yields each `{engine}_pae_iptm`, the sole input to
`consensus_iptm` / `consensus_iptm_mean` — i.e. both stages of the default ranking.
`compute_ipsae_from_pae` yields every `*_ipsae_min`, `quality_tier` and
`agreement_count`. Neither had a single test, while the docstring claims
cross-validation against DunbrackLab ipsae v1.0.1 — a claim CI could not check, so a
transpose or d0 regression would have passed silently.

The expected values here are recomputed from the published formulas rather than
copied from the current implementation, so these are a check on the maths and not a
snapshot of whatever it happens to do today.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("numpy")
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.comparison.scoring import (
    IPSAE_PAE_CUTOFF,
    compute_ipsae_from_pae,
    compute_iptm_from_pae,
)

# ── Reference implementations, written straight from the papers ────────────────


def _d0_ref(n: float) -> float:
    """Dunbrack 2025: d0 = max(1.0, 1.24*(N-15)^(1/3) - 1.8), with N floored at 27."""
    n = max(float(n), 27.0)
    return max(1.0, 1.24 * (n - 15.0) ** (1.0 / 3.0) - 1.8)


def _ipsae_ref(pae_block: np.ndarray, cutoff: float = IPSAE_PAE_CUTOFF) -> float:
    """max_i [ mean_j ( 1/(1+(PAE_ij/d0_i)^2) ) ] over j with PAE_ij < cutoff."""
    best = 0.0
    for row in pae_block:
        q = row[row < cutoff]
        if len(q) == 0:
            continue
        d0 = _d0_ref(len(q))
        best = max(best, float(np.mean(1.0 / (1.0 + (q / d0) ** 2))))
    return best


def _d0_global_ref(n: float) -> float:
    """ipTM's d0: same shape as ipSAE's but WITHOUT the N>=27 floor.

    The two kernels genuinely differ here — ipSAE uses a per-residue d0 computed from
    the count of qualifying pairs and floors N at 27 (the Dunbrack reference does), while
    ipTM uses one global d0 from the total chain lengths and does not. Pinned in
    TestTheTwoKernelsUseDifferentD0 below so the distinction cannot be "tidied" away.
    """
    return max(1.0, 1.24 * float(np.cbrt(float(n) - 15.0)) - 1.8)


def _iptm_ref(pae_block: np.ndarray, l_a: int, l_b: int) -> float:
    """Global-d0 TM kernel over every cross-chain pair, no PAE cutoff."""
    d0 = _d0_global_ref(l_a + l_b)
    per_row = np.mean(1.0 / (1.0 + (pae_block / d0) ** 2), axis=1)
    return float(np.max(per_row))


# ── Fixtures ──────────────────────────────────────────────────────────────────

L_B, L_T = 6, 9


def _asymmetric_pae(seed: int = 0) -> np.ndarray:
    """A deliberately ASYMMETRIC square PAE matrix in [binder|target] order.

    Asymmetry matters: a symmetric matrix would make bt and tb identical and hide any
    transpose error, which is exactly the class of bug these tests exist to catch.
    """
    rng = np.random.default_rng(seed)
    m = rng.uniform(0.5, 25.0, size=(L_B + L_T, L_B + L_T))
    m[:L_B, L_B:] *= 0.35  # binder→target confident
    m[L_B:, :L_B] *= 0.90  # target→binder less so
    np.fill_diagonal(m, 0.0)
    return m


def _to_target_first(pae: np.ndarray) -> np.ndarray:
    """Re-block a [binder|target] matrix into [target|binder] (AF3 / ESMFold2 order)."""
    return np.block(
        [
            [pae[L_B:, L_B:], pae[L_B:, :L_B]],
            [pae[:L_B, L_B:], pae[:L_B, :L_B]],
        ]
    )


class TestIpsaeMatchesTheFormula:
    def test_bt_and_tb_match_independent_reference(self):
        pae = _asymmetric_pae()
        got = compute_ipsae_from_pae(pae, binder_length=L_B)
        assert got["bt_ipsae"] == pytest.approx(_ipsae_ref(pae[:L_B, L_B:]), rel=1e-12)
        assert got["tb_ipsae"] == pytest.approx(_ipsae_ref(pae[L_B:, :L_B]), rel=1e-12)

    def test_min_and_max_are_the_pessimistic_and_optimistic_directions(self):
        got = compute_ipsae_from_pae(_asymmetric_pae(), binder_length=L_B)
        assert got["ipsae_min"] == pytest.approx(min(got["bt_ipsae"], got["tb_ipsae"]))
        assert got["ipsae_max"] == pytest.approx(max(got["bt_ipsae"], got["tb_ipsae"]))

    def test_directions_genuinely_differ_on_an_asymmetric_matrix(self):
        """Guards the guard: if these were equal the transpose tests would prove nothing."""
        got = compute_ipsae_from_pae(_asymmetric_pae(), binder_length=L_B)
        assert got["bt_ipsae"] != pytest.approx(got["tb_ipsae"])

    def test_target_first_ordering_is_transposed_not_ignored(self):
        """AF3 and ESMFold2 emit [target|binder]; the evaluator must re-block, not slice
        the wrong quadrants. Feeding both layouts must give the same answer."""
        pae = _asymmetric_pae()
        native = compute_ipsae_from_pae(pae, binder_length=L_B, ordering="binder_target")
        swapped = compute_ipsae_from_pae(_to_target_first(pae), binder_length=L_B, ordering="target_binder")
        for key in ("bt_ipsae", "tb_ipsae", "ipsae_min", "ipsae_max"):
            assert swapped[key] == pytest.approx(native[key], rel=1e-12), key

    def test_mislabelling_the_ordering_changes_the_answer(self):
        """If ordering were ignored, this would silently agree — and a real AF3 report
        would be scored on the wrong quadrants."""
        pae = _asymmetric_pae()
        correct = compute_ipsae_from_pae(_to_target_first(pae), binder_length=L_B, ordering="target_binder")
        wrong = compute_ipsae_from_pae(_to_target_first(pae), binder_length=L_B, ordering="binder_target")
        assert wrong["ipsae_min"] != pytest.approx(correct["ipsae_min"])

    def test_cutoff_excludes_distant_pairs(self):
        """Pairs at or above the cutoff must not contribute at all."""
        pae = np.full((L_B + L_T, L_B + L_T), 99.0)
        np.fill_diagonal(pae, 0.0)
        got = compute_ipsae_from_pae(pae, binder_length=L_B)
        assert got["bt_ipsae"] == 0.0
        assert got["tb_ipsae"] == 0.0

    def test_perfect_interface_approaches_one(self):
        pae = np.zeros((L_B + L_T, L_B + L_T))
        got = compute_ipsae_from_pae(pae, binder_length=L_B)
        assert got["bt_ipsae"] == pytest.approx(1.0)
        assert got["ipsae_min"] == pytest.approx(1.0)

    def test_scores_are_bounded(self):
        got = compute_ipsae_from_pae(_asymmetric_pae(3), binder_length=L_B)
        for key in ("bt_ipsae", "tb_ipsae", "ipsae_min", "ipsae_max"):
            assert 0.0 <= got[key] <= 1.0, key

    @pytest.mark.parametrize("bad_len", [0, -1, L_B + L_T])
    def test_degenerate_binder_length_yields_nan_not_a_crash(self, bad_len):
        got = compute_ipsae_from_pae(_asymmetric_pae(), binder_length=bad_len)
        assert np.isnan(got["ipsae_min"])

    def test_non_square_matrix_is_rejected(self):
        with pytest.raises(ValueError, match="square"):
            compute_ipsae_from_pae(np.zeros((4, 7)), binder_length=2)


class TestIptmMatchesTheFormula:
    def test_matches_independent_reference(self):
        pae = _asymmetric_pae()
        got = compute_iptm_from_pae(pae, binder_length=L_B)
        assert got["bt_iptm"] == pytest.approx(_iptm_ref(pae[:L_B, L_B:], L_B, L_T), rel=1e-12)
        assert got["tb_iptm"] == pytest.approx(_iptm_ref(pae[L_B:, :L_B], L_T, L_B), rel=1e-12)

    def test_iptm_is_the_optimistic_direction(self):
        got = compute_iptm_from_pae(_asymmetric_pae(), binder_length=L_B)
        assert got["iptm"] == pytest.approx(max(got["bt_iptm"], got["tb_iptm"]))

    def test_target_first_ordering_is_transposed(self):
        pae = _asymmetric_pae()
        native = compute_iptm_from_pae(pae, binder_length=L_B, ordering="binder_target")
        swapped = compute_iptm_from_pae(_to_target_first(pae), binder_length=L_B, ordering="target_binder")
        assert swapped["iptm"] == pytest.approx(native["iptm"], rel=1e-12)

    def test_no_cutoff_so_distant_pairs_still_contribute(self):
        """Unlike ipSAE, ipTM has no PAE cutoff — a hopeless interface must score low
        but non-zero, which is what makes it usable as a continuous ranking key."""
        pae = np.full((L_B + L_T, L_B + L_T), 99.0)
        got = compute_iptm_from_pae(pae, binder_length=L_B)
        assert 0.0 < got["iptm"] < 0.05

    def test_perfect_interface_approaches_one(self):
        got = compute_iptm_from_pae(np.zeros((L_B + L_T, L_B + L_T)), binder_length=L_B)
        assert got["iptm"] == pytest.approx(1.0)

    def test_monotonic_in_interface_quality(self):
        """The property the ranking depends on: a better interface must score higher."""
        base = _asymmetric_pae(7)
        better = base.copy()
        better[:L_B, L_B:] *= 0.5
        better[L_B:, :L_B] *= 0.5
        assert (
            compute_iptm_from_pae(better, binder_length=L_B)["iptm"]
            > compute_iptm_from_pae(base, binder_length=L_B)["iptm"]
        )

    def test_non_square_matrix_is_rejected(self):
        with pytest.raises(ValueError, match="square"):
            compute_iptm_from_pae(np.zeros((3, 5)), binder_length=2)


class TestD0Floor:
    """d0's N is floored at 27, per the Dunbrack reference implementation."""

    def test_small_interfaces_share_the_floored_d0(self):
        small = np.zeros((4, 4))
        small[:2, 2:] = 3.0
        small[2:, :2] = 3.0
        got = compute_ipsae_from_pae(small, binder_length=2)
        d0 = _d0_ref(2)  # floors to 27
        assert got["bt_ipsae"] == pytest.approx(1.0 / (1.0 + (3.0 / d0) ** 2), rel=1e-12)


class TestTheTwoKernelsUseDifferentD0:
    """ipSAE floors N at 27 (per the Dunbrack reference); ipTM does not, and uses one
    global d0 from the total chain lengths. Conflating them would shift every ranked
    number, so the difference is pinned rather than left implicit in a comment."""

    def test_ipsae_floors_n_at_27(self):
        assert _d0_ref(2) == _d0_ref(27)
        assert _d0_ref(2) > _d0_global_ref(2)

    def test_iptm_survives_a_complex_under_15_total_residues(self):
        """Regression found by these tests: (n-15)**(1/3) returns a COMPLEX number for
        n < 15, so max(1.0, complex) raised TypeError. np.cbrt takes the real root, which
        the max() floors to 1.0 as the formula intends. Only reachable from
        sequence-only mode (the configurator's binders are >= 10 aa), but a crash is a
        crash."""
        got = compute_iptm_from_pae(np.full((10, 10), 5.0), binder_length=4)
        assert 0.0 < got["iptm"] <= 1.0

    def test_iptm_does_not_floor(self):
        # L_A + L_B = 15 -> the cube-root term vanishes and only the 1.0 floor remains.
        assert _d0_global_ref(15) == pytest.approx(1.0)
        assert _d0_global_ref(60) > _d0_global_ref(30)

    def test_the_two_kernels_disagree_on_the_same_matrix(self):
        pae = _asymmetric_pae(11)
        ipsae = compute_ipsae_from_pae(pae, binder_length=L_B)["ipsae_max"]
        iptm = compute_iptm_from_pae(pae, binder_length=L_B)["iptm"]
        assert ipsae != pytest.approx(iptm), "different d0 and cutoff must give different scores"
