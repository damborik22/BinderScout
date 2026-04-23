"""Merge Boltz-2 refolding results (and future Protenix / AF3 engines) into a single DataFrame.

Column naming convention after merge:
  - Boltz-2 columns are prefixed with ``boltz_`` (e.g. ``boltz_iptm``, ``boltz_ipae``)
  - Future engines (Protenix, AF3) will carry ``protenix_`` / ``af3_`` prefixes
  - ``sequence`` is the join key, present in every engine's CSV

The FASTA extracted by 'binder-compare extract' is used to join the source
tool tag back onto the merged results.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..io.read import read_csv_safe, read_fasta

# Columns from Boltz-2 CSV (refold_boltz2) that should NOT be prefixed
_BOLTZ2_PASSTHROUGH_COLS = {"sequence", "target_sequence", "binder_length", "run_id"}


def merge_refold_results(
    boltz2_csv: str | Path | None,
    sequences_fasta: str | Path | None = None,
) -> pd.DataFrame:
    """Load Boltz-2 results and optionally attach FASTA-extracted metadata.

    Args:
        boltz2_csv:       Path to boltz2_results.csv from 'refold-boltz2'.
        sequences_fasta:  Optional FASTA from 'extract'; used to attach
                          binder_id and source_tool columns.

    Returns:
        DataFrame with all Boltz-2 metrics, ``boltz_``-prefixed for columns
        outside the passthrough set.
    """
    boltz_df = _load_boltz2(boltz2_csv) if boltz2_csv else pd.DataFrame()
    if boltz_df.empty:
        raise ValueError("boltz2_csv is absent or empty — nothing to report on.")

    merged = boltz_df.copy()
    if sequences_fasta:
        merged = _attach_fasta_metadata(merged, sequences_fasta)
    return merged


def _load_boltz2(path: str | Path) -> pd.DataFrame:
    """Load and prefix Boltz-2 CSV columns with 'boltz_'."""
    df = read_csv_safe(path)
    if df.empty:
        return df

    rename = {col: f"boltz_{col}" for col in df.columns if col not in _BOLTZ2_PASSTHROUGH_COLS}
    return df.rename(columns=rename)


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
    return pd.merge(df, meta_df, on="sequence", how="left")
