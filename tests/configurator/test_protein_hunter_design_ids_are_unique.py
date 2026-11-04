"""Protein-Hunter collector: two different designs never share a design_id.

summary_high_iptm.csv has one row per PASSING CYCLE, so one run (one run_id) contributes
several rows with different sequences. The collector built `ph_<run_id>` from the run id
alone, and the pool came out with distinct sequences under one id. The id now carries the
cycle (the Evaluator extractor already names them `protein_hunter_<run>_c<cycle>`).

The collector's heredoc is cut out of the generated script and run against a hand-built
output tree; nothing here runs Protein-Hunter.
"""

import csv
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

NAME = "demo"
SEQ_A = "MKTAYIAKQRQISFVKSHFSRQ"
SEQ_B = "MKTAYIAKQRQISFVKSHFSRA"
SEQ_C = "GSHMKTAYIAKQRQISFVKSHF"


@pytest.fixture
def collector(tmp_path):
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
    sh = tmp_path / "run_protein_hunter.sh"
    conf.write_run_protein_hunter(sh, cfg)
    m = re.search(r"python3 - .*<<'PYEOF'\n(.*?)\nPYEOF\n", sh.read_text(), re.S)
    assert m, "the generated script has no collector heredoc"
    py = tmp_path / "collector.py"
    py.write_text(m.group(1))
    return py


def _collect(py: Path, out_dir: Path, tmp_path: Path) -> list[dict]:
    csv_path = tmp_path / "sequences.csv"
    proc = subprocess.run(
        [sys.executable, str(py), str(out_dir), str(csv_path), NAME], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return list(csv.DictReader(csv_path.open()))


def _write_summary(out: Path, rows: list[dict]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "summary_high_iptm.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run_id", "cycle", "sequence", "iptm", "plddt"])
        w.writeheader()
        w.writerows(rows)


def test_cycles_of_one_run_get_distinct_ids(collector, tmp_path):
    out = tmp_path / "out"
    _write_summary(
        out,
        [
            {"run_id": 0, "cycle": 3, "sequence": SEQ_A, "iptm": 0.81, "plddt": 0.9},
            {"run_id": 0, "cycle": 5, "sequence": SEQ_B, "iptm": 0.84, "plddt": 0.9},
            {"run_id": 1, "cycle": 5, "sequence": SEQ_C, "iptm": 0.79, "plddt": 0.9},
        ],
    )
    rows = _collect(collector, out, tmp_path)
    # control: the summary CSV was the source and all three different sequences survived
    assert {r["sequence"] for r in rows} == {SEQ_A, SEQ_B, SEQ_C}
    assert {r["csv_source"] for r in rows} == {"summary_high_iptm.csv"}
    ids = [r["design_id"] for r in rows]
    assert len(set(ids)) == len(ids), f"two designs share a design_id: {ids}"
    assert sorted(ids) == ["ph_0_c3", "ph_0_c5", "ph_1_c5"]


def test_ids_are_stable_across_reruns(collector, tmp_path):
    out = tmp_path / "out"
    _write_summary(out, [{"run_id": 7, "cycle": 2, "sequence": SEQ_A, "iptm": 0.8, "plddt": 0.9}])
    first = [r["design_id"] for r in _collect(collector, out, tmp_path)]
    second = [r["design_id"] for r in _collect(collector, out, tmp_path)]
    assert first == second == ["ph_7_c2"]


def test_a_cycle_less_source_still_gets_unique_ids(collector, tmp_path):
    """FASTA fallback: two records with the same header must not share an id."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.fasta").write_text(f">d1\n{SEQ_A}\n>d1\n{SEQ_B}\n")
    rows = _collect(collector, out, tmp_path)
    assert {r["sequence"] for r in rows} == {SEQ_A, SEQ_B}, "the FASTA fallback was not reached"
    ids = [r["design_id"] for r in rows]
    assert len(set(ids)) == 2, ids


def test_the_call_site_passes_the_cycle_through(collector):
    """Mutating the call site (dropping cycle=...) must be caught: the id is built from it."""
    text = collector.read_text()
    assert re.search(r"row = _row\(\s*design_id,\s*seq_field,\s*cycle=cycle", text), (
        "_row() is no longer given the cycle, so ids cannot carry it"
    )
