"""Abstract base class for sequence extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..core.schema import ExtractedBinder


class SequenceExtractor(ABC):
    """Pull binder sequences (and tool-native supplementary metrics) from a tool's output."""

    @abstractmethod
    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        """Extract all binders from *input_dir*.

        Args:
            input_dir: Root directory of the tool's output.

        Returns:
            List of ExtractedBinder objects, one per unique sequence.
        """

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Short name for this tool (e.g. 'bindcraft')."""

    def _validate_sequence(self, seq: str) -> bool:
        """Return True if *seq* is a non-empty string of standard amino acids."""
        valid = set("ACDEFGHIKLMNPQRSTVWY")
        return bool(seq) and all(c in valid for c in seq.upper())
