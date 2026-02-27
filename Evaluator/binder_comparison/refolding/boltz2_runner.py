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
    scripts_path: str | Path | None = None,
) -> None:
    """Refold *sequences* against *target_sequence* using Boltz2.

    Args:
        sequences:       List of binder amino acid strings.
        target_sequence: Target protein sequence.
        output_dir:      Directory where structure files (PDB/NPY/CSV) are written.
        output_csv:      Path for the output CSV of metrics.
        scripts_path:    Path to the scripts/ directory containing refold_boltz2.py.
                         Defaults to <repo_root>/scripts/.
    """
    output_dir = Path(output_dir)
    output_csv = Path(output_csv)
    output_dir.mkdir(parents=True, exist_ok=True)

    scripts_dir = _resolve_scripts_path(scripts_path)

    # refold_boltz2.refold_batch writes refold_designs.csv relative to CWD.
    # Change to output_dir so the CSV lands there.
    old_cwd = os.getcwd()
    os.chdir(output_dir)
    try:
        sys.path.insert(0, str(scripts_dir))
        from refold_boltz2 import refold_batch  # noqa: PLC0415

        refold_batch(
            binder_sequences=sequences,
            target_sequence=target_sequence,
            output_dir="structures",
        )
    finally:
        os.chdir(old_cwd)

    # Move the CSV to the requested output path
    generated_csv = output_dir / "refold_designs.csv"
    if generated_csv.exists():
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(generated_csv), str(output_csv))
        print(f"[boltz2] Results → {output_csv}")
    else:
        raise FileNotFoundError(
            f"Expected refold_boltz2 to write {generated_csv} but it was not found."
        )


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
    raise FileNotFoundError(
        f"Could not locate scripts directory at {candidate}. "
        "Pass --scripts-path explicitly."
    )
