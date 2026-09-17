"""Tests for the BindCraft 2 extractor.

BindCraft 2 is the one extractor that has to read two different schemas. The
pools already archived in this project came from a pre-1.0 build (TitleCase
``Rank`` / ``Design`` / ``Sequence`` in a flat ``<target>_ranked.csv``); the
shipped v1.0.0 writes lowercase ``rank`` / ``design`` / ``Binder_Sequence`` into
``3_Ranked/!_Ranked.csv``. Both are exercised here, because an extractor that
reads only the documented one cannot re-report our own archive.

The fixtures mirror the real delivered files rather than an idealised CSV:

* CBG has 62 columns and CALCA 60 — a metric column exists only if the campaign
  set a threshold for it, so every native read must be optional.
* ``Notes`` legitimately contains a semicolon in both pools. That is why the
  multi-target guard reads the targets column and not "any ';' in the row": the
  obvious implementation of the latter rejects both real files.
* ``i_pDAE`` ties are pervasive (a 17-way tie in CALCA), so rank is only ever
  non-increasing in that metric, never strictly decreasing.
"""

import sys
import warnings
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Evaluator"))
from binder_comparison.extractors import BindCraft2Extractor

_SEQ_A = "ACDEFGHIKLMNPQRSTVWY" * 3
_SEQ_B = "MKTAYIAKQRQISFVKSHFS" * 3
_SEQ_C = "GSGSGSEIQLVESGGGLVQP" * 3

_NOTE = "Structure contains clashes. Low absorption (0.74); consider adding a tryptophan."


def _legacy_rows():
    """Three rows in the pre-1.0 vocabulary, as delivered for CBG."""
    return [
        {
            "Rank": 1,
            "Design": "CBG_l60_aaa_seq3",
            "Targets": "CBG",
            "Target_Weights": 1,
            "Length": 60,
            "Sequence": _SEQ_A,
            "pLDDT": 0.85,
            "pTM": 0.91,
            "i_pTM": 0.86,
            "i_pAE": 0.25,
            "i_pDAE": 0.42,
            "Target_pLDDT": 0.89,
            "Target_RMSD": 1.33,
            "Backbone_Clashes": 0,
            "Interface_Residues": 34,
            "Notes": _NOTE,
        },
        {
            "Rank": 2,
            "Design": "CBG_l60_bbb_seq1",
            "Targets": "CBG",
            "Target_Weights": 1,
            "Length": 60,
            "Sequence": _SEQ_B,
            "pLDDT": 0.88,
            "pTM": 0.89,
            "i_pTM": 0.91,
            "i_pAE": 0.24,
            "i_pDAE": 0.39,
            "Target_pLDDT": 0.89,
            "Target_RMSD": 0.34,
            "Backbone_Clashes": 5,
            "Interface_Residues": 28,
            "Notes": _NOTE,
        },
        {
            "Rank": 3,
            "Design": "CBG_l60_ccc_seq2",
            "Targets": "CBG",
            "Target_Weights": 1,
            "Length": 60,
            "Sequence": _SEQ_C,
            "pLDDT": 0.80,
            "pTM": 0.85,
            "i_pTM": 0.88,
            "i_pAE": 0.30,
            "i_pDAE": 0.39,
            "Target_pLDDT": 0.85,
            "Target_RMSD": 2.10,
            "Backbone_Clashes": 2,
            "Interface_Residues": 21,
            "Notes": _NOTE,
        },
    ]


def _modern_rows():
    """The same designs in the v1.0.0 vocabulary."""
    return [
        {
            "rank": 1,
            "design": "pdl1_denovo_l60_aaa_seq0",
            "targets": "hPDL1",
            "target_weights": 1,
            "length": 60,
            "Binder_Sequence": _SEQ_A,
            "i_pDAE": 0.42,
            "i_pTM": 0.86,
            "pLDDT": 0.85,
            "pTM": 0.91,
            "i_pAE": 0.25,
            "Interface_Residues": 34,
            "Backbone_Clashes": 0,
        },
        {
            "rank": 2,
            "design": "pdl1_denovo_l60_bbb_seq1",
            "targets": "hPDL1",
            "target_weights": 1,
            "length": 60,
            "Binder_Sequence": _SEQ_B,
            "i_pDAE": 0.39,
            "i_pTM": 0.91,
            "pLDDT": 0.88,
            "pTM": 0.89,
            "i_pAE": 0.24,
            "Interface_Residues": 28,
            "Backbone_Clashes": 5,
        },
    ]


def _write(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


class TestBothSchemas:
    def test_reads_the_v1_stage_layout(self, tmp_path):
        _write(tmp_path / "3_Ranked" / "!_Ranked.csv", _modern_rows())
        got = BindCraft2Extractor().extract(tmp_path)
        assert [b.binder_id for b in got] == [
            "bindcraft2_pdl1_denovo_l60_aaa_seq0",
            "bindcraft2_pdl1_denovo_l60_bbb_seq1",
        ]
        assert got[0].native.bindcraft2_ipdae == pytest.approx(0.42)

    def test_reads_the_pre_1_0_delivered_layout(self, tmp_path):
        _write(tmp_path / "CBG_ranked.csv", _legacy_rows())
        got = BindCraft2Extractor().extract(tmp_path)
        assert len(got) == 3
        assert got[0].binder_id == "bindcraft2_CBG_l60_aaa_seq3"
        assert got[0].sequence == _SEQ_A
        assert got[0].source_tool == "bindcraft2"

    def test_native_metrics_survive_from_both(self, tmp_path):
        """i_pDAE is the one the first hand-written ingest dropped."""
        for name, rows in (("3_Ranked/!_Ranked.csv", _modern_rows()), ("ranked.csv", _legacy_rows())):
            d = tmp_path / name.replace("/", "_")
            _write(d / name, rows)
            got = BindCraft2Extractor().extract(d)
            assert got[0].native.bindcraft2_ipdae == pytest.approx(0.42)
            assert got[0].native.bindcraft2_iptm == pytest.approx(0.86)
            # pLDDT is ALREADY 0-1 here, unlike AF3's 0-100 — never rescale it.
            assert 0.0 <= got[0].native.bindcraft2_plddt <= 1.0


class TestNativeRank:
    def test_rank_comes_from_the_file_and_is_not_recomputed(self, tmp_path):
        """Ranks 2 and 3 tie on i_pDAE; the file's order must survive."""
        rows = _legacy_rows()
        shuffled = [rows[2], rows[0], rows[1]]  # as if the CSV were re-sorted
        _write(tmp_path / "CBG_ranked.csv", shuffled)
        got = BindCraft2Extractor().extract(tmp_path)
        assert [b.binder_id for b in got] == [
            "bindcraft2_CBG_l60_aaa_seq3",
            "bindcraft2_CBG_l60_bbb_seq1",
            "bindcraft2_CBG_l60_ccc_seq2",
        ]

    def test_ipdae_is_only_non_increasing_not_strictly_decreasing(self, tmp_path):
        _write(tmp_path / "CBG_ranked.csv", _legacy_rows())
        got = BindCraft2Extractor().extract(tmp_path)
        vals = [b.native.bindcraft2_ipdae for b in got]
        assert vals == sorted(vals, reverse=True)
        assert len(set(vals)) < len(vals), "fixture must contain a tie, as the real data does"

    def test_a_rank_column_that_is_not_1_to_n_warns_but_still_extracts(self, tmp_path):
        rows = [dict(r, Rank=r["Rank"] + 10) for r in _legacy_rows()]
        _write(tmp_path / "CBG_ranked.csv", rows)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            got = BindCraft2Extractor().extract(tmp_path)
        assert len(got) == 3
        assert any("not 1..3" in str(x.message) for x in w)


class TestGuards:
    def test_a_semicolon_in_notes_does_not_look_like_multi_target(self, tmp_path):
        """The real delivered pools both carry ';' in Notes and must still parse."""
        _write(tmp_path / "CBG_ranked.csv", _legacy_rows())
        got = BindCraft2Extractor().extract(tmp_path)
        assert len(got) == 3

    def test_multi_target_export_is_refused(self, tmp_path):
        rows = [dict(r, Targets="CBG;CBG_off", i_pDAE="0.42;0.31") for r in _legacy_rows()]
        _write(tmp_path / "CBG_ranked.csv", rows)
        with pytest.raises(ValueError, match="multi-target"):
            BindCraft2Extractor().extract(tmp_path)

    def test_multi_chain_binder_is_skipped_not_concatenated(self, tmp_path):
        rows = _legacy_rows()
        rows[1]["Sequence"] = f"{_SEQ_B}/{_SEQ_C}"
        _write(tmp_path / "CBG_ranked.csv", rows)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            got = BindCraft2Extractor().extract(tmp_path)
        assert len(got) == 2
        assert all("/" not in b.sequence for b in got)
        assert any("multi-chain" in str(x.message) for x in w)

    def test_the_trajectory_and_candidate_tables_are_never_read(self, tmp_path):
        """1_Trajectories holds PRE-ProteinMPNN sequences; 2_Refolded holds rejects."""
        _write(tmp_path / "1_Trajectories" / "!_Trajectories.csv", _modern_rows())
        _write(tmp_path / "2_Refolded" / "!_Refolded.csv", _modern_rows())
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert BindCraft2Extractor().extract(tmp_path) == []

    @pytest.mark.parametrize("decoy", ["accepted.csv", "ranked_by_i_pTM.csv", "filtered.csv"])
    def test_lookalike_tables_are_not_mistaken_for_the_ranked_one(self, tmp_path, decoy):
        """accepted.csv has no rank column; the other two are user re-sorts/subsets."""
        _write(tmp_path / decoy, _legacy_rows())
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            assert BindCraft2Extractor().extract(tmp_path) == []

    def test_nan_sequence_is_skipped_before_str(self, tmp_path):
        """str(nan) is 'NAN', which passes the amino-acid validator."""
        rows = _legacy_rows()
        rows[1]["Sequence"] = None
        _write(tmp_path / "CBG_ranked.csv", rows)
        got = BindCraft2Extractor().extract(tmp_path)
        assert len(got) == 2
        assert all(b.sequence != "NAN" for b in got)

    def test_ambiguous_glob_refuses_to_guess(self, tmp_path):
        _write(tmp_path / "a" / "CBG_ranked.csv", _legacy_rows())
        _write(tmp_path / "b" / "CALCA_ranked.csv", _legacy_rows())
        with pytest.raises(ValueError, match="refusing to guess"):
            BindCraft2Extractor().extract(tmp_path)

    def test_colliding_design_names_stay_distinct(self, tmp_path):
        rows = [dict(r, Design="same") for r in _legacy_rows()]
        _write(tmp_path / "CBG_ranked.csv", rows)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            got = BindCraft2Extractor().extract(tmp_path)
        assert len({b.binder_id for b in got}) == 3


class TestCampaignDependentColumns:
    def test_a_60_column_export_without_target_rmsd_still_parses(self, tmp_path):
        """CALCA's IDR-protocol export has no Target_RMSD and no hotspot column."""
        rows = [{k: v for k, v in r.items() if k != "Target_RMSD"} for r in _legacy_rows()]
        _write(tmp_path / "CALCA_ranked.csv", rows)
        got = BindCraft2Extractor().extract(tmp_path)
        assert len(got) == 3
        assert got[0].native.bindcraft2_target_rmsd is None
        assert got[0].native.bindcraft2_ipdae == pytest.approx(0.42)

    def test_sequence_is_upper_cased_and_stripped(self, tmp_path):
        """Every downstream join is on the sequence string."""
        rows = _legacy_rows()
        rows[0]["Sequence"] = f"  {_SEQ_A.lower()}  "
        _write(tmp_path / "CBG_ranked.csv", rows)
        got = BindCraft2Extractor().extract(tmp_path)
        assert got[0].sequence == _SEQ_A

    def test_crlf_file_with_no_trailing_newline_yields_every_row(self, tmp_path):
        """Exactly the shape of the delivered files, which end mid-token.

        Both archived pools are CRLF and neither ends with a newline. A parser
        that splits on "\\n" and drops the last element loses design 50 — the
        best-ranked designs survive and the worst silently vanishes, which is
        the kind of truncation that looks like a complete run.
        """
        rows = _legacy_rows()
        header = ",".join(rows[0].keys())
        lines = [header] + [",".join(str(r[k]).replace(",", ";") for k in rows[0]) for r in rows]
        path = tmp_path / "CBG_ranked.csv"
        path.write_bytes("\r\n".join(lines).encode())  # no trailing newline, as delivered
        assert not path.read_bytes().endswith(b"\n")

        got = BindCraft2Extractor().extract(tmp_path)
        assert len(got) == 3, "the last row must not be lost to the missing newline"
        assert got[-1].binder_id == "bindcraft2_CBG_l60_ccc_seq2"
