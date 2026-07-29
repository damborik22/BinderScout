"""PXDesign sequence extractor.

PXDesign (protenix-server.com) output files:
  - summary.csv — one row per design, ranked by confidence
  - sequences.csv — the configurator's PXDesign collector aggregates every
    per-length ``filtered_summary.csv`` into this one file

Key columns:
  - 'sequence'   — binder amino acid sequence
  - 'design_id'  — per-design name written by the configurator collector
                   (already ``pxdesign_<name>``-prefixed); 'name' is the
                   equivalent column in PXDesign's own CSVs
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
from .base import SequenceExtractor, disambiguate_ids, resolve_single_match

_CSV_CANDIDATES = [
    "summary.csv",
    "sequences.csv",
]

_SEQUENCE_COL = "sequence"

# Columns carrying a per-design NAME. A name survives a re-sort or a re-run of
# the source CSV, so it is preferred over row position when building binder_id.
# 'design_id' is what the configurator's PXDesign collector writes; 'name' is
# PXDesign's own column in filtered_summary.csv / sample_level_output.csv.
_ID_COL_CANDIDATES = ("design_id", "name")

# Schema field name → PXDesign CSV column name(s). Multiple candidates per field
# tolerate the column-name drift PXDesign has between releases (e.g. af2_ipae
# vs. af2_ipAE — different versions, different casing).
_NATIVE_COL_MAP = {
    "pxdesign_composite_score": ("composite_score",),
    "pxdesign_af2_iptm": ("af2_iptm",),
    "pxdesign_af2_ipae": ("af2_ipae", "af2_ipAE"),
    "pxdesign_protenix_iptm": ("ptx_iptm",),
    "pxdesign_sequence_recovery": ("sequence_recovery",),
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
        self._n_positional_ids = 0

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

        if self._n_positional_ids:
            warnings.warn(
                f"PXDesign: {self._n_positional_ids} of {len(results)} design(s) in {csv_path} carry no "
                f"design_id/name/rank column, so their binder_id is the ROW POSITION "
                f"(pxdesign_0, pxdesign_1, …). Those ids change if the CSV is re-sorted or the "
                f"run is repeated, and cannot be grepped back to the source CSV.",
                stacklevel=2,
            )
        disambiguate_ids(results, tool="PXDesign")
        return results

    def _extract_native(self, row: pd.Series) -> NativeMetrics:
        values: dict[str, float | None] = {}
        for schema_field, csv_cols in _NATIVE_COL_MAP.items():
            # Try each candidate column name; first match wins.
            picked = None
            for csv_col in csv_cols:
                if csv_col in row.index:
                    picked = csv_col
                    break
            if picked is not None:
                values[schema_field] = _safe_float(row[picked])
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
            matches = sorted(input_dir.rglob(name))
            if matches:
                return resolve_single_match(matches, tool="PXDesign", what=name, input_dir=input_dir)
        return None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        """Build a binder_id, preferring keys that survive a re-sort of the CSV.

        Order: ``design_id`` / ``name`` (per-design names) → ``task_name``+``rank``
        → ``rank`` → row position. Row position is the LAST RESORT only: it
        renames every design when the source CSV is re-sorted or the run is
        repeated, and binder_id is the label the report, the
        ``*_native_metrics.csv`` sidecar and ``add_design_groups`` carry for the
        rest of the pipeline. ``extract`` warns once when it fires.
        """
        for col in _ID_COL_CANDIDATES:
            if col in row.index and pd.notna(row[col]):
                val = str(row[col]).strip()
                if val:
                    # The collector already prefixes design_id with "pxdesign_";
                    # keep it verbatim so the id greps back to the source CSV.
                    return val if val.startswith("pxdesign_") else f"pxdesign_{val}"
        has_task = "task_name" in row.index and pd.notna(row["task_name"])
        has_rank = "rank" in row.index and pd.notna(row["rank"])
        if has_task and has_rank:
            return f"pxdesign_{row['task_name']}_{int(row['rank'])}"
        if has_rank:
            return f"pxdesign_{int(row['rank'])}"
        self._n_positional_ids += 1
        return f"pxdesign_{fallback_idx}"
