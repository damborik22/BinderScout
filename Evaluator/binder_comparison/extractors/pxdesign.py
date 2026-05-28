"""PXDesign sequence extractor.

PXDesign (protenix-server.com) output files:
  - summary.csv — one row per design, ranked by confidence

Key columns:
  - 'sequence'   — binder amino acid sequence
  - 'rank'       — design rank (1 = best)
  - 'task_name'  — run name (e.g. 'protenix_CALCA_120')
  - 'af2_iptm', 'af2_ipAE' — AF2-IG metrics from internal pipeline
  - 'ptx_iptm', 'ptx_plddt' — Protenix metrics from internal pipeline

Note: PXDesign runs AF2 and Protenix internally, but those are biased
toward PXDesign-optimised sequences. We re-fold everything standardly.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

_CSV_CANDIDATES = [
    "summary.csv",
    "sequences.csv",
]

_SEQUENCE_COL = "sequence"

# Schema field name → PXDesign CSV column name
_NATIVE_COL_MAP = {
    "pxdesign_composite_score": "composite_score",
    "pxdesign_af2_iptm": "af2_iptm",
    "pxdesign_af2_ipae": "af2_ipae",
    "pxdesign_protenix_iptm": "ptx_iptm",
    "pxdesign_sequence_recovery": "sequence_recovery",
}


def _safe_float(val) -> float | None:
    if pd.isna(val) or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


class PXDesignExtractor(SequenceExtractor):
    """Extract binder sequences from PXDesign summary.csv."""

    @property
    def tool_name(self) -> str:
        return "pxdesign"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_path = self._find_csv(input_dir)
        if csv_path is None:
            warnings.warn(f"PXDesign: no summary.csv found in {input_dir} or subdirectories.")
            return []

        df = pd.read_csv(csv_path)
        if _SEQUENCE_COL not in df.columns:
            raise ValueError(
                f"PXDesign CSV {csv_path} missing '{_SEQUENCE_COL}' column. Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []

        for idx, row in df.iterrows():
            seq = str(row[_SEQUENCE_COL]).strip().upper()
            if not self._validate_sequence(seq):
                warnings.warn(f"PXDesign row {idx}: invalid sequence — skipping")
                continue

            binder_id = self._make_id(row, idx)

            # PXDesign's own af2_iptm / ptx_iptm are biased (optimised against),
            # so they are recorded as NativeMetrics for side-by-side comparison
            # with independent refolding (Boltz-2 / AF3 / Protenix).
            native = self._extract_native(row)
            results.append(
                ExtractedBinder(
                    binder_id=binder_id,
                    sequence=seq,
                    source_tool="pxdesign",
                    native=native,
                )
            )

        return results

    def _extract_native(self, row: pd.Series) -> NativeMetrics:
        values: dict[str, float | None] = {}
        for schema_field, csv_col in _NATIVE_COL_MAP.items():
            if csv_col in row.index:
                values[schema_field] = _safe_float(row[csv_col])
            else:
                values[schema_field] = None
        return NativeMetrics(**values)

    def _find_csv(self, input_dir: Path) -> Path | None:
        for name in _CSV_CANDIDATES:
            candidate = input_dir / name
            if candidate.exists():
                return candidate
        # Search subdirectories (e.g. design_outputs/run_name/summary.csv)
        for name in _CSV_CANDIDATES:
            matches = list(input_dir.rglob(name))
            if matches:
                return matches[0]
        return None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        has_task = "task_name" in row.index and pd.notna(row["task_name"])
        has_rank = "rank" in row.index and pd.notna(row["rank"])
        if has_task and has_rank:
            return f"pxdesign_{row['task_name']}_{int(row['rank'])}"
        if has_rank:
            return f"pxdesign_{int(row['rank'])}"
        return f"pxdesign_{fallback_idx}"
