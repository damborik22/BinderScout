"""Fixtures that replay a --config file the way a user does: a subprocess, by path.

A subprocess is the point. The configurator resolves its checkout, its conda and
every relative path at import time or against the working directory, so asserting
on an in-process call would test the test's own cwd and sys.path instead.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIGURATOR = REPO / "configurator" / "configurator.py"
SMOKE = REPO / "examples" / "CALCA" / "smoke.json"


def make_fake_checkout(root: Path) -> Path:
    """Just enough of an installed checkout for every design tool to generate.

    The generators read presets out of the cloned tool repos and refuse to write
    anything when a tool is absent, so a bare tmp dir cannot be replayed into.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "binderscout.py").write_text("# stand-in marking a checkout root\n")
    for sub, stem in (("settings_filters", "no_filters"), ("settings_advanced", "default_4stage_multimer")):
        d = root / "BindCraft" / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stem}.json").write_text("{}\n")
    (root / "Mosaic" / ".venv").mkdir(parents=True, exist_ok=True)
    examples = root / "binderscout_examples"
    examples.mkdir(exist_ok=True)
    shutil.copy2(REPO / "binderscout_examples" / "hallucinate_binderscout.py", examples)
    return root


@pytest.fixture
def fake_checkout(tmp_path):
    return make_fake_checkout(tmp_path / "checkout")


@pytest.fixture
def replay():
    """replay(config, checkout, cwd, **env) -> CompletedProcess of `configurator.py --config`."""

    def _replay(config: Path, checkout: Path, cwd: Path, **extra_env: str) -> subprocess.CompletedProcess:
        home = cwd / "home"
        home.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "NO_COLOR": "1",
            "BINDERSCOUT_DIR": str(checkout),
            **extra_env,
        }
        return subprocess.run(
            [sys.executable, str(CONFIGURATOR), "--config", str(config)],
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )

    return _replay


def env_for_scripts(**extra: str) -> dict:
    """A scrubbed environment for running `bash -n` / dry markers over generated scripts."""
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", **extra}
