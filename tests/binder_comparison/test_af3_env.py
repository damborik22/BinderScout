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


def test_default_cap_and_preallocate(build_env):
    """Default 0.8 leaves headroom for the OS; PREALLOCATE stays true (false fragments/hangs)."""
    env = build_env({})

    assert env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == "0.8"
    assert env["XLA_PYTHON_CLIENT_PREALLOCATE"] == "true"


def test_blank_values_fall_through_to_default(build_env):
    """An exported-but-empty var must not silently disarm the cap."""
    env = build_env({"AF3_XLA_MEM_FRACTION": "  ", "XLA_CLIENT_MEM_FRACTION": ""})

    assert env["XLA_PYTHON_CLIENT_MEM_FRACTION"] == "0.8"


def test_parent_environment_is_preserved(build_env):
    env = build_env({"AF3_MODEL_DIR": "/models", "PATH": "/usr/bin"})

    assert env["AF3_MODEL_DIR"] == "/models"
    assert env["PATH"] == "/usr/bin"
