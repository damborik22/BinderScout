"""BoltzGen sequence extractor.

BoltzGen output files (from task/analyze/analyze.py):
  - aggregate_metrics_{name}.csv  — metrics for all designs in an analysis step
  - final_designs_metrics_{budget}.csv — metrics for the final filtered set

Sequence column: 'designed_sequence' (single binder chain)
                 'designed_chain_sequence' (designed residues only, subset)
ID column: 'id' (format: target_name__design_index)

Note: BoltzGen has no PyRosetta metrics, so NativeMetrics is empty.
      The standardised refolding will provide all comparison metrics.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

# In order of preference
_CSV_CANDIDATES = [
    "final_designs_metrics_*.csv",
    "aggregate_metrics_*.csv",
]

_SEQUENCE_COL_CANDIDATES = [
    "designed_sequence",
    "designed_chain_sequence",
    "sequence",
]


class BoltzGenExtractor(SequenceExtractor):
    """Extract binder sequences from BoltzGen output CSV."""

    @property
    def tool_name(self) -> str:
        return "boltzgen"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_path = self._find_csv(input_dir)
        if csv_path is None:
            warnings.warn(f"BoltzGen: no metrics CSV found in {input_dir}. Looked for: {_CSV_CANDIDATES}")
            return []

        df = pd.read_csv(csv_path)
        seq_col = self._detect_sequence_col(df)
        if seq_col is None:
            raise ValueError(
                f"BoltzGen CSV {csv_path} has no recognised sequence column. "
                f"Expected one of: {_SEQUENCE_COL_CANDIDATES}. "
                f"Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []
        stem = csv_path.stem

        for idx, row in df.iterrows():
            seq = str(row[seq_col]).strip().upper()
            if not self._validate_sequence(seq):
                warnings.warn(f"BoltzGen row {idx}: invalid sequence — skipping")
                continue

            # Build ID from 'id' column if available
            if "id" in row.index and pd.notna(row["id"]):
                binder_id = f"boltzgen_{row['id']}"
            else:
                binder_id = f"boltzgen_{stem}_{idx}"

            # Surface BoltzGen's own ipSAE_min (ρ = +0.84 with refold) and final_rank.
            # See INVESTIGATION_RANKING_DISCREPANCY.md §5.
            native = NativeMetrics()
            for col in ("design_ipsae_min", "ipsae_min", "design_ipsae", "ipsae_min_top10"):
                if col in row.index and pd.notna(row[col]):
                    try:
                        native.bg_design_ipsae_min = float(row[col])
                    except (TypeError, ValueError):
                        pass
                    break
            if "final_rank" in row.index and pd.notna(row["final_rank"]):
                try:
                    native.bg_final_rank = int(row["final_rank"])
                except (TypeError, ValueError):
                    pass

            results.append(
                ExtractedBinder(
                    binder_id=binder_id,
                    sequence=seq,
                    source_tool="boltzgen",
                    native=native,
                )
            )

        return results

    def _find_csv(self, input_dir: Path) -> Path | None:
        # final_designs_metrics takes priority
        for pattern in _CSV_CANDIDATES:
            matches = sorted(input_dir.rglob(pattern))
            if matches:
                return matches[-1]  # take latest if multiple budgets
        return None

    def _detect_sequence_col(self, df: pd.DataFrame) -> str | None:
        for col in _SEQUENCE_COL_CANDIDATES:
            if col in df.columns:
                return col
        return None
