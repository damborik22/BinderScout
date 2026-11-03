"""Protein-Hunter extractor: when summary_high_iptm.csv is absent, the message says why."""

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


def _csv(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _collect(extractor, directory):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        got = extractor.extract(directory)
    return got, [str(w.message) for w in caught]


class TestNothingClearedTheThresholdSaysSo:
    def _all_runs_only(self, tmp_path):
        _csv(
            tmp_path / "summary_all_runs.csv",
            [
                {"run_id": 1, "best_seq": _SEQ_A, "best_iptm": 0.41, "best_plddt": 0.8},
                {"run_id": 2, "best_seq": _SEQ_B, "best_iptm": 0.62, "best_plddt": 0.8},
                {"run_id": 3, "best_seq": None, "best_iptm": None, "best_plddt": None},
            ],
        )

    def test_message_gives_reason_count_best_iptm_and_the_flag(self, tmp_path):
        self._all_runs_only(tmp_path)
        _, messages = _collect(ProteinHunterExtractor(), tmp_path)
        text = " ".join(messages)
        assert "--high_iptm_threshold" in text
        assert "0.7" in text
        assert "2 design" in text  # the run with no best_seq is not a design
        assert "0.62" in text  # best iPTM among them
        assert "--all-protein-hunter-designs" in text

    def test_default_extraction_is_unchanged(self, tmp_path):
        self._all_runs_only(tmp_path)
        got, _ = _collect(ProteinHunterExtractor(), tmp_path)
        assert got == []

    def test_control_the_flag_the_message_names_does_return_those_designs(self, tmp_path):
        self._all_runs_only(tmp_path)
        got, _ = _collect(ProteinHunterExtractor(all_runs=True), tmp_path)
        assert sorted(b.sequence for b in got) == sorted([_SEQ_A, _SEQ_B])

    def test_an_all_runs_file_without_best_iptm_still_gets_the_reason(self, tmp_path):
        _csv(tmp_path / "summary_all_runs.csv", [{"run_id": 1, "best_seq": _SEQ_A}])
        _, messages = _collect(ProteinHunterExtractor(), tmp_path)
        text = " ".join(messages)
        assert "--high_iptm_threshold" in text
        assert "1 design" in text
        assert "best iPTM" not in text

    def test_no_summary_files_at_all_does_not_claim_a_threshold_was_missed(self, tmp_path):
        _, messages = _collect(ProteinHunterExtractor(), tmp_path)
        text = " ".join(messages)
        assert "summary_high_iptm.csv" in text
        assert "--high_iptm_threshold" not in text
