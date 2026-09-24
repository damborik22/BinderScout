"""Two ways the configurator accepted input it could not honour.

1. A RELATIVE `run_dir` was accepted by `--config` replay and reported ready
   (exit 0, "Run folder ready"), but the generated scripts bake absolute paths
   derived from it and cannot run from anywhere else. The docstring at
   configurator.py:3234 already claimed run_dir was "re-resolved"; only
   `expanduser()` was called. A downloadable config from a front-end is exactly
   the thing most likely to carry a relative path.

2. A chain letter matching nothing in the structure produced NO output at all --
   no confirmation, no warning -- leaving target_sequence empty. That is the
   root cause feeding the RFD3 mislabelling guarded in write_run_rfd3: with no
   sequence and no matching CA atoms, the computed target length is zero.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

PDB = "".join(
    f"ATOM  {i:5d}  CA  ALA {c} {i:3d}       0.000   0.000   0.000  1.00  0.00           C\n"
    for c, i in (("A", 1), ("A", 2), ("B", 3))
)


def _write_cfg(tmp_path, run_dir_value):
    pdb = tmp_path / "t.pdb"
    pdb.write_text(PDB)
    payload = {
        "config_version": 1,
        "tools_enabled": {"bindcraft2": True},
        "cfg": {"name": "T", "run_dir": run_dir_value, "target_pdb_src": str(pdb), "target_sequence": "AAAA"},
    }
    p = tmp_path / "c.json"
    p.write_text(json.dumps(payload))
    return p


def test_a_relative_run_dir_is_made_absolute(tmp_path, monkeypatch):
    """Accepting it and generating unrunnable scripts is worse than rejecting."""
    monkeypatch.chdir(tmp_path)
    cfg_path = _write_cfg(tmp_path, "relative_run")
    cfg, _tools = conf.load_run_config(cfg_path)
    assert Path(cfg["run_dir"]).is_absolute(), f"run_dir stayed relative: {cfg['run_dir']!r}"


def test_an_absolute_run_dir_is_left_alone(tmp_path):
    target = tmp_path / "abs_run"
    cfg, _tools = conf.load_run_config(_write_cfg(tmp_path, str(target)))
    assert Path(cfg["run_dir"]) == target


def test_tilde_still_expands(tmp_path):
    cfg, _tools = conf.load_run_config(_write_cfg(tmp_path, "~/somewhere"))
    assert str(cfg["run_dir"]).startswith(str(Path.home()))


# ---------------------------------------------------------------- chain names


def test_available_chains_lists_what_is_in_the_structure(tmp_path):
    pdb = tmp_path / "t.pdb"
    pdb.write_text(PDB)
    assert conf.available_chains(pdb) == ["A", "B"]


def test_available_chains_is_empty_for_an_unreadable_file(tmp_path):
    assert conf.available_chains(tmp_path / "nope.pdb") == []


@pytest.mark.parametrize("chain", ["A", "B"])
def test_a_real_chain_extracts_a_sequence(tmp_path, chain):
    pdb = tmp_path / "t.pdb"
    pdb.write_text(PDB)
    assert conf.extract_sequence_from_structure(pdb, chain)


def test_a_missing_chain_extracts_nothing(tmp_path):
    """The condition the wizard must not pass over in silence."""
    pdb = tmp_path / "t.pdb"
    pdb.write_text(PDB)
    assert not conf.extract_sequence_from_structure(pdb, "Z")
