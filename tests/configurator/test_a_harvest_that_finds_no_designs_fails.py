"""A design step that produced nothing must not report success.

The generated Proteina-Complexa and PXDesign scripts end in a harvest that reads the tool's
output tree and writes `sequences.csv`. Finding no sequences at all, each printed a warning
and exited 0. `run_all.sh` counted the step as passed, the Evaluator then logged "no CSV
found" and dropped the tool, and the report simply had no column for it -- a design step that
produced nothing, reporting success. `run_all.sh` is built to carry on past a failed step and
name it at the end, so the harvest only has to say it failed.

The tail of each generated script is run under real bash, against an EMPTY output directory,
so what is asserted is the exit status of the shipped text rather than of a re-typed copy. A
populated tree is the control: without it, "exits non-zero" would be just as true of a snippet
that dies on its first line.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))

import configurator as conf

RUN_NAME = "emptycase"
SEQ = "MKAEELLRKAWEIAKQNPQAVELLKKAAELAKEHGDKELAKKVLEIAKQ"
MARKER = 'echo "=== Collecting binder sequences ==="'


def _target(tmp_path: Path) -> Path:
    pdb = tmp_path / "target.pdb"
    pdb.write_text(
        "".join(
            f"ATOM  {i:5d}  CA  ALA A{i:4d}    {float(i):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C\n"
            for i in range(1, 6)
        )
        + "END\n"
    )
    return pdb


def _cfg(tmp_path: Path, run_dir: Path) -> dict:
    return {
        "name": RUN_NAME,
        "run_dir": str(run_dir),
        "target_pdb": str(_target(tmp_path)),
        "target_sequence": "AAAAA",
        "chains": "A",
        "hotspots": "2,3",
        "min_length": 20,
        "max_length": 30,
        "pxdesign_binder_length": 25,
    }


def _harvest_snippet(tool: str, tmp_path: Path, run_dir: Path) -> str:
    """The generated script from its collection banner to the end, i.e. exactly the harvest."""
    script = tmp_path / f"run_{tool}.sh"
    writer = {"pxdesign": conf.write_run_pxdesign, "proteina_complexa": conf.write_run_proteina_complexa}[tool]
    writer(script, _cfg(tmp_path, run_dir))
    text = script.read_text()
    assert MARKER in text, f"{tool}: the harvest no longer starts at {MARKER!r}; update this test with it"
    return "set -euo pipefail\n" + text[text.index(MARKER) :]


def _run(snippet: str, run_dir: Path, cwd: Path) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "RUN_DIR": str(run_dir), "HOME": str(cwd)}
    return subprocess.run(["bash", "-c", snippet], capture_output=True, text=True, cwd=cwd, env=env, timeout=120)


def _populate(tool: str, run_dir: Path, cwd: Path) -> None:
    """The smallest output tree the tool's harvest recognises as a design."""
    if tool == "pxdesign":
        d = run_dir / "pxdesign" / "outputs_len25" / "summary"
        d.mkdir(parents=True)
        with (d / "summary.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["rank", "task_name", "sequence"])
            w.writeheader()
            w.writerow({"rank": "1", "task_name": "t", "sequence": SEQ})
    else:
        d = cwd / "evaluation_results" / f"pipeline_binderscout_{RUN_NAME}"
        d.mkdir(parents=True)
        with (d / "binder_results_0.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["self_sequence", "self_complex_i_pTM"])
            w.writeheader()
            w.writerow({"self_sequence": SEQ, "self_complex_i_pTM": "0.5"})


@pytest.fixture(params=["pxdesign", "proteina_complexa"])
def tool(request):
    return request.param


def _layout(tool: str, tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    (run_dir / ("pxdesign" if tool == "pxdesign" else "proteina_complexa")).mkdir(parents=True)
    # Proteina-Complexa's harvest is relative to ITS clone (the script cd's there); an empty
    # directory is "Complexa wrote nothing". PXDesign's is relative to $RUN_DIR.
    cwd = tmp_path / "clone"
    cwd.mkdir()
    return run_dir, cwd


def test_a_harvest_of_an_empty_output_directory_exits_nonzero(tool, tmp_path):
    run_dir, cwd = _layout(tool, tmp_path)
    proc = _run(_harvest_snippet(tool, tmp_path, run_dir), run_dir, cwd)

    assert proc.returncode != 0, f"{tool}: extracted nothing and still exited 0\nstdout={proc.stdout}\n{proc.stderr}"
    assert "No binder sequences extracted" in proc.stderr, proc.stderr
    assert not (run_dir / ("pxdesign" if tool == "pxdesign" else "proteina_complexa") / "sequences.csv").exists()


def test_control_the_same_snippet_succeeds_on_a_populated_tree(tool, tmp_path):
    """Proves the empty-tree failure above came from finding nothing, not from the snippet dying."""
    run_dir, cwd = _layout(tool, tmp_path)
    _populate(tool, run_dir, cwd)
    proc = _run(_harvest_snippet(tool, tmp_path, run_dir), run_dir, cwd)

    assert proc.returncode == 0, f"{tool}: could not harvest a populated tree\nstdout={proc.stdout}\n{proc.stderr}"
    out = run_dir / ("pxdesign" if tool == "pxdesign" else "proteina_complexa") / "sequences.csv"
    with out.open() as fh:
        assert [r["sequence"] for r in csv.DictReader(fh)] == [SEQ]
