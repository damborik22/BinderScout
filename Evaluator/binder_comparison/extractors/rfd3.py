"""RFD3 (foundry) sequence extractor.

RFD3 (RosettaCommons/foundry, Butcher et al. 2025) is BindMaster's all-atom
diffusion tool. The Hydra-driven `rfd3 design` CLI writes per-trajectory outputs beneath the out_dir,
typically including PDB files and a results manifest.

This extractor is defensive about the exact layout (the foundry output schema
may tighten up in future releases):

  1. Prefer a top-level CSV with a ``sequence`` column (common naming:
     ``results.csv`` / ``designs.csv`` / ``rfd3_designs.csv``).
  2. Fall back to scanning for ``*.pdb`` files alongside ``*.fasta`` sequence
     manifests.
  3. Emit a warning and return ``[]`` when neither pattern matches — this
     lets the caller inform the user without raising.

Sequences designed post-diffusion by RFD3's integrated ``foundry/models/mpnn``
pass (ProteinMPNN / LigandMPNN) live in the same directory.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

_CSV_CANDIDATES = ["sequences.csv", "results.csv", "designs.csv", "rfd3_designs.csv", "summary.csv"]
_SEQUENCE_COLS = ("sequence", "Sequence", "designed_sequence", "binder_sequence")

_NATIVE_COL_MAP = {
    "rfd3_n_chainbreaks": ("n_chainbreaks",),
    "rfd3_n_clashing": ("n_clashing",),
    "rfd3_helix_fraction": ("helix_fraction",),
    "rfd3_sequence_recovery": ("sequence_recovery", "mpnn_sequence_recovery"),
}
# NOTE: chainbreaks / clashing / helix_fraction live in per-design JSON sidecars
# alongside the CSV, not in the CSV itself. Wiring those would require reading
# each design's JSON separately — tracked as a follow-up to the native-metrics
# preservation work (see docs/PLAN_soluprot_integration.md commit history).


def _safe_float(val) -> float | None:
    if pd.isna(val) or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    f = _safe_float(val)
    return None if f is None else int(f)


class RFD3Extractor(SequenceExtractor):
    """Extract binder sequences from an RFD3 / foundry output directory."""

    @property
    def tool_name(self) -> str:
        return "rfd3"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_results = self._extract_from_csv(input_dir)
        if csv_results:
            return csv_results
        fasta_results = self._extract_from_fasta(input_dir)
        if fasta_results:
            return fasta_results
        warnings.warn(f"RFD3: no CSV (tried {_CSV_CANDIDATES}) or *.fasta with sequences found under {input_dir}.")
        return []

    def _extract_from_csv(self, input_dir: Path) -> list[ExtractedBinder]:
        csv_path = self._find_csv(input_dir)
        if csv_path is None:
            return []
        df = pd.read_csv(csv_path)
        seq_col = next((c for c in _SEQUENCE_COLS if c in df.columns), None)
        if seq_col is None:
            warnings.warn(
                f"RFD3 CSV {csv_path} missing sequence column. Tried {_SEQUENCE_COLS}. "
                f"Available: {list(df.columns[:10])}"
            )
            return []

        results: list[ExtractedBinder] = []
        for idx, row in df.iterrows():
            seq = str(row[seq_col]).strip().upper()
            if not self._validate_sequence(seq):
                continue
            results.append(
                ExtractedBinder(
                    binder_id=self._make_id(row, int(idx)),
                    sequence=seq,
                    source_tool="rfd3",
                    native=self._extract_native(row),
                )
            )
        return results

    def _extract_native(self, row: pd.Series) -> NativeMetrics:
        def _get(candidates: tuple[str, ...]):
            # Each schema field maps to a tuple of alternative CSV column names.
            # First match wins; absent columns return None.
            for col in candidates:
                if col in row.index:
                    return row.get(col)
            return None

        return NativeMetrics(
            rfd3_n_chainbreaks=_safe_int(_get(_NATIVE_COL_MAP["rfd3_n_chainbreaks"])),
            rfd3_n_clashing=_safe_int(_get(_NATIVE_COL_MAP["rfd3_n_clashing"])),
            rfd3_helix_fraction=_safe_float(_get(_NATIVE_COL_MAP["rfd3_helix_fraction"])),
            rfd3_sequence_recovery=_safe_float(_get(_NATIVE_COL_MAP["rfd3_sequence_recovery"])),
        )

    def _extract_from_fasta(self, input_dir: Path) -> list[ExtractedBinder]:
        from ..io.read import read_fasta

        fastas = list(input_dir.rglob("*.fasta")) + list(input_dir.rglob("*.fa"))
        if not fastas:
            return []

        results: list[ExtractedBinder] = []
        for fp in fastas:
            try:
                entries = read_fasta(fp)
            except Exception:
                continue
            for idx, (header, seq) in enumerate(entries):
                seq = seq.strip().upper()
                if not self._validate_sequence(seq):
                    continue
                binder_id = header.split()[0] if header else f"rfd3_{fp.stem}_{idx}"
                results.append(
                    ExtractedBinder(
                        binder_id=f"rfd3_{binder_id}",
                        sequence=seq,
                        source_tool="rfd3",
                        native=NativeMetrics(),
                    )
                )
        return results

    def _find_csv(self, input_dir: Path) -> Path | None:
        for name in _CSV_CANDIDATES:
            direct = input_dir / name
            if direct.exists():
                return direct
        for name in _CSV_CANDIDATES:
            hits = list(input_dir.rglob(name))
            if hits:
                return hits[0]
        return None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        for key in ("design_id", "name", "run_id", "trajectory", "id"):
            if key in row.index and pd.notna(row[key]):
                return f"rfd3_{row[key]}"
        return f"rfd3_{fallback_idx}"
