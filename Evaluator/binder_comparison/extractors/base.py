"""Abstract base class for sequence extractors, plus the two guards every one needs."""

from __future__ import annotations

import hashlib
import warnings
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path

from ..comparison.tool_classification import DEFAULT_EXTRACTOR_METADATA, ExtractorMetadata
from ..core.schema import ExtractedBinder


def resolve_single_match(matches: list[Path], *, tool: str, what: str, input_dir: Path) -> Path:
    """Return the one match, or refuse to guess between several.

    Every extractor used to resolve a multi-hit glob with ``matches[0]`` — raw
    filesystem order, no warning. Pointed at a parent directory that holds N
    replicates, that silently keeps ONE of them: measured 96 of 4804 rows on the
    ApoE4-iso PC-v3 pool and 100 of 500 on a Clara run, and on an ordinary
    multi-variant run dir it picked ``bindcraft_variant_a`` out of four and
    discarded a whole 700-design BoltzGen pool. The result is a wrong-but-nonzero
    pool, which passes every downstream guard including ``--allow-empty`` and then
    spends hours of Boltz-2 + AF3 + ESMFold2 GPU time looking complete.

    So ambiguity stops the run and names every candidate. The caller decides —
    point at the specific directory, or opt into aggregation where several files
    genuinely are one pool (Proteina-Complexa's MCTS replicates).
    """
    if len(matches) == 1:
        return matches[0]
    listing = "\n  ".join(str(p) for p in sorted(matches))
    raise ValueError(
        f"{tool}: {len(matches)} files match {what} under {input_dir} — refusing to guess "
        f"which one is the design pool.\n  {listing}\n"
        f"Point --{tool.lower().replace(' ', '-')} at the specific directory, or extract each "
        f"and concatenate."
    )


def disambiguate_ids(binders: list[ExtractedBinder], *, tool: str) -> None:
    """Make binder_ids unique, in place.

    A duplicate binder_id is a silent DROP, not a crash: ``add_design_groups``
    keys design_group on it and the report keeps only the first row per group, so
    the colliding design disappears from the report, Top-N, candidates and
    diversity while surviving in metrics.csv — announced by a "Collapsing N
    near-duplicate variant(s)" line indistinguishable from the intended
    Protein-Hunter/BindCraft collapse. Measured on shipped data: Proteina-Complexa
    on 2VDY collapses 1000 designs into 253 ids, and a merged Protein-Hunter
    summary gives 1654 rows → 1487 ids with all 164 collisions covering
    *different* sequences.

    Break ties with a short hash of the sequence: deterministic and
    order-independent, so the id stays stable across a re-sorted CSV.
    """
    dupes = {bid for bid, n in Counter(b.binder_id for b in binders).items() if n > 1}
    if not dupes:
        return
    for b in binders:
        if b.binder_id in dupes:
            b.binder_id = f"{b.binder_id}_{hashlib.sha1(b.sequence.encode()).hexdigest()[:6]}"
    warnings.warn(
        f"{tool}: {len(dupes)} binder_id(s) were not unique across the extracted pool "
        f"(e.g. {sorted(dupes)[0]!r}); disambiguated with a sequence hash suffix.",
        stacklevel=2,
    )


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
