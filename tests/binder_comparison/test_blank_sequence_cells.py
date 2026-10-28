"""A blank sequence cell must not become the three-residue binder "NAN".

pandas reads an empty CSV cell as NaN. `str(nan).strip().upper()` is `"NAN"`, and
N, A and N are all standard amino acids — so the string sails through
`_validate_sequence()`, is written to the FASTA, is refolded by all three engines,
scores, ranks, and can land in a top-N table. Nothing errors anywhere.

`ProteinHunterExtractor` guarded this at both of its call sites and said why in a
comment. The other six extractors did not: BindCraft, BoltzGen, Mosaic, PXDesign
and RFD3 each did `str(row[col]).strip().upper()` directly, and
Proteina-Complexa did the same inside a list comprehension.

The guard now lives once, in `SequenceExtractor._sequence_cell`. These tests pin
the behaviour through the real extractors, and the last one keeps the raw pattern
from coming back at a new call site.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from binder_comparison.extractors.base import SequenceExtractor
from binder_comparison.extractors.bindcraft import BindCraftExtractor
from binder_comparison.extractors.boltzgen import BoltzGenExtractor
from binder_comparison.extractors.mosaic import MosaicExtractor
from binder_comparison.extractors.pxdesign import PXDesignExtractor

_SEQ = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"

_EXTRACTORS = Path(__file__).resolve().parents[2] / "Evaluator" / "binder_comparison" / "extractors"


def _csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


class TestTheGuardItself:
    """`_sequence_cell` is the one place the NaN check lives."""

    @pytest.mark.parametrize("blank", [None, float("nan"), "", "   "])
    def test_an_empty_cell_is_not_a_sequence(self, blank):
        assert SequenceExtractor._sequence_cell(SequenceExtractor, blank) is None

    def test_nan_would_otherwise_have_validated(self):
        """Why this bug was silent: "NAN" is a legal peptide, so no validator rejects it."""
        assert SequenceExtractor._validate_sequence(SequenceExtractor, str(float("nan")).upper())

    def test_a_real_sequence_is_normalised_and_kept(self):
        assert SequenceExtractor._sequence_cell(SequenceExtractor, f"  {_SEQ.lower()} \n") == _SEQ


class TestThroughTheExtractors:
    def test_bindcraft_skips_the_blank_row_and_keeps_the_good_one(self, tmp_path):
        d = tmp_path / "Accepted"
        d.mkdir()
        _csv(
            tmp_path / "final_design_stats.csv",
            [{"Design": "good", "Sequence": _SEQ}, {"Design": "blank", "Sequence": None}],
        )
        got = BindCraftExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ]

    def test_boltzgen_skips_the_blank_row(self, tmp_path):
        _csv(
            tmp_path / "final_designs_metrics_run1.csv",
            [{"id": "good", "designed_chain_sequence": _SEQ}, {"id": "blank", "designed_chain_sequence": None}],
        )
        got = BoltzGenExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ]

    def test_mosaic_skips_the_blank_row(self, tmp_path):
        _csv(
            tmp_path / "designs.csv",
            [
                {"sequence": _SEQ, "is_top": 1, "name": "good"},
                {"sequence": None, "is_top": 1, "name": "blank"},
            ],
        )
        got = MosaicExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ]

    def test_pxdesign_skips_the_blank_row(self, tmp_path):
        _csv(
            tmp_path / "summary.csv",
            [{"name": "good", "sequence": _SEQ}, {"name": "blank", "sequence": None}],
        )
        got = PXDesignExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ]


def test_no_extractor_reads_a_sequence_cell_without_the_guard():
    """Keeps the raw pattern from reappearing at a seventh call site.

    `str(row[...]).strip().upper()` is exactly the construct that produced "NAN".
    A new extractor should call `self._sequence_cell(...)` instead.
    """
    raw = re.compile(r"str\(\s*(?:row|v)\[[^\]]+\]\s*\)\s*\.strip\(\)\s*\.upper\(\)")
    offenders = []
    for path in sorted(_EXTRACTORS.glob("*.py")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if raw.search(line) and "pd.isna" not in line:
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, "sequence cell read without the NaN guard:\n  " + "\n  ".join(offenders)
