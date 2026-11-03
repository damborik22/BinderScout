"""`report` must refuse when no refold result belongs to the --sequences pool.

The merger now treats the FASTA as the pool (ported from master 1.0.6) and drops engine rows outside it.
With a fully disjoint, stale engine CSV that used to leave an EMPTY frame, and `report` still wrote a complete
report (metrics.csv, report.html, ...) and exited 0 -- a plausible-looking nothing. Found in review 2026-11-03.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "integration" / "golden_pool"


def _report(tmp_path, fasta: Path):
    out = tmp_path / "out"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "binder_comparison",
            "report",
            "--boltz2-results",
            str(GOLDEN / "boltz2_results.csv"),
            "--sequences",
            str(fasta),
            "-o",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env={
            "PYTHONPATH": str(REPO / "Evaluator"),
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        timeout=300,
    )
    return proc, out


def test_a_pool_that_matches_nothing_is_refused(tmp_path):
    other = tmp_path / "other.fasta"
    other.write_text(">x source=mosaic\nACDEFGHIKLMNPQRSTVWYACDEFGHIK\n")
    proc, out = _report(tmp_path, other)
    assert proc.returncode == 1, (proc.returncode, proc.stderr[-600:])
    assert "nothing to report" in proc.stderr
    assert not (out / "report.html").exists(), "a report was written for a pool nothing matched"


def test_control_the_matching_pool_still_reports(tmp_path):
    """Without this the test above would also pass if the CLI could not run at all."""
    proc, out = _report(tmp_path, GOLDEN / "sequences.fasta")
    assert proc.returncode == 0, proc.stderr[-800:]
    assert (out / "report.html").exists()
