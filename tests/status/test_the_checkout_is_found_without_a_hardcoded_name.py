"""`binderscout status` used to find a checkout only under four home-relative names.

Those names were one fleet's pre-rename layout, so any other box (a checkout under
``~/src/tools``, a cluster home with no ``~/dev``) reported "no checkout found" and
showed nothing -- while the local arm was running FROM a checkout and could simply
have used it. Resolution is now: the repo the CLI runs from; then ``$BINDERSCOUT_DIR``;
then a marker the shortcut installer writes; then a bounded, name-agnostic scan.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from status import cli
from status.collect import checkout_marker_path, collect_local, record_checkout, resolve_repo

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("BINDERSCOUT_DIR", raising=False)
    return h


def _checkout(path: Path, runs: bool = True) -> Path:
    path.mkdir(parents=True)
    (path / "binderscout.py").write_text("# stand-in\n")
    if runs:
        (path / "runs").mkdir()
    return path


def test_the_local_arm_uses_the_checkout_the_cli_runs_from(home, tmp_path, monkeypatch, capsys):
    repo = _checkout(tmp_path / "anywhere" / "at-all")
    run = repo / "runs" / "r1"
    run.mkdir()
    (run / "config.json").write_text(json.dumps({"n_designs": 5, "tools_enabled": {"rfd3": True}}))
    monkeypatch.setattr(cli, "REPO", repo)

    assert cli.main(["--local", "--json"]) == 0

    local = json.loads(capsys.readouterr().out)["hosts"]["local"]
    assert "error" not in local, local
    assert "r1" in local["runs"], "the local arm ignored the checkout it is running from"


def test_a_directory_with_a_pre_rename_name_is_not_a_checkout_by_name(home):
    # The old code accepted ~/dev/<old name>/runs as a checkout on the strength of its NAME.
    (home / "dev" / "BindMaster" / "runs").mkdir(parents=True)
    assert resolve_repo() is None


def test_the_scan_finds_a_checkout_under_any_name(home):
    repo = _checkout(home / "work" / "my-copy")
    assert resolve_repo() == repo


def test_the_scan_is_bounded_in_depth(home):
    _checkout(home / "a" / "b" / "c" / "d")
    assert resolve_repo() is None


def test_the_scan_skips_hidden_directories(home):
    _checkout(home / ".cache" / "stray")
    assert resolve_repo() is None


def test_the_environment_variable_beats_the_marker_and_the_scan(home, tmp_path, monkeypatch):
    _checkout(home / "scanned")
    record_checkout(_checkout(tmp_path / "marked"))
    chosen = _checkout(tmp_path / "chosen")
    monkeypatch.setenv("BINDERSCOUT_DIR", str(chosen))
    assert resolve_repo() == chosen


def test_the_marker_beats_the_scan(home, tmp_path):
    _checkout(home / "scanned")
    marked = _checkout(tmp_path / "elsewhere")
    record_checkout(marked)
    assert resolve_repo() == marked


def test_a_stale_marker_falls_through_to_the_scan(home, tmp_path):
    gone = _checkout(tmp_path / "gone")
    record_checkout(gone)
    (gone / "binderscout.py").unlink()
    scanned = _checkout(home / "here")
    assert resolve_repo() == scanned


def test_the_shortcut_installer_writes_the_marker_the_probe_reads(home, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("binderscout_cli_marker_test", REPO / "binderscout.py")
    cli_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_mod)
    fake = _checkout(tmp_path / "far" / "away")
    monkeypatch.setattr(cli_mod, "REPO", fake)

    cli_mod._install_binderscout_shortcut()

    assert checkout_marker_path().is_file(), "the installer wrote no marker"
    assert resolve_repo() == fake


def test_an_explicit_root_with_no_runs_is_reported_not_called_missing(home, tmp_path):
    doc = collect_local(repo_root=_checkout(tmp_path / "fresh", runs=False), host="x")
    assert "error" not in doc and doc["runs"] == {}
