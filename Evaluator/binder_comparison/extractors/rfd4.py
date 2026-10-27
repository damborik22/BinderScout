"""RFD4-Proteina sequence extractor.

RFD4-Proteina (``RosettaCommons/RFD4-Proteina``) is the ninth design tool, and the
only one here that writes **no table at all**. ``rfd4-generate`` emits one all-atom
mmCIF per sample::

    <out_dir>/.../inference_samples/<name>_<i>/<name>_<i>_generated.cif

with the designed binder in chain **B** and the preserved target in chain **A**
(``i`` is the 0-based replicate index). There is no CSV, no summary file and no
score, so this extractor reads structures rather than parsing a table — and the
``.cif`` is uncompressed, unlike RFD3's ``.cif.gz``.

**No native metrics, by configuration.** The generator's own metrics block needs
AF2/AF3 environments that are not installed here, so the pool is produced with
``~metrics`` and RFD4 contributes no ``native_*`` column. That is handled, not
ignored: the report's per-tool section has no native sort column for RFD4 and
falls back to our ranking, and ``evaluate.sh`` gives RFD4 the same Boltz-2
fold-back native rank it already gives RFD3 (diffusion gives geometry, the
fold-back gives the rank). Nothing here invents a score.

Composition flags (Shannon entropy, per-residue fraction) that the one-off
scripts behind the first 690-design run computed are deliberately **not** here:
they are pool QC, which ``binder-compare qc-annotate`` / ``prefilter`` already
own, and ``NativeMetrics`` has no field that would honestly hold them.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from ..core.schema import ExtractedBinder, NativeMetrics
from ..io.design_ids import safe_stem
from ..io.read import cif_chain_sequences
from .base import SequenceExtractor, disambiguate_ids, parse_trailing_index, resolve_single_match

#: One file per sample. Anchored on the suffix the generator writes.
_SAMPLE_GLOB = "*_generated.cif"

#: Chain B is the designed binder, chain A the preserved target.
_BINDER_CHAIN = "B"


class RFD4Extractor(SequenceExtractor):
    """Extract binder sequences from an RFD4-Proteina output directory."""

    @property
    def tool_name(self) -> str:
        return "rfd4"

    def extract(self, input_dir: str | Path) -> list[ExtractedBinder]:
        input_dir = Path(input_dir)
        cifs = list(input_dir.rglob(_SAMPLE_GLOB))
        if not cifs:
            warnings.warn(
                f"RFD4: no {_SAMPLE_GLOB} under {input_dir}. The generator writes one per sample at "
                f"<out_dir>/.../inference_samples/<name>_<i>/<name>_<i>_generated.cif — check the "
                f"path, and that the run finished."
            )
            return []

        # A timing job and a production job sit side by side under one target directory
        # (that is the shipped layout), and each has its own inference_samples/. Pooling
        # them would silently pad the production pool with throwaway designs, so refuse
        # to guess — the same rule every other extractor applies to a multi-hit glob.
        roots = sorted({c.parent.parent for c in cifs})
        if len(roots) > 1:
            resolve_single_match(roots, tool="RFD4", what="inference_samples/ directory", input_dir=input_dir)

        results: list[ExtractedBinder] = []
        no_binder_chain: list[Path] = []
        for cif in cifs:
            sequence = cif_chain_sequences(cif).get(_BINDER_CHAIN, "")
            if not self._validate_sequence(sequence):
                no_binder_chain.append(cif)
                continue
            # safe_stem, not a local sanitiser: the id becomes the first token of the
            # FASTA header and then the structure filename stem, and a space in it is
            # a hard refusal downstream (io.design_ids.header_binder_id).
            binder = ExtractedBinder(
                binder_id=f"rfd4_{safe_stem(cif.parent.name)}",
                sequence=sequence,
                source_tool="rfd4",
                native=NativeMetrics(),
            )
            # <name>_<i> carries the replicate index, and the generator produces them in
            # ascending i — so the trailing integer IS the generation ordinal. Parsed
            # with the shared helper, which anchors at the END so a run tag containing
            # digits cannot be mistaken for the index.
            index = parse_trailing_index(cif.parent.name)
            if index is not None:
                binder.generation_index = index
                binder.generation_index_source = "parsed"
            results.append(binder)

        if no_binder_chain:
            warnings.warn(
                f"RFD4: {len(no_binder_chain)} of {len(cifs)} structure(s) under {input_dir} have no "
                f"readable chain {_BINDER_CHAIN} (the binder), e.g. {no_binder_chain[0]}. Those designs "
                f"were not extracted."
            )
        if not results:
            warnings.warn(
                f"RFD4: found {len(cifs)} structure(s) under {input_dir} but could not read a chain "
                f"{_BINDER_CHAIN} binder sequence from any of them — extracting nothing. Chain B is the "
                f"designed binder and chain A the target; check that these are rfd4-generate outputs."
            )
            return []

        # rglob order is arbitrary and a lexicographic sort puts _10 before _2, so order
        # by the parsed index. Ids without one keep a stable alphabetical tail.
        results.sort(key=lambda b: (b.generation_index is None, b.generation_index, b.binder_id))
        disambiguate_ids(results, tool="RFD4")
        return results
