"""There is one answer to "where is conda?" (binderscout_paths.find_conda_base).

binderscout.py, tui/app.py and the configurator each carried their own candidate list.
With conda on PATH and CONDA_EXE exported but no checkout-local conda, `binderscout
evaluate` said "conda not found -- install the evaluator first" (wrong advice, and a
miss silently drops refold engines), while the configurator found it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binderscout_paths as bp


def _fake_base(root: Path) -> Path:
    (root / "etc" / "profile.d").mkdir(parents=True)
    (root / "etc" / "profile.d" / "conda.sh").write_text("# conda\n")
    (root / "bin").mkdir()
    return root


def _env(tmp_path, **extra):
    return {"HOME": str(tmp_path / "home"), "PATH": "", **extra}


def test_a_conda_in_an_unusual_place_is_found_through_conda_exe(tmp_path, monkeypatch):
    base = _fake_base(tmp_path / "somewhere" / "odd")
    (base / "bin" / "conda").write_text("#!/bin/sh\n")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert bp.find_conda_base(None, _env(tmp_path, CONDA_EXE=str(base / "bin" / "conda"))) == base


def test_an_activated_env_leads_back_to_its_base(tmp_path, monkeypatch):
    base = _fake_base(tmp_path / "odd")
    (base / "envs" / "x").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert bp.find_conda_base(None, _env(tmp_path, CONDA_PREFIX=str(base / "envs" / "x"))) == base


def test_the_checkouts_own_standalone_conda_wins_over_the_system_one(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "my repo"  # a space on purpose
    local = _fake_base(repo / "conda")
    other = _fake_base(tmp_path / "odd")
    got = bp.find_conda_base(repo, _env(tmp_path, BINDERSCOUT_CONDA="", CONDA_PREFIX=str(other)))
    assert got == local


def test_the_explicit_override_beats_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "r"
    _fake_base(repo / "conda")
    chosen = _fake_base(tmp_path / "chosen")
    assert bp.find_conda_base(repo, _env(tmp_path, BINDERSCOUT_CONDA=str(chosen))) == chosen


def test_a_directory_without_conda_sh_is_not_a_base(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "x" / "bin").mkdir(parents=True)
    assert not bp._is_base(tmp_path / "x")


def test_require_skips_a_base_that_lacks_the_named_file(tmp_path, monkeypatch):
    monkeypatch.setattr(bp, "_FIXED_SYSTEM_DIRS", ())
    shadow = _fake_base(tmp_path / "repo" / "conda")
    good = _fake_base(tmp_path / "good")
    (good / "bin" / "conda").write_text("#!/bin/sh\n")
    env = _env(tmp_path, CONDA_EXE=str(good / "bin" / "conda"))
    assert bp.find_conda_base(tmp_path / "repo", env) == shadow
    assert bp.find_conda_base(tmp_path / "repo", env, require="bin/conda") == good
    assert bp.find_conda_base(tmp_path / "repo", _env(tmp_path), require="bin/conda") is None
