"""What report.html says must match what the ranking does.

Found in the v2.0.3 end-to-end run: the HTML still described the removed Stage-1 top-50% max
screen as a live selection stage (on the same page that says it was retired), never showed
consensus_iptm_n although the docs tell the reader to read it beside the rank, and answered
"no native column available" for five tools whose native metrics were attached and populated.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[2]
VIS = REPO / "Evaluator" / "binder_comparison" / "visualization"
GOLDEN = REPO / "tests" / "integration" / "golden_pool"


def test_no_visualization_text_presents_the_removed_stage_one_screen_as_live():
    banned = ("Two-stage selection", "(Stage-1 screen)", "(Stage-2 rank)", "top-50% max-screen cut", "max-screen (x)")
    hits = [f"{p.name}: {phrase}" for p in sorted(VIS.glob("*.py")) for phrase in banned if phrase in p.read_text()]
    assert not hits, hits


def test_every_tool_with_a_native_metric_is_wired_to_a_native_sort():
    sys.path.insert(0, str(REPO / "Evaluator"))
    from binder_comparison.visualization import report

    for tool, col in {
        "pxdesign": "native_pxdesign_af2_iptm",
        "protein_hunter": "native_protein_hunter_iptm_best",
        "proteina_complexa": "native_complexa_self_iptm",
        "mosaic": "ipsae_min_aux",
        "boltzgen": "native_bg_design_ipsae_min",
    }.items():
        assert report._TOOL_NATIVE_SORT.get(tool) == col, tool
        assert report._TOOL_NATIVE_SORT_DIR.get(tool) in ("asc", "desc"), tool


def test_the_report_shows_how_many_engines_back_each_mean(tmp_path):
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
            str(GOLDEN / "sequences.fasta"),
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
    assert proc.returncode == 0, proc.stderr[-600:]
    html = re.sub(r"data:[^\"']{200,}", "", (out / "report.html").read_text())
    assert "consensus_iptm_n" in html
