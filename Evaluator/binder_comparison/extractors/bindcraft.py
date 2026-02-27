"""BindCraft sequence extractor.

Reads final_design_stats.csv (preferred) or mpnn_design_stats.csv.

BindCraft CSV structure (from generate_dataframe_labels in generic_utils.py):
  - Sequence column: 'Sequence'
  - Native metrics: 'Average_dG', 'Average_dSASA', 'Average_ShapeComplementarity',
                    'Average_PackStat', 'Average_n_InterfaceHbonds',
                    'Average_InterfaceHbondsPercentage', 'MPNN_seq_recovery'
  - Each metric also has per-model columns: '1_dG', '2_dG', ... '5_dG'
  - Final CSV has a leading 'Rank' column.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

# Column names as defined in BindCraft's generate_dataframe_labels()
_SEQUENCE_COL = "Sequence"

_NATIVE_COL_MAP = {
    "dG":                   "Average_dG",
    "dSASA":                "Average_dSASA",
    "shape_complementarity":"Average_ShapeComplementarity",
    "packstat":             "Average_PackStat",
    "hbonds_interface":     "Average_n_InterfaceHbonds",
    "hbonds_pct":           "Average_InterfaceHbondsPercentage",
    "mpnn_recovery":        "MPNN_seq_recovery",
}

# Preferred CSV filenames, in search order
_CSV_CANDIDATES = [
    "final_design_stats.csv",
    "mpnn_design_stats.csv",
    "trajectory_stats.csv",
]


class BindCraftExtractor(SequenceExtractor):
    """Extract binder sequences and PyRosetta native metrics from BindCraft output."""

    @property
    def tool_name(self) -> str:
        return "bindcraft"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_path = self._find_csv(input_dir)
        if csv_path is None:
            warnings.warn(
                f"BindCraft: no CSV found in {input_dir}. "
                f"Looked for: {_CSV_CANDIDATES}"
            )
            return []

        df = pd.read_csv(csv_path)
        if _SEQUENCE_COL not in df.columns:
            raise ValueError(
                f"BindCraft CSV {csv_path} missing '{_SEQUENCE_COL}' column. "
                f"Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []
        stem = csv_path.stem

        for idx, row in df.iterrows():
            seq = str(row[_SEQUENCE_COL]).strip().upper()
            if not self._validate_sequence(seq):
                warnings.warn(f"BindCraft row {idx}: invalid sequence '{seq[:20]}...' — skipping")
                continue

            native = self._extract_native(row)
            binder_id = f"bindcraft_{stem}_{idx}"

            # Use the 'Design' column as part of the ID when available
            if "Design" in row and pd.notna(row["Design"]):
                binder_id = f"bindcraft_{row['Design']}"

            results.append(ExtractedBinder(
                binder_id=binder_id,
                sequence=seq,
                source_tool="bindcraft",
                native=native,
            ))

        return results

    def _find_csv(self, input_dir: Path) -> Path | None:
        for name in _CSV_CANDIDATES:
            candidate = input_dir / name
            if candidate.exists():
                return candidate
        # Also search one level deep (e.g. if input_dir is the design_path parent)
        for name in _CSV_CANDIDATES:
            matches = list(input_dir.rglob(name))
            if matches:
                return matches[0]
        return None

    def _extract_native(self, row: pd.Series) -> NativeMetrics:
        def _get(col: str) -> float | None:
            if col in row.index and pd.notna(row[col]):
                try:
                    return float(row[col])
                except (TypeError, ValueError):
                    return None
            return None

        return NativeMetrics(
            dG=_get(_NATIVE_COL_MAP["dG"]),
            dSASA=_get(_NATIVE_COL_MAP["dSASA"]),
            shape_complementarity=_get(_NATIVE_COL_MAP["shape_complementarity"]),
            packstat=_get(_NATIVE_COL_MAP["packstat"]),
            hbonds_interface=_get(_NATIVE_COL_MAP["hbonds_interface"]),
            hbonds_pct=_get(_NATIVE_COL_MAP["hbonds_pct"]),
            mpnn_recovery=_get(_NATIVE_COL_MAP["mpnn_recovery"]),
        )
