"""Tests for the RFAAExtractor in the Evaluator package."""

import csv
import warnings
from pathlib import Path

import pytest

from Evaluator.binder_comparison.extractors.rfaa import RFAAExtractor


@pytest.fixture
def extractor():
    return RFAAExtractor()


class TestRFAAExtractor:
    def test_tool_name(self, extractor):
        assert extractor.tool_name == "rfaa"

    def test_extract_from_csv(self, extractor, tmp_path):
        csv_path = tmp_path / "sequences.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["design_id", "sequence", "overall_confidence"])
            w.writeheader()
            w.writerow({"design_id": "s0_111", "sequence": "MAEVKLSYVL", "overall_confidence": "0.87"})
            w.writerow({"design_id": "s0_112", "sequence": "KGDVLAEVSL", "overall_confidence": "0.82"})

        results = extractor.extract(tmp_path)
        assert len(results) == 2
        assert results[0].binder_id == "s0_111"
        assert results[0].sequence == "MAEVKLSYVL"
        assert results[0].source_tool == "rfaa"
        assert results[1].binder_id == "s0_112"

    def test_extract_skips_invalid_sequences(self, extractor, tmp_path):
        csv_path = tmp_path / "sequences.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["design_id", "sequence"])
            w.writeheader()
            w.writerow({"design_id": "good", "sequence": "MAEVKLSYVL"})
            w.writerow({"design_id": "bad", "sequence": "12345"})
            w.writerow({"design_id": "empty", "sequence": ""})

        results = extractor.extract(tmp_path)
        assert len(results) == 1
        assert results[0].binder_id == "good"

    def test_fallback_backbone_pdbs(self, extractor, tmp_path):
        outputs = tmp_path / "outputs"
        outputs.mkdir()
        (outputs / "sample_0.pdb").write_text("ATOM ...")
        (outputs / "sample_1.pdb").write_text("ATOM ...")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            results = extractor.extract(tmp_path)
            assert len(results) == 2
            assert results[0].sequence == ""
            assert results[0].binder_id == "rfaa_sample_0"
            assert results[1].binder_id == "rfaa_sample_1"
            assert len(w) == 1
            assert "LigandMPNN" in str(w[0].message)

    def test_empty_dir_returns_empty(self, extractor, tmp_path):
        results = extractor.extract(tmp_path)
        assert results == []

    def test_csv_in_parent_dir(self, extractor, tmp_path):
        csv_path = tmp_path / "sequences.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["design_id", "sequence"])
            w.writeheader()
            w.writerow({"design_id": "s0", "sequence": "MAEVKLSYVL"})

        subdir = tmp_path / "outputs"
        subdir.mkdir()
        results = extractor.extract(subdir)
        assert len(results) == 1
