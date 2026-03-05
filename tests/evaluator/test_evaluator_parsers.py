"""Tests for the new _parse_pxdesign() and _parse_rfaa() evaluator parsers."""

import csv
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add evaluator to path so we can import the module
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evaluator"))
import evaluator as ev


@pytest.fixture
def run_dir(tmp_path):
    """Create a minimal run directory structure."""
    return tmp_path / "runs" / "test_run"


# ── PXDesign parser tests ─────────────────────────────────────────────────────


class TestParsePxdesign:
    def test_returns_empty_when_no_dir(self, run_dir):
        assert ev._parse_pxdesign(run_dir) == []

    def test_reads_summary_csv_from_outputs(self, run_dir):
        pxd = run_dir / "pxdesign" / "outputs"
        pxd.mkdir(parents=True)
        csv_path = pxd / "summary.csv"
        csv_path.write_text("sequence,rank\nMGGSSHHH,1\nAEVKLSYV,2\n")

        rows = ev._parse_pxdesign(run_dir)
        assert len(rows) == 2
        assert rows[0]["source"] == "pxdesign"
        assert rows[0]["sequence"] == "MGGSSHHH"
        assert rows[1]["sequence"] == "AEVKLSYV"

    def test_reads_summary_csv_from_import_dir(self, run_dir):
        pxd = run_dir / "pxdesign"
        pxd.mkdir(parents=True)
        csv_path = pxd / "summary.csv"
        csv_path.write_text("sequence,rank\nMGGSSHHH,1\n")

        rows = ev._parse_pxdesign(run_dir)
        assert len(rows) == 1
        assert rows[0]["source"] == "pxdesign"

    def test_reads_nested_summary_csv(self, run_dir):
        nested = run_dir / "pxdesign" / "outputs" / "design_outputs" / "task1"
        nested.mkdir(parents=True)
        csv_path = nested / "summary.csv"
        csv_path.write_text("sequence,rank\nAAAAAA,1\n")

        rows = ev._parse_pxdesign(run_dir)
        assert len(rows) == 1
        assert rows[0]["sequence"] == "AAAAAA"

    def test_sets_default_sequence(self, run_dir):
        pxd = run_dir / "pxdesign" / "outputs"
        pxd.mkdir(parents=True)
        csv_path = pxd / "summary.csv"
        csv_path.write_text("rank,score\n1,0.95\n")

        rows = ev._parse_pxdesign(run_dir)
        assert len(rows) == 1
        assert rows[0]["sequence"] == ""


# ── RFAA parser tests ─────────────────────────────────────────────────────────


class TestParseRfaa:
    def test_returns_empty_when_no_dir(self, run_dir):
        assert ev._parse_rfaa(run_dir) == []

    def test_reads_sequences_csv(self, run_dir):
        rfaa = run_dir / "rfaa"
        rfaa.mkdir(parents=True)
        csv_path = rfaa / "sequences.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["design_id", "sequence", "overall_confidence", "source"])
            w.writeheader()
            w.writerow({"design_id": "sample_0_111", "sequence": "MAEVKLSYVL", "overall_confidence": "0.87", "source": "rfaa"})
            w.writerow({"design_id": "sample_0_112", "sequence": "KGDVLAEVSL", "overall_confidence": "0.82", "source": "rfaa"})

        rows = ev._parse_rfaa(run_dir)
        assert len(rows) == 2
        assert rows[0]["source"] == "rfaa"
        assert rows[0]["sequence"] == "MAEVKLSYVL"
        assert rows[1]["sequence"] == "KGDVLAEVSL"

    def test_filters_empty_sequences(self, run_dir):
        rfaa = run_dir / "rfaa"
        rfaa.mkdir(parents=True)
        csv_path = rfaa / "sequences.csv"
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["design_id", "sequence", "source"])
            w.writeheader()
            w.writerow({"design_id": "good", "sequence": "MAEVKLSYVL", "source": "rfaa"})
            w.writerow({"design_id": "empty", "sequence": "", "source": "rfaa"})

        rows = ev._parse_rfaa(run_dir)
        assert len(rows) == 1
        assert rows[0]["design_id"] == "good"

    def test_warns_backbone_only(self, run_dir):
        outputs = run_dir / "rfaa" / "outputs"
        outputs.mkdir(parents=True)
        (outputs / "sample_0.pdb").write_text("ATOM ...")
        (outputs / "sample_1.pdb").write_text("ATOM ...")

        with patch.object(ev, "_print_warn") as mock_warn:
            rows = ev._parse_rfaa(run_dir)
            assert rows == []
            mock_warn.assert_called_once()
            assert "2 backbone PDB(s)" in mock_warn.call_args[0][0]
            assert "LigandMPNN" in mock_warn.call_args[0][0]

    def test_no_warn_when_nothing_exists(self, run_dir):
        rfaa = run_dir / "rfaa"
        rfaa.mkdir(parents=True)
        # outputs dir doesn't exist at all

        with patch.object(ev, "_print_warn") as mock_warn:
            rows = ev._parse_rfaa(run_dir)
            assert rows == []
            mock_warn.assert_not_called()
