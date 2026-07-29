"""Proteina-Complexa sequence extractor.

Handles two output layouts:

1. **Configurator-aggregated** — `sequences.csv` produced by the BindMaster
   run script's collector. Columns include a string ``sequence`` and a
   ``design_id``. The collector **renames** the raw evaluation metrics on the
   way out: ``self_complex_i_pTM`` → ``iptm``, ``self_complex_pLDDT`` →
   ``plddt_binder_mean``, ``self_complex_i_pAE`` → ``pae_bt_mean``,
   ``self_binder_scRMSD`` → ``scrmsd_binder`` (same mapping the legacy
   evaluator's ``_normalize_complexa_row`` applies). Both spellings are
   accepted below — older aggregated CSVs and hand-assembled ones still carry
   the raw ``self_*`` names, and (when reward models were active)
   ``af2_reward`` / ``rf3_reward``.

2. **NVIDIA native output** — `top_samples_search_binder_local_pipeline.csv`
   (or any ``top_samples_*.csv``). This is what the upstream Proteina-Complexa
   pipeline writes directly. It has:
   - ``aatype``: comma-separated integers 0–19 in the canonical AF2 RESTYPES
     order (A R N D C Q E G H I L K M F P S T W Y V). The decoder produces
     a one-letter AA string from it.
   - ``total_reward``: scalar reward used by the search; we expose as
     ``complexa_af2_reward`` (renaming is informational only — for MCTS or
     beam-search runs the reward composition may differ).
   - ``af2folding_*`` columns: per-sample AF2-folding scores. The ``_log``
     suffix is a naming convention from NVIDIA's logging pipeline ("this
     value is logged to output"), NOT log-transformation. For most metrics
     the ``_log`` and non-``_log`` columns are byte-identical raw values.
     The exception is ``af2folding_plddt`` vs ``af2folding_plddt_log``:
     the non-``_log`` is reward-shaped (≈ ``1 - plddt``) while the
     ``_log`` version is the raw pLDDT in [0, 1]. We therefore prefer
     ``_log`` candidates everywhere so the schema always carries the raw
     value. (Same reasoning applies to ``af2folding_i_ptm_log`` — only the
     ``_log`` column is written for that metric.)
   - ``pdb_path`` and ``metadata_tag``: used to derive a stable binder_id.

The legacy column names (``self_complex_*``) are preserved as the first
candidate in the multi-alias map below so configurator-aggregated CSVs keep
working.
"""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor, disambiguate_ids, resolve_single_match

# Try the configurator-aggregated form first, then the NVIDIA native output.
_CSV_CANDIDATES = [
    "sequences.csv",
]
_NATIVE_CSV_GLOB = "top_samples_*.csv"

# Binder-only sequence columns, in preference order. "sequence" is what the
# configurator's collector writes; "binder_sequence" (RAW_protein_binder_results_*)
# and "self_sequence" (binder_results_*) are PC's OWN evaluation columns, which
# carry the binder verbatim — no decode, no arithmetic, no target to strip.
_SEQUENCE_COL_CANDIDATES = ("sequence", "binder_sequence", "self_sequence")
_AATYPE_COL = "aatype"
_PDB_PATH_COL = "pdb_path"

# NVIDIA names each job directory ``job_<i>_n_<N>_id_<j>_...`` where N is
# len(target) + len(binder) — the exact end of the binder, before the padding.
# Verified against PC's own evaluation CSVs on 1100/1100 designs across two runs.
_JOB_LEN_RE = re.compile(r"_n_(\d+)_")

# ``metadata_tag`` has no seed in it, so it collides across replicates. The
# replicate directory name is the only thing that separates them.
_SEED_RE = re.compile(r"seed[_-](\d+)")

# A shared prefix shorter than this is not evidence of a target — real binders
# from one MCTS run can share a short motif.
_MIN_INFERRED_TARGET_LEN = 20

# Fallback boundary when the job name carries no ``_n_<N>_`` (PC-v3's pdb_path is
# a bare filename): strip a trailing poly-alanine run this long or longer. The
# longest genuine C-terminal alanine run in a clean pool on disk is 7, and the
# pads measured on PC-v3 reach 42, so the threshold sits between them.
_PAD_MIN_RUN = 10

# Canonical AF2 / Proteina residue order. Index = aatype int, value = one-letter.
_RESTYPES = "ARNDCQEGHILKMFPSTWYV"

# Each schema field maps to a tuple of candidate CSV column names. First match
# wins. The raw "self_complex_*" / "self_binder_*" / "af2_reward" /
# "rf3_reward" names come from Proteina-Complexa's evaluation CSVs; the
# "af2folding_*" / "total_reward" columns come from NVIDIA's native
# top_samples_*.csv; the generic "iptm" / "plddt_binder_mean" / "pae_bt_mean" /
# "scrmsd_binder" names are what the configurator's collector writes into the
# aggregated sequences.csv (it renames the raw columns — see module docstring).
# The generic names are listed LAST so a CSV carrying both keeps its raw value.
# Where the column is genuinely missing in a variant, the field stays None —
# same behavior as the other extractors.
_NATIVE_COL_MAP: dict[str, tuple[str, ...]] = {
    "complexa_self_iptm": ("self_complex_i_pTM", "af2folding_i_ptm_log", "iptm"),
    "complexa_self_ipae": ("self_complex_i_pAE", "af2folding_i_pae_log", "af2folding_i_pae", "pae_bt_mean"),
    # plddt: prefer the _log column — see module docstring. The non-_log
    # variant is reward-shaped (≈ 1 - plddt) and would mis-rank designs.
    "complexa_self_plddt": ("self_complex_pLDDT", "af2folding_plddt_log", "plddt_binder_mean"),
    "complexa_self_scrmsd": ("self_binder_scRMSD", "af2folding_rmsd_log", "af2folding_rmsd", "scrmsd_binder"),
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
    """Extract binder sequences from Proteina-Complexa outputs.

    Args:
        target_sequence: The target chain the designs were made against. Only the
            ``aatype`` path needs it — that column encodes the whole complex, so
            without the target there is no principled place to cut. Passed through
            from ``binder-compare extract --target-seq``.
        aggregate_replicates: Treat every matching ``top_samples_*.csv`` under
            *input_dir* as one pool. PC's MCTS runs write one per replicate seed,
            and 50 of them are a single campaign — but a mis-pointed parent
            directory is not, so this is opt-in and the default refuses to guess.
    """

    def __init__(self, target_sequence: str | None = None, aggregate_replicates: bool = False):
        self.target_sequence = target_sequence.strip().upper() if target_sequence else None
        self.aggregate_replicates = aggregate_replicates

    @property
    def tool_name(self) -> str:
        return "proteina_complexa"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_paths = self._find_csvs(input_dir)
        if not csv_paths:
            warnings.warn(
                f"Proteina-Complexa: no CSV found in {input_dir}. Looked for {_CSV_CANDIDATES} and {_NATIVE_CSV_GLOB}."
            )
            return []

        frames = []
        for path in csv_paths:
            frame = pd.read_csv(path)
            if frame.empty:
                continue
            frame["__source_csv"] = str(path)
            frames.append(frame)
        if not frames:
            return []
        df = pd.concat(frames, ignore_index=True)
        if len(csv_paths) > 1:
            print(f"[extract] Proteina-Complexa: aggregated {len(csv_paths)} replicate CSVs → {len(df)} rows")

        # Decide which sequence source this CSV uses. Dispatch on the COLUMNS, not
        # on which _find_csvs branch matched — a file named sequences.csv can carry
        # aatype, and an evaluation CSV carries binder_sequence.
        seq_col = next((c for c in _SEQUENCE_COL_CANDIDATES if c in df.columns), None)
        if seq_col is not None:
            sequences: list[str | None] = [str(v).strip().upper() for v in df[seq_col]]
        elif _AATYPE_COL in df.columns:
            sequences = self._binders_from_aatype(df)
        else:
            raise ValueError(
                f"Proteina-Complexa CSV {csv_paths[0]} has none of {_SEQUENCE_COL_CANDIDATES} "
                f"nor '{_AATYPE_COL}'. Available: {list(df.columns[:10])}"
            )

        results: list[ExtractedBinder] = []
        n_decode_fail = 0

        for (idx, row), seq in zip(df.iterrows(), sequences, strict=True):
            if seq is None:
                n_decode_fail += 1
                continue

            if not self._validate_sequence(seq):
                warnings.warn(f"Proteina-Complexa row {idx}: invalid sequence — skipping")
                continue

            results.append(
                ExtractedBinder(
                    binder_id=self._make_id(row, idx),
                    sequence=seq,
                    source_tool="proteina_complexa",
                    native=self._extract_native(row),
                )
            )

        if n_decode_fail:
            warnings.warn(f"Proteina-Complexa: failed to decode aatype for {n_decode_fail} row(s)")
        disambiguate_ids(results, tool="Proteina-Complexa")
        return results

    def _binders_from_aatype(self, df: pd.DataFrame) -> list[str | None]:
        """Decode ``aatype`` and cut the binder out of the complex.

        ``aatype`` is the WHOLE COMPLEX: ``target + binder + poly-alanine pad``.
        Measured on three production runs — 2VDY (1000 designs, 500-509 aa against
        a 389-aa target), ApoE4/Clara (100 designs, 298-305 aa against 185 aa) and
        ApoE4-iso PC-v3 (4804/4804 rows carrying the 141-aa target as an exact
        prefix). Refolding that unstripped feeds the engines a target+binder fusion
        against the same target, and every iPTM computed from it is meaningless.
        """
        decoded = [_decode_aatype(v) for v in df[_AATYPE_COL]]
        ok = [d for d in decoded if d]
        prefix_len = 0

        if self.target_sequence:
            if ok and all(d.startswith(self.target_sequence) for d in ok):
                prefix_len = len(self.target_sequence)
            else:
                warnings.warn(
                    f"Proteina-Complexa: the declared target ({len(self.target_sequence)} aa) is "
                    f"not a prefix of the decoded complex — PC's target_input can select a "
                    f"sub-range of the configured chain. Emitting sequences unstripped rather "
                    f"than cutting at the wrong residue."
                )
        elif len(ok) >= 2:
            # Every row of a run embeds the same target, so the pool reveals it.
            lcp = os.path.commonprefix(ok)
            if _MIN_INFERRED_TARGET_LEN <= len(lcp) < min(len(d) for d in ok):
                prefix_len = len(lcp)
                warnings.warn(
                    f"Proteina-Complexa: no --target-seq given; inferred a {len(lcp)}-residue "
                    f"target prefix shared by all {len(ok)} designs and stripped it. Pass "
                    f"--target-seq to make the boundary declared rather than inferred."
                )

        if not prefix_len:
            warnings.warn(
                "Proteina-Complexa: could not resolve the target prefix in the decoded "
                "'aatype' complex — pass --target-seq. Sequences are emitted as decoded, so "
                "they may be target+binder fusions."
            )

        ends = self._binder_ends(df, decoded)
        return [None if d is None else d[prefix_len:end] for d, end in zip(decoded, ends, strict=True)]

    @staticmethod
    def _binder_ends(df: pd.DataFrame, decoded: list[str | None]) -> list[int]:
        """Where the binder stops, before NVIDIA's poly-alanine padding.

        The job-directory name carries ``_n_<N>_`` = len(target) + len(binder),
        exact on 1100/1100 designs checked against PC's own evaluation CSVs. The
        ``aatype`` column itself is padded and the job name is not, so they agree
        on only 26/1000 — the name is the authority.

        Where the name has no length field (PC-v3 writes a bare filename), fall
        back to the trailing alanine run, which is a heuristic and is why the
        declared boundary is preferred wherever it exists.
        """
        paths = df[_PDB_PATH_COL] if _PDB_PATH_COL in df.columns else [None] * len(df)
        ends = []
        for d, p in zip(decoded, paths, strict=True):
            end = len(d) if d else 0
            match = _JOB_LEN_RE.search(str(p)) if p is not None and not pd.isna(p) else None
            if match and 0 < int(match.group(1)) <= end:
                ends.append(int(match.group(1)))
                continue
            if d:
                pad = len(d) - len(d.rstrip("A"))
                if pad >= _PAD_MIN_RUN:
                    end -= pad
            ends.append(end)
        return ends

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

    def _find_csvs(self, input_dir: Path) -> list[Path]:
        # 1. Configurator-aggregated sequences.csv (top-level then recursive). The
        #    top-level hit short-circuits: it is the primary layout, and a stray
        #    nested CSV must not turn a correct run dir into an ambiguity error.
        for name in _CSV_CANDIDATES:
            candidate = input_dir / name
            if candidate.exists():
                return [candidate]
        for name in _CSV_CANDIDATES:
            matches = sorted(input_dir.rglob(name))
            if matches:
                return self._resolve(matches, name, input_dir)

        # 2. NVIDIA native top_samples_*.csv (top-level then recursive)
        native_top = sorted(input_dir.glob(_NATIVE_CSV_GLOB))
        if native_top:
            return self._resolve(native_top, _NATIVE_CSV_GLOB, input_dir)
        native_recursive = sorted(input_dir.rglob(_NATIVE_CSV_GLOB))
        if native_recursive:
            return self._resolve(native_recursive, _NATIVE_CSV_GLOB, input_dir)

        # 3. Last resort: any CSV under evaluation_results/
        eval_dir = input_dir / "evaluation_results"
        if eval_dir.exists():
            csvs = sorted(eval_dir.rglob("*.csv"))
            if csvs:
                return self._resolve(csvs, "evaluation_results/**/*.csv", input_dir)
        return []

    def _resolve(self, matches: list[Path], what: str, input_dir: Path) -> list[Path]:
        if self.aggregate_replicates:
            return matches
        return [resolve_single_match(matches, tool="Proteina-Complexa", what=what, input_dir=input_dir)]

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        # Configurator-aggregated CSV: prefer explicit ID columns.
        if "design_id" in row.index and pd.notna(row["design_id"]):
            did = str(row["design_id"])
            return did if did.startswith("complexa_") else f"complexa_{did}"
        if "name" in row.index and pd.notna(row["name"]):
            return f"complexa_{row['name']}"
        # NVIDIA native: metadata_tag is unique only WITHIN a replicate — it carries
        # no seed — so key it on the replicate directory the row came from.
        seed = _SEED_RE.search(str(row.get("__source_csv", "")))
        prefix = f"complexa_s{seed.group(1)}_" if seed else "complexa_"
        if "metadata_tag" in row.index and pd.notna(row["metadata_tag"]):
            return f"{prefix}{row['metadata_tag']}"
        if "pdb_path" in row.index and pd.notna(row["pdb_path"]):
            return f"{prefix}{Path(str(row['pdb_path'])).stem}"
        return f"{prefix}{fallback_idx}"
