"""Abstract base class for sequence extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..comparison.tool_classification import DEFAULT_EXTRACTOR_METADATA, ExtractorMetadata
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

    def extractor_metadata(self) -> ExtractorMetadata:
        """Per-run metadata for the report's fairness banner (Item 3).

        Subclasses override to declare a pre-filtered source CSV (e.g.
        Protein-Hunter's ``summary_high_iptm.csv``). The default conservatively
        reports an unfiltered, source-CSV-unknown pool — safe for tools that
        always read their full output. Static framing (modality, native-metric
        interpretation) lives in :mod:`..comparison.tool_classification`.
        """
        return DEFAULT_EXTRACTOR_METADATA

    def _validate_sequence(self, seq: str) -> bool:
        """Return True if *seq* is a non-empty string of standard amino acids."""
        valid = set("ACDEFGHIKLMNPQRSTVWY")
        return bool(seq) and all(c in valid for c in seq.upper())
