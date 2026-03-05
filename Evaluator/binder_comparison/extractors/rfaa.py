"""RFAA sequence extractor.

Reads sequences from the RFAA+LigandMPNN combined pipeline output.
Expected input: directory containing sequences.csv (produced by run_rfaa.sh).

If sequences.csv is not found, falls back to listing backbone PDBs
(with empty sequences and a warning).
"""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

from ..core.schema import ExtractedBinder
from .base import SequenceExtractor


class RFAAExtractor(SequenceExtractor):
    """Extract binder sequences from RFAA + LigandMPNN output."""

    @property
    def tool_name(self) -> str:
        return "rfaa"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        csv_path = self._find_csv(input_dir)
        if csv_path is not None:
            return self._from_csv(csv_path)
        return self._from_backbone_pdbs(input_dir)

    def _find_csv(self, input_dir: Path) -> Path | None:
        """Look for sequences.csv in the RFAA output directory."""
        candidate = input_dir / "sequences.csv"
        if candidate.exists():
            return candidate
        candidate = input_dir.parent / "sequences.csv"
        if candidate.exists():
            return candidate
        return None

    def _from_csv(self, csv_path: Path) -> list[ExtractedBinder]:
        """Parse LigandMPNN sequences.csv output."""
        results: list[ExtractedBinder] = []
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                seq = row.get("sequence", "").strip().upper()
                if not self._validate_sequence(seq):
                    continue
                design_id = row.get("design_id", f"rfaa_{idx}")
                results.append(
                    ExtractedBinder(
                        binder_id=design_id,
                        sequence=seq,
                        source_tool="rfaa",
                    )
                )
        return results

    def _from_backbone_pdbs(self, input_dir: Path) -> list[ExtractedBinder]:
        """Fallback: list backbone PDBs with empty sequences."""
        outputs_dir = input_dir / "outputs" if (input_dir / "outputs").is_dir() else input_dir
        pdb_files = sorted(outputs_dir.glob("*.pdb"))
        if not pdb_files:
            return []
        warnings.warn(
            f"RFAA: {len(pdb_files)} backbone PDB(s) found but no sequences.csv. "
            "Run LigandMPNN to design sequences before evaluation."
        )
        results: list[ExtractedBinder] = []
        for pdb_path in pdb_files:
            results.append(
                ExtractedBinder(
                    binder_id=f"rfaa_{pdb_path.stem}",
                    sequence="",
                    source_tool="rfaa",
                )
            )
        return results
