"""A checkout path with a space, and fixed /tmp paths, in the installers.

Miniforge's installer refuses a prefix containing whitespace. The installer found that out by
downloading ~80 MB, running the installer, and printing a bare "Miniforge3 installation
failed" -- no cause, no way out. It now refuses up front and says what to do.

The one in-script workaround for spaced paths (aarch64 BindCraft: PyRosetta cannot parse a
spaced path) linked the binaries into a FIXED /tmp directory shared by every user of the host:
a second user's run collides with the first's, and anyone can pre-create that path and have the
installer write symlinks and edit settings through it. Temp paths are mktemp -d now.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, run_bash, system_conda_present  # noqa: E402


def _sandbox(tmp_path: Path, platform: str) -> tuple[Path, Path, dict[str, str], Path]:
    repo = tmp_path / "my checkout"  # a space on purpose
    (repo / "install").mkdir(parents=True)
    script = repo / "install" / INSTALLERS[platform].name
    shutil.copy(INSTALLERS[platform], script)
    calls = tmp_path / "network-calls"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "curl"
    fake.write_text(f'#!/bin/sh\necho "curl $*" >> "{calls}"\nexit 1\n')
    fake.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    return repo, script, {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "LC_ALL": "C"}, calls


@pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be used instead")
@pytest.mark.parametrize("platform", sorted(INSTALLERS))
@pytest.mark.parametrize("mode", [["--standalone"], []])
def test_a_spaced_path_is_refused_before_the_download_and_says_what_to_do(platform, mode, tmp_path):
    repo, script, env, calls = _sandbox(tmp_path, platform)

    r = run_bash(f'bash "{script}" --tool evaluator --yes --skip-preflight ' + " ".join(mode) + " </dev/null", env, repo)
    out = r.stdout + r.stderr

    assert r.returncode != 0, out
    assert not calls.exists(), f"downloaded Miniforge into a path it cannot use: {calls.read_text()}"
    assert "contains a space" in out, out
    assert "BINDERSCOUT_CONDA" in out and "without spaces" in out, "the refusal names no way out"


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_no_installer_hardcodes_a_shared_tmp_path(platform):
    offenders = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(INSTALLERS[platform].read_text().splitlines(), 1)
        if "/tmp/" in line and not line.lstrip().startswith("#") and "mktemp" not in line
    ]
    assert not offenders, "fixed /tmp paths (use mktemp -d):\n" + "\n".join(offenders)


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_every_tmp_template_is_a_directory_or_file_made_by_mktemp(platform):
    for line in INSTALLERS[platform].read_text().splitlines():
        if "/tmp/" in line and not line.lstrip().startswith("#"):
            assert re.search(r"mktemp (-d )?\"?\$\{TMPDIR:-/tmp\}/\S*XXXXXXXX", line), line
