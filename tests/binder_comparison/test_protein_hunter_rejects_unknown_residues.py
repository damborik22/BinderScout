"""Protein-Hunter extractor: a mostly-unknown (X) sequence is never emitted as a design."""

import sys
import warnings
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.extractors import ProteinHunterExtractor

_SEQ_A = "ACDEFGHIKLMNPQRSTVWY" * 3
_SEQ_B = "MKTAYIAKQRQISFVKSHFS" * 3
# 23 residues, 18 of them unknown: the shape of a pre-design cycle_0 structure.
_MOSTLY_X = "MKTAY" + "X" * 18


def _csv(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _collect(extractor, directory):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        got = extractor.extract(directory)
    return got, [str(w.message) for w in caught]


class TestUnknownResiduesAreNeverADesign:
    """A mostly-X sequence (an unmodelled / pre-design structure) must not reach the refold queue."""

    def test_high_iptm_row_that_is_mostly_x_is_rejected_and_counted(self, tmp_path):
        _csv(
            tmp_path / "summary_high_iptm.csv",
            [
                {"run_id": 1, "cycle": 0, "iptm": 0.9, "sequence": _MOSTLY_X},
                {"run_id": 2, "cycle": 5, "iptm": 0.8, "sequence": _SEQ_A},
            ],
        )
        got, messages = _collect(ProteinHunterExtractor(collapse_variants=False), tmp_path)
        assert [b.sequence for b in got] == [_SEQ_A]
        assert any("invalid sequence" in m for m in messages)

    def test_all_runs_row_that_is_mostly_x_is_rejected(self, tmp_path):
        _csv(
            tmp_path / "summary_all_runs.csv",
            [{"run_id": 1, "best_seq": _MOSTLY_X}, {"run_id": 2, "best_seq": _SEQ_B}],
        )
        got, _ = _collect(ProteinHunterExtractor(all_runs=True), tmp_path)
        assert [b.sequence for b in got] == [_SEQ_B]

    def test_structures_alone_are_never_harvested_as_designs(self, tmp_path):
        """No PDB fallback exists: a directory holding only a pre-design cycle_0 structure
        (every residue UNK) yields nothing."""
        unk = "".join(
            f"ATOM  {i:5d}  CA  UNK A{i:4d}    {float(i):8.3f}   0.000   0.000  1.00  0.00           C\n"
            for i in range(1, 24)
        )
        (tmp_path / "demo_predicted_cycle_0.pdb").write_text(unk)
        got, _ = _collect(ProteinHunterExtractor(), tmp_path)
        assert got == []
        got, _ = _collect(ProteinHunterExtractor(all_runs=True), tmp_path)
        assert got == []
