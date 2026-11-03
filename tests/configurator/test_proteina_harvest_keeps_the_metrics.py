"""The Proteina-Complexa harvest must reach the metrics Complexa computed, not just the PDBs.

An audit of a finished run found `proteina_complexa` carrying 2 populated `native_*` columns in
`metrics.csv` against 4-9 for every other tool. Three faults in the generated harvest all pushed it
onto its chain-B PDB fallback, which has no metrics:

1. It committed to the FIRST candidate directory that existed. Complexa writes two trees that hold
   different things: `inference/<config>_<task>_<run>/` has one subdirectory per design with its
   `.pdb` and no sequence-bearing CSV, while `evaluation_results/<config>_<task>_<run>/` holds the
   metrics. Taking whichever came first reached the PDBs and never the metrics.
2. Its CSV strategy read one column name. Complexa names the binder column `binder_sequence`.
3. A design Complexa lists in several CSVs (a combined file and an all-successes file) was kept once
   per file, and a design with no name column got the CSV's stem for its id -- the same id for every
   row of the file.

The tail of the GENERATED script is run under real bash against a synthetic tree in Complexa's
layout, so the shipped text is what is exercised. No design job is run.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))

from configurator import write_run_proteina_complexa

RUN_NAME = "harvestcase"
TASK = f"search_binder_local_pipeline_binderscout_{RUN_NAME}"
BINDER_A = "FKHFDKDGDGTITTKELGTVMRSLGQNPTEAELQDMINEVDADGDGTIDYDEFLTLMAARRKD"
BINDER_B = "AEAYYNRGNAYFNLGNYEEAIEDYSRAIELKPDFAKAYANRAAAYEKLNQPVEAIKDRIEAEK"
TARGET = "NAFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQ"
AA3 = {"F": "PHE", "K": "LYS", "H": "HIS", "D": "ASP", "G": "GLY", "T": "THR", "I": "ILE", "E": "GLU", "L": "LEU"}
AA3.update({"V": "VAL", "M": "MET", "R": "ARG", "S": "SER", "Q": "GLN", "N": "ASN", "P": "PRO", "A": "ALA"})
AA3.update({"Y": "TYR", "W": "TRP", "C": "CYS"})

METRICS = ["self_complex_i_pTM", "self_complex_i_pAE", "self_complex_pLDDT", "self_binder_scRMSD"]
DESIGNS = {
    BINDER_A: {"id": "job_0_id_1_r1", "self_complex_i_pTM": "0.176", "self_complex_i_pAE": "0.639"},
    BINDER_B: {"id": "job_0_id_0_r0", "self_complex_i_pTM": "0.509", "self_complex_i_pAE": "0.336"},
}
for _d in DESIGNS.values():
    _d.setdefault("self_complex_pLDDT", "0.9")
    _d.setdefault("self_binder_scRMSD", "1.1")


def _target_pdb(tmp_path: Path) -> Path:
    path = tmp_path / "target.pdb"
    path.write_text(
        "".join(
            f"ATOM  {i:5d}  CA  ALA A{i:4d}    {float(i):8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C\n"
            for i in range(1, 6)
        )
        + "END\n"
    )
    return path


def _pdb(binder: str) -> str:
    """CA-only two-chain complex in Complexa's layout: target A, binder B."""
    lines = []
    for chain, seq in (("A", TARGET), ("B", binder)):
        for i, aa in enumerate(seq, 1):
            lines.append(
                f"ATOM  {len(lines) + 1:5d}  CA  {AA3[aa]} {chain}{i:4d}    {float(i):8.3f}{0.0:8.3f}{0.0:8.3f}"
                "  1.00  0.00           C"
            )
    return "\n".join(lines) + "\nEND\n"


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _metric_rows(column: str) -> list[dict]:
    return [{column: seq, "target_sequence": TARGET, **{m: d[m] for m in METRICS}} for seq, d in DESIGNS.items()]


def _build_tree(clone: Path, *, column: str = "binder_sequence", metrics: bool = True) -> None:
    """Both trees Complexa writes, relative to its own clone."""
    inf = clone / "inference" / f"search_binder_local_pipeline_{RUN_NAME}_{RUN_NAME}"
    inf.mkdir(parents=True)
    # Non-sequence CSVs: what made "first existing directory" fatal.
    (inf / "rewards_0.csv").write_text("job_id,reward\n0,0.5\n")
    (inf / "timing_0.csv").write_text("job_id,seconds\n0,12\n")
    for seq, d in DESIGNS.items():
        (inf / d["id"]).mkdir()
        (inf / d["id"] / f"{d['id']}.pdb").write_text(_pdb(seq))
    if metrics:
        ev = clone / "evaluation_results" / TASK
        ev.mkdir(parents=True)
        rows = _metric_rows(column)
        _write_csv(ev / "RAW_protein_binder_results_combined.csv", rows)
        # The same design again: Complexa duplicates successes into a second file.
        _write_csv(ev / "all_successes_protein_binder.csv", rows[1:])


def _snippet(tmp_path: Path, run_dir: Path) -> str:
    script = tmp_path / "run_proteina_complexa.sh"
    write_run_proteina_complexa(
        script,
        {
            "name": RUN_NAME,
            "run_dir": str(run_dir),
            "target_pdb": str(_target_pdb(tmp_path)),
            "chains": "A",
            "hotspots": "2,3",
            "min_length": 60,
            "max_length": 80,
        },
    )
    text = script.read_text()
    marker = 'echo "=== Collecting binder sequences ==="'
    assert marker in text, "the harvest no longer starts at its banner; update this test with it"
    return "set -euo pipefail\n" + text[text.index(marker) :]


@pytest.fixture
def harvested(tmp_path):
    """harvested(column=..., metrics=...) -> (rows by sequence, completed process)."""

    def _go(**tree):
        run_dir = tmp_path / "run"
        (run_dir / "proteina_complexa").mkdir(parents=True)
        clone = tmp_path / "clone"
        clone.mkdir()
        _build_tree(clone, **tree)
        proc = subprocess.run(
            ["bash", "-c", _snippet(tmp_path, run_dir)],
            capture_output=True,
            text=True,
            cwd=clone,
            env={"PATH": "/usr/bin:/bin", "RUN_DIR": str(run_dir), "HOME": str(tmp_path)},
            timeout=120,
        )
        out = run_dir / "proteina_complexa" / "sequences.csv"
        rows = list(csv.DictReader(out.open())) if out.exists() else []
        return rows, proc

    return _go


@pytest.mark.parametrize("column", ["binder_sequence", "sequence", "self_sequence"])
def test_every_name_complexa_has_used_for_the_binder_column_is_read(harvested, column):
    rows, proc = harvested(column=column)
    assert proc.returncode == 0, proc.stderr
    assert {r["sequence"] for r in rows} == set(DESIGNS), proc.stdout
    assert "(fallback)" not in proc.stdout, "fell through to the metric-less PDB fallback"


def test_the_metrics_are_reached_when_the_pdbs_sit_in_an_earlier_directory(harvested):
    """inference/ holds the PDBs and is found first; the metrics are in evaluation_results/."""
    rows, proc = harvested()
    assert proc.returncode == 0, proc.stderr
    by_seq = {r["sequence"]: r for r in rows}
    for seq, d in DESIGNS.items():
        row = by_seq[seq]
        assert row["iptm"] == d["self_complex_i_pTM"]
        assert row["pae_bt_mean"] == d["self_complex_i_pAE"]
        assert row["plddt_binder_mean"] == d["self_complex_pLDDT"]
        assert row["scrmsd_binder"] == d["self_binder_scRMSD"]


def test_a_design_listed_in_two_csvs_is_kept_once(harvested):
    rows, _ = harvested()
    assert len(rows) == len(DESIGNS), [r["design_id"] for r in rows]


def test_each_design_is_named_after_its_own_structure_not_its_csv(harvested):
    """No name column in the metrics CSV: the id must come from the PDB that holds that binder."""
    rows, _ = harvested()
    ids = {r["sequence"]: r["design_id"] for r in rows}
    assert ids == {seq: f"complexa_{d['id']}" for seq, d in DESIGNS.items()}


def test_control_without_a_metrics_csv_the_pdb_fallback_is_what_runs(harvested):
    """Proves the tests above distinguish the two paths: the fallback carries no iptm."""
    rows, proc = harvested(metrics=False)
    assert proc.returncode == 0, proc.stderr
    assert "(fallback)" in proc.stdout
    assert {r["sequence"] for r in rows} == set(DESIGNS)
    assert all(not r.get("iptm") for r in rows)
