"""detect_conda in both installers uses the shared discovery order.

It carried its own list (PATH mamba/conda via `conda info --base`, then nine fixed
locations), so a conda reachable only through $CONDA_EXE or $BINDERSCOUT_CONDA was
"not found" and the installer went off to download a second Miniforge beside it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.shell_helpers import (
    INSTALLERS,
    clean_env,
    extract_block,
    extract_functions,
    fake_base,
    run_bash,
    system_conda_present,
)

pytestmark = pytest.mark.skipif(bool(system_conda_present()), reason="a conda under /opt answers for 'nothing found'")

_FUNCS = ("_use_conda_base", "detect_conda", "_check_system_conda_writable")


def _detect(platform: str, tmp_path: Path, *, standalone: str = "auto", **extra: str):
    script = INSTALLERS[platform]
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    prog = "\n".join(
        [
            "set -u",
            extract_block(script),
            extract_functions(script, *_FUNCS),
            f'BINDERSCOUT_DIR="{repo}"; LOCAL_CONDA_DIR="{repo}/conda"; STANDALONE={standalone}',
            "CONDA_READONLY=false; CONDA_BASE=''; CONDA_CMD=''",
            'print_warn() { echo "WARN $*"; }; print_fail() { echo "FAIL $*"; }',
            'install_local_conda() { echo "WOULD-DOWNLOAD"; return 1; }',
            'if detect_conda; then echo "BASE=$CONDA_BASE CMD=$CONDA_CMD"; else echo "NONE"; fi',
        ]
    )
    return run_bash(prog, clean_env(tmp_path / "home", **extra), tmp_path).stdout


@pytest.mark.parametrize("platform", sorted(INSTALLERS))
class TestDetectConda:
    def test_conda_exe_alone_is_enough(self, platform, tmp_path):
        odd = fake_base(tmp_path / "somewhere" / "odd")
        out = _detect(platform, tmp_path, CONDA_EXE=str(odd / "bin" / "conda"))
        assert f"BASE={odd} CMD={odd}/bin/conda" in out
        assert "WOULD-DOWNLOAD" not in out

    def test_the_explicit_override_wins_over_the_checkouts_own_conda(self, platform, tmp_path):
        fake_base(tmp_path / "repo" / "conda")
        chosen = fake_base(tmp_path / "chosen")
        out = _detect(platform, tmp_path, BINDERSCOUT_CONDA=str(chosen))
        assert f"BASE={chosen} " in out

    def test_mamba_is_preferred_over_conda_in_the_chosen_base(self, platform, tmp_path):
        base = fake_base(tmp_path / "b")
        mamba = base / "bin" / "mamba"
        mamba.write_text("#!/bin/sh\n")
        mamba.chmod(0o755)
        out = _detect(platform, tmp_path, BINDERSCOUT_CONDA=str(base))
        assert f"CMD={base}/bin/mamba" in out

    def test_standalone_uses_the_checkouts_conda_whatever_else_exists(self, platform, tmp_path):
        local = fake_base(tmp_path / "repo" / "conda")
        other = fake_base(tmp_path / "other")
        out = _detect(platform, tmp_path, standalone="true", BINDERSCOUT_CONDA=str(other))
        assert f"BASE={local} " in out

    def test_nothing_found_still_falls_back_to_a_local_install(self, platform, tmp_path):
        out = _detect(platform, tmp_path)
        assert "WOULD-DOWNLOAD" in out
