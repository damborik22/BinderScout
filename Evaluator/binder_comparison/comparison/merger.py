"""Merge Boltz2 and AF2 refolding results into a single DataFrame.

Column naming convention after merge:
  - Boltz2 columns are prefixed with 'boltz_' (e.g. boltz_iptm, boltz_ipae)
  - AF2 columns already carry the 'af2_' prefix from refold_Version6
  - 'sequence' is the join key, present in both CSVs

The FASTA extracted by 'binder-compare extract' is used to join the source
tool tag back onto the merged results.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..io.read import read_csv_safe, read_fasta

# Columns from Boltz2 CSV (refold_Version5) that should NOT be prefixed
_BOLTZ2_PASSTHROUGH_COLS = {"sequence", "target_sequence", "binder_length", "run_id"}

# Identity columns from AF2 CSV (refold_Version6) to drop after merge (redundant)
_AF2_DROP_COLS = {"run_id", "idx", "target_pdb", "binder_length"}


def merge_refold_results(
    boltz2_csv: str | Path | None,
    af2_csv: str | Path | None,
    sequences_fasta: str | Path | None = None,
) -> pd.DataFrame:
    """Join Boltz2 and AF2 results on the 'sequence' column.

    Args:
        boltz2_csv:       Path to boltz2_results.csv from 'refold-boltz2'.
        af2_csv:          Path to af2_results.csv from 'refold-af2'.
        sequences_fasta:  Optional FASTA from 'extract' step; used to attach
                          binder_id and source_tool columns.

    Returns:
        DataFrame with all metrics. Sequences present in only one model's CSV
        get NaN for the missing model's columns (outer join).
    """
    boltz_df = _load_boltz2(boltz2_csv) if boltz2_csv else pd.DataFrame()
    af2_df = _load_af2(af2_csv) if af2_csv else pd.DataFrame()

    if boltz_df.empty and af2_df.empty:
        raise ValueError("Both boltz2_csv and af2_csv are absent or empty.")

    if boltz_df.empty:
        warnings.warn("No Boltz2 results — AF2 metrics only.")
        merged = af2_df.copy()
    elif af2_df.empty:
        warnings.warn("No AF2 results — Boltz2 metrics only.")
        merged = boltz_df.copy()
    else:
        merged = pd.merge(boltz_df, af2_df, on="sequence", how="outer")
        n_both = merged[["boltz_iptm", "af2_iptm"]].notna().all(axis=1).sum()
        n_total = len(merged)
        print(
            f"[merger] {n_total} unique sequences: {n_both} have both models, "
            f"{(merged['boltz_iptm'].isna()).sum()} Boltz2-only, "
            f"{(merged['af2_iptm'].isna()).sum()} AF2-only"
        )

    # Attach binder_id and source_tool from the FASTA if provided
    if sequences_fasta:
        merged = _attach_fasta_metadata(merged, sequences_fasta)

    return merged


def _load_boltz2(path: str | Path) -> pd.DataFrame:
    """Load and prefix Boltz2 CSV columns with 'boltz_'."""
    df = read_csv_safe(path)
    if df.empty:
        return df

    rename = {col: f"boltz_{col}" for col in df.columns if col not in _BOLTZ2_PASSTHROUGH_COLS}
    return df.rename(columns=rename)


def _load_af2(path: str | Path) -> pd.DataFrame:
    """Load AF2 CSV; columns already have 'af2_' prefix in refold_Version6."""
    df = read_csv_safe(path)
    if df.empty:
        return df

    # Drop identity columns that would create conflicts in the merge
    drop = [c for c in _AF2_DROP_COLS if c in df.columns]
    return df.drop(columns=drop)


def _attach_fasta_metadata(df: pd.DataFrame, fasta_path: str | Path) -> pd.DataFrame:
    """Add binder_id and source_tool columns from the extract FASTA."""
    entries = read_fasta(fasta_path)
    meta_rows = []
    for header, seq in entries:
        tokens = header.split()
        parts = {}
        for token in tokens:
            if "=" in token:
                k, v = token.split("=", 1)
                parts[k] = v
        # First token before whitespace/tags is the binder_id
        binder_id = tokens[0] if tokens else header
        meta_rows.append(
            {
                "sequence": seq,
                "binder_id": binder_id,
                "source_tool": parts.get("source", "unknown"),
            }
        )

    if not meta_rows:
        return df

    meta_df = pd.DataFrame(meta_rows)
    # Left-join so we keep all sequences even if the FASTA is stale
    merged = pd.merge(df, meta_df, on="sequence", how="left")
    return merged
