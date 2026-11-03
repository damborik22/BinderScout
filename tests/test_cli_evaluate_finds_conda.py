"""`binderscout evaluate` and the TUI use the one shared conda discovery.

Each carried a private candidate list, so a box whose conda was reachable only through
``$CONDA_EXE`` (or PATH, or ``$BINDERSCOUT_CONDA``) was "conda not found" here and fine in
the configurator -- and the message then told the user to install what was installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import binderscout_paths
from tui import app

REPO = Path(__file__).resolve().parents[1]


def _load_cli():
    spec = importlib.util.spec_from_file_location("binderscout_cli_conda_test", REPO / "binderscout.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _base(root: Path, with_conda_bin: bool = True) -> Path:
    (root / "etc" / "profile.d").mkdir(parents=True)
    (root / "etc" / "profile.d" / "conda.sh").write_text("# conda\n")
    (root / "bin").mkdir()
    if with_conda_bin:
        (root / "bin" / "conda").write_text("#!/bin/sh\n")
    return root


@pytest.fixture
def bare_box(tmp_path, monkeypatch):
    """A box where conda is discoverable only by the means a test grants."""
    for var in ("BINDERSCOUT_CONDA", "CONDA_EXE", "CONDA_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(binderscout_paths, "_FIXED_SYSTEM_DIRS", ())
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return checkout


def _run_evaluate(cli, monkeypatch, checkout):
    calls = []
    monkeypatch.setattr(cli, "REPO", checkout)
    monkeypatch.setattr(cli, "_exec", lambda path, argv: calls.append((path, argv)))
    return calls


def test_evaluate_finds_a_conda_that_is_only_reachable_through_conda_exe(bare_box, tmp_path, monkeypatch):
    base = _base(tmp_path / "somewhere" / "odd")
    monkeypatch.setenv("CONDA_EXE", str(base / "bin" / "conda"))
    cli = _load_cli()
    calls = _run_evaluate(cli, monkeypatch, bare_box)

    cli._dispatch("evaluate", ["--help"])

    assert calls, "evaluate exited instead of running conda"
    assert calls[0][0] == str(base / "bin" / "conda")
    assert calls[0][1][-1] == "--help"


def test_evaluate_honours_binderscout_conda(bare_box, tmp_path, monkeypatch):
    base = _base(tmp_path / "chosen")
    monkeypatch.setenv("BINDERSCOUT_CONDA", str(base))
    cli = _load_cli()
    calls = _run_evaluate(cli, monkeypatch, bare_box)

    cli._dispatch("evaluate", [])

    assert calls and calls[0][0] == str(base / "bin" / "conda")


def test_no_conda_says_how_to_point_at_one_or_to_install_it(bare_box, monkeypatch, capsys):
    cli = _load_cli()
    _run_evaluate(cli, monkeypatch, bare_box)

    with pytest.raises(SystemExit) as stop:
        cli._dispatch("evaluate", [])

    err = capsys.readouterr().err
    assert stop.value.code == 1
    assert "BINDERSCOUT_CONDA" in err and "install" in err.lower()
    assert "reinstall" not in err.lower()


def test_a_base_without_a_conda_executable_is_refused_not_a_traceback(bare_box, tmp_path, monkeypatch, capsys):
    base = _base(tmp_path / "micro", with_conda_bin=False)
    monkeypatch.setenv("BINDERSCOUT_CONDA", str(base))
    cli = _load_cli()
    calls = _run_evaluate(cli, monkeypatch, bare_box)

    with pytest.raises(SystemExit) as stop:
        cli._dispatch("evaluate", [])

    assert stop.value.code == 1 and not calls
    assert str(base / "bin" / "conda") in capsys.readouterr().err


def test_the_tui_finds_an_env_under_a_conda_that_is_only_reachable_through_conda_exe(bare_box, tmp_path, monkeypatch):
    base = _base(tmp_path / "somewhere" / "odd")
    (base / "envs" / "BoltzGen").mkdir(parents=True)
    monkeypatch.setenv("CONDA_EXE", str(base / "bin" / "conda"))

    assert app._detect_tools(bare_box)["BoltzGen"] is True


def test_neither_entry_point_keeps_a_private_conda_search():
    cli = _load_cli()
    assert not hasattr(cli, "_find_conda_base")
    assert not hasattr(app, "_find_conda_base")
