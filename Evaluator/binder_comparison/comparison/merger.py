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
            # validate="1:1" turns any future regression into an error rather than
            # silent row inflation -- the same guard cli/report.py:729 uses.
            if ("target_sequence" in merged.columns) != ("target_sequence" in df.columns):
                # The mismatch guard below compares the two copies; with one missing there is
                # nothing to compare, and it used to skip without a word. All current runners
                # write the column, so its absence means an old or hand-made CSV.
                warnings.warn(
                    f"[merger] {name} CSV and the earlier engine CSV do not both carry "
                    "'target_sequence', so these results cannot be checked for having been folded "
                    "against the same target. A CSV left over from another target would merge "
                    "silently. Re-refold with the current runners, or check the inputs by hand.",
                    stacklevel=2,
                )
            merged = pd.merge(merged, df, on="sequence", how="outer", suffixes=("", f"_{name}_dup"), validate="1:1")
            # BEFORE the _dup columns are dropped: the duplicate target_sequence is the
            # only evidence that two engines folded the same complex, and dropping it
            # unchecked is what let CSVs from different targets merge into one design
            # carrying consensus_iptm_n = 3. Ported from master (v1.0.8) 2026-10-29.
            _refuse_mismatched_targets(merged, name)
            # Passthrough columns: prefer the first engine's values, but FILL GAPS from this
            # engine's copy before dropping it. A design the first engine never scored has no
            # first-engine value (the outer join leaves NaN), and dropping this engine's copy
            # threw away the only real one: `binder_length` is what the report slices every
            # PAE matrix with, so the design lost all its PAE-derived scores and was ranked
            # last without a warning.
            for col in _PASSTHROUGH_COLS - {"sequence"}:
                dup = f"{col}_{name}_dup"
                if dup in merged.columns and col in merged.columns:
                    merged[col] = merged[col].fillna(merged[dup])
            # Drop the duplicate passthrough columns
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
        merged = _attach_fasta_metadata(merged, sequences_fasta)
    return merged


def _load_engine(path: str | Path, prefix: str) -> pd.DataFrame:
    """Load a refolding-engine CSV and prefix non-passthrough columns with ``{prefix}_``."""
    df = read_csv_safe(path)
    if df.empty:
        warnings.warn(f"[merger] {prefix} CSV is empty: {path}")
        return df
    # Collapse repeated sequences BEFORE the join. The engine frames are merged with
    # `on="sequence", how="outer"`, which is many-to-many: K duplicate rows for one
    # sequence in each of N engines produce K**N rows for that single design.
    # Measured 2026-09-28 on the 6-design golden pool -- 3 duplicate rows in all three
    # engines gave that design 27 rows and a 32-row pool, while the banner below
    # reported "32 unique sequences". Everything downstream is pool-relative
    # (percentiles, top-N, per-tool means, z-scores, `rank`), so the inflation is not
    # cosmetic. This is Part AC's seed hazard; `:129` already guarded the FASTA
    # metadata join and this one was missed.
    # Reachable via the documented append path: refold_boltz2.py appends to its CSV, so
    # a re-run without --resume repeats rows. (`extract` deduplicates by sequence and
    # AF3 collapses its seeds, so neither of those can trigger it.)
    if "sequence" in df.columns:
        # The join key must be canonical: a refold CSV that was hand-edited, re-keyed or
        # written by another path can carry the same binder in lower case or with trailing
        # whitespace, and the exact-string outer join then split ONE design into several
        # single-engine rows (n=1 each, ranked last). Same normalisation resume.py uses.
        df = df.assign(sequence=df["sequence"].astype(str).str.strip().str.upper())
        n_before = len(df)
        if "iptm" in df.columns:
            # Prefer a scored row over a blank one for the same sequence. AF3 and
            # ESMFold2 write a BLANK row when a design fails and append the retry's
            # scored row after it, so `keep="first"` alone kept the blank and threw away
            # the score `--resume` existed to produce -- the design then stayed one
            # engine short and was ranked last for a hardware reason. kind="stable"
            # keeps file order among rows that are equally scored.
            df = (
                df.assign(_scored=df["iptm"].notna())
                .sort_values("_scored", ascending=False, kind="stable")
                .drop(columns=["_scored"])
            )
        df = df.drop_duplicates("sequence", keep="first")
        n_dropped = n_before - len(df)
        if n_dropped:
            warnings.warn(
                f"[merger] {prefix}: dropped {n_dropped} duplicate row(s) sharing a sequence "
                f"with an earlier row, keeping the scored one where there was one and "
                f"otherwise the first ({n_before} -> {len(df)}). "
                "Left in, the outer join would have multiplied those designs across every "
                "engine. Usual causes: a `--resume` retry appending a score next to the "
                "blank row an earlier failure wrote, or a refold re-run WITHOUT --resume "
                f"appending the whole pool again -- check {path}.",
                stacklevel=2,
            )
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
                "sequence": seq.strip().upper(),
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
