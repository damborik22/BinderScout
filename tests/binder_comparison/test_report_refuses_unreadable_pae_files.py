"""`report` must refuse when PAE files are listed but not one of them can be read.

A refold CSV copied away from its PAE directory (or read with relative paths from another
working directory) used to produce a complete-looking report: boltz_pae_iptm and
consensus_iptm_mean blank, consensus_iptm_n 0, and `rank` still written from tiebreakers
alone -- with exit 0. Found in the v2.0.3 end-to-end run on the aarch64 host.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "integration" / "golden_pool"


def _report(tmp_path, boltz_csv: Path):
    out = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "binder_comparison",
            "report",
            "--boltz2-results",
            str(boltz_csv),
            "--sequences",
            str(GOLDEN / "sequences.fasta"),
            "-o",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            "PYTHONPATH": str(REPO / "Evaluator"),
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        timeout=300,
    )
    return proc, out


def test_a_csv_copied_without_its_pae_directory_is_refused(tmp_path):
    alone = tmp_path / "elsewhere" / "boltz2_results.csv"
    alone.parent.mkdir()
    shutil.copy(GOLDEN / "boltz2_results.csv", alone)
    proc, out = _report(tmp_path, alone)
    assert proc.returncode == 1, (proc.returncode, proc.stdout[-400:], proc.stderr[-400:])
    assert "none could be read" in proc.stderr
    assert not (out / "metrics.csv").exists(), "a ranking was written from no scores at all"


def test_control_the_same_csv_beside_its_pae_directory_reports(tmp_path):
    """Without this the test above would also pass if the CLI could not run at all."""
    beside = tmp_path / "pool"
    shutil.copytree(GOLDEN, beside)
    proc, out = _report(tmp_path, beside / "boltz2_results.csv")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert (out / "metrics.csv").exists()
