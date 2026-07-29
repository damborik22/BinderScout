"""Tests for `binder-compare validate`'s target loading.

`--target-pdb` imported a function that does not exist, and the import sat inside
a bare `except Exception: return f"ERROR: {e}"` — so the command reported an
import error *as the target sequence* and every downstream length comparison was
made against that string. Silent, and exit code 0.
"""

import argparse
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.cli.validate import _load_target

_SEQ = "AGACD"
_THREE = {"A": "ALA", "G": "GLY", "C": "CYS", "D": "ASP"}


def _pdb(path: Path) -> Path:
    lines = [
        f"ATOM  {i + 1:>5}  CA  {_THREE[aa]} A{i + 1:>4}       0.000   0.000   0.000  1.00  0.00           C"
        for i, aa in enumerate(_SEQ)
    ]
    path.write_text("\n".join(lines) + "\nEND\n")
    return path


class TestLoadTarget:
    def test_target_pdb_returns_the_sequence(self, tmp_path):
        args = argparse.Namespace(target_seq=None, target_pdb=str(_pdb(tmp_path / "t.pdb")))
        assert _load_target(args) == _SEQ

    def test_target_pdb_never_returns_an_import_error_as_a_sequence(self, tmp_path):
        args = argparse.Namespace(target_seq=None, target_pdb=str(_pdb(tmp_path / "t.pdb")))
        got = _load_target(args)
        assert not got.startswith("ERROR"), f"an error string was handed back as the target: {got}"

    def test_target_seq_still_wins_and_is_normalised(self, tmp_path):
        args = argparse.Namespace(target_seq=" mkt ", target_pdb=str(_pdb(tmp_path / "t.pdb")))
        assert _load_target(args) == "MKT"

    def test_unreadable_pdb_is_reported_as_an_error(self, tmp_path):
        args = argparse.Namespace(target_seq=None, target_pdb=str(tmp_path / "missing.pdb"))
        assert _load_target(args).startswith("ERROR")
