"""Proteina-Complexa sequence extractor.

Proteina-Complexa (NVIDIA) output files:
  - sequences.csv — aggregated by BindMaster run script (preferred)
  - evaluation_results/*.csv — per-sample evaluation CSVs from Complexa pipeline

Key columns (in evaluation_results CSVs):
  - 'sequence'               — binder amino acid sequence
  - 'self_complex_i_pTM'     — AF2 interface pTM from internal eval
  - 'self_complex_i_pAE'     — AF2 interface PAE from internal eval
  - 'self_complex_pLDDT'     — AF2 pLDDT from internal eval
  - 'self_binder_scRMSD'     — binder self-consistency RMSD

Note: Complexa's internal AF2 scores are used as a reward signal during
generation. For cross-tool comparison, we re-fold everything with our
standardised Boltz-2 and AF2 pipeline.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

_CSV_CANDIDATES = [
    "sequences.csv",
]

_SEQUENCE_COL = "sequence"


class ProteinaComplexaExtractor(SequenceExtractor):
    """Extract binder sequences from Proteina-Complexa outputs."""

    @property
    def tool_name(self) -> str:
        return "proteina_complexa"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_path = self._find_csv(input_dir)
        if csv_path is None:
            warnings.warn(f"Proteina-Complexa: no sequences.csv found in {input_dir} or subdirectories.")
            return []

        df = pd.read_csv(csv_path)
        if _SEQUENCE_COL not in df.columns:
            raise ValueError(
                f"Proteina-Complexa CSV {csv_path} missing '{_SEQUENCE_COL}' column. Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []

        for idx, row in df.iterrows():
            seq = str(row[_SEQUENCE_COL]).strip().upper()
            if not self._validate_sequence(seq):
                warnings.warn(f"Proteina-Complexa row {idx}: invalid sequence — skipping")
                continue

            binder_id = self._make_id(row, idx)

            results.append(
                ExtractedBinder(
                    binder_id=binder_id,
                    sequence=seq,
                    source_tool="proteina_complexa",
                    native=NativeMetrics(),
                )
            )

        return results

    def _find_csv(self, input_dir: Path) -> Path | None:
        for name in _CSV_CANDIDATES:
            candidate = input_dir / name
            if candidate.exists():
                return candidate
        # Search subdirectories
        for name in _CSV_CANDIDATES:
            matches = list(input_dir.rglob(name))
            if matches:
                return matches[0]
        # Fall back to any CSV in evaluation_results/
        eval_dir = input_dir / "evaluation_results"
        if eval_dir.exists():
            csvs = list(eval_dir.rglob("*.csv"))
            if csvs:
                return csvs[0]
        return None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        has_name = "name" in row.index and pd.notna(row["name"])
        has_design_id = "design_id" in row.index and pd.notna(row["design_id"])
        if has_design_id:
            did = str(row["design_id"])
            if did.startswith("complexa_"):
                return did
            return f"complexa_{did}"
        if has_name:
            return f"complexa_{row['name']}"
        return f"complexa_{fallback_idx}"
