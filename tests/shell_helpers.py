"""Helpers for tests that drive the shell scripts' functions in a subshell.

The installers are 5,000-line scripts that cannot be sourced whole (they parse argv and
start installing), so a test pulls out just the functions it exercises, the same way
tests/test_install_state_tracks_the_commit.py does.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
X86 = REPO / "install" / "install.sh"
ARM = REPO / "install" / "install_aarch.sh"
INSTALLERS = {"x86": X86, "aarch64": ARM}

BLOCK_BEGIN = "# >>> binderscout-conda-block >>>"
BLOCK_END = "# <<< binderscout-conda-block <<<"


def extract_functions(script: Path, *names: str) -> str:
    """The text of the named top-level shell functions of *script*."""
    lines = script.read_text().splitlines()
    out: list[str] = []
    for name in names:
        start = next((i for i, line in enumerate(lines) if line.startswith(f"{name}(")), None)
        assert start is not None, f"{name} missing from {script.name}"
        depth = 0
        for i in range(start, len(lines)):
            out.append(lines[i])
            depth += lines[i].count("{") - lines[i].count("}")
            if depth == 0:  # also true on the first line of a one-line function
                break
    return "\n".join(out)


def extract_block(script: Path) -> str:
    """The shared conda-discovery block, markers included."""
    text = script.read_text()
    assert BLOCK_BEGIN in text and BLOCK_END in text, f"{script.name} carries no conda block"
    return BLOCK_BEGIN + text.split(BLOCK_BEGIN, 1)[1].split(BLOCK_END, 1)[0] + BLOCK_END


def _arch_override(env: dict[str, str]) -> dict[str, str]:
    """install/install.sh refuses an aarch64 host; tests drive its logic against stand-ins, so
    they use its documented override there (and only there). Tests that build an env of their
    own instead of inheriting os.environ never see the autouse fixture in tests/conftest.py."""
    if platform.machine() == "aarch64":
        return {"BINDERSCOUT_ALLOW_X86_INSTALLER": "1", **env}
    return env


def run_bash(program: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    env = _arch_override(env)
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, env=env, cwd=str(cwd), timeout=120)


def clean_env(home: Path, path: str | None = None, **extra: str) -> dict[str, str]:
    """A minimal environment: no conda variables, a scratch HOME."""
    env = {"HOME": str(home), "PATH": path if path is not None else "/usr/bin:/bin", "LC_ALL": "C"}
    env.update(extra)
    return _arch_override(env)


def fake_base(root: Path, *, conda_script: str | None = None) -> Path:
    """A directory that passes for a conda base."""
    (root / "etc" / "profile.d").mkdir(parents=True, exist_ok=True)
    (root / "etc" / "profile.d" / "conda.sh").write_text("# conda\n")
    (root / "bin").mkdir(exist_ok=True)
    conda = root / "bin" / "conda"
    conda.write_text(conda_script or '#!/bin/sh\necho "conda 24.0.0"\n')
    conda.chmod(0o755)
    return root


def system_conda_present() -> str | None:
    """A conda in one of the fixed system locations would make 'no conda' tests meaningless."""
    for d in ("/opt/conda", "/opt/miniforge3", "/opt/miniconda3", "/opt/anaconda3"):
        if os.path.isfile(f"{d}/etc/profile.d/conda.sh"):
            return d
    return None
