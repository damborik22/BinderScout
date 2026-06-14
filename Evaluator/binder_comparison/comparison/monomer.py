"""Monomer validation — does the binder hold its fold without the target?

Grafted from BindMaster 2: refold the binder *alone* and compare it to its conformation
in the complex. A large Cα RMSD means the fold is target-stabilized (context-dependent) —
a real expression/behaviour risk. Pure geometry here (Kabsch superposition + a Cα parser);
the binder-only refold is a GPU step the caller delegates to a refold engine.
"""

from __future__ import annotations

import numpy as np

CONTEXT_DEPENDENT_RMSD = 3.0  # Cα RMSD (Å) above which the fold is flagged target-stabilized


def kabsch_rmsd(mobile, reference) -> float:
    """Minimal Cα RMSD (Å) between two (N,3) coordinate sets after optimal rigid superposition.

    Implements the Kabsch algorithm (SVD), with the reflection correction so the rotation is
    proper (det = +1). Translation and rotation are removed; only the residual deformation
    remains. Raises ValueError on mismatched shapes.
    """
    p = np.asarray(mobile, dtype=float)
    q = np.asarray(reference, dtype=float)
    if p.shape != q.shape or p.ndim != 2 or p.shape[1] != 3:
        raise ValueError(f"need matching (N,3) arrays, got {p.shape} and {q.shape}")
    if p.shape[0] == 0:
        raise ValueError("no coordinates to align")

    pc = p - p.mean(axis=0)
    qc = q - q.mean(axis=0)
    h = pc.T @ qc
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, 1.0, d]) @ u.T
    aligned = pc @ rot.T
    diff = aligned - qc
    return float(np.sqrt((diff**2).sum() / p.shape[0]))


def classify_fold_robustness(rmsd: float, threshold: float = CONTEXT_DEPENDENT_RMSD) -> bool:
    """True if the binder fold is robust (rmsd <= threshold), False if context-dependent."""
    return rmsd <= threshold


def ca_coords_from_pdb(pdb_text: str, chain: str | None = None) -> np.ndarray:
    """Extract Cα coordinates (N,3) from PDB text, optionally restricted to one chain.

    Reads ATOM records with atom name ``CA``; chain id is column 22 (index 21). Returns an
    empty (0,3) array if none match.
    """
    coords: list[list[float]] = []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if line[12:16].strip() != "CA":
            continue
        if chain is not None and line[21:22].strip() != chain:
            continue
        coords.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
    return np.asarray(coords, dtype=float).reshape(-1, 3)
