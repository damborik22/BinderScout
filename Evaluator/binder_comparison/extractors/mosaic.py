"""Mosaic sequence extractor.

Mosaic output files:
  - designs.csv         — all design candidates (sequence, worker_id, rank, metrics)
  - refold_designs.csv  — Boltz2 cross-validation (optional, for cross-reference)
  - af2_eval.csv        — AF2 cross-validation (optional, for cross-reference)

Primary sequence column: 'sequence'
ID: f"mosaic_{worker_id}_{rank}" when both columns exist, else f"mosaic_{stem}_{idx}"

Note: Mosaic has no PyRosetta metrics, so NativeMetrics is empty.
      The standardised refolding provides all comparison metrics.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

_CSV_CANDIDATES = [
    "designs.csv",
    "refold_designs.csv",  # fallback if designs.csv absent
]

_SEQUENCE_COL = "sequence"


def _read_mosaic_csv(path: Path) -> pd.DataFrame:
    """Read a Mosaic designs.csv that may have rows with varying column counts.

    Mosaic appends designs across runs. If different runs wrote different numbers
    of columns (e.g. an older run had 11, a newer run added target_sequence and
    binder_length giving 13), pandas drops the extra-column rows.

    Fix: find the widest row, extend the header with anonymous extra columns,
    then read normally. The named columns (sequence, worker_id, etc.) stay correct
    since they're always in the same position.
    """
    import csv as _csv

    with open(path, newline="") as fh:
        reader = _csv.reader(fh)
        header = next(reader)
        max_cols = len(header)
        for row in reader:
            if len(row) > max_cols:
                max_cols = len(row)

    # Pad header with anonymous names for extra columns
    extra = max_cols - len(header)
    padded_header = header + [f"_extra_{i}" for i in range(extra)]

    return pd.read_csv(path, names=padded_header, skiprows=1, on_bad_lines="warn")


class MosaicExtractor(SequenceExtractor):
    """Extract binder sequences from Mosaic designs.csv."""

    @property
    def tool_name(self) -> str:
        return "mosaic"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_path = self._find_csv(input_dir)
        if csv_path is None:
            warnings.warn(f"Mosaic: no CSV found in {input_dir}. Looked for: {_CSV_CANDIDATES}")
            return []

        # Mosaic appends across runs; later runs may have extra columns
        # (e.g. target_sequence, binder_length inserted after the sequence column).
        # Read with the widest column count to avoid skipping rows.
        df = _read_mosaic_csv(csv_path)
        if _SEQUENCE_COL not in df.columns:
            raise ValueError(
                f"Mosaic CSV {csv_path} missing '{_SEQUENCE_COL}' column. Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []

        for idx, row in df.iterrows():
            seq = str(row[_SEQUENCE_COL]).strip().upper()
            if not self._validate_sequence(seq):
                warnings.warn(f"Mosaic row {idx}: invalid sequence — skipping")
                continue

            binder_id = self._make_id(row, idx)

            results.append(
                ExtractedBinder(
                    binder_id=binder_id,
                    sequence=seq,
                    source_tool="mosaic",
                    native=NativeMetrics(),
                )
            )

        return results

    def _find_csv(self, input_dir: Path) -> Path | None:
        for name in _CSV_CANDIDATES:
            candidate = input_dir / name
            if candidate.exists():
                return candidate
        for name in _CSV_CANDIDATES:
            matches = list(input_dir.rglob(name))
            if matches:
                return matches[0]
        return None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        has_worker = "worker_id" in row.index and pd.notna(row["worker_id"])
        has_rank = "rank" in row.index and pd.notna(row["rank"])
        if has_worker and has_rank:
            return f"mosaic_{row['worker_id']}_{int(row['rank'])}"
        if has_worker:
            return f"mosaic_{row['worker_id']}"
        return f"mosaic_{fallback_idx}"
