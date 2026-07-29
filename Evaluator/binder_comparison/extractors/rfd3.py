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

Structural QC metrics — ``n_chainbreaks``, ``n_clashing`` (sum of side-chain
and backbone interresidue clashes), ``helix_fraction`` — are NOT in the CSV.
They live in per-design JSON sidecars under ``<csv_dir>/diffusion/`` named
``binder_spec_<design_id_without_rfd3_prefix>.json``. The CSV value (if any)
wins; otherwise we fall back to the JSON sidecar — that mirrors how foundry
versions sometimes start emitting fields directly in the CSV.
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path

import pandas as pd

from ..core.schema import ExtractedBinder, NativeMetrics
from .base import SequenceExtractor, disambiguate_ids, resolve_single_match

_CSV_CANDIDATES = ["sequences.csv", "results.csv", "designs.csv", "rfd3_designs.csv", "summary.csv"]
_SEQUENCE_COLS = ("sequence", "Sequence", "designed_sequence", "binder_sequence")

_NATIVE_COL_MAP = {
    "rfd3_n_chainbreaks": ("n_chainbreaks",),
    "rfd3_n_clashing": ("n_clashing",),
    "rfd3_helix_fraction": ("helix_fraction",),
    "rfd3_sequence_recovery": ("sequence_recovery", "mpnn_sequence_recovery"),
}

# Per-design JSON sidecars live under <csv_dir>/diffusion/.
# Longest sequence the FASTA fallback will accept as a binder. Above this it is almost
# certainly mpnn's full chain (target prefix + designed binder) rather than a binder —
# the configurator's own binder-length ceiling is 500 aa (validate_int max_val), and
# real designs in this pipeline run 60-150 aa.
_MAX_PLAUSIBLE_BINDER_LEN = 500

# A prefix this long shared by every FASTA sequence is the target, not a motif.
_MIN_SHARED_TARGET_PREFIX = 20

_SIDECAR_SUBDIR = "diffusion"
# Within each sidecar JSON, the structural QC metrics live under data["metrics"].
# The two n_clashing sub-keys use dot notation in the JSON ("n_clashing.x")
# rather than nested dicts, so we look them up as flat strings.
_SIDECAR_CLASH_SC = "n_clashing.interresidue_clashes_w_sidechain"
_SIDECAR_CLASH_BB = "n_clashing.interresidue_clashes_w_backbone"


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
            disambiguate_ids(csv_results, tool="RFD3")
            return csv_results
        fasta_results = self._extract_from_fasta(input_dir)
        if fasta_results:
            disambiguate_ids(fasta_results, tool="RFD3")
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
            sidecar = self._read_sidecar(csv_path, row)
            results.append(
                ExtractedBinder(
                    binder_id=self._make_id(row, int(idx)),
                    sequence=seq,
                    source_tool="rfd3",
                    native=self._extract_native(row, sidecar),
                )
            )
        return results

    def _read_sidecar(self, csv_path: Path, row: pd.Series) -> dict:
        """Read the per-design JSON sidecar's `metrics` block.

        The CSV's `design_id` column looks like
        ``rfd3_binder_spec_<name>_<idx>_model_<m>``; the matching JSON is
        ``<csv_dir>/diffusion/binder_spec_<name>_<idx>_model_<m>.json``.
        Returns ``{}`` when no sidecar is available so callers can treat
        missing-fields uniformly.
        """
        design_id = str(row.get("design_id", "")) if "design_id" in row.index else ""
        if not design_id:
            return {}
        stem = design_id.removeprefix("rfd3_")
        candidate = csv_path.parent / _SIDECAR_SUBDIR / f"{stem}.json"
        if not candidate.exists():
            # Be tolerant of layout drift — fall back to a recursive search.
            hits = list(csv_path.parent.rglob(f"{stem}.json"))
            if not hits:
                return {}
            candidate = hits[0]
        try:
            data = json.loads(candidate.read_text())
            return data.get("metrics", {}) or {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _extract_native(self, row: pd.Series, sidecar: dict | None = None) -> NativeMetrics:
        sidecar = sidecar or {}

        def _from_csv(candidates: tuple[str, ...]):
            # Each schema field maps to a tuple of alternative CSV column names.
            # First match wins; absent columns return None.
            for col in candidates:
                if col in row.index:
                    return row.get(col)
            return None

        # CSV wins when present (some foundry versions emit these directly);
        # otherwise fall back to the JSON sidecar.
        chainbreaks_csv = _from_csv(_NATIVE_COL_MAP["rfd3_n_chainbreaks"])
        chainbreaks = chainbreaks_csv if chainbreaks_csv is not None else sidecar.get("n_chainbreaks")

        clashing_csv = _from_csv(_NATIVE_COL_MAP["rfd3_n_clashing"])
        if clashing_csv is not None:
            clashing = clashing_csv
        else:
            sc = sidecar.get(_SIDECAR_CLASH_SC)
            bb = sidecar.get(_SIDECAR_CLASH_BB)
            clashing = None if (sc is None and bb is None) else (sc or 0) + (bb or 0)

        helix_csv = _from_csv(_NATIVE_COL_MAP["rfd3_helix_fraction"])
        helix = helix_csv if helix_csv is not None else sidecar.get("helix_fraction")

        return NativeMetrics(
            rfd3_n_chainbreaks=_safe_int(chainbreaks),
            rfd3_n_clashing=_safe_int(clashing),
            rfd3_helix_fraction=_safe_float(helix),
            rfd3_sequence_recovery=_safe_float(_from_csv(_NATIVE_COL_MAP["rfd3_sequence_recovery"])),
        )

    def _extract_from_fasta(self, input_dir: Path) -> list[ExtractedBinder]:
        """Fallback for a manual foundry workflow that left no aggregated CSV.

        DANGER, and why the length guard below exists: `mpnn` writes the FULL chain —
        the preserved target prefix followed by the designed binder. CLAUDE.md's own
        RFD3 gotcha list says you must "strip the target prefix (first len(target_seq)
        chars)". This code path has no target sequence to strip with, so an unguarded
        pass-through would hand the refold engines a target+binder concatenation
        labelled as a binder, and every iPTM computed for it would be meaningless.

        Refusing implausible lengths is the honest option: the aggregated
        `sequences.csv` that `run_rfd3.sh` produces already carries stripped binders,
        so anyone hitting this path can generate it instead.

        The length ceiling alone does not detect this. It is calibrated on the
        configurator's binder-length cap, not on target+binder length, so it only
        fires when the TARGET alone exceeds ~360 aa: on the shipped CALCA run it
        rejected 0 of 8000 sequences that all carried the same 32-aa target prefix.
        What does detect it is the prefix itself — every mpnn sequence for one
        target starts with the same residues — so a long shared prefix across
        designs refuses the whole pool.
        """
        from ..io.read import read_fasta

        fastas = list(input_dir.rglob("*.fasta")) + list(input_dir.rglob("*.fa"))
        if not fastas:
            return []

        entries_by_file = []
        for fp in fastas:
            try:
                entries_by_file.append((fp, read_fasta(fp)))
            except Exception:
                continue

        seqs = [s.strip().upper() for _, entries in entries_by_file for _, s in entries]
        seqs = [s for s in seqs if self._validate_sequence(s)]
        shared = os.path.commonprefix(seqs) if len(seqs) >= 2 else ""
        if _MIN_SHARED_TARGET_PREFIX <= len(shared) < min((len(s) for s in seqs), default=0):
            warnings.warn(
                f"RFD3: all {len(seqs)} FASTA sequences under {input_dir} share a "
                f"{len(shared)}-residue prefix — this is mpnn's full chain (target prefix + "
                f"binder), not a binder, and refolding it would produce meaningless iPTM. "
                f"Extracting nothing. Generate the aggregated sequences.csv (run_rfd3.sh does "
                f"this) so the target prefix is stripped properly."
            )
            return []

        results: list[ExtractedBinder] = []
        n_rejected = 0
        for fp, entries in entries_by_file:
            for idx, (header, seq) in enumerate(entries):
                seq = seq.strip().upper()
                if not self._validate_sequence(seq):
                    continue
                if len(seq) > _MAX_PLAUSIBLE_BINDER_LEN:
                    n_rejected += 1
                    continue
                # mpnn writes ">name, sequence_recovery=0.45" — the comma sticks to
                # the name token and would otherwise ride into every binder_id join.
                binder_id = header.split()[0].rstrip(",") if header else f"rfd3_{fp.stem}_{idx}"
                results.append(
                    ExtractedBinder(
                        binder_id=f"rfd3_{binder_id}",
                        sequence=seq,
                        source_tool="rfd3",
                        native=NativeMetrics(),
                    )
                )
        if n_rejected:
            warnings.warn(
                f"RFD3: skipped {n_rejected} FASTA sequence(s) longer than "
                f"{_MAX_PLAUSIBLE_BINDER_LEN} aa — these look like mpnn's full chain "
                f"(target prefix + binder), not a binder. Refolding them would produce "
                f"meaningless iPTM. Generate the aggregated sequences.csv (run_rfd3.sh "
                f"does this) so the target prefix is stripped properly."
            )
        return results

    def _find_csv(self, input_dir: Path) -> Path | None:
        for name in _CSV_CANDIDATES:
            direct = input_dir / name
            if direct.exists():
                return direct
        for name in _CSV_CANDIDATES:
            hits = sorted(input_dir.rglob(name))
            if hits:
                return resolve_single_match(hits, tool="RFD3", what=name, input_dir=input_dir)
        return None

    def _make_id(self, row: pd.Series, fallback_idx: int) -> str:
        for key in ("design_id", "name", "run_id", "trajectory", "id"):
            if key in row.index and pd.notna(row[key]):
                return f"rfd3_{row[key]}"
        return f"rfd3_{fallback_idx}"
