"""ESMFold2 refolding runner.

Wraps scripts/refold_esmfold2.refold_batch() to evaluate a batch of binder
sequences against a target using ESMFold2 (biohub).

Must be run in the ``binder-eval-esmfold2`` conda env:

    conda run -n binder-eval-esmfold2 binder-compare refold-esmfold2 ...

Output CSV columns (pLDDT auto-rescaled to 0-1):
    run_id, idx, sequence, target_sequence, binder_length,
    iptm, ptm,
    plddt_binder_mean, plddt_binder_min, plddt_target_mean,
    pae_bt_mean, pae_tb_mean, pae_bb_mean, pae_overall_mean, pae_max,
    cif, pdb, pae_file

Array ordering: refold_esmfold2 places target first (chain A) and binder
second (chain B) in the ``ESMFold2InputBuilder`` ``StructurePredictionInput``.
The PAE .npy files use [target | binder] ordering — scoring.py reads with
``ordering="target_binder"`` (same convention as Protenix and AF3).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def run_esmfold2_refold(
    sequences: list[str],
    target_sequence: str,
    output_dir: str | Path,
    output_csv: str | Path,
    *,
    model_name: str = "fast",
    num_loops: int = 3,
    num_sampling_steps: int = 50,
    num_diffusion_samples: int = 1,
    seed: int = 0,
    scripts_path: str | Path | None = None,
    resume: bool = False,
) -> None:
    """Refold *sequences* against *target_sequence* using ESMFold2.

    Args:
        sequences:             Binder amino acid strings.
        target_sequence:       Target protein sequence.
        output_dir:            Directory for structures + PAE files.
        output_csv:            Path for the metrics CSV.
        model_name:            ``fast`` (default, biohub/ESMFold2-Fast) or
                               ``full`` (biohub/ESMFold2).
        num_loops:             Recycling loops (default 3, HF docs).
        num_sampling_steps:    Diffusion sampling steps (default 50).
        num_diffusion_samples: Diffusion samples per call (default 1).
        seed:                  Random seed (default 0).
        scripts_path:          Override path to scripts/ (auto-detected).
        resume:                If True, skip binders already in output_csv.
    """
    output_dir = Path(output_dir).resolve()
    output_csv = Path(output_csv).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    scripts_dir = _resolve_scripts_path(scripts_path)

    skip_indices: set[int] = set()
    if resume and output_csv.exists():
        skip_indices = _load_completed_indices(output_csv)
        if skip_indices:
            print(f"[esmfold2] Resuming — skipping {len(skip_indices)} already-completed binders")

    old_cwd = os.getcwd()
    os.chdir(output_dir)
    try:
        sys.path.insert(0, str(scripts_dir))
        from refold_esmfold2 import refold_batch

        refold_batch(
            binder_sequences=sequences,
            target_sequence=target_sequence,
            output_dir=output_dir,
            output_csv=output_csv,
            model_name=model_name,
            num_loops=num_loops,
            num_sampling_steps=num_sampling_steps,
            num_diffusion_samples=num_diffusion_samples,
            seed=seed,
            skip_indices=skip_indices,
        )
    finally:
        os.chdir(old_cwd)

    if not output_csv.exists():
        raise FileNotFoundError(f"Expected refold_esmfold2 to write {output_csv} but it was not found.")

    _absolutize_csv_paths(output_csv, output_dir, ["cif", "pdb", "pae_file"])
    print(f"[esmfold2] Results → {output_csv}")


def _load_completed_indices(csv_path: Path) -> set[int]:
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
    repo_root = Path(__file__).parent.parent.parent
    candidate = repo_root / "scripts"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Could not locate scripts directory at {candidate}. Pass --scripts-path explicitly.")
