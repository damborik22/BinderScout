"""binderscout_paths.find_env_prefix: where a conda env lives, beyond <base>/envs.

install.sh already finds an env under $CONDA_ENVS_PATH, a condarc ``envs_dirs`` or ~/.conda/envs,
so the wizard and the TUI -- which only probed <base>/envs/<name> -- called a tool the installer had
just finished "not installed". This pins the order the shell side uses, with no subprocess.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binderscout_paths as bp


def _env(tmp_path, **extra):
    return {"HOME": str(tmp_path / "home"), "PATH": "", **extra}


def test_an_env_under_the_base_is_found(tmp_path):
    (tmp_path / "base" / "envs" / "x").mkdir(parents=True)
    assert bp.find_env_prefix("x", tmp_path / "base", _env(tmp_path)) == tmp_path / "base" / "envs" / "x"


def test_a_missing_env_is_none_and_a_missing_base_is_tolerated(tmp_path):
    assert bp.find_env_prefix("x", tmp_path / "base", _env(tmp_path)) is None
    assert bp.find_env_prefix("x", None, _env(tmp_path)) is None


def test_conda_envs_path_entries_come_first_and_all_are_searched(tmp_path):
    (tmp_path / "base" / "envs" / "x").mkdir(parents=True)
    (tmp_path / "second" / "x").mkdir(parents=True)
    (tmp_path / "second" / "only_here").mkdir()
    env = _env(tmp_path, CONDA_ENVS_PATH=f"{tmp_path / 'first'}:{tmp_path / 'second'}")
    assert bp.find_env_prefix("only_here", tmp_path / "base", env) == tmp_path / "second" / "only_here"
    # $CONDA_ENVS_PATH beats <base>/envs when both hold the name
    assert bp.find_env_prefix("x", tmp_path / "base", env) == tmp_path / "second" / "x"


def test_a_condarc_block_list_is_read(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".condarc").write_text(
        "channels:\n  - conda-forge\nenvs_dirs:\n  - /nonexistent/a  # a comment\n"
        f"  - '{tmp_path / 'shared'}'\nauto_update_conda: false\n"
    )
    (tmp_path / "shared" / "x").mkdir(parents=True)
    assert bp.find_env_prefix("x", tmp_path / "base", _env(tmp_path)) == tmp_path / "shared" / "x"


def test_a_condarc_inline_list_is_read(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".condarc").write_text(f"envs_dirs: [/nonexistent/a, {tmp_path / 'inline'}]\n")
    (tmp_path / "inline" / "x").mkdir(parents=True)
    assert bp.find_env_prefix("x", tmp_path / "base", _env(tmp_path)) == tmp_path / "inline" / "x"


def test_only_the_envs_dirs_key_counts(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".condarc").write_text(f"pkgs_dirs:\n  - {tmp_path / 'pkgs'}\n")
    (tmp_path / "pkgs" / "x").mkdir(parents=True)
    assert bp.find_env_prefix("x", tmp_path / "base", _env(tmp_path)) is None


def test_the_per_user_conda_envs_dir_is_the_last_resort(tmp_path):
    (tmp_path / "home" / ".conda" / "envs" / "x").mkdir(parents=True)
    assert bp.find_env_prefix("x", tmp_path / "base", _env(tmp_path)) == tmp_path / "home" / ".conda" / "envs" / "x"
