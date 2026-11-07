"""The merger's second slot: AF3 by default, or Protenix.

`merge_refold_results` joins up to three engine CSVs, one per slot (anchor, second, ESMFold2).
The second slot used to be spelled `af3_csv` and nothing else. It now also takes `second_csv`
with `second_engine="protenix"`; the engine's columns are prefixed with its real name and every
guard (target mismatch, one row per design, pool filtering) applies to it exactly as to AF3.

Column names and prefixes are pinned as literals on purpose: a test that derived them from the
registry would pass whatever the registry said.
"""

import sys
import warnings
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.comparison.merger import merge_refold_results

_SEQ_A = "MAEVKLSYVL"
_SEQ_B = "SPEELLQKAI"
_TARGET = "GSHMKTAYIAKQRQISFVKSHF"
_OTHER_TARGET = "MNIFEMLRIDEGLRLKIYKDTE"


def _csv(tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _fasta(tmp_path, entries):
    path = tmp_path / "sequences.fasta"
    path.write_text("".join(f">{bid}  source={tool}  length={len(seq)}\n{seq}\n" for bid, tool, seq in entries))
    return path


def _row(seq, iptm, target=_TARGET):
    return {
        "sequence": seq,
        "target_sequence": target,
        "binder_length": len(seq),
        "run_id": "r1",
        "iptm": iptm,
        "pae_file": f"/x/{seq}_pae.npy",
    }


class TestProtenixSlot:
    def test_protenix_columns_are_prefixed_with_the_real_engine_name(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        prot = _csv(tmp_path, "protenix.csv", [_row(_SEQ_A, 0.7)])
        out = merge_refold_results(boltz2_csv=boltz, second_csv=prot, second_engine="protenix")
        assert "protenix_iptm" in out.columns
        assert "protenix_pae_file" in out.columns
        assert not [c for c in out.columns if c.startswith("af3_")]
        assert float(out.loc[0, "protenix_iptm"]) == 0.7

    def test_slot_order_is_anchor_second_esmfold2(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        prot = _csv(tmp_path, "protenix.csv", [_row(_SEQ_A, 0.7)])
        esm = _csv(tmp_path, "esm.csv", [_row(_SEQ_A, 0.6)])
        out = merge_refold_results(boltz2_csv=boltz, second_csv=prot, esmfold2_csv=esm, second_engine="protenix")
        cols = [c for c in out.columns if c.endswith("_iptm")]
        assert cols == ["boltz_iptm", "protenix_iptm", "esmfold2_iptm"]

    def test_second_csv_with_default_engine_is_the_af3_slot(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        af3 = _csv(tmp_path, "af3.csv", [_row(_SEQ_A, 0.7)])
        via_old = merge_refold_results(boltz2_csv=boltz, af3_csv=af3)
        via_new = merge_refold_results(boltz2_csv=boltz, second_csv=af3)
        pd.testing.assert_frame_equal(via_old, via_new)

    def test_target_mismatch_guard_names_protenix(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        prot = _csv(tmp_path, "protenix.csv", [_row(_SEQ_A, 0.7, target=_OTHER_TARGET)])
        with pytest.raises(ValueError, match="protenix") as exc:
            merge_refold_results(boltz2_csv=boltz, second_csv=prot, second_engine="protenix")
        assert "disagree about the target" in str(exc.value)
        assert "af3" not in str(exc.value).lower()

    def test_agreeing_targets_do_not_raise(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        prot = _csv(tmp_path, "protenix.csv", [_row(_SEQ_A, 0.7)])
        merge_refold_results(boltz2_csv=boltz, second_csv=prot, second_engine="protenix")

    def test_duplicate_rows_do_not_multiply_a_design(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        blank = _row(_SEQ_A, None)
        prot = _csv(tmp_path, "protenix.csv", [blank, _row(_SEQ_A, 0.7), _row(_SEQ_A, 0.7)])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = merge_refold_results(boltz2_csv=boltz, second_csv=prot, second_engine="protenix")
        assert len(out) == 1
        assert float(out.loc[0, "protenix_iptm"]) == 0.7
        assert any("protenix: dropped 2 duplicate" in str(w.message) for w in caught)

    def test_pool_filter_applies_to_the_protenix_slot(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        prot = _csv(tmp_path, "protenix.csv", [_row(_SEQ_A, 0.7), _row(_SEQ_B, 0.9)])
        fasta = _fasta(tmp_path, [("d1", "mosaic", _SEQ_A)])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out = merge_refold_results(
                boltz2_csv=boltz, sequences_fasta=fasta, second_csv=prot, second_engine="protenix"
            )
        assert list(out["sequence"]) == [_SEQ_A]
        assert list(out["binder_id"]) == ["d1"]

    def test_protenix_only_gap_fills_passthrough_columns(self, tmp_path):
        # A design the anchor never scored keeps the second engine's binder_length.
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        prot = _csv(tmp_path, "protenix.csv", [_row(_SEQ_A, 0.7), _row(_SEQ_B, 0.6)])
        out = merge_refold_results(boltz2_csv=boltz, second_csv=prot, second_engine="protenix")
        row_b = out.set_index("sequence").loc[_SEQ_B]
        assert row_b["binder_length"] == len(_SEQ_B)


class TestOneSlot:
    def test_both_af3_csv_and_second_csv_refuse_naming_both(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        af3 = _csv(tmp_path, "af3.csv", [_row(_SEQ_A, 0.7)])
        prot = _csv(tmp_path, "protenix.csv", [_row(_SEQ_A, 0.7)])
        with pytest.raises(ValueError, match="af3_csv") as exc:
            merge_refold_results(boltz2_csv=boltz, af3_csv=af3, second_csv=prot, second_engine="protenix")
        assert "second_csv" in str(exc.value)

    def test_both_slots_refuse_even_with_the_default_engine(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        af3 = _csv(tmp_path, "af3.csv", [_row(_SEQ_A, 0.7)])
        with pytest.raises(ValueError, match="second_csv") as exc:
            merge_refold_results(boltz2_csv=boltz, af3_csv=af3, second_csv=af3)
        assert "af3_csv" in str(exc.value)

    def test_af3_csv_with_protenix_engine_refuses_instead_of_dropping_it(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        af3 = _csv(tmp_path, "af3.csv", [_row(_SEQ_A, 0.7)])
        with pytest.raises(ValueError, match="af3_csv") as exc:
            merge_refold_results(boltz2_csv=boltz, af3_csv=af3, second_engine="protenix")
        assert "protenix" in str(exc.value)

    def test_unknown_second_engine_raises_the_registry_error(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        prot = _csv(tmp_path, "p.csv", [_row(_SEQ_A, 0.7)])
        with pytest.raises(ValueError, match="unknown second engine 'esmfold2'"):
            merge_refold_results(boltz2_csv=boltz, second_csv=prot, second_engine="esmfold2")

    def test_unknown_second_engine_raises_even_without_a_second_csv(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        with pytest.raises(ValueError, match="unknown second engine 'nope'"):
            merge_refold_results(boltz2_csv=boltz, second_engine="nope")


class TestAf3PathUnchanged:
    def test_exact_column_list_and_values_for_the_af3_call(self, tmp_path):
        boltz = _csv(tmp_path, "boltz2.csv", [_row(_SEQ_A, 0.8)])
        af3 = _csv(tmp_path, "af3.csv", [_row(_SEQ_A, 0.7)])
        esm = _csv(tmp_path, "esm.csv", [_row(_SEQ_A, 0.6)])
        out = merge_refold_results(boltz2_csv=boltz, af3_csv=af3, esmfold2_csv=esm)
        assert list(out.columns) == [
            "sequence",
            "target_sequence",
            "binder_length",
            "run_id",
            "boltz_iptm",
            "boltz_pae_file",
            "af3_iptm",
            "af3_pae_file",
            "esmfold2_iptm",
            "esmfold2_pae_file",
        ]
        assert out.loc[0, ["boltz_iptm", "af3_iptm", "esmfold2_iptm"]].tolist() == [0.8, 0.7, 0.6]
