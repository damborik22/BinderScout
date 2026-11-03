"""`path_base` says what a config file's relative paths are relative to; never the cwd."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "configurator"))
import configurator as conf  # noqa: E402


def _config(tmp_path: Path, **top) -> Path:
    (tmp_path / "t.pdb").write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n")
    payload = {
        "config_version": 1,
        "tools_enabled": {"bindcraft2": True},
        "cfg": {"name": "T", "run_dir": "out/run", "target_pdb_src": "t.pdb", "target_sequence": "A"},
        **top,
    }
    path = tmp_path / "c.json"
    path.write_text(json.dumps(payload))
    return path


def test_path_base_config_resolves_relative_paths_against_the_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path.parent)  # a cwd that is neither the file's directory nor the checkout
    cfg, _tools = conf.load_run_config(_config(tmp_path, path_base="config"))
    assert cfg["run_dir"] == (tmp_path / "out" / "run").resolve()
    assert cfg["target_pdb_src"] == (tmp_path / "t.pdb").resolve()


def test_the_default_path_base_is_the_checkout_not_the_cwd(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    (checkout / "out").mkdir(parents=True)
    (checkout / "t.pdb").write_text("ATOM\n")
    config = _config(tmp_path)  # its own t.pdb sits beside it, NOT in the checkout
    monkeypatch.setattr(conf, "BINDERSCOUT_DIR", checkout)
    monkeypatch.chdir(tmp_path)
    cfg, _tools = conf.load_run_config(config)
    assert cfg["run_dir"] == (checkout / "out" / "run").resolve()
    assert cfg["target_pdb_src"] == (checkout / "t.pdb").resolve()


def test_an_unknown_path_base_is_refused(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        conf.load_run_config(_config(tmp_path, path_base="cwd"))
    assert exc.value.code == 1
    assert "path_base" in capsys.readouterr().out
