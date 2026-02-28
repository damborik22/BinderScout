"""AF2 refolding runner.

Wraps Mosaic/refold_Version6.refold_batch_af2() to evaluate a batch of
binder sequences against a target using AlphaFold2 (ColabDesign).

Must be run in the 'bindcraft_pr' conda environment:
    conda run -n bindcraft_pr binder-compare refold-af2 ...

Output CSV columns (from refold_Version6):
    run_id, idx, sequence, target_pdb, binder_length,
    af2_iptm,
    af2_plddt_binder_mean, af2_plddt_binder_min, af2_plddt_binder_max,
    af2_plddt_target_mean,
    af2_pae_bt_mean, af2_pae_tb_mean, af2_ipae,
    af2_pae_bb_mean, af2_pae_tt_mean, af2_pae_overall_mean, af2_pae_max,
    pdb,
    af2_pae_file   ← path to PAE .npy; enables AF2 ipSAE via Dunbrack formula

Array ordering: refold_Version6 uses [target | binder] ordering.
PAE .npy files: same [target | binder] ordering — scoring.py reads with
    ordering="target_binder" to normalise before ipSAE computation.
"""

from __future__ import annotations

import sys
from pathlib import Path


def run_af2_refold(
    sequences: list[str],
    target_pdb_path: str | Path,
    output_dir: str | Path,
    output_csv: str | Path,
    *,
    models: list[int] | None = None,
    num_recycles: int = 3,
    mosaic_path: str | Path | None = None,
    resume: bool = False,
) -> None:
    """Refold *sequences* against *target_pdb_path* using AF2 (ColabDesign).

    Args:
        sequences:       List of binder amino acid strings.
        target_pdb_path: Path to the target PDB file (chain A used).
        output_dir:      Directory where structure PDB files are written.
        output_csv:      Path for the output CSV of metrics.
        models:          AF2 model indices to use (default: [1]).
        num_recycles:    Number of recycling iterations (default: 3).
        mosaic_path:     Path to the Mosaic repo root. Auto-detected if None.
        resume:          If True, skip binders already present in existing output CSV.
    """
    output_dir = Path(output_dir)
    output_csv = Path(output_csv)
    target_pdb_path = Path(target_pdb_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    if not target_pdb_path.exists():
        raise FileNotFoundError(f"Target PDB not found: {target_pdb_path}")

    skip_indices: set[int] = set()
    if resume:
        skip_indices = _load_completed_indices(output_csv)
        if skip_indices:
            print(f"[af2] Resuming — skipping {len(skip_indices)} already-completed binders")

    mosaic_root = _resolve_mosaic_path(mosaic_path)
    sys.path.insert(0, str(mosaic_root))
    from refold_Version6 import refold_batch_af2  # noqa: PLC0415

    refold_batch_af2(
        binder_sequences=sequences,
        target_pdb_path=str(target_pdb_path),
        output_dir=str(output_dir),
        csv_path=str(output_csv),
        models=models if models is not None else [1],
        num_recycles=num_recycles,
        skip_indices=skip_indices,
    )
    print(f"[af2] Results → {output_csv}")


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


def _resolve_mosaic_path(override: str | Path | None) -> Path:
    if override is not None:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"Mosaic path not found: {p}")
        return p
    repo_root = Path(__file__).parent.parent.parent
    candidate = repo_root / "Mosaic"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"Could not locate Mosaic directory at {candidate}. "
        "Pass --mosaic-path explicitly."
    )
