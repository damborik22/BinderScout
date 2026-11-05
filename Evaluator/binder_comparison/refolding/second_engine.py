"""Shared helpers for the per-candidate second-engine refold scripts.

Two contracts live here so that every candidate script gets them identically:

* ``to_binder_target_pae`` puts an engine's token-level PAE into our ``[binder|target]``
  order. A target-first matrix is re-blocked (the four blocks swap places), never
  transposed -- ``compute_iptm_from_pae`` does exactly the same swap for
  ``ordering="target_binder"``.
* ``write_refold_row`` appends to a refold CSV whose header is the AF3 refold CSV's,
  unprefixed. The engine name enters later, at merge time, through
  ``add_iptm_from_pae_files(prefix=...)``. A failed design is a row with blank metric
  cells, never a zero.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

# Must equal refold_af3.py's _csv_fieldnames(); tests/binder_comparison/test_second_engine_helpers.py
# pins the two together (that file is a script, not importable).
REFOLD_CSV_FIELDS: tuple[str, ...] = (
    "run_id",
    "idx",
    "sequence",
    "target_sequence",
    "binder_length",
    "iptm",
    "ptm",
    "ranking_score",
    "plddt_binder_mean",
    "plddt_binder_min",
    "plddt_target_mean",
    "pae_bt_mean",
    "pae_tb_mean",
    "pae_bb_mean",
    "pae_overall_mean",
    "pae_max",
    "cif",
    "pdb",
    "pae_file",
)


def to_binder_target_pae(pae: np.ndarray, n_binder: int, n_target: int, *, order: str) -> np.ndarray:
    """Return ``pae`` as a ``[binder|target]`` matrix (a copy).

    ``order`` is the engine's native layout: ``"binder_target"`` (returned unchanged) or
    ``"target_binder"`` (blocks swapped, not transposed). Raises ValueError for any other
    ``order``, a non-square or non-2D matrix, or a size other than n_binder + n_target.
    """
    if order not in ("binder_target", "target_binder"):
        raise ValueError(f"order must be 'binder_target' or 'target_binder', got {order!r}")
    pae = np.asarray(pae)
    if pae.ndim != 2 or pae.shape[0] != pae.shape[1]:
        raise ValueError(f"PAE must be a square 2D matrix, got shape {pae.shape}")
    expected = n_binder + n_target
    if pae.shape[0] != expected:
        raise ValueError(
            f"PAE is {pae.shape[0]}x{pae.shape[0]} but (n_binder + n_target) = {n_binder} + {n_target} = {expected}; "
            "refusing to guess which axis is the binder"
        )
    if order == "binder_target":
        return pae.copy()
    return np.block(
        [
            [pae[n_target:, n_target:], pae[n_target:, :n_target]],
            [pae[:n_target, n_target:], pae[:n_target, :n_target]],
        ]
    )


def write_refold_row(csv_path: str | Path, row: dict) -> None:
    """Append ``row`` to ``csv_path``; the header is written only when the file is new or empty.

    ``row`` may hold any subset of ``REFOLD_CSV_FIELDS`` (missing columns are written blank, which
    is how a failed design is recorded). A key outside the header raises ValueError naming it.
    """
    unknown = sorted(set(row) - set(REFOLD_CSV_FIELDS))
    if unknown:
        raise ValueError(f"not refold CSV columns: {', '.join(unknown)}")
    path = Path(csv_path)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(REFOLD_CSV_FIELDS), restval="")
        if write_header:
            writer.writeheader()
        writer.writerow(row)
