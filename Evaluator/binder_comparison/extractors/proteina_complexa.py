"""Proteina-Complexa sequence extractor.

Handles two output layouts:

1. **Configurator-aggregated** — `sequences.csv` produced by the BindMaster
   run script's collector. Columns include a string ``sequence``,
   ``self_complex_i_pTM`` / ``_i_pAE`` / ``_pLDDT``, ``self_binder_scRMSD``,
   and (when reward models were active) ``af2_reward`` / ``rf3_reward``.

2. **NVIDIA native output** — `top_samples_search_binder_local_pipeline.csv`
   (or any ``top_samples_*.csv``). This is what the upstream Proteina-Complexa
   pipeline writes directly. It has:
   - ``aatype``: comma-separated integers 0–19 in the canonical AF2 RESTYPES
     order (A R N D C Q E G H I L K M F P S T W Y V). The decoder produces
     a one-letter AA string from it.
   - ``total_reward``: scalar reward used by the search; we expose as
     ``complexa_af2_reward`` (renaming is informational only — for MCTS or
     beam-search runs the reward composition may differ).
   - ``af2folding_plddt`` / ``af2folding_pae`` / ``af2folding_i_pae`` /
     ``af2folding_i_ptm_log`` / ``af2folding_rmsd``: per-sample scores from
     the AF2-folding reward block. These are reward-shaped (often
     normalised or log-transformed), NOT raw pLDDT / PAE values; they're
     still useful for ranking within a single run but should not be
     compared directly to other engines' raw values.
   - ``pdb_path`` and ``metadata_tag``: used to derive a stable binder_id.

The legacy column names (``self_complex_*``) are preserved as the first
candidate in the multi-alias map below so configurator-aggregated CSVs keep
working.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor

# Try the configurator-aggregated form first, then the NVIDIA native output.
_CSV_CANDIDATES = [
    "sequences.csv",
]
_NATIVE_CSV_GLOB = "top_samples_*.csv"

_SEQUENCE_COL = "sequence"
_AATYPE_COL = "aatype"

# Canonical AF2 / Proteina residue order. Index = aatype int, value = one-letter.
_RESTYPES = "ARNDCQEGHILKMFPSTWYV"

# Each schema field maps to a tuple of candidate CSV column names. First match
# wins. The legacy "self_complex_*" / "self_binder_*" / "af2_reward" /
# "rf3_reward" columns come from configurator-aggregated CSVs; the
# "af2folding_*" / "total_reward" columns come from NVIDIA's native
# top_samples_*.csv. Where the column is genuinely missing in a variant, the
# field stays None — same behavior as the other extractors.
_NATIVE_COL_MAP: dict[str, tuple[str, ...]] = {
    "complexa_self_iptm": ("self_complex_i_pTM", "af2folding_i_ptm_log"),
    "complexa_self_ipae": ("self_complex_i_pAE", "af2folding_i_pae"),
    "complexa_self_plddt": ("self_complex_pLDDT", "af2folding_plddt"),
    "complexa_self_scrmsd": ("self_binder_scRMSD", "af2folding_rmsd"),
    "complexa_af2_reward": ("af2_reward", "total_reward"),
    "complexa_rf3_reward": ("rf3_reward",),
}


def _safe_float(val) -> float | None:
    if pd.isna(val) or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _decode_aatype(aatype_str: str) -> str | None:
    """Decode a comma-separated string of aatype integers to a one-letter
    sequence. Returns None on malformed input.
    """
    if not isinstance(aatype_str, str) or not aatype_str.strip():
        return None
    try:
        chars = []
        for tok in aatype_str.split(","):
            i = int(tok.strip())
            if 0 <= i < len(_RESTYPES):
                chars.append(_RESTYPES[i])
            else:
                return None
        return "".join(chars) if chars else None
    except (TypeError, ValueError):
        return None


class ProteinaComplexaExtractor(SequenceExtractor):
    """Extract binder sequences from Proteina-Complexa outputs."""

    @property
    def tool_name(self) -> str:
        return "proteina_complexa"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_path = self._find_csv(input_dir)
        if csv_path is None:
            warnings.warn(
                f"Proteina-Complexa: no CSV found in {input_dir}. Looked for {_CSV_CANDIDATES} and {_NATIVE_CSV_GLOB}."
            )
            return []

        df = pd.read_csv(csv_path)
        if df.empty:
            return []

        # Decide which sequence source this CSV uses.
        if _SEQUENCE_COL in df.columns:
            seq_source = "sequence_col"
        elif _AATYPE_COL in df.columns:
            seq_source = "aatype"
        else:
            raise ValueError(
                f"Proteina-Complexa CSV {csv_path} has neither '{_SEQUENCE_COL}' "
                f"nor '{_AATYPE_COL}' column. Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []
        n_decode_fail = 0

        for idx, row in df.iterrows():
            if seq_source == "sequence_col":
                seq = str(row[_SEQUENCE_COL]).strip().upper()
            else:
                decoded = _decode_aatype(row.get(_AATYPE_COL))
                if decoded is None:
                    n_decode_fail += 1
                    continue
                seq = decoded

            if not self._validate_sequence(seq):
                warnings.warn(f"Proteina-Complexa row {idx}: invalid sequence — skipping")
                continue

            binder_id = self._make_id(row, idx)
            native = self._extract_native(row)

            results.append(
                ExtractedBinder(
                    binder_id=binder_id,
                    sequence=seq,
                    source_tool="proteina_complexa",
                    native=native,
                )
            )

        if n_decode_fail:
            warnings.warn(f"Proteina-Complexa: failed to decode aatype for {n_decode_fail} row(s)")
        return results

    def _extract_native(self, row: pd.Series) -> NativeMetrics:
        def _get(candidates: tuple[str, ...]) -> float | None:
            # First column that's present wins. Absent columns stay None.
            for col in candidates:
                if col in row.index:
                    return _safe_float(row.get(col))
            return None

        return NativeMetrics(
            complexa_self_iptm=_get(_NATIVE_COL_MAP["complexa_self_iptm"]),
            complexa_self_ipae=_get(_NATIVE_COL_MAP["complexa_self_ipae"]),
            complexa_self_plddt=_get(_NATIVE_COL_MAP["complexa_self_plddt"]),
            complexa_self_scrmsd=_get(_NATIVE_COL_MAP["complexa_self_scrmsd"]),
            complexa_af2_reward=_get(_NATIVE_COL_MAP["complexa_af2_reward"]),
            complexa_rf3_reward=_get(_NATIVE_COL_MAP["complexa_rf3_reward"]),
        )

    def _find_csv(self, input_dir: Path) -> Path | None:
        # 1. Configurator-aggregated sequences.csv (top-level then recursive)
        for name in _CSV_CANDIDATES:
            candidate = input_dir / name
            if candidate.exists():
                return candidate
        for name in _CSV_CANDIDATES:
            matches = list(input_dir.rglob(name))
            if matches:
                return matches[0]

        # 2. NVIDIA native top_samples_*.csv (top-level then recursive)
        native_top = list(input_dir.glob(_NATIVE_CSV_GLOB))
        if native_top:
            return native_top[0]
        native_recursive = list(input_dir.rglob(_NATIVE_CSV_GLOB))
        if native_recursive:
            return native_recursive[0]

        # 3. Last resort: any CSV under evaluation_results/
        eval_dir = input_dir / "evaluation_results"
        if eval_dir.exists():
            csvs = list(eval_dir.rglob("*.csv"))
            if csvs:
                return csvs[0]
        return None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        # Configurator-aggregated CSV: prefer explicit ID columns.
        if "design_id" in row.index and pd.notna(row["design_id"]):
            did = str(row["design_id"])
            return did if did.startswith("complexa_") else f"complexa_{did}"
        if "name" in row.index and pd.notna(row["name"]):
            return f"complexa_{row['name']}"
        # NVIDIA native: derive from metadata_tag or pdb_path.
        if "metadata_tag" in row.index and pd.notna(row["metadata_tag"]):
            return f"complexa_{row['metadata_tag']}"
        if "pdb_path" in row.index and pd.notna(row["pdb_path"]):
            stem = Path(str(row["pdb_path"])).stem
            return f"complexa_{stem}"
        return f"complexa_{fallback_idx}"
