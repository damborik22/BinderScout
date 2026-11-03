"""`binder-compare extract` with one empty tool among tools that produced designs.

A live campaign had 50 real RFD3 sequences and a Protein-Hunter run in which no cycle
cleared its iPTM threshold. `extract` printed "-> 50 sequences", then exited 1 and wrote
NO FASTA, discarding the real pool. A tool that is empty is now a named warning and the
FASTA is still written; only "no tool produced anything", or a path that is not a
directory, stops the run.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

_EVALUATOR = Path(__file__).resolve().parents[2] / "Evaluator"
_SEQ_A = "ACDEFGHIKLMNPQRSTVWY" * 3
_SEQ_B = "MKTAYIAKQRQISFVKSHFS" * 3


def _extract(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "binder_comparison", "extract", *args, "--output", str(tmp_path / "seqs.fasta")],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(_EVALUATOR), "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def rfd3_pool(tmp_path):
    d = tmp_path / "rfd3"
    d.mkdir()
    pd.DataFrame([{"sequence": _SEQ_A, "design_id": "r1"}, {"sequence": _SEQ_B, "design_id": "r2"}]).to_csv(
        d / "sequences.csv", index=False
    )
    return d


@pytest.fixture
def empty_ph(tmp_path):
    d = tmp_path / "ph_nothing_cleared"
    d.mkdir()
    return d


class TestOneEmptyToolDoesNotDiscardTheRest:
    def test_real_pool_is_written_and_exit_is_zero(self, tmp_path, rfd3_pool, empty_ph):
        res = _extract(tmp_path, "--rfd3", str(rfd3_pool), "--protein-hunter", str(empty_ph))
        assert res.returncode == 0, res.stderr
        fasta = (tmp_path / "seqs.fasta").read_text()
        assert _SEQ_A in fasta and _SEQ_B in fasta

    def test_the_empty_tool_is_named_with_its_directory_and_the_flag_to_pass(self, tmp_path, rfd3_pool, empty_ph):
        res = _extract(tmp_path, "--rfd3", str(rfd3_pool), "--protein-hunter", str(empty_ph))
        warning = next(ln for ln in res.stderr.splitlines() if "[extract] WARNING" in ln)
        assert "protein_hunter" in warning
        assert str(empty_ph) in warning
        assert "--all-protein-hunter-designs" in warning
        assert "rfd3" not in warning  # the productive tool is not accused

    def test_control_the_empty_tool_really_was_read_and_the_pool_is_only_rfd3(self, tmp_path, rfd3_pool, empty_ph):
        """Without this the tests above could pass because Protein-Hunter was never reached."""
        res = _extract(tmp_path, "--rfd3", str(rfd3_pool), "--protein-hunter", str(empty_ph))
        assert "[extract] Protein-Hunter:" in res.stdout
        assert "Total: 2 unique binders" in res.stdout


class TestStillFailsLoudly:
    def test_every_tool_empty_exits_1_and_writes_no_file(self, tmp_path, empty_ph):
        other = tmp_path / "rfd3_empty"
        other.mkdir()
        res = _extract(tmp_path, "--rfd3", str(other), "--protein-hunter", str(empty_ph))
        assert res.returncode == 1
        assert "produced 0 sequences" in res.stderr
        assert "--allow-empty" in res.stderr
        assert not (tmp_path / "seqs.fasta").exists()

    def test_allow_empty_does_not_make_an_all_empty_call_succeed(self, tmp_path, empty_ph):
        res = _extract(tmp_path, "--protein-hunter", str(empty_ph), "--allow-empty")
        assert res.returncode == 1
        assert "no binders found" in res.stderr
        assert not (tmp_path / "seqs.fasta").exists()

    def test_a_tool_path_that_is_not_a_directory_is_an_error_even_with_a_real_pool(self, tmp_path, rfd3_pool):
        missing = tmp_path / "typo"
        res = _extract(tmp_path, "--rfd3", str(rfd3_pool), "--protein-hunter", str(missing))
        assert res.returncode == 1
        assert "--protein-hunter" in res.stderr
        assert "not a directory" in res.stderr
        assert not (tmp_path / "seqs.fasta").exists()
