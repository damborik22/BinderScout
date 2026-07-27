"""Tests for comparison/merger.py — the cross-engine join.

The join key is the amino-acid sequence string, not a design id: each engine
folds a sequence independently and emits its own ``run_id`` (``af3_0001`` vs
``esmfold2_0001``), so the sequence is the only thing they share. That makes the
merge sensitive to duplicate sequences, which is what these tests pin down.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.comparison.merger import merge_refold_results

_SEQ_A = "MAEVKLSYVL"
_SEQ_B = "SPEELLQKAI"


def _engine_csv(tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _fasta(tmp_path, entries, name="sequences.fasta"):
    """entries: list of (binder_id, source_tool, sequence)."""
    path = tmp_path / name
    path.write_text("".join(f">{bid}  source={tool}  length={len(seq)}\n{seq}\n" for bid, tool, seq in entries))
    return path


class TestEnginePrefixing:
    def test_non_passthrough_columns_get_engine_prefix(self, tmp_path):
        boltz = _engine_csv(tmp_path, "boltz2.csv", [{"sequence": _SEQ_A, "iptm": 0.8, "binder_length": 10}])
        out = merge_refold_results(boltz2_csv=boltz)
        assert "boltz_iptm" in out.columns
        # passthrough identifiers stay unprefixed so the join key is shared
        assert "sequence" in out.columns
        assert "binder_length" in out.columns

    def test_outer_join_keeps_designs_only_one_engine_saw(self, tmp_path):
        boltz = _engine_csv(tmp_path, "boltz2.csv", [{"sequence": _SEQ_A, "iptm": 0.8}])
        af3 = _engine_csv(tmp_path, "af3.csv", [{"sequence": _SEQ_B, "iptm": 0.7}])
        out = merge_refold_results(boltz2_csv=boltz, af3_csv=af3)
        assert set(out["sequence"]) == {_SEQ_A, _SEQ_B}
        assert len(out) == 2


class TestDuplicateSequenceFanout:
    """Regression: _attach_fasta_metadata left-joined a non-deduplicated frame, so
    a FASTA carrying one sequence under two binder_ids multiplied the metrics rows.
    One design then occupied several Top-30 slots and inflated the eligible count
    the two-stage screen takes its top 50% from."""

    def test_duplicate_fasta_entries_do_not_multiply_rows(self, tmp_path):
        boltz = _engine_csv(tmp_path, "boltz2.csv", [{"sequence": _SEQ_A, "iptm": 0.8}])
        fasta = _fasta(tmp_path, [("mosaic_1", "mosaic", _SEQ_A), ("bindcraft_7", "bindcraft", _SEQ_A)])
        with pytest.warns(UserWarning, match="duplicate sequence"):
            out = merge_refold_results(boltz2_csv=boltz, sequences_fasta=fasta)
        assert len(out) == 1, "one refold result must stay one report row"
        assert out["binder_id"].iloc[0] == "mosaic_1", "first occurrence wins"

    def test_distinct_sequences_are_unaffected(self, tmp_path):
        boltz = _engine_csv(
            tmp_path, "boltz2.csv", [{"sequence": _SEQ_A, "iptm": 0.8}, {"sequence": _SEQ_B, "iptm": 0.6}]
        )
        fasta = _fasta(tmp_path, [("mosaic_1", "mosaic", _SEQ_A), ("rfd3_2", "rfd3", _SEQ_B)])
        out = merge_refold_results(boltz2_csv=boltz, sequences_fasta=fasta)
        assert len(out) == 2
        assert dict(zip(out["sequence"], out["source_tool"])) == {_SEQ_A: "mosaic", _SEQ_B: "rfd3"}

    def test_no_warning_when_the_fasta_is_clean(self, tmp_path, recwarn):
        boltz = _engine_csv(tmp_path, "boltz2.csv", [{"sequence": _SEQ_A, "iptm": 0.8}])
        fasta = _fasta(tmp_path, [("mosaic_1", "mosaic", _SEQ_A)])
        merge_refold_results(boltz2_csv=boltz, sequences_fasta=fasta)
        assert not [w for w in recwarn if "duplicate sequence" in str(w.message)]


class TestEmptyInputs:
    def test_all_empty_raises_rather_than_reporting_on_nothing(self, tmp_path):
        empty = tmp_path / "empty.csv"
        empty.write_text("sequence,iptm\n")
        with pytest.warns(UserWarning), pytest.raises(ValueError, match="nothing to report"):
            merge_refold_results(boltz2_csv=empty)
