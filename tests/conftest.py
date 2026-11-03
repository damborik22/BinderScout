"""Suite-wide fixtures."""

from __future__ import annotations

import platform

import pytest


@pytest.fixture(autouse=True)
def _let_the_x86_installer_run_under_test_on_aarch64(monkeypatch):
    """install/install.sh refuses to run on an aarch64 machine (it would put a CPU-only
    torch over a working CUDA one). Many tests drive that installer's functions or its
    read-only modes against stand-in conda trees, which is a test of the script's logic and
    not an install; on an aarch64 host they all failed on the refusal alone (26 failures in
    the v2.0.3 end-to-end run). The documented override is the right tool for a test. It is
    set only on aarch64, where the refusal exists, so an x86 run is untouched.
    """
    if platform.machine() == "aarch64":
        monkeypatch.setenv("BINDERSCOUT_ALLOW_X86_INSTALLER", "1")
