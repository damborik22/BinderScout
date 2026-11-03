"""Shell and Python answer "where is conda?" identically.

Shell had four private algorithms (install.sh, install_aarch.sh, evaluate.sh, install.sh in
Evaluator/), each with its own candidate list, and Python had a fifth that was then unified
as binderscout_paths.find_conda_base. Same box, different answers: with conda reachable only
through $CONDA_EXE the CLI found it and `evaluate.sh` silently skipped every refold engine
that lives in a conda env.

This runs the shell block against find_conda_base on the same environment and asserts they
agree, scenario by scenario, in the order the docstring promises.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binderscout_paths as bp  # noqa: E402
from tests.shell_helpers import X86, clean_env, extract_block, fake_base, run_bash, system_conda_present  # noqa: E402

pytestmark = pytest.mark.skipif(
    bool(system_conda_present()) or bool(shutil.which("conda", path="/usr/bin:/bin")),
    reason="a conda in /opt or /usr/bin would answer for the 'nothing set' scenarios",
)


def _shell_answer(repo: Path | None, env: dict[str, str], tmp_path: Path) -> str:
    arg = f'"{repo}"' if repo else ""
    prog = f"set -u\n{extract_block(X86)}\nbs_find_conda_base {arg}"
    r = run_bash(prog, env, tmp_path)
    return r.stdout.strip() if r.returncode == 0 else ""


def _both(tmp_path, monkeypatch, env, repo=None):
    monkeypatch.setenv("HOME", env["HOME"])
    py = bp.find_conda_base(repo, env)
    return (str(py) if py else ""), _shell_answer(repo, env, tmp_path)


def test_nothing_anywhere_is_no_answer_in_both(tmp_path, monkeypatch):
    env = clean_env(tmp_path / "home")
    py, sh = _both(tmp_path, monkeypatch, env)
    assert py == sh == ""


def test_the_explicit_override_beats_the_checkouts_own_conda(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    fake_base(repo / "conda")
    chosen = fake_base(tmp_path / "chosen")
    env = clean_env(tmp_path / "home", BINDERSCOUT_CONDA=str(chosen))
    py, sh = _both(tmp_path, monkeypatch, env, repo)
    assert py == sh == str(chosen)


def test_the_checkouts_own_conda_beats_conda_exe_and_a_path_with_a_space_works(tmp_path, monkeypatch):
    repo = tmp_path / "my repo"
    local = fake_base(repo / "conda")
    other = fake_base(tmp_path / "odd")
    env = clean_env(tmp_path / "home", CONDA_EXE=str(other / "bin" / "conda"))
    py, sh = _both(tmp_path, monkeypatch, env, repo)
    assert py == sh == str(local)


def test_a_conda_in_an_unusual_place_is_found_through_conda_exe(tmp_path, monkeypatch):
    odd = fake_base(tmp_path / "somewhere" / "odd")
    env = clean_env(tmp_path / "home", CONDA_EXE=str(odd / "bin" / "conda"))
    py, sh = _both(tmp_path, monkeypatch, env, tmp_path / "repo")
    assert py == sh == str(odd)


def test_an_activated_env_leads_back_to_its_base(tmp_path, monkeypatch):
    base = fake_base(tmp_path / "odd")
    (base / "envs" / "x").mkdir(parents=True)
    env = clean_env(tmp_path / "home", CONDA_PREFIX=str(base / "envs" / "x"))
    py, sh = _both(tmp_path, monkeypatch, env)
    assert py == sh == str(base)


def test_conda_on_path_is_found(tmp_path, monkeypatch):
    base = fake_base(tmp_path / "onpath")
    env = clean_env(tmp_path / "home", path=f"{base / 'bin'}:/usr/bin:/bin")
    py, sh = _both(tmp_path, monkeypatch, env)
    assert py == sh == str(base)


def test_the_usual_home_locations_are_the_last_resort(tmp_path, monkeypatch):
    home = tmp_path / "home"
    base = fake_base(home / "miniforge3")
    env = clean_env(home)
    py, sh = _both(tmp_path, monkeypatch, env)
    assert py == sh == str(base)


def test_a_directory_without_conda_sh_is_not_a_base_in_either(tmp_path, monkeypatch):
    (tmp_path / "x" / "bin").mkdir(parents=True)
    env = clean_env(tmp_path / "home", BINDERSCOUT_CONDA=str(tmp_path / "x"))
    py, sh = _both(tmp_path, monkeypatch, env)
    assert py == sh == ""
