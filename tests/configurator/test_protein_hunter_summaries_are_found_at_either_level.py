"""Protein-Hunter summaries: found whether or not boltz_ph made a {name}/ subdirectory.

The generated script (and the hand-written template) read the summary CSVs from
`<save_dir>/<name>/`. A boltz_ph build that writes them straight into `<save_dir>` left
that path empty, and the collector fell through to the FASTA / PDB scan WITHOUT saying
so: the pool still came out, but every native metric (iptm, plddt) was gone.

Nothing here runs Protein-Hunter. The collector's heredoc and the locate loop are cut out
of the generated text and run against hand-built output trees, one per layout.
"""

import csv
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "binderscout_examples" / "run_protein_hunter.sh.template"
NAME = "demo"
SEQ = "MKTAYIAKQRQISFVKSHFSRQ"


@pytest.fixture
def script(tmp_path):
    pdb = tmp_path / "t.pdb"
    pdb.write_text("ATOM      1  CA  MET A   1       0.000   0.000   0.000  1.00  0.00           C\n")
    cfg = {
        "name": NAME,
        "run_dir": tmp_path / "run",
        "target_pdb": pdb,
        "target_sequence": "MAE",
        "chains": "A",
        "min_length": 20,
        "max_length": 30,
        "n_designs": 1,
    }
    path = tmp_path / "run_protein_hunter.sh"
    conf.write_run_protein_hunter(path, cfg)
    return path.read_text()


def _collector(script_text: str, tmp_path: Path) -> Path:
    m = re.search(r"python3 - .*<<'PYEOF'\n(.*?)\nPYEOF\n", script_text, re.S)
    assert m, "the generated script has no collector heredoc"
    py = tmp_path / "collector.py"
    py.write_text(m.group(1))
    return py


def _summaries(where: Path) -> None:
    where.mkdir(parents=True, exist_ok=True)
    with (where / "summary_high_iptm.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run_id", "cycle", "sequence", "iptm", "plddt"])
        w.writeheader()
        w.writerow({"run_id": 0, "cycle": 3, "sequence": SEQ, "iptm": 0.81, "plddt": 0.9})


def _run_collector(py: Path, out_dir: Path, tmp_path: Path):
    csv_path = tmp_path / "sequences.csv"
    proc = subprocess.run(
        [sys.executable, str(py), str(out_dir), str(csv_path), NAME], capture_output=True, text=True, check=False
    )
    rows = list(csv.DictReader(csv_path.open())) if csv_path.exists() else []
    return proc, rows


@pytest.mark.parametrize("nested", [True, False], ids=["name-subdir", "flat"])
def test_the_collector_keeps_the_native_metrics_at_either_level(script, tmp_path, nested):
    out = tmp_path / "out"
    _summaries(out / NAME if nested else out)
    proc, rows = _run_collector(_collector(script, tmp_path), out, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert [r["sequence"] for r in rows] == [SEQ]
    assert rows[0]["iptm"] == "0.81", "the native iptm was lost: the summary CSV was not used"
    assert rows[0]["csv_source"] == "summary_high_iptm.csv"
    where = str(out / NAME) if nested else str(out)
    assert f"{where}/summary_high_iptm.csv" in proc.stdout, "the collector must say which file it read"
    assert "WARNING" not in proc.stderr


def test_the_name_subdir_wins_when_both_levels_hold_summaries(script, tmp_path):
    out = tmp_path / "out"
    _summaries(out)
    nested = out / NAME
    nested.mkdir()
    (nested / "summary_high_iptm.csv").write_text("run_id,cycle,sequence,iptm,plddt\n0,1,GGGGGGGGGG,0.5,0.5\n")
    proc, rows = _run_collector(_collector(script, tmp_path), out, tmp_path)
    assert [r["sequence"] for r in rows] == ["GGGGGGGGGG"]
    assert str(nested) in proc.stdout


def test_losing_the_summaries_is_loud_not_silent(script, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "d1.fasta").write_text(f">d1\n{SEQ}\n")
    proc, rows = _run_collector(_collector(script, tmp_path), out, tmp_path)
    assert [r["sequence"] for r in rows] == [SEQ], "the FASTA fallback must still produce the pool"
    assert "WARNING" in proc.stderr and "native metrics" in proc.stderr


def _locate_loop(text: str) -> str:
    m = re.search(r'^PH_SUMMARY_DIR=""\n.*?^fi\n', text, re.S | re.M)
    assert m, "no summary-locating block"
    return m.group(0)


def _locate(which: str, script: str) -> tuple[str, str]:
    """(script text, name of the variable that holds the output dir) for the generated script or template."""
    return (script, "PH_DIR_OUT") if which == "generated" else (TEMPLATE.read_text(), "RUN_DIR")


@pytest.mark.parametrize("nested", [True, False], ids=["name-subdir", "flat"])
@pytest.mark.parametrize("which", ["generated", "template"])
def test_the_locate_block_reports_the_level_it_found(script, tmp_path, nested, which):
    text, var = _locate(which, script)
    out = tmp_path / "out"
    _summaries(out / NAME if nested else out)
    block = _locate_loop(text).replace("{{NAME}}", NAME)
    probe = f'{var}="{out}"\n{block}\necho "FOUND=$PH_SUMMARY_DIR"\n'
    proc = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, check=False)
    expected = out / NAME if nested else out
    assert proc.returncode == 0, proc.stderr
    assert f"FOUND={expected}" in proc.stdout
    assert f"found in: {expected}" in proc.stdout


@pytest.mark.parametrize("which", ["generated", "template"])
def test_the_locate_block_warns_when_neither_level_has_them(script, tmp_path, which):
    text, var = _locate(which, script)
    out = tmp_path / "empty"
    out.mkdir()
    block = _locate_loop(text).replace("{{NAME}}", NAME)
    proc = subprocess.run(["bash", "-c", f'{var}="{out}"\n{block}'], capture_output=True, text=True, check=False)
    assert "WARNING" in proc.stderr and "native metrics" in proc.stderr
