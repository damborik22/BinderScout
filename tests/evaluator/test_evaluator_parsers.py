"""Tests for the new _parse_pxdesign() evaluator parser."""

import sys
from pathlib import Path

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
