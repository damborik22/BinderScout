"""The report's universe is the `--sequences` FASTA, not the union of engine CSVs.

A refold CSV written into a directory shared across runs carries designs from
earlier pools and none of the ones being reported. `merge_refold_results`
outer-joins the engines and then LEFT-joins the FASTA metadata, so without a
restriction every off-pool row survives: it enters the near-duplicate collapse, the
diversity families and the Top-30, and the primary ranking column is computed over
designs that were never in the campaign. `source_tool` is simply NaN for them.

An engine CSV legitimately holds more than the current pool (`--resume` depends on
it accumulating), so the fix is to treat the FASTA as the universe at merge time.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pandas as pd
import pytest
from binder_comparison.comparison.merger import merge_refold_results


def _engine_csv(path: Path, rows: list[tuple[str, float]], target: str | None = None) -> Path:
    records = []
    for i, (s, v) in enumerate(rows, 1):
        rec = {"idx": i, "sequence": s, "iptm": v, "binder_length": len(s)}
        if target is not None:
            rec["target_sequence"] = target
        records.append(rec)
    pd.DataFrame(records).to_csv(path, index=False)
    return path


def _fasta(path: Path, seqs: list[str], tool: str = "mosaic") -> Path:
    path.write_text("".join(f">b{i} source={tool} length={len(s)}\n{s}\n" for i, s in enumerate(seqs, 1)))
    return path


class TestOffPoolRowsAreDropped:
    def test_rows_absent_from_the_fasta_do_not_reach_the_report(self, tmp_path: Path) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("STALE", 0.99)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA"])

        with pytest.warns(UserWarning, match="1 refold row"):
            merged = merge_refold_results(boltz, fasta)

        assert list(merged["sequence"]) == ["AAAA"]

    def test_control_without_the_restriction_the_stale_row_would_be_ranked(self, tmp_path: Path) -> None:
        """Same CSV, no FASTA: nothing restricts, so the off-pool row survives. Proves the
        fixture really carries an off-pool row and the test above is not vacuous."""
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("STALE", 0.99)])
        merged = merge_refold_results(boltz, None)
        assert set(merged["sequence"]) == {"AAAA", "STALE"}

    def test_a_disjoint_cache_yields_an_empty_report_and_names_the_count(self, tmp_path: Path) -> None:
        """The honest outcome. Ranking 1003 off-pool designs was the bug."""
        boltz = _engine_csv(tmp_path / "b.csv", [(f"STALE{i:04d}", 0.9) for i in range(1003)])
        fasta = _fasta(tmp_path / "s.fasta", [f"POOL{i:04d}" for i in range(65)])

        with pytest.warns(UserWarning, match="1003 refold row"):
            merged = merge_refold_results(boltz, fasta)

        assert len(merged) == 0

    def test_a_clean_pool_is_untouched_and_warns_nothing(self, tmp_path: Path) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("CCCC", 0.8)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC"])

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            merged = merge_refold_results(boltz, fasta)

        assert set(merged["sequence"]) == {"AAAA", "CCCC"}
        assert set(merged["source_tool"]) == {"mosaic"}

    def test_a_pool_design_no_engine_refolded_is_simply_absent(self, tmp_path: Path) -> None:
        """Restricting must not invent rows: coverage is the engine guard's job."""
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA", "NOTREFOLDED"])

        merged = merge_refold_results(boltz, fasta)
        assert list(merged["sequence"]) == ["AAAA"]

    def test_whitespace_and_case_do_not_drop_a_real_pool_design(self, tmp_path: Path) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("aaaa", 0.9)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA"])

        merged = merge_refold_results(boltz, fasta)
        assert len(merged) == 1

    def test_no_fasta_means_no_universe_and_no_restriction(self, tmp_path: Path) -> None:
        """`report` can be run without --sequences; that path must keep every row."""
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("STALE", 0.99)])

        merged = merge_refold_results(boltz, None)
        assert len(merged) == 2


class TestRestrictionAppliesAcrossEngines:
    def test_a_second_engines_off_pool_rows_are_dropped_too(self, tmp_path: Path) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9)])
        af3 = _engine_csv(tmp_path / "a.csv", [("AAAA", 0.7), ("OTHERPOOL", 0.95)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA"])

        with pytest.warns(UserWarning, match="1 refold row"):
            merged = merge_refold_results(boltz, fasta, af3_csv=af3)

        assert list(merged["sequence"]) == ["AAAA"]
        assert merged.loc[0, "boltz_iptm"] == pytest.approx(0.9)
        assert merged.loc[0, "af3_iptm"] == pytest.approx(0.7)

    def test_disjoint_engines_over_a_shared_pool_still_merge(self, tmp_path: Path) -> None:
        """Both engines in-pool but covering different designs: the gate's input."""
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9)])
        af3 = _engine_csv(tmp_path / "a.csv", [("CCCC", 0.7)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC"])

        merged = merge_refold_results(boltz, fasta, af3_csv=af3)
        assert set(merged["sequence"]) == {"AAAA", "CCCC"}
        assert merged["boltz_iptm"].notna().sum() == 1
        assert merged["af3_iptm"].notna().sum() == 1


class TestItComposesWithTheOtherMergerGuards:
    def test_canonical_join_key_a_lowercase_engine_row_is_kept_and_joins_across_engines(self, tmp_path: Path) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("aaaa", 0.9), ("STALE", 0.5)])
        af3 = _engine_csv(tmp_path / "a.csv", [(" AAAA ", 0.7)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA"])

        with pytest.warns(UserWarning, match="1 refold row"):
            merged = merge_refold_results(boltz, fasta, af3_csv=af3)

        assert len(merged) == 1
        assert merged.loc[0, "boltz_iptm"] == pytest.approx(0.9)
        assert merged.loc[0, "af3_iptm"] == pytest.approx(0.7)

    def test_identity_coalescing_still_fills_binder_length_from_the_later_engine(self, tmp_path: Path) -> None:
        """The first engine lacks the design; the later engine's passthrough copy must survive."""
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("STALE", 0.5)])
        af3 = _engine_csv(tmp_path / "a.csv", [("CCCCCC", 0.7)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCCCC"])

        with pytest.warns(UserWarning, match="1 refold row"):
            merged = merge_refold_results(boltz, fasta, af3_csv=af3)

        by_seq = merged.set_index("sequence")
        assert by_seq.loc["CCCCCC", "binder_length"] == 6
        assert by_seq.loc["AAAA", "binder_length"] == 4

    def test_the_target_mismatch_guard_still_refuses_an_in_pool_design(self, tmp_path: Path) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("STALE", 0.5)], target="TARGETONE")
        af3 = _engine_csv(tmp_path / "a.csv", [("AAAA", 0.7)], target="TARGETTWO")
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA"])

        with pytest.raises(ValueError, match="disagree about the target"):
            merge_refold_results(boltz, fasta, af3_csv=af3)

    def test_the_engine_count_banner_counts_the_pool_not_the_stale_rows(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("STALE1", 0.5), ("STALE2", 0.5)])
        af3 = _engine_csv(tmp_path / "a.csv", [("AAAA", 0.7)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA"])

        with pytest.warns(UserWarning):
            merge_refold_results(boltz, fasta, af3_csv=af3)

        assert "1 unique sequences" in capsys.readouterr().out


def test_a_lowercase_or_padded_fasta_entry_still_matches_an_uppercase_engine_row(tmp_path):
    """The POOL side of the comparison is normalised too (found in review: nothing pinned it).

    On this line `_load_engine` already canonicalises the engine CSV, so only the FASTA side can differ; without
    normalising it a real pool design was silently dropped from the report.
    """
    fasta = tmp_path / "pool.fasta"
    fasta.write_text(">b1 source=mosaic\n  aaaa \n")
    csv = tmp_path / "boltz.csv"
    pd.DataFrame([{"idx": 1, "sequence": "AAAA", "target_sequence": "T" * 10, "binder_length": 4, "iptm": 0.8}]).to_csv(
        csv, index=False
    )
    merged = merge_refold_results(csv, sequences_fasta=fasta)
    assert len(merged) == 1, "a real pool design was dropped because the FASTA entry was lower-case / padded"
