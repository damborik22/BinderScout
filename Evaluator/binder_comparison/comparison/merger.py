"""Merge refolding results from multiple engines into a single DataFrame.

Column naming convention after merge:
  - Boltz-2 columns are prefixed with ``boltz_``
  - AF3 columns (Part K, aarch64) are prefixed with ``af3_``
  - ESMFold2 columns (biohub) are prefixed with ``esmfold2_``
  - ``sequence`` is the join key, present in every engine's CSV

The FASTA extracted by 'binder-compare extract' is used to join the source
tool tag back onto the merged results.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..io.read import read_csv_safe, read_fasta

# Columns that should NOT be prefixed — passthrough identifiers shared across engines
_PASSTHROUGH_COLS = {"sequence", "target_sequence", "binder_length", "run_id"}


def merge_refold_results(
    boltz2_csv: str | Path | None,
    sequences_fasta: str | Path | None = None,
    *,
    af3_csv: str | Path | None = None,
    esmfold2_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Outer-join refolding-engine CSVs on the ``sequence`` column.

    Args:
        boltz2_csv:       Path to boltz2_results.csv from 'refold-boltz2' (required
                          anchor — report needs at least one engine).
        sequences_fasta:  Optional FASTA from 'extract'; attaches binder_id and
                          source_tool columns.
        af3_csv:          Optional AF3 results (refold-af3 output).
        esmfold2_csv:     Optional ESMFold2 results (refold-esmfold2 output).

    Returns:
        DataFrame with per-engine prefixed columns + passthrough identifiers.
    """
    engine_dfs: dict[str, pd.DataFrame] = {}
    if boltz2_csv:
        engine_dfs["boltz"] = _load_engine(boltz2_csv, "boltz")
    if af3_csv:
        engine_dfs["af3"] = _load_engine(af3_csv, "af3")
    if esmfold2_csv:
        engine_dfs["esmfold2"] = _load_engine(esmfold2_csv, "esmfold2")

    engine_dfs = {k: v for k, v in engine_dfs.items() if not v.empty}
    if not engine_dfs:
        raise ValueError("No non-empty refolding CSVs supplied — nothing to report on.")

    merged: pd.DataFrame | None = None
    for name, df in engine_dfs.items():
        if merged is None:
            merged = df.copy()
        else:
            merged = pd.merge(merged, df, on="sequence", how="outer", suffixes=("", f"_{name}_dup"))
            _refuse_mismatched_targets(merged, name)
            # Drop accidental duplicate passthrough columns (prefer the first engine's values)
            for col in list(merged.columns):
                if col.endswith(f"_{name}_dup"):
                    merged.drop(columns=[col], inplace=True)

    assert merged is not None  # engine_dfs non-empty guarantee

    if len(engine_dfs) > 1:
        iptm_cols = {name: f"{name}_iptm" for name in engine_dfs}
        present = [c for c in iptm_cols.values() if c in merged.columns]
        if present:
            n_total = len(merged)
            both_mask = merged[present].notna().all(axis=1)
            print(
                f"[merger] {n_total} unique sequences — "
                f"{int(both_mask.sum())} have all {len(present)} engines, "
                + ", ".join(f"{int(merged[c].isna().sum())} missing {c.split('_')[0]}" for c in present)
            )

    if sequences_fasta:
        merged = _restrict_to_pool(merged, sequences_fasta)
        merged = _attach_fasta_metadata(merged, sequences_fasta)
    return merged


def _refuse_mismatched_targets(merged: pd.DataFrame, name: str) -> None:
    """Refuse to merge engine rows that describe different targets.

    ``target_sequence`` is a passthrough column: it stays unprefixed because every
    engine in a run folds against the same target, and the merge therefore drops the
    later engine's copy as a redundant duplicate. Nothing used to compare the two
    before dropping one. So CSVs produced against *different* targets joined on the
    binder ``sequence`` alone and came out as a single row carrying the first
    engine's target, with ``consensus_iptm_n`` counting every engine as independent
    agreement. Exit 0, no warning, and the design ranked first — a fabricated
    cross-engine consensus, which is the one thing the ranking exists to resist.

    This is reachable without anyone doing something strange. A refold CSV
    accumulates across runs (``--resume`` depends on that), and until 1.0.7
    ``refold-boltz2`` defaulted its output to a CWD-relative directory shared by
    every run against every target.

    A disagreement means the inputs do not describe one experiment. There is no
    correct row to emit, so the report is refused rather than written: a crash costs
    an operator ten minutes, and a plausible wrong answer can cost a gene order.
    """
    dup = f"target_sequence_{name}_dup"
    if dup not in merged.columns or "target_sequence" not in merged.columns:
        return

    def _norm(col: pd.Series) -> pd.Series:
        return col.astype(str).str.strip().str.upper()

    comparable = merged["target_sequence"].notna() & merged[dup].notna()
    clash = comparable & (_norm(merged["target_sequence"]) != _norm(merged[dup]))
    if not clash.any():
        return

    row = merged.loc[clash].iloc[0]
    raise ValueError(
        f"refold CSVs disagree about the target: {int(clash.sum())} of {int(comparable.sum())} shared "
        f"designs have a different target_sequence in the {name} CSV than in the first engine's. "
        f"These results were folded against different targets, so merging them would report one design "
        f"as confirmed by several engines when the engines did not fold the same complex.\n"
        f"  binder   {str(row['sequence'])[:40]}…\n"
        f"  first    {str(row['target_sequence'])[:60]}…\n"
        f"  {name:<8} {str(row[dup])[:60]}…\n"
        f"Most likely one CSV is left over from another run or another target — a refold CSV accumulates "
        f"across runs. Re-refold this pool into a per-run --output-dir, or pass the CSVs that belong to "
        f"this target."
    )


def _restrict_to_pool(df: pd.DataFrame, fasta_path: str | Path) -> pd.DataFrame:
    """Drop engine rows whose sequence is not in *fasta_path*.

    The FASTA is the pool being reported on, so it is the universe — an engine CSV
    may legitimately hold more (it accumulates across runs; `--resume` depends on
    that). Those extra rows must not be ranked.

    2026-10-28 PD-L1: Boltz-2's CSV came from a shared directory and held 1003
    designs from earlier pools, none of them among the 65 being reported. The outer
    join carried all 1068 into `metrics.csv`, the off-pool rows were collapsed into
    the diversity families and the Top-30, and `boltz_pae_ipsae_min` — the primary
    ranking column — was computed over designs that were never in the campaign.
    """
    pool = {seq.strip().upper() for _, seq in read_fasta(fasta_path) if seq.strip()}
    if not pool or "sequence" not in df.columns:
        return df

    in_pool = df["sequence"].astype(str).str.strip().str.upper().isin(pool)
    n_off = int((~in_pool).sum())
    if n_off:
        warnings.warn(
            f"[merger] {n_off} refold row(s) are not in {fasta_path} and were dropped from "
            f"the report ({int(in_pool.sum())} of {len(pool)} pool design(s) kept). An engine "
            "CSV holding another pool's designs usually means a stale output directory.",
            stacklevel=2,
        )
    return df[in_pool].reset_index(drop=True)


def _load_engine(path: str | Path, prefix: str) -> pd.DataFrame:
    """Load a refolding-engine CSV and prefix non-passthrough columns with ``{prefix}_``."""
    df = read_csv_safe(path)
    if df.empty:
        warnings.warn(f"[merger] {prefix} CSV is empty: {path}")
        return df
    rename = {col: f"{prefix}_{col}" for col in df.columns if col not in _PASSTHROUGH_COLS}
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

    # One metadata row per sequence. With `extract --keep-duplicates` the FASTA can
    # carry the same sequence under several binder_ids; a left join against a
    # duplicated right key multiplies the metrics rows, so one design would occupy
    # several Top-30 slots and inflate the two-stage screen's eligible count.
    # cli/autosize.py:160 already guards its equivalent merge the same way.
    n_before = len(meta_df)
    meta_df = meta_df.drop_duplicates("sequence", keep="first")
    n_dupes = n_before - len(meta_df)
    if n_dupes:
        warnings.warn(
            f"[merger] {n_dupes} duplicate sequence(s) in {fasta_path} — keeping the first "
            f"binder_id for each. Re-run 'extract' without --keep-duplicates to avoid this.",
            stacklevel=2,
        )
    # validate="m:1" turns any future regression here into an error instead of silent
    # row inflation.
    return pd.merge(df, meta_df, on="sequence", how="left", validate="m:1")
