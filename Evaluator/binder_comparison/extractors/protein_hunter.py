"""Protein-Hunter sequence extractor.

Protein-Hunter (Cho et al. 2025, bioRxiv 10.1101/2025.10.10.681530) runs
Boltz-2 / Chai-1 multi-cycle hallucination and writes per-job outputs into
``results_boltz/<name>/`` or ``results_chai/<name>/``:

  - summary_high_iptm.csv  — successes with iptm > threshold & %X filter
  - summary_all_runs.csv   — every run, all cycles (best_* columns)
  - high_iptm_pdb/*.pdb    — PDBs of passing designs
  - high_iptm_yaml/*.yaml  — Boltz-formatted YAMLs for AF3 rerun

Default: read ``summary_high_iptm.csv`` (already filtered by ipTM + %X — tracks
the Mosaic ``is_top=1`` pattern). Pass ``all_runs=True`` to return every
``best_seq`` from ``summary_all_runs.csv`` instead.

Note: Protein-Hunter has no PyRosetta interface metrics; NativeMetrics is empty.
      Cross-validation metrics come from the standardised refolding pipeline
      (Boltz-2 / Protenix / AF3).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

_HIGH_IPTM_CSV = "summary_high_iptm.csv"
_ALL_RUNS_CSV = "summary_all_runs.csv"


class ProteinHunterExtractor(SequenceExtractor):
    """Extract binder sequences from a Protein-Hunter results directory."""

    def __init__(self, *, all_runs: bool = False):
        self.all_runs = all_runs

    @property
    def tool_name(self) -> str:
        return "protein_hunter"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        if self.all_runs:
            return self._extract_all_runs(input_dir)
        return self._extract_high_iptm(input_dir)

    def _extract_high_iptm(self, input_dir: Path) -> list[ExtractedBinder]:
        csv_path = self._find_csv(input_dir, _HIGH_IPTM_CSV)
        if csv_path is None:
            warnings.warn(
                f"Protein-Hunter: no {_HIGH_IPTM_CSV} found in {input_dir}. "
                f"Fall back to --all-protein-hunter-designs to read {_ALL_RUNS_CSV}."
            )
            return []

        df = pd.read_csv(csv_path)
        if "sequence" not in df.columns:
            raise ValueError(
                f"Protein-Hunter CSV {csv_path} missing 'sequence' column. Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []
        for idx, row in df.iterrows():
            seq = str(row["sequence"]).strip().upper()
            if not self._validate_sequence(seq):
                warnings.warn(f"Protein-Hunter row {idx}: invalid sequence — skipping")
                continue
            results.append(
                ExtractedBinder(
                    binder_id=self._make_id(row, int(idx)),
                    sequence=seq,
                    source_tool="protein_hunter",
                    native=NativeMetrics(),
                )
            )
        return results

    def _extract_all_runs(self, input_dir: Path) -> list[ExtractedBinder]:
        """Read summary_all_runs.csv and return the best sequence per run."""
        csv_path = self._find_csv(input_dir, _ALL_RUNS_CSV)
        if csv_path is None:
            warnings.warn(f"Protein-Hunter: no {_ALL_RUNS_CSV} found in {input_dir}.")
            return []

        df = pd.read_csv(csv_path)
        seq_col = "best_seq" if "best_seq" in df.columns else "sequence"
        if seq_col not in df.columns:
            raise ValueError(
                f"Protein-Hunter CSV {csv_path} missing 'best_seq' or 'sequence' column. "
                f"Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []
        for idx, row in df.iterrows():
            seq = str(row[seq_col]).strip().upper()
            if not self._validate_sequence(seq):
                continue
            results.append(
                ExtractedBinder(
                    binder_id=self._make_id(row, int(idx)),
                    sequence=seq,
                    source_tool="protein_hunter",
                    native=NativeMetrics(),
                )
            )
        return results

    def _find_csv(self, input_dir: Path, name: str) -> Path | None:
        direct = input_dir / name
        if direct.exists():
            return direct
        matches = list(input_dir.rglob(name))
        return matches[0] if matches else None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        run_id = row.get("run_id")
        cycle = row.get("cycle")
        if pd.notna(run_id) and pd.notna(cycle):
            return f"protein_hunter_{run_id}_c{int(cycle)}"
        if pd.notna(run_id):
            return f"protein_hunter_{run_id}"
        return f"protein_hunter_{fallback_idx}"
