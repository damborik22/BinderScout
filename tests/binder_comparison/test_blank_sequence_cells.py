"""A blank sequence cell must not become the three-residue binder "NAN".

pandas reads an empty CSV cell as NaN. `str(nan).strip().upper()` is `"NAN"`, and
N, A and N are all standard amino acids, so the string passes `_validate_sequence()`,
is written to the FASTA, is refolded by every engine, scores, ranks, and can land in
a top-N table. Nothing errors anywhere.

The guard lives once, in `SequenceExtractor._sequence_cell`, and every extractor that
reads a sequence column goes through it. These tests pin the behaviour through the
real extractors, and the last one keeps the raw pattern from coming back at a new
call site.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.extractors import (
    BindCraft2Extractor,
    BindCraftExtractor,
    BoltzGenExtractor,
    MosaicExtractor,
    ProteinaComplexaExtractor,
    ProteinHunterExtractor,
    PXDesignExtractor,
    RFD3Extractor,
)
from binder_comparison.extractors.base import SequenceExtractor

_SEQ = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"

_EXTRACTORS = Path(__file__).resolve().parents[2] / "Evaluator" / "binder_comparison" / "extractors"


def _csv(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


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


def _bindcraft(root: Path, seq):
    _csv(root / "final_design_stats.csv", [{"Design": "good", "Sequence": _SEQ}, {"Design": "blank", "Sequence": seq}])
    return BindCraftExtractor()


def _bindcraft2(root: Path, seq):
    _csv(
        root / "3_Ranked" / "!_Ranked.csv",
        [
            {"rank": 1, "design": "good", "Binder_Sequence": _SEQ},
            {"rank": 2, "design": "blank", "Binder_Sequence": seq},
        ],
    )
    return BindCraft2Extractor()


def _boltzgen(root: Path, seq):
    _csv(
        root / "final_designs_metrics_run1.csv",
        [{"id": "good", "designed_chain_sequence": _SEQ}, {"id": "blank", "designed_chain_sequence": seq}],
    )
    return BoltzGenExtractor()


def _mosaic(root: Path, seq):
    rows = [{"sequence": _SEQ, "is_top": 1, "name": "good"}, {"sequence": seq, "is_top": 1, "name": "blank"}]
    _csv(root / "designs.csv", rows)
    return MosaicExtractor()


def _pxdesign(root: Path, seq):
    _csv(root / "summary.csv", [{"name": "good", "sequence": _SEQ}, {"name": "blank", "sequence": seq}])
    return PXDesignExtractor()


def _rfd3(root: Path, seq):
    _csv(root / "sequences.csv", [{"name": "good", "sequence": _SEQ}, {"name": "blank", "sequence": seq}])
    return RFD3Extractor()


def _proteina_complexa(root: Path, seq):
    _csv(root / "sequences.csv", [{"name": "good", "sequence": _SEQ}, {"name": "blank", "sequence": seq}])
    return ProteinaComplexaExtractor()


def _protein_hunter_high_iptm(root: Path, seq):
    _csv(
        root / "summary_high_iptm.csv",
        [{"run_id": 1, "sequence": _SEQ, "iptm": 0.9}, {"run_id": 2, "sequence": seq, "iptm": 0.8}],
    )
    return ProteinHunterExtractor()


def _protein_hunter_all_runs(root: Path, seq):
    _csv(
        root / "summary_all_runs.csv",
        [{"run_id": 1, "best_seq": _SEQ, "best_iptm": 0.9}, {"run_id": 2, "best_seq": seq, "best_iptm": 0.8}],
    )
    return ProteinHunterExtractor(all_runs=True)


_BUILDERS = [
    _bindcraft,
    _bindcraft2,
    _boltzgen,
    _mosaic,
    _pxdesign,
    _rfd3,
    _proteina_complexa,
    _protein_hunter_high_iptm,
    _protein_hunter_all_runs,
]


@pytest.mark.parametrize("build", _BUILDERS, ids=lambda f: f.__name__.lstrip("_"))
class TestThroughTheExtractors:
    def test_the_blank_row_is_skipped_and_the_good_one_kept(self, build, tmp_path):
        got = build(tmp_path, None).extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ]

    def test_control_the_same_fixture_with_a_real_sequence_yields_both_rows(self, build, tmp_path):
        """Proves the fixture reaches the row-reading path, so the test above is not vacuous."""
        got = build(tmp_path, _SEQ[::-1]).extract(tmp_path)
        assert sorted(b.sequence for b in got) == sorted([_SEQ, _SEQ[::-1]])


def test_no_extractor_reads_a_sequence_cell_without_the_guard():
    """Keeps the raw pattern from reappearing at a new call site.

    `str(row[...]).strip().upper()` is exactly the construct that produced "NAN".
    A new extractor should call `self._sequence_cell(...)` instead.
    """
    raw = re.compile(r"str\(\s*(?:row|v|raw)\b[^)]*\)\s*\.strip\(\)\s*\.upper\(\)")
    offenders = []
    for path in sorted(_EXTRACTORS.glob("*.py")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if raw.search(line) and "pd.isna" not in line:
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert not offenders, "sequence cell read without the NaN guard:\n  " + "\n  ".join(offenders)
