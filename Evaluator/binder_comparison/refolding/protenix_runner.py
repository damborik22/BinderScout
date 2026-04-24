"""Protenix refolding runner.

Wraps scripts/refold_protenix.refold_batch() to evaluate a batch of
binder sequences against a target using Protenix v0.5.0 (ByteDance's open-
source AlphaFold3 reimplementation).

Must be run inside the ``bindmaster_pxdesign`` conda env, which ships
Protenix pinned by the PXDesign installer:

    conda run -n bindmaster_pxdesign binder-compare refold-protenix ...

Output CSV columns (from refold_protenix, pLDDT rescaled to 0–1):
    run_id, idx, sequence, target_sequence, binder_length,
    iptm, ptm, ranking_score,
    plddt_binder_mean, plddt_binder_min, plddt_target_mean,
    pae_bt_mean, pae_tb_mean, pae_bb_mean, pae_overall_mean, pae_max,
    cif, pdb, pae_file
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def run_protenix_refold(
    sequences: list[str],
    target_sequence: str,
    output_dir: str | Path,
    output_csv: str | Path,
    *,
    num_samples: int = 5,
    num_seeds: int = 1,
    use_msa: bool = False,
    n_cycle: int = 10,
    n_step: int = 200,
    scripts_path: str | Path | None = None,
    resume: bool = False,
) -> None:
    """Refold *sequences* against *target_sequence* using Protenix v0.5.0.

    Args:
        sequences:       Binder amino acid strings.
        target_sequence: Target protein sequence.
        output_dir:      Directory where Protenix output (predictions/, *.npy)
                         is written.
        output_csv:      Path for the metrics CSV.
        num_samples:     Protenix diffusion samples per seed (default: 5).
        num_seeds:       Number of random seeds, starting at 101 (default: 1).
        use_msa:         Request ColabFold MMseqs2 MSAs? Default False — MSA-free
                         inference is much faster and needs no internet access.
        n_cycle:         Evoformer recycling iterations (Protenix default: 10).
        n_step:          Diffusion steps (Protenix default: 200).
        scripts_path:    Override path to scripts/ (auto-detected).
        resume:          If True, skip binders with rows already in output_csv.
    """
    output_dir = Path(output_dir).resolve()
    output_csv = Path(output_csv).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    scripts_dir = _resolve_scripts_path(scripts_path)

    skip_indices: set[int] = set()
    if resume and output_csv.exists():
        skip_indices = _load_completed_indices(output_csv)
        if skip_indices:
            print(f"[protenix] Resuming — skipping {len(skip_indices)} already-completed binders")

    old_cwd = os.getcwd()
    os.chdir(output_dir)
    try:
        sys.path.insert(0, str(scripts_dir))
        from refold_protenix import refold_batch

        refold_batch(
            binder_sequences=sequences,
            target_sequence=target_sequence,
            output_dir=output_dir,
            output_csv=output_csv,
            num_samples=num_samples,
            num_seeds=num_seeds,
            use_msa=use_msa,
            n_cycle=n_cycle,
            n_step=n_step,
            skip_indices=skip_indices,
        )
    finally:
        os.chdir(old_cwd)

    if not output_csv.exists():
        raise FileNotFoundError(f"Expected refold_protenix to write {output_csv} but it was not found.")

    # Absolutise CSV path columns so downstream tools (merger/report) can find artefacts.
    _absolutize_csv_paths(output_csv, output_dir, ["cif", "pdb", "pae_file"])
    print(f"[protenix] Results → {output_csv}")


def _load_completed_indices(csv_path: Path) -> set[int]:
    """Read existing CSV and return a set of already-populated 1-based indices."""
    if not csv_path.exists():
        return set()
    try:
        import csv

        indices: set[int] = set()
        with csv_path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                idx_val = row.get("idx")
                if idx_val is not None:
                    try:
                        indices.add(int(idx_val))
                    except ValueError:
                        continue
        return indices
    except Exception:
        return set()


def _absolutize_csv_paths(csv_path: Path, base_dir: Path, path_cols: list[str]) -> None:
    """Rewrite relative path columns in a CSV to absolute using *base_dir*."""
    import csv as csv_mod

    rows: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    with csv_path.open() as f:
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
    with csv_path.open("w", newline="") as f:
        writer = csv_mod.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _resolve_scripts_path(override: str | Path | None) -> Path:
    if override is not None:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"scripts path not found: {p}")
        return p
    # Default: <repo_root>/scripts (two levels up from this module)
    repo_root = Path(__file__).parent.parent.parent
    candidate = repo_root / "scripts"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Could not locate scripts directory at {candidate}. Pass --scripts-path explicitly.")


# Keep stale CIF/PAE outputs tidy
def cleanup_stale_outputs(output_dir: str | Path) -> None:
    """Remove Protenix's predictions/ tree to start from a clean state."""
    pred = Path(output_dir) / "predictions"
    if pred.exists():
        shutil.rmtree(pred, ignore_errors=True)
