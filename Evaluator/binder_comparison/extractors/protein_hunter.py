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

Note: Protein-Hunter has no PyRosetta interface metrics. NativeMetrics is
      populated with the per-row Boltz-2 design-time values from the CSV
      (iptm / best_iptm / plddt / sequence_recovery). Cross-validation
      metrics still come from the standardised refolding pipeline
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

# schema field name → Protein-Hunter CSV column name.
# Column availability differs between the two summary CSVs:
#   summary_high_iptm.csv → iptm, plddt (per row); no best_*
#   summary_all_runs.csv  → best_iptm, best_plddt (per run); no per-cycle iptm/plddt
# In _extract_high_iptm we merge best_iptm + best_plddt from all_runs by run_id
# so a single row carries both the per-cycle and the run-level aggregates.
# `sequence_recovery` is not emitted by Protein-Hunter — kept here for schema
# symmetry; will always resolve to None.
_NATIVE_COL_MAP = {
    "protein_hunter_iptm_cycle": "iptm",
    "protein_hunter_iptm_best": "best_iptm",
    "protein_hunter_plddt": "plddt",
    "protein_hunter_plddt_best": "best_plddt",
    "protein_hunter_sequence_recovery": "sequence_recovery",
}


def _safe_float(val) -> float | None:
    if pd.isna(val) or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


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

        # Optionally enrich per-cycle rows with the run-level best_iptm /
        # best_plddt from summary_all_runs.csv (joined by run_id). Falls
        # through silently if all_runs.csv is missing — the schema fields
        # just stay None.
        all_runs_path = csv_path.parent / _ALL_RUNS_CSV
        if all_runs_path.exists() and "run_id" in df.columns:
            try:
                all_runs = pd.read_csv(all_runs_path)
            except (OSError, pd.errors.ParserError) as exc:
                warnings.warn(f"Protein-Hunter: could not read {all_runs_path.name}: {exc}")
            else:
                if "run_id" in all_runs.columns:
                    merge_cols = [c for c in ("run_id", "best_iptm", "best_plddt") if c in all_runs.columns]
                    if len(merge_cols) > 1:
                        df = df.merge(all_runs[merge_cols], on="run_id", how="left")

        results: list[ExtractedBinder] = []
        for idx, row in df.iterrows():
            if pd.isna(row["sequence"]):
                continue
            seq = str(row["sequence"]).strip().upper()
            if not self._validate_sequence(seq):
                warnings.warn(f"Protein-Hunter row {idx}: invalid sequence — skipping")
                continue
            results.append(
                ExtractedBinder(
                    binder_id=self._make_id(row, int(idx)),
                    sequence=seq,
                    source_tool="protein_hunter",
                    native=self._extract_native(row),
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
            # Empty best_seq means "No structure was generated for run N (no
            # eligible best design)" — pandas reads it as NaN; without this
            # guard, str(NaN).upper() yields "NAN", which slips past the
            # amino-acid validator (N, A, N are all valid residues).
            if pd.isna(row[seq_col]):
                continue
            seq = str(row[seq_col]).strip().upper()
            if not self._validate_sequence(seq):
                continue
            results.append(
                ExtractedBinder(
                    binder_id=self._make_id(row, int(idx)),
                    sequence=seq,
                    source_tool="protein_hunter",
                    native=self._extract_native(row),
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

    def _extract_native(self, row: pd.Series) -> NativeMetrics:
        """Populate NativeMetrics from per-row Protein-Hunter CSV columns.

        Defensive: `row.get(col)` returns None when the column is absent (which
        differs between summary_high_iptm.csv and summary_all_runs.csv), and
        _safe_float passes None through as None.
        """
        return NativeMetrics(
            protein_hunter_iptm_cycle=_safe_float(row.get(_NATIVE_COL_MAP["protein_hunter_iptm_cycle"])),
            protein_hunter_iptm_best=_safe_float(row.get(_NATIVE_COL_MAP["protein_hunter_iptm_best"])),
            protein_hunter_plddt=_safe_float(row.get(_NATIVE_COL_MAP["protein_hunter_plddt"])),
            protein_hunter_plddt_best=_safe_float(row.get(_NATIVE_COL_MAP["protein_hunter_plddt_best"])),
            protein_hunter_sequence_recovery=_safe_float(row.get(_NATIVE_COL_MAP["protein_hunter_sequence_recovery"])),
        )
