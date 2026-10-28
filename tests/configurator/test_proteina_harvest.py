"""The Proteina-Complexa harvest, executed rather than inspected.

Found by auditing the PD-L1 run directory on 2026-10-28. Two faults made the harvest
always fall through to its chain-B PDB fallback, and a third left the run directory
without any raw output at all:

1. It picked the FIRST candidate directory that existed. The two trees hold different
   things -- `inference/<config>_<task>_<run>/` has a subdirectory per design with its
   .pdb and no sequence-bearing CSV, `evaluation_results/<config>_<task>/` has the
   metrics CSVs -- so it reached the PDBs and never the metrics.
2. Strategy 1 read a column named `sequence`. Complexa writes `binder_sequence`, so
   even pointed straight at evaluation_results it matched nothing.
3. Complexa's PDBs and CSVs live inside its own gitignored clone, which
   `install --uninstall` deletes. `runs/<name>/proteina_complexa/` held 3 files
   against 34-639 for the other six tools, so an archived run had sequences and no
   structures.

Observable effect: `proteina_complexa` carried 2 populated `native_*` columns in
metrics.csv where every other tool had 4-9, and its iPTM / pLDDT / scRMSD -- which
Complexa had computed and written -- were discarded.

These tests pull the embedded `python3 -c` harvest out of the generated run script and
execute it against a synthetic output tree, so the real code runs.
"""

from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "configurator"))

import configurator as cfgmod  # noqa: E402

# Two designs Complexa reports with metrics, plus the target chain.
BINDER_A = "FKHFDKDGDGTITTKELGTVMRSLGQNPTEAELQDMINEVDADGDGTIDYDEFLTLMAARRKD"
BINDER_B = "AEAYYNRGNAYFNLGNYEEAIEDYSRAIELKPDFAKAYANRAAAYEKLNQPVEAIKDRIEAEK"
TARGET = "NAFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQ"

_AA1TO3 = {
    "A": "ALA",
    "R": "ARG",
    "N": "ASN",
    "D": "ASP",
    "C": "CYS",
    "Q": "GLN",
    "E": "GLU",
    "G": "GLY",
    "H": "HIS",
    "I": "ILE",
    "L": "LEU",
    "K": "LYS",
    "M": "MET",
    "F": "PHE",
    "P": "PRO",
    "S": "SER",
    "T": "THR",
    "W": "TRP",
    "Y": "TYR",
    "V": "VAL",
}


def _pdb(target: str, binder: str) -> str:
    """Minimal CA-only two-chain PDB: target as A, binder as B (Complexa's layout)."""
    out, serial = [], 1
    for chain, seq in (("A", target), ("B", binder)):
        for i, aa in enumerate(seq, 1):
            out.append(
                f"ATOM  {serial:>5}  CA  {_AA1TO3[aa]} {chain}{i:>4}    "
                f"{i * 1.0:>8.3f}{0.0:>8.3f}{0.0:>8.3f}  1.00  0.00           C"
            )
            serial += 1
    return "\n".join(out) + "\nEND\n"


def _build_tree(root: Path, run_name: str, *, with_metrics_csv: bool = True) -> None:
    """The layout observed at PROTEINA_COMPLEXA_COMMIT."""
    inf = root / "inference" / f"search_binder_local_pipeline_bindmaster_{run_name}_{run_name}"
    inf.mkdir(parents=True)
    # Non-sequence CSVs — exactly what made the first-existing-dir choice fatal.
    for name in ("rewards_search_binder_local_pipeline_0.csv", "timing_0.csv"):
        (inf / name).write_text("job_id,reward\n0,0.5\n")
    for stem, binder in (("job_0_n_181_id_1_bon_orig2_r1", BINDER_A), ("job_0_n_181_id_0_bon_orig2_r0", BINDER_B)):
        d = inf / stem
        d.mkdir()
        (d / f"{stem}.pdb").write_text(_pdb(TARGET, binder))

    ev = root / "evaluation_results" / f"search_binder_local_pipeline_bindmaster_{run_name}"
    ev.mkdir(parents=True)
    if with_metrics_csv:
        rows = [
            {
                "binder_sequence": BINDER_A,
                "target_sequence": TARGET,
                "self_complex_i_pTM": "0.176",
                "self_complex_i_pAE": "0.639",
                "self_complex_pLDDT": "0.672",
                "self_binder_scRMSD": "1.024",
            },
            {
                "binder_sequence": BINDER_B,
                "target_sequence": TARGET,
                "self_complex_i_pTM": "0.509",
                "self_complex_i_pAE": "0.336",
                "self_complex_pLDDT": "0.921",
                "self_binder_scRMSD": "0.217",
            },
        ]
        with open(ev / "RAW_protein_binder_results_combined.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        # The same design again — Complexa duplicates it into all_successes.
        with open(ev / "all_successes_protein_binder_self.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows([rows[1]])


def _generated_harvest(tmp_path: Path, run_name: str) -> str:
    """Write a run script via the real writer and extract its embedded harvest."""
    run_dir = tmp_path / "runs" / run_name
    (run_dir / "proteina_complexa").mkdir(parents=True, exist_ok=True)
    script = run_dir / "run_proteina_complexa.sh"

    cfg = {
        "name": run_name,
        "target_sequence": TARGET,
        "target_pdb": str(tmp_path / "t.pdb"),
        "target_chain": "A",
        "binder_length_min": 60,
        "binder_length_max": 80,
        "proteina_complexa_designs": 2,
        # Bare residue numbers: the writer int()s these. A chain-prefixed "A54" raises,
        # and this used to be wrapped in a try/except that turned the setup error into
        # a skip -- eight green-looking tests that never ran the harvest.
        "hotspots": "54,56",
        "run_dir": run_dir,
    }
    cfgmod.write_run_proteina_complexa(script, cfg)

    text = script.read_text()
    m = re.search(r'python3 -c "\n(.*?)\n"\n', text, re.S)
    assert m, "could not find the embedded python3 -c harvest in the generated script"
    body = m.group(1)
    # The generated script resolves $RUN_DIR from the shell; substitute it directly.
    return body.replace("$RUN_DIR", str(run_dir))


def _run_harvest(tmp_path: Path, run_name: str, cwd: Path) -> subprocess.CompletedProcess:
    code = _generated_harvest(tmp_path, run_name)
    return subprocess.run([sys.executable, "-I", "-c", code], cwd=str(cwd), capture_output=True, text=True, timeout=120)


@pytest.fixture
def tree(tmp_path: Path):
    run_name = "PDL1x10"
    clone = tmp_path / "Proteina-Complexa"
    clone.mkdir()
    _build_tree(clone, run_name)
    return tmp_path, run_name, clone


class TestMetricsAreHarvested:
    def test_sequences_come_from_the_metrics_csv_not_the_pdb_fallback(self, tree) -> None:
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr
        assert "with metrics from Complexa CSVs" in proc.stdout
        assert "(fallback)" not in proc.stdout

    def test_iptm_plddt_and_scrmsd_survive(self, tree) -> None:
        """These existed all along and were being discarded."""
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr

        out = tmp_path / "runs" / run_name / "proteina_complexa" / "sequences.csv"
        rows = list(csv.DictReader(open(out)))
        by_seq = {r["sequence"]: r for r in rows}

        assert set(by_seq) == {BINDER_A, BINDER_B}
        assert by_seq[BINDER_B]["iptm"] == "0.509"
        assert by_seq[BINDER_B]["plddt_binder_mean"] == "0.921"
        assert by_seq[BINDER_B]["pae_bt_mean"] == "0.336"
        assert by_seq[BINDER_B]["scrmsd_binder"] == "0.217"

    def test_a_design_listed_in_two_csvs_is_not_duplicated(self, tree) -> None:
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr
        out = tmp_path / "runs" / run_name / "proteina_complexa" / "sequences.csv"
        seqs = [r["sequence"] for r in csv.DictReader(open(out))]
        assert len(seqs) == len(set(seqs)) == 2

    def test_the_inference_tree_alone_still_falls_back_to_pdbs(self, tmp_path: Path) -> None:
        """No metrics CSV anywhere is the one case the chain-B fallback is for."""
        run_name = "PDL1x10"
        clone = tmp_path / "Proteina-Complexa"
        clone.mkdir()
        _build_tree(clone, run_name, with_metrics_csv=False)
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr
        assert "(fallback)" in proc.stdout
        out = tmp_path / "runs" / run_name / "proteina_complexa" / "sequences.csv"
        assert {r["sequence"] for r in csv.DictReader(open(out))} == {BINDER_A, BINDER_B}


class TestSequencesAreTraceableToStructures:
    """Complexa's metrics CSVs carry no design-name column.

    Without matching each row back to the PDB that holds that chain B, design_id
    degrades to `<csv stem>_<row index>` -- the PD-L1 run's eight designs came out as
    `complexa_RAW_protein_binder_results_..._combined_0..7`, with no way to reach the
    structure the metrics describe.
    """

    def test_design_id_carries_the_structure_stem(self, tree) -> None:
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr

        out = tmp_path / "runs" / run_name / "proteina_complexa" / "sequences.csv"
        ids = {r["sequence"]: r["design_id"] for r in csv.DictReader(open(out))}
        assert ids[BINDER_A] == "complexa_job_0_n_181_id_1_bon_orig2_r1"
        assert ids[BINDER_B] == "complexa_job_0_n_181_id_0_bon_orig2_r0"

    def test_structure_column_names_a_file_that_was_copied(self, tree) -> None:
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr

        pc = tmp_path / "runs" / run_name / "proteina_complexa"
        rows = list(csv.DictReader(open(pc / "sequences.csv")))
        assert all(r["structure"] for r in rows), "every design should resolve to a PDB"
        for r in rows:
            assert (pc / "structures" / r["structure"]).is_file(), r["structure"]

    def test_the_linked_count_is_reported(self, tree) -> None:
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert "2 linked to a structure" in proc.stdout, proc.stdout


class TestRunDirectoryIsSelfContained:
    def test_structures_are_copied_into_the_run_dir(self, tree) -> None:
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr

        structs = sorted((tmp_path / "runs" / run_name / "proteina_complexa" / "structures").glob("*.pdb"))
        assert len(structs) == 2, f"expected both designs' PDBs, got {[p.name for p in structs]}"
        assert all(p.stat().st_size > 0 for p in structs)

    def test_raw_csvs_are_copied_into_the_run_dir(self, tree) -> None:
        tmp_path, run_name, clone = tree
        proc = _run_harvest(tmp_path, run_name, clone)
        assert proc.returncode == 0, proc.stderr
        raw = sorted((tmp_path / "runs" / run_name / "proteina_complexa" / "raw").glob("*.csv"))
        assert raw, "no raw CSVs preserved"
        assert any("RAW_protein_binder_results" in p.name for p in raw)

    def test_a_rerun_does_not_duplicate_copies(self, tree) -> None:
        tmp_path, run_name, clone = tree
        assert _run_harvest(tmp_path, run_name, clone).returncode == 0
        before = sorted(p.name for p in (tmp_path / "runs" / run_name / "proteina_complexa" / "structures").iterdir())
        assert _run_harvest(tmp_path, run_name, clone).returncode == 0
        after = sorted(p.name for p in (tmp_path / "runs" / run_name / "proteina_complexa" / "structures").iterdir())
        assert before == after


class TestStillFailsLoudlyWithNothingToHarvest:
    def test_no_outputs_at_all_exits_non_zero(self, tmp_path: Path) -> None:
        run_name = "PDL1x10"
        empty = tmp_path / "Proteina-Complexa"
        empty.mkdir()
        proc = _run_harvest(tmp_path, run_name, empty)
        assert proc.returncode != 0
        assert "No binder sequences extracted" in proc.stderr
