"""`--uninstall` with no usable conda must not delete a partial local `conda/` directory.

--uninstall continues with NO_CONDA=true when detect_conda fails, and each conda-backed tool then
reports "its conda env was not removed (nothing of it was changed)". The "also remove local
Miniforge3" block was gated only on the DO_* flags and the directory existing, so it rm -rf'd the
rejected conda/ dir with every env inside it, contradicting those messages.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import INSTALLERS, run_bash, system_conda_present
from tests.test_installer_moved_checkout import _sandbox

pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt would be found")


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
def test_uninstall_without_usable_conda_leaves_a_partial_local_conda_dir_alone(platform, tmp_path):
    repo, script, env, _base = _sandbox(tmp_path, platform)
    env = {k: v for k, v in env.items() if k != "BINDERSCOUT_CONDA"}
    keep = repo / "conda" / "envs" / "X" / "keep"
    keep.parent.mkdir(parents=True)
    keep.write_text("an env inside a conda/ dir that detect_conda rejected\n")

    r = run_bash(f'bash "{script}" --uninstall --tool all --yes --force </dev/null', env, repo)
    out = r.stdout + r.stderr

    assert keep.exists(), out
    assert "Removed local Miniforge3" not in out, out
