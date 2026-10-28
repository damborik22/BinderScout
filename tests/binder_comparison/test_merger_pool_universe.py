"""The report's universe is the `--sequences` FASTA, not the union of engine CSVs.

2026-10-28, PD-L1. `refold-boltz2` had written into a directory shared across runs,
so `boltz2_results.csv` carried 1003 designs from earlier pools and none of the 65
being reported. `merge_refold_results` outer-joined the engines and then LEFT-joined
the FASTA metadata, so all 1068 rows survived: the off-pool designs entered the
near-duplicate collapse, the diversity families and the Top-30, and the primary
ranking column `boltz_pae_ipsae_min` was computed over designs that were never in
the campaign. `source_tool` was simply NaN for them.

An engine CSV legitimately holds more than the current pool — `--resume` depends on
it accumulating. So the fix is to treat the FASTA as the universe at merge time.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from binder_comparison.comparison.merger import merge_refold_results


def _engine_csv(path: Path, rows: list[tuple[str, float]]) -> Path:
    pd.DataFrame(
        [{"idx": i, "sequence": s, "iptm": v, "binder_length": len(s)} for i, (s, v) in enumerate(rows, 1)]
    ).to_csv(path, index=False)
    return path


def _fasta(path: Path, seqs: list[str], tool: str = "mosaic") -> Path:
    path.write_text("".join(f">b{i} source={tool} length={len(s)}\n{s}\n" for i, s in enumerate(seqs, 1)))
    return path


class TestOffPoolRowsAreDropped:
    def test_rows_absent_from_the_fasta_do_not_reach_the_report(self, tmp_path: Path) -> None:
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9), ("STALE", 0.99)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA"])

        with pytest.warns(UserWarning, match="not in"):
            merged = merge_refold_results(boltz, fasta)

        assert list(merged["sequence"]) == ["AAAA"]

    def test_the_pdl1_shape_a_disjoint_cache_yields_an_empty_report_not_a_ranking(self, tmp_path: Path) -> None:
        """The honest outcome. Ranking 1003 off-pool designs was the bug."""
        boltz = _engine_csv(tmp_path / "b.csv", [(f"STALE{i:04d}", 0.9) for i in range(1003)])
        fasta = _fasta(tmp_path / "s.fasta", [f"POOL{i:04d}" for i in range(65)])

        with pytest.warns(UserWarning, match="1003 refold row"):
            merged = merge_refold_results(boltz, fasta)

        assert len(merged) == 0

    def test_a_clean_pool_is_untouched_and_warns_nothing(self, tmp_path: Path) -> None:
        import warnings

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

        with pytest.warns(UserWarning):
            merged = merge_refold_results(boltz, fasta, af3_csv=af3)

        assert list(merged["sequence"]) == ["AAAA"]
        assert merged.loc[0, "boltz_iptm"] == pytest.approx(0.9)
        assert merged.loc[0, "af3_iptm"] == pytest.approx(0.7)

    def test_disjoint_engines_over_a_shared_pool_still_merge(self, tmp_path: Path) -> None:
        """Both engines in-pool but covering different designs — the gate's input."""
        boltz = _engine_csv(tmp_path / "b.csv", [("AAAA", 0.9)])
        af3 = _engine_csv(tmp_path / "a.csv", [("CCCC", 0.7)])
        fasta = _fasta(tmp_path / "s.fasta", ["AAAA", "CCCC"])

        merged = merge_refold_results(boltz, fasta, af3_csv=af3)
        assert set(merged["sequence"]) == {"AAAA", "CCCC"}
        assert merged["boltz_iptm"].notna().sum() == 1
        assert merged["af3_iptm"].notna().sum() == 1
