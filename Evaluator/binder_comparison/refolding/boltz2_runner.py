"""Boltz2 refolding runner.

Wraps scripts/refold_boltz2.refold_batch() to evaluate a batch of
binder sequences against a target using the Boltz2 JAX model.

Must be run in the 'binder-eval-boltz2' conda environment:
    conda run -n binder-eval-boltz2 binder-compare refold-boltz2 ...

Output CSV columns (from refold_boltz2):
    run_id, idx, sequence, target_sequence, binder_length,
    iptm_aux, bt_ipsae, tb_ipsae, ipsae_min, ipsae_valid,
    bt_iptm, binder_ptm, plddt_aux, bb_pae, bt_pae_aux, tb_pae,
    intra_contact, target_contact, pTMEnergy,
    iptm, plddt_binder_mean, plddt_binder_min, plddt_binder_max,
    plddt_binder_std, plddt_target_mean, plddt_target_min,
    pae_bb_mean, pae_bt_mean, pae_tb_mean, ipae,
    pae_tt_mean, pae_overall_mean, pae_max,
    pdb, pae_file, plddt_file
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def run_boltz2_refold(
    sequences: list[str],
    target_sequence: str,
    output_dir: str | Path,
    output_csv: str | Path,
    *,
    target_pdb: str | Path | None = None,
    num_samples: int = 6,
    recycling_steps: int = 3,
    scripts_path: str | Path | None = None,
    resume: bool = False,
) -> None:
    """Refold *sequences* against *target_sequence* using Boltz2.

    Args:
        sequences:       List of binder amino acid strings.
        target_sequence: Target protein sequence.
        output_dir:      Directory where structure files (PDB/NPY/CSV) are written.
        output_csv:      Path for the output CSV of metrics.
        target_pdb:      Optional path to target PDB/CIF for forced template mode.
                         When provided, the target backbone is constrained while the
                         binder is predicted de novo.
        num_samples:     Number of Boltz-2 samples for metrics (default: 6).
        recycling_steps: Number of recycling steps (default: 3).
        scripts_path:    Path to the scripts/ directory containing refold_boltz2.py.
                         Defaults to <repo_root>/scripts/.
        resume:          If True, skip binders already present in existing output CSV.
    """
    output_dir = Path(output_dir).resolve()
    output_csv = Path(output_csv).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    scripts_dir = _resolve_scripts_path(scripts_path)

    skip_indices: set[int] = set()
    if resume:
        skip_indices = _load_completed_indices(output_dir / "refold_designs.csv")
        if skip_indices:
            print(f"[boltz2] Resuming — skipping {len(skip_indices)} already-completed binders")

    # Resolve target_pdb to absolute path before chdir changes CWD
    target_pdb_abs = str(Path(target_pdb).resolve()) if target_pdb else None

    # refold_boltz2.refold_batch writes refold_designs.csv relative to CWD.
    # Change to output_dir so the CSV lands there.
    old_cwd = os.getcwd()
    os.chdir(output_dir)
    try:
        sys.path.insert(0, str(scripts_dir))
        from refold_boltz2 import refold_batch

        refold_batch(
            binder_sequences=sequences,
            target_sequence=target_sequence,
            output_dir="structures",
            target_pdb=target_pdb_abs,
            num_samples=num_samples,
            recycling_steps=recycling_steps,
            skip_indices=skip_indices,
        )
    finally:
        os.chdir(old_cwd)

    # Move the CSV to the requested output path
    generated_csv = output_dir / "refold_designs.csv"
    if generated_csv.exists():
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(generated_csv), str(output_csv))
        # refold_boltz2.py writes paths relative to output_dir (which was CWD).
        # Rewrite them as absolute so downstream tools can find the files.
        _absolutize_csv_paths(output_csv, output_dir, ["pdb", "pae_file", "plddt_file"])
        print(f"[boltz2] Results → {output_csv}")
    else:
        raise FileNotFoundError(f"Expected refold_boltz2 to write {generated_csv} but it was not found.")


def _load_completed_indices(csv_path: Path) -> set[int]:
    """Read existing CSV and return a set of completed 1-based binder indices."""
    if not csv_path.exists():
        return set()
    try:
        import csv

        indices: set[int] = set()
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                idx_val = row.get("idx")
                if idx_val is not None:
                    indices.add(int(idx_val))
        return indices
    except Exception:
        return set()


def _absolutize_csv_paths(csv_path: Path, base_dir: Path, path_cols: list[str]) -> None:
    """Rewrite relative path columns in a CSV to absolute using *base_dir*."""
    import csv as csv_mod

    rows: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    with open(csv_path) as f:
        reader = csv_mod.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            for col in path_cols:
                val = row.get(col, "")
                if val and not Path(val).is_absolute():
                    row[col] = str((base_dir / val).resolve())
            rows.append(row)

    if fieldnames is None:
        return
    with open(csv_path, "w", newline="") as f:
        writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _resolve_scripts_path(override: str | Path | None) -> Path:
    if override is not None:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"scripts path not found: {p}")
        return p
    # Default: repo root is three levels up from this file
    repo_root = Path(__file__).parent.parent.parent
    candidate = repo_root / "scripts"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Could not locate scripts directory at {candidate}. Pass --scripts-path explicitly.")
