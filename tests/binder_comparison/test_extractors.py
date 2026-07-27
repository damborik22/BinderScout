"""Tests for the seven live extractors — the pipeline's ingestion layer.

Before this file the only parser tests in the repo targeted
`evaluator_legacy/evaluator.py`, documented as retired and dispatched by nothing, so
CI pinned dead code while the seven shipped extractors had zero coverage. That is the
layer where CLAUDE.md documents two known parsing traps (the BoltzGen
designed_sequence-vs-designed_chain_sequence truncation and the Mosaic mixed-width
CSV), and where audit findings F6, F7 and F39 lived.

Fixtures use the exact filenames and column names each extractor searches for, so a
rename upstream shows up here rather than as a silently empty pool.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.extractors import (
    BindCraftExtractor,
    BoltzGenExtractor,
    MosaicExtractor,
    ProteinaComplexaExtractor,
    ProteinHunterExtractor,
    PXDesignExtractor,
    RFD3Extractor,
)

_SEQ_A = "ACDEFGHIKLMNPQRSTVWY" * 3  # 60 aa
_SEQ_B = "MKTAYIAKQRQISFVKSHFS" * 3  # 60 aa


def _csv(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


class TestBindCraft:
    def test_reads_final_design_stats_and_native_metrics(self, tmp_path):
        _csv(
            tmp_path / "final_design_stats.csv",
            [
                {
                    "Design": "t_l60_s1_mpnn1",
                    "Sequence": _SEQ_A,
                    "Average_i_pTM": 0.81,
                    "Average_dG": -42.5,
                    "Average_ShapeComplementarity": 0.71,
                    "MPNN_seq_recovery": 0.34,
                }
            ],
        )
        got = BindCraftExtractor().extract(tmp_path)
        assert len(got) == 1
        assert got[0].sequence == _SEQ_A
        assert got[0].source_tool == "bindcraft"
        assert got[0].binder_id == "bindcraft_t_l60_s1_mpnn1"
        assert got[0].native.dG == pytest.approx(-42.5)
        assert got[0].native.shape_complementarity == pytest.approx(0.71)

    def test_collapses_mpnn_variants_to_best_per_trajectory(self, tmp_path):
        """ "Best design, not many sequences of one design" — keep the top Average_i_pTM
        MPNN variant per trajectory."""
        _csv(
            tmp_path / "final_design_stats.csv",
            [
                {"Design": "t_l60_s1_mpnn1", "Sequence": _SEQ_A, "Average_i_pTM": 0.60},
                {"Design": "t_l60_s1_mpnn2", "Sequence": _SEQ_B, "Average_i_pTM": 0.90},
            ],
        )
        got = BindCraftExtractor(collapse_variants=True).extract(tmp_path)
        assert len(got) == 1
        assert got[0].sequence == _SEQ_B, "should keep the higher-ipTM sibling"

        assert len(BindCraftExtractor(collapse_variants=False).extract(tmp_path)) == 2

    def test_missing_dir_returns_empty_with_warning(self, tmp_path):
        with pytest.warns(UserWarning):
            assert BindCraftExtractor().extract(tmp_path / "absent") == []


class TestBoltzGen:
    def test_prefers_the_full_chain_over_the_designed_subset(self, tmp_path):
        """The documented nanobody trap: designed_sequence holds only the DESIGNED
        residues (a ~25-40 aa CDR), so reading it refolds a truncated binder. Verified
        on 2VDY: designed_sequence 24-42 aa vs designed_chain_sequence 112-133 aa."""
        cdr_only = "ACDEFGHIKL"
        _csv(
            tmp_path / "final_designs_metrics_run1.csv",
            [{"id": "d0", "designed_chain_sequence": _SEQ_A, "designed_sequence": cdr_only}],
        )
        got = BoltzGenExtractor().extract(tmp_path)
        assert len(got) == 1
        assert got[0].sequence == _SEQ_A, "must take the full chain, not the CDR"
        assert got[0].binder_id == "boltzgen_d0"

    def test_falls_back_to_designed_sequence_when_chain_absent(self, tmp_path):
        _csv(tmp_path / "final_designs_metrics_x.csv", [{"id": "d1", "designed_sequence": _SEQ_B}])
        got = BoltzGenExtractor().extract(tmp_path)
        assert got[0].sequence == _SEQ_B

    def test_surfaces_native_ipsae_and_rank(self, tmp_path):
        _csv(
            tmp_path / "final_designs_metrics_x.csv",
            [{"id": "d2", "designed_chain_sequence": _SEQ_A, "design_ipsae_min": 0.66, "final_rank": 3}],
        )
        got = BoltzGenExtractor().extract(tmp_path)
        assert got[0].native.bg_design_ipsae_min == pytest.approx(0.66)
        assert got[0].native.bg_final_rank == 3


class TestMosaic:
    def _designs(self, tmp_path, rows):
        return _csv(tmp_path / "designs.csv", rows)

    def test_filters_to_is_top_by_default(self, tmp_path):
        """~40 refolded designs out of ~800 — the default that keeps the refold pool sane."""
        self._designs(
            tmp_path,
            [
                {"sequence": _SEQ_A, "worker_id": "w1", "rank": 1, "is_top": 1},
                {"sequence": _SEQ_B, "worker_id": "w1", "rank": 2, "is_top": 0},
            ],
        )
        with pytest.warns(UserWarning, match="is_top"):
            got = MosaicExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_A]
        assert got[0].binder_id == "mosaic_w1_1"

    def test_all_designs_flag_keeps_everything(self, tmp_path):
        self._designs(
            tmp_path,
            [
                {"sequence": _SEQ_A, "worker_id": "w1", "rank": 1, "is_top": 1},
                {"sequence": _SEQ_B, "worker_id": "w1", "rank": 2, "is_top": 0},
            ],
        )
        assert len(MosaicExtractor(top_only=False).extract(tmp_path)) == 2

    def test_harvests_native_design_time_metrics(self, tmp_path):
        self._designs(
            tmp_path,
            [{"sequence": _SEQ_A, "worker_id": "w1", "rank": 1, "is_top": 1, "ranking_loss": 0.12, "iptm_aux": 0.88}],
        )
        got = MosaicExtractor().extract(tmp_path)
        assert got[0].native.mosaic_ranking_loss == pytest.approx(0.12)
        assert got[0].native.mosaic_iptm_design == pytest.approx(0.88)

    def test_mixed_width_rows_are_not_dropped(self, tmp_path):
        """designs.csv can mix column counts when several workers append to it. The
        reader widens the header so the extra-column rows survive."""
        p = tmp_path / "designs.csv"
        p.write_text(
            f"sequence,worker_id,rank,is_top\n{_SEQ_A},w1,1,1\n{_SEQ_B},w2,1,1,extra_value\n"  # one column wider
        )
        got = MosaicExtractor().extract(tmp_path)
        assert len(got) == 2, "the wider row must not be silently dropped"


class TestPXDesign:
    def test_reads_summary_csv(self, tmp_path):
        _csv(
            tmp_path / "summary.csv",
            [{"sequence": _SEQ_A, "task_name": "px_t_120", "rank": 1, "composite_score": 0.77, "af2_iptm": 0.8}],
        )
        got = PXDesignExtractor().extract(tmp_path)
        assert got[0].binder_id == "pxdesign_px_t_120_1"
        assert got[0].native.pxdesign_composite_score == pytest.approx(0.77)

    def test_tolerates_the_af2_ipae_casing_drift(self, tmp_path):
        """PXDesign has shipped both af2_ipae and af2_ipAE across releases."""
        _csv(tmp_path / "summary.csv", [{"sequence": _SEQ_A, "rank": 1, "af2_ipAE": 7.5}])
        got = PXDesignExtractor().extract(tmp_path)
        assert got[0].native.pxdesign_af2_ipae == pytest.approx(7.5)

    def test_falls_back_to_sequences_csv(self, tmp_path):
        _csv(tmp_path / "sequences.csv", [{"sequence": _SEQ_B, "rank": 2}])
        assert PXDesignExtractor().extract(tmp_path)[0].sequence == _SEQ_B


class TestProteinaComplexa:
    def test_reads_sequences_csv(self, tmp_path):
        _csv(tmp_path / "sequences.csv", [{"sequence": _SEQ_A, "design_id": "c7"}])
        got = ProteinaComplexaExtractor().extract(tmp_path)
        assert got[0].binder_id == "complexa_c7"
        assert got[0].source_tool == "proteina_complexa"

    def test_decodes_aatype_integers_when_no_sequence_column(self, tmp_path):
        """NVIDIA-native output carries aatype ints, not letters."""
        restypes = "ARNDCQEGHILKMFPSTWYV"
        idxs = [restypes.index(c) for c in restypes]
        # COMMA-separated — the decoder splits on "," (proteina_complexa.py:93).
        _csv(tmp_path / "sequences.csv", [{"aatype": ",".join(map(str, idxs)), "design_id": "c1"}])
        got = ProteinaComplexaExtractor().extract(tmp_path)
        assert got and got[0].sequence == restypes


class TestProteinHunter:
    def test_reads_high_iptm_summary_and_collapses_cycles(self, tmp_path):
        """Cycles are snapshots of one hallucination trajectory, so one row per run."""
        _csv(
            tmp_path / "summary_high_iptm.csv",
            [
                {"sequence": _SEQ_A, "run_id": 107, "cycle": 5, "iptm": 0.80, "plddt": 0.9},
                {"sequence": _SEQ_B, "run_id": 107, "cycle": 8, "iptm": 0.88, "plddt": 0.9},
            ],
        )
        got = ProteinHunterExtractor(collapse_variants=True).extract(tmp_path)
        assert len(got) == 1
        assert got[0].binder_id.startswith("protein_hunter_107")
        assert got[0].source_tool == "protein_hunter"

    def test_keeps_every_cycle_when_not_collapsing(self, tmp_path):
        _csv(
            tmp_path / "summary_high_iptm.csv",
            [
                {"sequence": _SEQ_A, "run_id": 107, "cycle": 5, "iptm": 0.80},
                {"sequence": _SEQ_B, "run_id": 107, "cycle": 8, "iptm": 0.88},
            ],
        )
        assert len(ProteinHunterExtractor(collapse_variants=False).extract(tmp_path)) == 2


class TestRFD3:
    def test_reads_sequences_csv_and_qc_metrics(self, tmp_path):
        _csv(
            tmp_path / "sequences.csv",
            [{"sequence": _SEQ_A, "design_id": "r14", "n_chainbreaks": 0, "helix_fraction": 0.9}],
        )
        got = RFD3Extractor().extract(tmp_path)
        assert got[0].binder_id == "rfd3_r14"
        assert got[0].native.rfd3_n_chainbreaks == pytest.approx(0)
        assert got[0].native.rfd3_helix_fraction == pytest.approx(0.9)

    def test_csv_is_preferred_over_the_fasta_fallback(self, tmp_path):
        _csv(tmp_path / "sequences.csv", [{"sequence": _SEQ_A, "design_id": "r1"}])
        (tmp_path / "mpnn").mkdir()
        (tmp_path / "mpnn" / "d.fa").write_text(f">other\n{_SEQ_B}\n")
        got = RFD3Extractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_A]


class TestSequenceHygieneAcrossExtractors:
    def test_invalid_sequences_are_skipped_not_emitted(self, tmp_path):
        """A non-protein string must never reach the refold queue. Note the CSV path
        skips it silently (no warning) — unlike BindCraft/BoltzGen/Mosaic, which warn
        per row. Asserted as filtering only, since that inconsistency is pre-existing."""
        _csv(
            tmp_path / "sequences.csv",
            [{"sequence": "NOT-A-SEQUENCE!!", "design_id": "bad"}, {"sequence": _SEQ_A, "design_id": "good"}],
        )
        got = RFD3Extractor().extract(tmp_path)
        assert [b.binder_id for b in got] == ["rfd3_good"]

    def test_sequences_are_upper_cased(self, tmp_path):
        _csv(tmp_path / "sequences.csv", [{"sequence": _SEQ_A.lower(), "design_id": "r1"}])
        assert RFD3Extractor().extract(tmp_path)[0].sequence == _SEQ_A

    def test_every_extractor_tags_its_own_source_tool(self, tmp_path):
        """source_tool is the join key that makes per-tool report sections work."""
        cases = [
            (BindCraftExtractor(), "final_design_stats.csv", {"Sequence": _SEQ_A, "Design": "d"}, "bindcraft"),
            (
                BoltzGenExtractor(),
                "final_designs_metrics_a.csv",
                {"designed_chain_sequence": _SEQ_A, "id": "d"},
                "boltzgen",
            ),
            (PXDesignExtractor(), "summary.csv", {"sequence": _SEQ_A, "rank": 1}, "pxdesign"),
            (RFD3Extractor(), "sequences.csv", {"sequence": _SEQ_A, "design_id": "d"}, "rfd3"),
        ]
        for extractor, filename, row, expected in cases:
            d = tmp_path / expected
            _csv(d / filename, [row])
            got = extractor.extract(d)
            assert got, f"{expected}: extracted nothing"
            assert got[0].source_tool == expected
