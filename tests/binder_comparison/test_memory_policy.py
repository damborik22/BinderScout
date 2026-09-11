"""Tests for the JAX GPU memory policy.

Regression cover for a silent undersizing bug: when ``libcudart`` could not be
dlopened, ``resolve_mem_fraction`` fell back to *system RAM* as the pool size.
That reading passes the unified-memory test by construction (pool == ram), so an
UNKNOWN pool was always classified as unified and handed the 40 GiB OS floor.

On BM2 (24 GB RTX 3090, 62.7 GiB host RAM) the Mosaic uv venv cannot load
libcudart, so the policy resolved "unified 62.7 GiB", took the OS floor, and
returned 0.362 — which JAX then applied to the *card*, giving Boltz-2 8.5 GiB of
23.6. Boltz-2 OOMed at 9 GB and it read as "this target is too big for a 24 GB
card", which was wrong and would have rerouted the whole campaign's refolding.
"""

from __future__ import annotations

import pytest
from binder_comparison.refolding import memory_policy as mp


@pytest.fixture
def pool(monkeypatch):
    """Set what each pool probe reports: (cudart_gib, nvidia_smi_gib, ram_gib)."""

    def _set(cudart: float, smi: float, ram: float):
        monkeypatch.setattr(mp, "_cuda_pool_gib", lambda: cudart)
        monkeypatch.setattr(mp, "_nvidia_smi_total_gib", lambda: smi)
        monkeypatch.setattr(mp, "_system_ram_gib", lambda: ram)

    return _set


class TestDiscreteCardIsNotMistakenForUnified:
    def test_cudart_unavailable_falls_back_to_nvidia_smi_not_system_ram(self, pool):
        """The exact BM2 case: no libcudart, 24 GB card, 62.7 GiB host RAM."""
        pool(0.0, 24.0, 62.7)

        frac, why = mp.resolve_mem_fraction(24.0)

        assert "discrete" in why, f"a 24 GB card beside 62.7 GiB of RAM is not unified: {why}"
        # The bug produced 0.362 (=(62.7-40)/62.7). Anything near that starves the card.
        assert float(frac) > 0.5, f"discrete card undersized to {frac}"

    def test_the_bug_would_have_been_caught(self, pool):
        """Guard the specific arithmetic, so a future 'helpful' RAM fallback fails here."""
        pool(0.0, 24.0, 62.7)

        frac = float(mp.resolve_mem_fraction(24.0)[0])

        assert abs(frac - 0.362) > 0.05, "resolved the RAM-derived fraction that starved Boltz-2"

    def test_pool_genuinely_unknown_says_so_rather_than_inventing_a_size(self, pool):
        """Both probes dark: report unknown and use the JAX-like default."""
        pool(0.0, 0.0, 62.7)

        frac, why = mp.resolve_mem_fraction(24.0)

        assert "unknown" in why
        assert "unified" not in why, "an unknown pool must never be reported as unified"
        assert float(frac) == pytest.approx(0.8)


class TestUnifiedMemoryStillKeepsTheOSFloor:
    def test_gb10_keeps_forty_gib_for_the_os(self, pool):
        """BM5: cudaMemGetInfo total == system RAM. Over-reserving here rebooted the box."""
        pool(121.7, 0.0, 121.7)

        frac, why = mp.resolve_mem_fraction(24.0)

        assert "unified" in why
        assert float(frac) * 121.7 == pytest.approx(24.0, abs=0.5)
        # Whatever the target, never leave the host under DEFAULT_MIN_OS_GIB.
        big, _ = mp.resolve_mem_fraction(1000.0)
        assert 121.7 - float(big) * 121.7 >= mp.DEFAULT_MIN_OS_GIB - 0.5

    def test_unified_detection_survives_a_small_reporting_discrepancy(self, pool):
        """pool and ram rarely match to the byte; 20 % tolerance is the existing rule."""
        pool(120.0, 0.0, 121.7)

        assert "unified" in mp.resolve_mem_fraction(24.0)[1]


class TestNvidiaSmiProbe:
    def test_missing_binary_is_zero_not_a_crash(self, monkeypatch):
        """The probe is a fallback; on a host without nvidia-smi it must stay quiet."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)

        assert mp._nvidia_smi_total_gib() == 0.0
