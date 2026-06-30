"""Cross-design diversity clustering (Item 1).

Reviewer concern: ``candidates.collapse_native_df`` only collapses exact MPNN
siblings of *one* backbone (the ``design_group`` concept). Independent designs
from different tools that converge on the same fold or sequence motif are
still counted as distinct candidates — so a top-30 dominated by a single
helical-repeat motif (e.g. Mosaic's E/L/A repeats) silently loses diversity.

This module annotates each design with a ``family_id`` derived from sequence
identity (CD-HIT-style greedy clustering on shared k-mer Jaccard, no external
tool required). A second pass on refolded PDBs (Cα RMSD after Kabsch
alignment) can refine the families.

Advisory only: report adds ``family_id`` + ``family_size`` columns;
recommends top-1-2 reps per family in a separate block; ranking is unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# ─── Sequence clustering ─────────────────────────────────────────────────────


def _kmer_set(seq: str, k: int = 4) -> set[str]:
    """Hashable k-mer multiset (collapsed to set) for Jaccard similarity."""
    if not seq or len(seq) < k:
        return set()
    return {seq[i : i + k] for i in range(len(seq) - k + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two k-mer sets. 0 when both empty."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


@dataclass
class SequenceCluster:
    """One cluster's centroid + members."""

    family_id: str
    centroid_idx: int
    member_indices: list[int]


def cluster_sequences(
    seqs: list[str],
    threshold: float = 0.7,
    k: int = 4,
) -> list[int]:
    """Greedy CD-HIT-style sequence clustering by k-mer Jaccard similarity.

    Returns a parallel list of integer family IDs (same length as ``seqs``). A
    sequence joins the first existing cluster whose centroid has Jaccard
    similarity ≥ ``threshold``; otherwise it starts a new cluster.

    Args:
        seqs: list of binder sequences (uppercase amino acids; empty strings
            become singleton clusters with id = their own index in seqs).
        threshold: Jaccard cutoff. 0.7 with k=4 is a reasonable starting
            point for de-novo binders (corresponds roughly to 70-80% identity).
        k: k-mer length. 4 balances speed and discrimination for ~50-150 aa
            binders; raise for longer / lower for shorter.

    Note: This is an approximate clustering, not a guaranteed-optimal one —
    the order of input determines centroids. Sort ``seqs`` by length descending
    (or by quality) for the best results.
    """
    if not seqs:
        return []
    cleaned = [(s or "").upper().strip() for s in seqs]
    kmers = [_kmer_set(s, k=k) for s in cleaned]
    # Process longer sequences first so they become the centroids (CD-HIT default).
    order = sorted(range(len(cleaned)), key=lambda i: -len(cleaned[i]))
    family_for: dict[int, int] = {}
    centroids: list[tuple[int, set[str]]] = []  # (family_id, kmers)
    next_id = 0
    for idx in order:
        km = kmers[idx]
        if not km:
            family_for[idx] = next_id
            centroids.append((next_id, km))
            next_id += 1
            continue
        assigned = None
        best_sim = -1.0
        for fid, cm in centroids:
            sim = _jaccard(km, cm)
            if sim >= threshold and sim > best_sim:
                assigned = fid
                best_sim = sim
        if assigned is None:
            family_for[idx] = next_id
            centroids.append((next_id, km))
            next_id += 1
        else:
            family_for[idx] = assigned
    return [family_for[i] for i in range(len(cleaned))]


def cluster_sequences_df(
    df: pd.DataFrame,
    sequence_col: str = "sequence",
    threshold: float = 0.7,
    k: int = 4,
    prefix: str = "fam",
) -> pd.DataFrame:
    """Annotate a DataFrame with ``family_id`` + ``family_size`` columns.

    Stable: input row order is preserved; the family IDs are zero-padded so
    they sort lexicographically the same as numerically.
    """
    out = df.copy()
    if sequence_col not in out.columns or out.empty:
        out["family_id"] = ""
        out["family_size"] = 0
        out["family_rank"] = 0
        return out
    fam_ids = cluster_sequences(out[sequence_col].fillna("").astype(str).tolist(), threshold=threshold, k=k)
    out["family_id"] = [f"{prefix}{i:04d}" for i in fam_ids]
    sizes = out["family_id"].value_counts().to_dict()
    out["family_size"] = out["family_id"].map(sizes).astype(int)
    # Within-family rank: order by position in the input (caller can sort
    # beforehand if they want a different ordering, e.g. by two_stage_rank).
    out["family_rank"] = out.groupby("family_id").cumcount() + 1
    return out


# ─── Optional structural refinement (Cα RMSD after Kabsch) ────────────────────


def _kabsch_rmsd(a: np.ndarray, b: np.ndarray) -> float:
    """Cα RMSD after rigid superposition (Kabsch). Returns inf if shapes differ.

    Both ``a`` and ``b`` are (N, 3) float arrays of equal length.
    """
    if a.shape != b.shape or a.size == 0:
        return math.inf
    a = a - a.mean(axis=0)
    b = b - b.mean(axis=0)
    h = a.T @ b
    u, _, vt = np.linalg.svd(h)
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1, 1, d]) @ u.T
    aligned = a @ rot.T
    diff = aligned - b
    return float(np.sqrt((diff * diff).sum() / len(b)))


def refine_families_by_structure(
    df: pd.DataFrame,
    coordinates_by_id: dict[str, np.ndarray],
    id_col: str = "binder_id",
    rmsd_threshold: float = 3.0,
) -> pd.DataFrame:
    """Optional refinement step: split families whose members differ by RMSD > threshold.

    For each family from ``cluster_sequences_df``, compute pairwise Cα RMSD
    across members whose binder_id has coordinates supplied; members whose
    RMSD to the family centroid exceeds ``rmsd_threshold`` form a new
    subcluster (suffixed ``_b``, ``_c``, …).

    This is the second-pass refinement and is strictly optional — many use
    cases just want the sequence-only clustering. Requires extracting Cα
    coords from refolded PDBs (cheap; see :func:`comparison.epitope._parse_pdb_cas`).
    """
    if "family_id" not in df.columns or df.empty:
        return df
    out = df.copy()
    out["family_id_seq"] = out["family_id"]  # preserve the pure-sequence family
    new_ids = list(out["family_id"])
    for fid, group in out.groupby("family_id"):
        members = group[id_col].astype(str).tolist()
        coords = {m: coordinates_by_id.get(m) for m in members}
        valid = {m: c for m, c in coords.items() if c is not None and c.size > 0}
        if len(valid) < 2:
            continue
        # Choose the longest-coords member as centroid.
        centroid_id = max(valid.keys(), key=lambda m: len(valid[m]))
        centroid_coords = valid[centroid_id]
        sub_suffix = "a"
        sub_assign: dict[str, str] = {centroid_id: f"{fid}_a"}
        for m, c in valid.items():
            if m == centroid_id:
                continue
            # Pad / trim by truncating to the shorter length — simple, robust.
            n = min(len(centroid_coords), len(c))
            rmsd = _kabsch_rmsd(centroid_coords[:n], c[:n])
            if rmsd > rmsd_threshold:
                # New subcluster.
                sub_suffix = chr(ord(sub_suffix) + 1)
                sub_assign[m] = f"{fid}_{sub_suffix}"
            else:
                sub_assign[m] = f"{fid}_a"
        # Apply subclusters back to the parallel new_ids list.
        for idx, row_id in zip(group.index, members):
            if row_id in sub_assign:
                new_ids[idx] = sub_assign[row_id]
    out["family_id"] = new_ids
    # Recompute sizes/ranks for the refined families.
    sizes = out["family_id"].value_counts().to_dict()
    out["family_size"] = out["family_id"].map(sizes).astype(int)
    out["family_rank"] = out.groupby("family_id").cumcount() + 1
    return out


# ─── Recommendation ──────────────────────────────────────────────────────────


def top_per_family(
    df: pd.DataFrame,
    n_per_family: int = 1,
    sort_col: str | None = None,
    ascending: bool = True,
) -> pd.DataFrame:
    """Return up to ``n_per_family`` representatives per family.

    Sorts within each family by ``sort_col`` (e.g. ``two_stage_rank``,
    ascending=True for lowest rank = best) before picking the top N.
    Designs without a ``family_id`` are returned as singletons.
    """
    if "family_id" not in df.columns or df.empty:
        return df
    work = df.copy()
    if sort_col and sort_col in work.columns:
        work = work.sort_values(by=sort_col, ascending=ascending, kind="stable")
    return work.groupby("family_id", sort=False).head(n_per_family).reset_index(drop=True)
