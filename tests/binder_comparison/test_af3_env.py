"""Tests for the AF3 subprocess environment (XLA memory cap).

Regression cover for the Spark crash path: jaxlib raises ValueError when both
XLA_PYTHON_CLIENT_MEM_FRACTION and XLA_CLIENT_MEM_FRACTION are set, and AF3's own
docs/performance.md tells unified-memory operators to export the latter.  Since
refold_af3 inherits os.environ, that collision killed every design in a pool while
still producing a "successful" run of empty af3_* columns.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "Evaluator" / "scripts" / "refold_af3.py"


@pytest.fixture(scope="module")
def build_env():
    """Load _build_af3_env from the standalone script without importing AF3 deps."""
    spec = importlib.util.spec_from_file_location("_refold_af3_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:  # gemmi/numpy absent outside binder-eval-af3
        pytest.skip(f"refold_af3 dependencies unavailable: {exc}")
    return module._build_af3_env


@pytest.fixture(scope="module")
def default_fraction():
    """The pool-aware default, computed the same way the script computes it.

    Deliberately NOT a hard-coded "0.8": that constant is what rebooted BM5, and
    _build_af3_env was changed to derive the fraction from the real pool. Asserting
    0.8 here made these tests pass on a discrete card and fail on a unified-memory
    host (GB10 resolves 12 GiB / 121.7 GiB = 0.099) — i.e. it asserted the bug.
    """
    spec = importlib.util.spec_from_file_location("_refold_af3_default_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        pytest.skip(f"refold_af3 dependencies unavailable: {exc}")
    return module._default_mem_fraction()


def test_never_sets_both_mem_fraction_names(build_env):
    """The two names must never both reach the child — that is a jaxlib ValueError."""
    env = build_env({"XLA_CLIENT_MEM_FRACTION": "3.2"})

    assert "XLA_CLIENT_MEM_FRACTION" not in env
    assert env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == "3.2"


def test_inherited_new_name_is_forwarded_not_dropped(build_env):
    """An operator following AF3's unified-memory docs keeps their value, under the legacy name."""
    env = build_env({"XLA_CLIENT_MEM_FRACTION": "3.2", "XLA_PYTHON_CLIENT_MEM_FRACTION": "0.8"})

    assert "XLA_CLIENT_MEM_FRACTION" not in env
    assert env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == "3.2"


def test_explicit_override_wins(build_env):
    env = build_env({"AF3_XLA_MEM_FRACTION": "0.5", "XLA_CLIENT_MEM_FRACTION": "3.2"})

    assert env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == "0.5"
    assert "XLA_CLIENT_MEM_FRACTION" not in env


def test_default_cap_and_preallocate(build_env, default_fraction):
    """With nothing set we fall back to the pool-aware default, and PREALLOCATE stays true.

    PREALLOCATE=true is load-bearing: with "false" and no device ceiling the allocator
    grows into the shared pool with no fail-fast, which is the slow-starve path.
    """
    env = build_env({})

    assert env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == default_fraction
    assert 0.0 < float(env["XLA_PYTHON_CLIENT_MEM_FRACTION"]) <= 0.8
    assert env["XLA_PYTHON_CLIENT_PREALLOCATE"] == "true"


def test_blank_values_fall_through_to_default(build_env, default_fraction):
    """An exported-but-empty var must not silently disarm the cap."""
    env = build_env({"AF3_XLA_MEM_FRACTION": "  ", "XLA_CLIENT_MEM_FRACTION": ""})

    assert env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == default_fraction


def test_parent_environment_is_preserved(build_env):
    env = build_env({"AF3_MODEL_DIR": "/models", "PATH": "/usr/bin"})

    assert env["AF3_MODEL_DIR"] == "/models"
    assert env["PATH"] == "/usr/bin"


# ---------------------------------------------------------------------------
# Unified-memory detection (2026-09-27)
# ---------------------------------------------------------------------------
#
# `_default_mem_fraction` decides whether the pool is UNIFIED (GPU memory == system
# RAM, e.g. GB10) because only then does over-reserving starve the OS. It decides it
# by asking whether the pool is the same size as system RAM -- which is only
# meaningful if the pool size actually came from the GPU.
#
# It did not. The ctypes probe loads libcudart by BARE NAME, which fails whenever
# CUDA came from pip wheels (the libs sit inside nvidia/*/lib, off the loader path).
# pool_gib then fell back to system RAM, so `pool == ram` EXACTLY, every host was
# declared unified, `(pool - 40)/pool` went negative on anything under 40 GiB, and the
# fraction was clamped to the 0.02 floor. Measured on a 12 GB discrete card: fraction
# 0.020 (~246 MiB) and every design died on a 54 MiB allocation -- the precise outcome
# the function's own comment warns about, reached by a path it did not consider.


@pytest.fixture
def fraction_under(monkeypatch):
    """Call _default_mem_fraction with the hardware probes under our control."""
    # Stub the heavy deps this function does not touch. The sibling fixtures skip
    # without gemmi, which meant CI (binder-eval, no gemmi) ran none of these -- so a
    # regression test for a bug that OOM'd every design would have been permanently
    # skipped on the only machine that gates merges. _default_mem_fraction reads
    # ctypes, subprocess and os.sysconf, and nothing else.
    import sys
    import types

    for dep in ("gemmi", "numpy"):
        if dep not in sys.modules:
            try:
                importlib.import_module(dep)
            except ImportError:
                monkeypatch.setitem(sys.modules, dep, types.ModuleType(dep))
    spec = importlib.util.spec_from_file_location("_refold_af3_fraction_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        pytest.skip(f"refold_af3 dependencies unavailable: {exc}")

    def _call(*, smi_total_mib: float | None, ram_gib: float, cuda_works: bool = False):
        import ctypes

        if not cuda_works:

            def _no_cudart(name, *a, **k):
                raise OSError(f"{name}: not on the loader path (pip-installed CUDA)")

            monkeypatch.setattr(ctypes, "CDLL", _no_cudart)

        class _Completed:
            def __init__(self, out):
                self.stdout = out

        def _fake_run(cmd, *a, **k):
            if cmd and "nvidia-smi" in cmd[0]:
                if smi_total_mib is None:
                    raise OSError("nvidia-smi not found")
                return _Completed(f"{smi_total_mib:.0f}\n")
            raise AssertionError(f"unexpected subprocess call: {cmd}")

        monkeypatch.setattr(module.subprocess, "run", _fake_run)
        monkeypatch.setattr(
            module.os,
            "sysconf",
            lambda n: 4096 if n == "SC_PAGE_SIZE" else int(ram_gib * (1024**3) / 4096),
        )
        return float(module._default_mem_fraction())

    return _call


def test_discrete_card_is_not_called_unified_when_the_cuda_probe_fails(fraction_under):
    """The exact observed configuration: 12 GB discrete card, 31 GB RAM, libcudart
    unloadable. nvidia-smi supplies the true pool, so the unified branch must not fire."""
    frac = fraction_under(smi_total_mib=12288, ram_gib=31.3)
    assert frac > 0.02, f"fraction collapsed to the floor again: {frac}"
    assert frac * 12.0 >= 4.4, (
        f"fraction {frac} gives {frac * 12.0:.2f} GiB on a 12 GB card, below AF3's ~4.4 GiB working set"
    )
    assert frac == pytest.approx(0.5, abs=0.01), "expected the discrete half-card cap"


def test_the_ram_fallback_does_not_force_the_unified_branch(fraction_under):
    """When NO GPU can be queried, pool_gib falls back to system RAM — and `pool == ram`
    must not then be read as evidence of unified memory, which is what clamped the
    fraction to 0.02."""
    frac = fraction_under(smi_total_mib=None, ram_gib=31.3)
    assert frac > 0.02, f"the RAM fallback still forces the 0.02 floor: {frac}"
    assert frac * 12.0 >= 4.4, f"{frac} leaves {frac * 12.0:.2f} GiB on a 12 GB card"


def test_a_real_unified_host_still_gets_the_os_floor(fraction_under):
    """The protection this heuristic exists for must survive the fix: a GB10-sized pool
    that genuinely equals system RAM keeps the 40 GiB OS reserve, so AF3 cannot
    preallocate the machine out of memory (the 2026-08-18 BM5 reboot)."""
    frac = fraction_under(smi_total_mib=121.7 * 1024, ram_gib=121.7)
    assert frac == pytest.approx(12.0 / 121.7, abs=0.01), f"unified host should target the 12 GiB reserve, got {frac}"
    assert frac * 121.7 <= 121.7 - 40.0, "the OS floor is no longer respected"


def test_a_pool_too_small_for_the_working_set_still_reaches_the_floor(fraction_under):
    """The 0.02 floor is not wrong in itself — it is the correct answer for a pool where
    the target reserve cannot fit. This pins that it is reached by arithmetic, not by a
    misfiring unified verdict."""
    frac = fraction_under(smi_total_mib=121.7 * 1024, ram_gib=121.7)
    assert frac > 0.02
