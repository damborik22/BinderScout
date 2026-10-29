"""Where a Proteina-Complexa binder ENDS: the declared length beats the alanine run, and a real 7-alanine tail survives.

NVIDIA's native ``top_samples_*.csv`` carries the WHOLE complex in ``aatype``: target,
then binder, then a poly-alanine pad. Refolded unstripped, every design was scored
against a target it already contained (F44(a), CHANGELOG 2026-07-28). The fix cuts the
binder out with ``ProteinaComplexaExtractor._binder_ends``, and two rules decide where
it stops:

1. ``_n_<N>_`` in the job-directory name (= len(target) + len(binder)) is the AUTHORITY.
   The ``aatype`` column is padded and the job name is not, so the decoded length equals
   the declared one on only 26 of the 1000 designs the module measured.
2. Only when the name carries no length (PC-v3 writes a bare filename) does a trailing
   alanine run stand in, and only a run of at least ``_PAD_MIN_RUN``. The module's own
   comment puts the longest GENUINE C-terminal alanine run in a clean pool on disk at 7,
   and the pads measured on PC-v3 at up to 42, so the threshold sits in between.

This is not a regression test for a defect that has shipped. It pins two properties of
that fix which nothing pins at this commit: that rule 1 outranks rule 2, and that rule
2's threshold stays above a genuine 7-alanine tail. Each of these edits to
``proteina_complexa.py`` leaves the whole suite green:

- ``_PAD_MIN_RUN = 10`` lowered to ``5``;
- the pad heuristic moved ahead of the ``_n_`` branch, so a pad run wins outright;
- the pad stripped first and the declared length accepted only if it still fits;
- the ``_n_`` branch deleted, so the job name is never consulted.

The neighbouring tests in ``test_extractors.py::TestProteinaComplexaBinderIsolation``
look like they cover this and do not. ``test_keeps_a_short_genuine_alanine_tail`` keeps
a 3-alanine tail, so it only stops the threshold falling to 3. And
``test_strips_the_poly_alanine_pad_using_the_job_name_length`` feeds a binder that ends
in S, so the declared length and the alanine run both say 120 and the fixture cannot
tell which of them was used. (The threshold is also held from above, at 25, by
``test_strips_the_pad_by_its_alanine_run_when_the_job_name_has_no_length``. That leaves
4 to 7 open, and 7 is the one value the module says is real.)

What a regression looks like is the shape of the failures this project has shipped:
exit 0, the same design count, a pool of plausible binders. Only the designs whose real
C-terminus is alanines come out shorter than what Proteina-Complexa designed, and that
shortened string is what all three engines refold, what the ranking scores and what the
wet-lab handoff would order.

The fixtures are built to make the two rules disagree. A binder that ends in S cannot:
there the declared boundary and the alanine run coincide and every ordering of the two
rules gives the same answer. So the binder here ends in seven alanines, and each test
asserts that precondition itself, so that a "tidied" fixture fails loudly instead of
quietly pinning nothing.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from binder_comparison.extractors import ProteinaComplexaExtractor

# Canonical AF2 residue order, the encoding NVIDIA's ``aatype`` column uses. Kept as an
# independent literal rather than imported, so this file is an oracle for the decoder.
_RESTYPES = "ARNDCQEGHILKMFPSTWYV"

_TARGET = "ACDEFGHIKLMNPQRSTVWY" * 3  # 60 aa, the declared target
_CORE = "MKTAYIAKQRQISFVKSHFS" * 3  # 60 aa, ends in S
_GENUINE_TAIL = "A" * 7  # the longest genuine C-terminal alanine run the module records
_BINDER = _CORE + _GENUINE_TAIL  # 67 aa: a design whose real C-terminus is alanines
_NVIDIA_PAD = "A" * 30  # the poly-alanine padding appended after the binder


def _aatype(seq: str) -> str:
    """Encode a one-letter sequence the way NVIDIA's top_samples_*.csv does."""
    return ",".join(str(_RESTYPES.index(c)) for c in seq)


def _trailing_alanines(seq: str) -> int:
    return len(seq) - len(seq.rstrip("A"))


def _extract(tmp_path: Path, complex_seq: str, pdb_path: str) -> list[str]:
    """Run the real extractor over a one-row native CSV and return the binder sequences it emits."""
    pd.DataFrame([{"aatype": _aatype(complex_seq), "pdb_path": pdb_path, "metadata_tag": "mcts_orig1"}]).to_csv(
        tmp_path / "top_samples_x.csv", index=False
    )
    return [b.sequence for b in ProteinaComplexaExtractor(target_sequence=_TARGET).extract(tmp_path)]


def test_the_job_names_declared_length_beats_the_trailing_alanine_run(tmp_path):
    """A design that really ends in alanines, followed by NVIDIA's pad: only the declared length can tell them apart.

    The trailing run here is 37 (7 genuine + 30 pad). A heuristic that is consulted
    first, or that is the only source, cuts at the start of the genuine tail and hands
    back a 60-aa binder for a 67-aa design.
    """
    padded = _TARGET + _BINDER + _NVIDIA_PAD
    assert _trailing_alanines(padded) == len(_GENUINE_TAIL) + len(_NVIDIA_PAD), (
        "the fixture no longer ends in a genuine tail PLUS a pad, so the declared length and the alanine run "
        "would agree and this test could not tell which one the extractor used"
    )

    declared = len(_TARGET) + len(_BINDER)
    got = _extract(tmp_path, padded, f"job_0_n_{declared}_id_3_bon_orig10_r1/sample.pdb")

    assert got == [_BINDER], (
        f"the job name declares a {len(_BINDER)}-aa binder, but the extractor emitted lengths "
        f"{[len(s) for s in got]}: the trailing-alanine heuristic overrode the declared boundary "
        f"and cut off the design's genuine C-terminus"
    )


def test_a_genuine_seven_alanine_c_terminus_survives_when_the_job_name_has_no_length(tmp_path):
    """PC-v3's bare filename leaves the alanine run as the only boundary; a run of 7 is a design, not padding.

    There is no pad on this row and no ``_n_<N>_`` in the name, so the heuristic alone
    decides, and the correct answer is to leave the sequence whole. Seven is the longest
    genuine run the module records; a threshold at or below it eats a real C-terminus.
    """
    unpadded = _TARGET + _BINDER
    assert _trailing_alanines(unpadded) == 7, (
        "the fixture's C-terminus is no longer exactly 7 alanines, so this test no longer pins the "
        "documented longest genuine run"
    )

    got = _extract(tmp_path, unpadded, "orig15.pdb")

    assert got == [_BINDER], (
        f"a genuine 7-alanine C-terminus was cut: expected a {len(_BINDER)}-aa binder, the extractor emitted "
        f"lengths {[len(s) for s in got]}. The pad threshold (_PAD_MIN_RUN) must stay above the longest "
        f"genuine alanine run the module documents (7), or real designs are truncated with no warning"
    )
