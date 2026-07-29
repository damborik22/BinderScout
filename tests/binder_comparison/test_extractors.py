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
import warnings
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


# Two rows in the shape the configurator's PXDesign collector writes: a
# per-design `design_id`, already "pxdesign_"-prefixed.
_PXD_COLLECTOR_ROWS = [
    {"sequence": _SEQ_A, "design_id": "pxdesign_len60_s3", "af2_iptm": 0.71},
    {"sequence": _SEQ_B, "design_id": "pxdesign_len80_s9", "af2_iptm": 0.85},
]


class TestPXDesignBinderIdStability:
    """F43(a): binder_id must survive a re-sort of the source CSV.

    The configurator's PXDesign collector writes a ``design_id`` per row
    (``pxdesign_<name>``). Ignoring it made the id row-position-derived, so a
    ``pxdesign_12`` in the report could not be grepped back to sequences.csv and
    a re-run renamed every design.
    """

    def test_prefers_the_collectors_design_id(self, tmp_path):
        _csv(tmp_path / "sequences.csv", _PXD_COLLECTOR_ROWS)
        got = PXDesignExtractor().extract(tmp_path)
        # Already "pxdesign_"-prefixed by the collector — kept verbatim so the id
        # greps straight back to the source CSV.
        assert [b.binder_id for b in got] == ["pxdesign_len60_s3", "pxdesign_len80_s9"]

    def test_ids_are_unchanged_by_a_reordered_csv(self, tmp_path):
        forward, reverse = tmp_path / "fwd", tmp_path / "rev"
        _csv(forward / "sequences.csv", _PXD_COLLECTOR_ROWS)
        _csv(reverse / "sequences.csv", list(reversed(_PXD_COLLECTOR_ROWS)))
        by_seq_fwd = {b.sequence: b.binder_id for b in PXDesignExtractor().extract(forward)}
        by_seq_rev = {b.sequence: b.binder_id for b in PXDesignExtractor().extract(reverse)}
        assert by_seq_fwd == by_seq_rev, "re-sorting the CSV must not rename designs"

    def test_uses_pxdesigns_own_name_column(self, tmp_path):
        """PXDesign's filtered_summary.csv / sample_level_output.csv name column,
        which the collector reads but which also reaches the extractor directly."""
        _csv(tmp_path / "summary.csv", [{"sequence": _SEQ_A, "name": "len60_s3", "rank": 1}])
        assert PXDesignExtractor().extract(tmp_path)[0].binder_id == "pxdesign_len60_s3"

    def test_positional_fallback_is_explicit(self, tmp_path):
        """Nothing stable in the row → row position, but say so out loud."""
        _csv(tmp_path / "sequences.csv", [{"sequence": _SEQ_A}, {"sequence": _SEQ_B}])
        with pytest.warns(UserWarning, match="ROW POSITION"):
            got = PXDesignExtractor().extract(tmp_path)
        assert [b.binder_id for b in got] == ["pxdesign_0", "pxdesign_1"]

    def test_no_positional_warning_when_ids_are_stable(self, tmp_path):
        _csv(tmp_path / "sequences.csv", _PXD_COLLECTOR_ROWS)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert len(PXDesignExtractor().extract(tmp_path)) == 2

    def test_colliding_design_ids_stay_distinct(self, tmp_path):
        """Length-scan runs aggregate one filtered_summary.csv per bucket and the
        collector falls back to the file stem when a row has no name, so the same
        design_id can arrive twice. binder_id is what add_design_groups keys on —
        duplicates there silently collapse two designs into one group."""
        _csv(
            tmp_path / "sequences.csv",
            [
                {"sequence": _SEQ_A, "design_id": "pxdesign_filtered_summary"},
                {"sequence": _SEQ_B, "design_id": "pxdesign_filtered_summary"},
            ],
        )
        with pytest.warns(UserWarning, match="not unique"):
            got = PXDesignExtractor().extract(tmp_path)
        ids = [b.binder_id for b in got]
        assert len(set(ids)) == 2, f"duplicate binder_id would drop a design: {ids}"
        assert all(i.startswith("pxdesign_filtered_summary_") for i in ids)

    def test_collision_suffix_is_order_independent(self, tmp_path):
        rows = [
            {"sequence": _SEQ_A, "design_id": "pxdesign_filtered_summary"},
            {"sequence": _SEQ_B, "design_id": "pxdesign_filtered_summary"},
        ]
        forward, reverse = tmp_path / "fwd", tmp_path / "rev"
        _csv(forward / "sequences.csv", rows)
        _csv(reverse / "sequences.csv", list(reversed(rows)))
        with pytest.warns(UserWarning):
            fwd = {b.sequence: b.binder_id for b in PXDesignExtractor().extract(forward)}
            rev = {b.sequence: b.binder_id for b in PXDesignExtractor().extract(reverse)}
        assert fwd == rev


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

    def test_reads_the_collectors_renamed_metric_columns(self, tmp_path):
        """F43(b): the configurator collector renames the raw evaluation columns
        (self_complex_i_pTM → iptm, _pLDDT → plddt_binder_mean, _i_pAE →
        pae_bt_mean, self_binder_scRMSD → scrmsd_binder) before writing
        sequences.csv, so a map keyed only on the raw names picks up nothing for
        the very layout this extractor documents as its primary input."""
        _csv(
            tmp_path / "sequences.csv",
            [
                {
                    "design_id": "complexa_CALCA_b1_007",
                    "sequence": _SEQ_A,
                    "length": len(_SEQ_A),
                    "iptm": 0.83,
                    "plddt_binder_mean": 0.91,
                    "pae_bt_mean": 4.2,
                    "scrmsd_binder": 1.3,
                    "source": "proteina_complexa",
                }
            ],
        )
        native = ProteinaComplexaExtractor().extract(tmp_path)[0].native
        assert native.complexa_self_iptm == pytest.approx(0.83)
        assert native.complexa_self_plddt == pytest.approx(0.91)
        assert native.complexa_self_ipae == pytest.approx(4.2)
        assert native.complexa_self_scrmsd == pytest.approx(1.3)

    def test_raw_evaluation_names_still_win(self, tmp_path):
        """The generic aliases are appended last, so a CSV carrying both spellings
        keeps the raw evaluation value."""
        _csv(
            tmp_path / "sequences.csv",
            [{"sequence": _SEQ_A, "design_id": "c1", "self_complex_i_pTM": 0.9, "iptm": 0.1}],
        )
        got = ProteinaComplexaExtractor().extract(tmp_path)
        assert got[0].native.complexa_self_iptm == pytest.approx(0.9)


_RESTYPES = "ARNDCQEGHILKMFPSTWYV"


def _aatype(seq: str) -> str:
    """Encode a one-letter sequence the way NVIDIA's top_samples_*.csv does."""
    return ",".join(str(_RESTYPES.index(c)) for c in seq)


class TestProteinaComplexaBinderIsolation:
    """F44(a): the NVIDIA-native ``aatype`` column encodes the WHOLE COMPLEX.

    Measured on three production runs: 2VDY (1000 designs, 500-509 aa against a
    389-aa target), ApoE4/Clara (100 designs, 298-305 aa against 185 aa) and
    ApoE4-iso PC-v3 (4804/4804 rows carrying the 141-aa target as an exact
    prefix). The decoded string is ``target + binder + poly-alanine padding``;
    unstripped it is refolded against the very target it already contains, and
    every iPTM computed for it is meaningless. The binder END is recoverable
    exactly from ``_n_<N>_`` in the job-directory name (verified 1100/1100);
    stripping the trailing alanine run instead is lossy — a clean pool on disk
    has a genuine 7-alanine C-terminus.
    """

    def test_strips_the_declared_target_prefix(self, tmp_path):
        _csv(
            tmp_path / "top_samples_x.csv",
            [{"aatype": _aatype(_SEQ_A + _SEQ_B), "metadata_tag": "mcts_orig1"}],
        )
        got = ProteinaComplexaExtractor(target_sequence=_SEQ_A).extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_B]

    def test_strips_the_poly_alanine_pad_using_the_job_name_length(self, tmp_path):
        n = len(_SEQ_A) + len(_SEQ_B)
        _csv(
            tmp_path / "top_samples_x.csv",
            [
                {
                    "aatype": _aatype(_SEQ_A + _SEQ_B + "A" * 30),
                    "pdb_path": f"job_0_n_{n}_id_3_bon_orig10_r1/sample.pdb",
                    "metadata_tag": "mcts_orig1",
                }
            ],
        )
        got = ProteinaComplexaExtractor(target_sequence=_SEQ_A).extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_B]

    def test_infers_the_target_prefix_when_none_is_declared(self, tmp_path):
        """Every row of a run shares one byte-identical target prefix, so the pool
        itself reveals it. Warn — an inferred boundary is not a declared one."""
        _csv(
            tmp_path / "top_samples_x.csv",
            [
                {"aatype": _aatype(_SEQ_A + _SEQ_B), "metadata_tag": "t1"},
                {"aatype": _aatype(_SEQ_A + _SEQ_B[::-1]), "metadata_tag": "t2"},
            ],
        )
        with pytest.warns(UserWarning, match="inferred"):
            got = ProteinaComplexaExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_B, _SEQ_B[::-1]]

    def test_refuses_to_strip_a_target_that_is_not_a_prefix(self, tmp_path):
        """PC's ``target_input`` can select a sub-range of the configured chain, so
        a declared target need not match what is embedded. Corrupting the binder is
        worse than emitting it unstripped — warn and leave it alone."""
        _csv(tmp_path / "top_samples_x.csv", [{"aatype": _aatype(_SEQ_B), "metadata_tag": "t1"}])
        with pytest.warns(UserWarning, match="not a prefix"):
            got = ProteinaComplexaExtractor(target_sequence=_SEQ_A).extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_B]

    def test_strips_the_pad_by_its_alanine_run_when_the_job_name_has_no_length(self, tmp_path):
        """PC-v3's pdb_path is a bare filename with no ``_n_<N>_`` field, and the CSV
        carries no length column — the alanine run is the only boundary left. 4543 of
        4804 rows in that pool carry one, up to 42 residues long."""
        _csv(
            tmp_path / "top_samples_x.csv",
            [
                {
                    "aatype": _aatype(_SEQ_A + _SEQ_B + "A" * 25),
                    "pdb_path": "orig15-s0to100br1.pdb",
                    "metadata_tag": "t1",
                }
            ],
        )
        got = ProteinaComplexaExtractor(target_sequence=_SEQ_A).extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_B]

    def test_keeps_a_short_genuine_alanine_tail(self, tmp_path):
        """A clean pool on disk ends a real design in 7 alanines, so the pad
        heuristic must not eat a plausible C-terminus."""
        binder = _SEQ_B + "AAA"
        _csv(
            tmp_path / "top_samples_x.csv",
            [{"aatype": _aatype(_SEQ_A + binder), "pdb_path": "orig15.pdb", "metadata_tag": "t1"}],
        )
        got = ProteinaComplexaExtractor(target_sequence=_SEQ_A).extract(tmp_path)
        assert [b.sequence for b in got] == [binder]

    def test_prefers_pcs_own_binder_sequence_column(self, tmp_path):
        """PC's evaluation CSVs carry the binder verbatim — no decode, no arithmetic."""
        _csv(
            tmp_path / "sequences.csv",
            [{"binder_sequence": _SEQ_B, "target_sequence": _SEQ_A, "design_id": "c1"}],
        )
        got = ProteinaComplexaExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_B]

    def test_unresolvable_target_passes_through_and_names_the_remedy(self, tmp_path):
        _csv(tmp_path / "top_samples_x.csv", [{"aatype": _aatype(_SEQ_A), "metadata_tag": "t1"}])
        with pytest.warns(UserWarning, match="--target-seq"):
            got = ProteinaComplexaExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_A]


class TestExtractorFileDiscovery:
    """F44(b): every extractor resolved a multi-match glob with ``matches[0]``.

    Measured: pointing extract at PC-v3's parent kept 96 of 4804 rows (one
    filesystem-order replicate) and at a Clara run 100 of 500; on a normal
    multi-variant run dir BindCraft's ``final_design_stats.csv`` has 4 matches and
    BoltzGen's ``sorted()[-1]`` silently discarded a 700-design pool. A
    wrong-but-nonzero pool passes every downstream guard, so ambiguity must stop
    the run rather than pick.
    """

    def test_ambiguous_native_csvs_fail_loudly(self, tmp_path):
        _csv(tmp_path / "seed_2000" / "top_samples_x.csv", [{"aatype": _aatype(_SEQ_A), "metadata_tag": "t1"}])
        _csv(tmp_path / "seed_2001" / "top_samples_x.csv", [{"aatype": _aatype(_SEQ_B), "metadata_tag": "t2"}])
        with pytest.raises(ValueError, match="seed_2001"):
            ProteinaComplexaExtractor().extract(tmp_path)

    def test_aggregate_replicates_keeps_every_replicate(self, tmp_path):
        _csv(tmp_path / "seed_2000" / "top_samples_x.csv", [{"aatype": _aatype(_SEQ_A), "metadata_tag": "t1"}])
        _csv(tmp_path / "seed_2001" / "top_samples_x.csv", [{"aatype": _aatype(_SEQ_B), "metadata_tag": "t2"}])
        got = ProteinaComplexaExtractor(aggregate_replicates=True).extract(tmp_path)
        assert sorted(b.sequence for b in got) == sorted([_SEQ_A, _SEQ_B])

    def test_top_level_sequences_csv_still_short_circuits(self, tmp_path):
        """The aggregated collector output is the primary layout — a nested stray
        CSV must not turn it into an ambiguity error."""
        _csv(tmp_path / "sequences.csv", [{"sequence": _SEQ_A, "design_id": "c1"}])
        _csv(tmp_path / "nested" / "sequences.csv", [{"sequence": _SEQ_B, "design_id": "c2"}])
        got = ProteinaComplexaExtractor().extract(tmp_path)
        assert [b.sequence for b in got] == [_SEQ_A]

    def test_bindcraft_ambiguous_stats_csv_fails_loudly(self, tmp_path):
        rows = [{"Sequence": _SEQ_A, "Design": "d1", "Average_i_pTM": 0.8}]
        _csv(tmp_path / "bindcraft_default" / "final_design_stats.csv", rows)
        _csv(tmp_path / "bindcraft_variant_a" / "final_design_stats.csv", rows)
        with pytest.raises(ValueError, match=r"final_design_stats\.csv"):
            BindCraftExtractor().extract(tmp_path)

    def test_boltzgen_ambiguous_metrics_csv_fails_loudly(self, tmp_path):
        rows = [{"designed_chain_sequence": _SEQ_A, "id": "b1"}]
        _csv(tmp_path / "boltzgen" / "final_designs_metrics_50.csv", rows)
        _csv(tmp_path / "boltzgen_nanobody" / "final_designs_metrics_700.csv", rows)
        with pytest.raises(ValueError, match="final_designs_metrics"):
            BoltzGenExtractor().extract(tmp_path)


class TestRFD3FastaFallback:
    """F44(a2): the FASTA fallback's 500-aa ceiling rejects 0% of real fusions.

    ``mpnn`` writes the full chain — target prefix + designed binder — and the
    threshold is calibrated on the configurator's binder-length ceiling, not on
    target+binder length, so it only fires when the TARGET alone exceeds ~360 aa.
    Measured on the shipped CALCA run: 1600 .fa files, 8000 sequences, 92-172 aa,
    ZERO rejected, and 8000/8000 carrying the same 32-aa target prefix. The
    correct guard is a shared-prefix check.
    """

    def test_refuses_sequences_that_share_a_target_prefix(self, tmp_path):
        target = "EDEARLLLAALVQDYVQMKASELEQEQEREGS"  # 32 aa, the CALCA helix
        (tmp_path / "mpnn").mkdir()
        for i, binder in enumerate([_SEQ_A, _SEQ_B]):
            (tmp_path / "mpnn" / f"d{i}.fa").write_text(f">d{i}, sequence_recovery=0.45\n{target}{binder}\n")
        with pytest.warns(UserWarning, match="sequences.csv"):
            got = RFD3Extractor().extract(tmp_path)
        assert got == [], "a target+binder fusion must never be emitted as a binder"

    def test_keeps_clean_binder_only_fastas(self, tmp_path):
        (tmp_path / "a.fa").write_text(f">d0\n{_SEQ_A}\n")
        (tmp_path / "b.fa").write_text(f">d1\n{_SEQ_B}\n")
        got = RFD3Extractor().extract(tmp_path)
        assert sorted(b.sequence for b in got) == sorted([_SEQ_A, _SEQ_B])

    def test_mpnns_trailing_comma_is_not_part_of_the_id(self, tmp_path):
        (tmp_path / "d.fa").write_text(f">calca_b0_d0, sequence_recovery=0.4533\n{_SEQ_A}\n")
        assert RFD3Extractor().extract(tmp_path)[0].binder_id == "rfd3_calca_b0_d0"


class TestBinderIdUniqueness:
    """F44(c): a duplicate binder_id is a SILENT DROP, not a crash.

    ``add_design_groups`` keys design_group on binder_id and the report keeps only
    the first row per group, so the colliding design vanishes from the report,
    Top-N, candidates and diversity while surviving in metrics.csv — announced by
    a line indistinguishable from the intended variant collapse. Measured: PC on
    2VDY collapses 1000 designs into 253 ids (75%), and a merged Protein-Hunter
    CSV gives 1654 rows → 1487 ids with all 164 collisions covering *different*
    sequences.
    """

    def test_complexa_colliding_metadata_tags_stay_distinct(self, tmp_path):
        _csv(
            tmp_path / "top_samples_x.csv",
            [
                {"aatype": _aatype(_SEQ_A), "metadata_tag": "mcts_orig1-br0"},
                {"aatype": _aatype(_SEQ_B), "metadata_tag": "mcts_orig1-br0"},
            ],
        )
        with pytest.warns(UserWarning, match="not unique"):
            got = ProteinaComplexaExtractor().extract(tmp_path)
        assert len({b.binder_id for b in got}) == 2

    def test_complexa_ids_carry_the_replicate_seed(self, tmp_path):
        """``metadata_tag`` has no seed in it, so it collides ACROSS replicates —
        the replicate directory name is the only thing that separates them."""
        _csv(
            tmp_path / "run_mcts_seed_2000" / "top_samples_x.csv",
            [{"aatype": _aatype(_SEQ_A), "metadata_tag": "mcts_orig1-br0"}],
        )
        _csv(
            tmp_path / "run_mcts_seed_2001" / "top_samples_x.csv",
            [{"aatype": _aatype(_SEQ_B), "metadata_tag": "mcts_orig1-br0"}],
        )
        got = ProteinaComplexaExtractor(aggregate_replicates=True).extract(tmp_path)
        assert sorted(b.binder_id for b in got) == [
            "complexa_s2000_mcts_orig1-br0",
            "complexa_s2001_mcts_orig1-br0",
        ]

    def test_protein_hunter_colliding_run_ids_stay_distinct(self, tmp_path):
        """run_id restarts at 1 in every replicate, so a merged summary collides."""
        _csv(
            tmp_path / "summary_high_iptm.csv",
            [
                {"sequence": _SEQ_A, "run_id": 1, "cycle": 5, "iptm": 0.80},
                {"sequence": _SEQ_B, "run_id": 1, "cycle": 5, "iptm": 0.81},
            ],
        )
        with pytest.warns(UserWarning, match="not unique"):
            got = ProteinHunterExtractor(collapse_variants=False).extract(tmp_path)
        assert len({b.binder_id for b in got}) == 2


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
