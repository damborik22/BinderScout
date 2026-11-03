"""Proteina-Complexa's collector must look where Complexa actually writes.

Complexa writes ``evaluation_results/<pipeline>_<task_name>/`` RELATIVE TO ITS
OWN CWD -- the generated script ``cd``s into ``PROTEINA_COMPLEXA_DIR`` before
calling ``complexa design`` -- and the run name appears in the CHILD directory,
never in ``evaluation_results`` itself.

The collector's fallback probe tested ``run_name in str(p)`` against the
``evaluation_results`` path, so it could never match. The consequence was not a
crash but a silent empty arm: a cluster job (2026-10-29) COMPLETED in 24:50
with 8 designs, 40 structures and 12 result CSVs, and the arm still ended

    WARNING: No binder sequences extracted from Proteina-Complexa

Two further things make this more than a glob swap:

* Complexa's sequence column is ``self_sequence``, not ``sequence``. Reading
  only ``sequence`` leaves Strategy 1 empty and drops the run to the PDB
  fallback, which carries NO metrics -- the same silent-emptiness bug, moved
  from the rows to the columns.
* ``target_pdb`` arrives as a ``str`` on the ``--config`` replay path, and the
  per-chain CA count calls ``.read_text()`` on it, so the writer must coerce.

These tests run the GENERATED snippet through bash, so the heredoc's quoting and
brace-doubling are exercised rather than assumed. No design job is run.
"""

from __future__ import annotations

import csv
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))

from configurator import write_run_proteina_complexa

RUN_NAME = "pmhc_g12d_t1"
# Complexa's own directory spelling, verbatim from a cluster job.
EVAL_CHILD = f"search_binder_local_pipeline_binderscout_{RUN_NAME}"
SEQ = "MKAEELLRKAWEIAKQNPQAVELLKKAAELAKEHGDKELAKKVLEIAKQ"

# binder_results_*.csv as Complexa writes it: `self_` prefixes throughout.
BINDER_COLUMNS = [
    "run_name",
    "self_complex_pLDDT",
    "self_complex_i_pAE",
    "self_complex_pTM",
    "self_complex_i_pTM",
    "self_sequence",
]


def _target_pdb(tmp_path: Path) -> Path:
    """A three-chain PDB, so the writer's per-chain contig walk has real input."""
    lines = []
    n = 0
    for chain, count in (("A", 4), ("B", 3), ("C", 2)):
        for i in range(1, count + 1):
            n += 1
            lines.append(
                f"ATOM  {n:5d}  CA  ALA {chain}{i:4d}    {10.0 + i:8.3f}{10.0:8.3f}{10.0:8.3f}  1.00  0.00           C"
            )
    path = tmp_path / "target.pdb"
    path.write_text("\n".join(lines) + "\nEND\n")
    return path


def _generate(tmp_path: Path, run_dir: Path) -> str:
    """Write the run script and return just its sequence-collecting tail."""
    script = tmp_path / "run_proteina_complexa.sh"
    write_run_proteina_complexa(
        script,
        {
            "name": RUN_NAME,
            "run_dir": str(run_dir),
            # a plain str on purpose: this is what `--config <json>` replay gives
            "target_pdb": str(_target_pdb(tmp_path)),
            "target_input": str(_target_pdb(tmp_path)),
            "chains": "A,B,C",
            "hotspots": "65,69,72",
            "min_length": 60,
            "max_length": 150,
        },
    )
    text = script.read_text()
    marker = "# Collect binder sequences from outputs"
    assert marker in text, "collector block moved; this test anchors on it"
    return f'RUN_DIR="{run_dir}"\n' + text[text.index(marker) :]


def _run(snippet: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", snippet], capture_output=True, text=True, cwd=cwd)


def _complexa_outputs(pc_dir: Path, *, with_csv: bool = True) -> None:
    """Replicate Complexa's on-disk layout, including the nested run-name dir."""
    base = pc_dir / "evaluation_results" / EVAL_CHILD
    design = base / "job_0_n_468_id_1_bon_orig3_r1"
    design.mkdir(parents=True, exist_ok=True)
    if with_csv:
        with (base / "binder_results_search_binder_local_pipeline_0.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=BINDER_COLUMNS)
            w.writeheader()
            w.writerow(
                {
                    "run_name": RUN_NAME,
                    "self_complex_pLDDT": "0.81",
                    "self_complex_i_pAE": "12.4",
                    "self_complex_pTM": "0.709",
                    "self_complex_i_pTM": "0.257",
                    "self_sequence": SEQ,
                }
            )
    # chain B is the binder, so the PDB fallback has something to read too
    with (design / "job_0_n_468_id_1_bon_orig3_r1_binder.pdb").open("w") as fh:
        for i, res in enumerate(["MET", "LYS", "ALA", "GLU", "GLU", "LEU"], 1):
            fh.write(f"ATOM  {i:5d}  CA  {res} B{i:4d}    10.000  10.000  10.000  1.00  0.00           C\n")


def _rows(run_dir: Path) -> list[dict]:
    out = run_dir / "proteina_complexa" / "sequences.csv"
    if not out.exists():
        return []
    with out.open(newline="") as fh:
        return list(csv.DictReader(fh))


def test_the_writer_accepts_a_string_target_pdb(tmp_path):
    """`--config` replay passes target_pdb as a str, and the per-chain CA count
    calls .read_text() on it -- so an uncoerced value is an AttributeError that
    `except OSError` does not catch. Generating at all is most of the assertion;
    the contig proves the file was really read rather than guessed."""
    run_dir = tmp_path / "run"
    (run_dir / "proteina_complexa").mkdir(parents=True)
    script = tmp_path / "coerce.sh"
    write_run_proteina_complexa(
        script,
        {
            "name": RUN_NAME,
            "run_dir": str(run_dir),
            "target_pdb": str(_target_pdb(tmp_path)),
            "target_input": str(_target_pdb(tmp_path)),
            "chains": "A,B,C",
            "hotspots": "2",
            "min_length": 60,
            "max_length": 150,
        },
    )
    assert '--target-input "A1-4,B1-3,C1-2"' in script.read_text()


def test_the_multichain_contig_and_hotspots_reach_the_target_registration(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "proteina_complexa").mkdir(parents=True)
    script = tmp_path / "s.sh"
    write_run_proteina_complexa(
        script,
        {
            "name": RUN_NAME,
            "run_dir": str(run_dir),
            "target_pdb": str(_target_pdb(tmp_path)),
            "target_input": str(_target_pdb(tmp_path)),
            "chains": "A,B,C",
            "hotspots": "2,3",
            "min_length": 60,
            "max_length": 150,
        },
    )
    text = script.read_text()
    # one comma-joined string, not a dict-of-chains
    assert '--target-input "A1-4,B1-3,C1-2"' in text
    # hotspots belong to the chain they were read off -- the primary one only
    assert "--hotspot-residues A2 A3" in text
    assert "B2" not in text.split("--hotspot-residues")[1].split("\n")[0]


def test_sequences_are_recovered_from_complexas_own_output_tree(tmp_path):
    """The regression: a completed run must not report an empty arm."""
    run_dir = tmp_path / "run"
    (run_dir / "proteina_complexa").mkdir(parents=True)
    pc_dir = tmp_path / "pc_install"
    pc_dir.mkdir()
    _complexa_outputs(pc_dir)

    proc = _run(_generate(tmp_path, run_dir), cwd=pc_dir)

    assert "No binder sequences extracted" not in proc.stderr, proc.stderr
    rows = _rows(run_dir)
    assert len(rows) == 1, f"stdout={proc.stdout} stderr={proc.stderr}"
    assert rows[0]["sequence"] == SEQ


def test_the_csv_metrics_survive_rather_than_dropping_to_the_pdb_fallback(tmp_path):
    """Reading `self_sequence` is what keeps iptm/plddt/ipae attached."""
    run_dir = tmp_path / "run"
    (run_dir / "proteina_complexa").mkdir(parents=True)
    pc_dir = tmp_path / "pc_install"
    pc_dir.mkdir()
    _complexa_outputs(pc_dir)

    _run(_generate(tmp_path, run_dir), cwd=pc_dir)

    row = _rows(run_dir)[0]
    assert row["iptm"] == "0.257"
    assert row["plddt_binder_mean"] == "0.81"
    assert row["pae_bt_mean"] == "12.4"


def test_the_pdb_fallback_still_works_when_no_csv_was_written(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "proteina_complexa").mkdir(parents=True)
    pc_dir = tmp_path / "pc_install"
    pc_dir.mkdir()
    _complexa_outputs(pc_dir, with_csv=False)

    proc = _run(_generate(tmp_path, run_dir), cwd=pc_dir)

    rows = _rows(run_dir)
    assert len(rows) == 1, f"stdout={proc.stdout} stderr={proc.stderr}"
    assert rows[0]["sequence"] == "MKAEEL"


def test_an_empty_tree_names_where_it_looked(tmp_path):
    """A genuinely empty run must say what it probed, not just refuse."""
    run_dir = tmp_path / "run"
    (run_dir / "proteina_complexa").mkdir(parents=True)
    pc_dir = tmp_path / "pc_install"
    pc_dir.mkdir()

    proc = _run(_generate(tmp_path, run_dir), cwd=pc_dir)

    assert "No binder sequences extracted" in proc.stderr
    assert "looked in:" in proc.stderr
    assert "candidates probed:" in proc.stderr
    assert _rows(run_dir) == []


def test_the_collector_runs_from_a_run_folder_with_a_space_a_dollar_and_an_apostrophe(tmp_path):
    """$RUN_DIR used to be pasted inside a single-quoted Python literal, so an apostrophe in the run
    folder made the collector a SyntaxError AFTER the design step had run. It is read from the
    environment instead, like the PXDesign collector."""
    run_dir = tmp_path / "it's a $HOME run"
    (run_dir / "proteina_complexa").mkdir(parents=True)
    pc_dir = tmp_path / "pc_install"
    pc_dir.mkdir()
    _complexa_outputs(pc_dir)

    tail = _generate(tmp_path, run_dir).split("\n", 1)[1]
    proc = _run(f"RUN_DIR={shlex.quote(str(run_dir))}\n" + tail, cwd=pc_dir)

    assert "SyntaxError" not in proc.stderr, proc.stderr
    rows = _rows(run_dir)
    assert len(rows) == 1, f"stdout={proc.stdout} stderr={proc.stderr}"
    assert rows[0]["sequence"] == SEQ
