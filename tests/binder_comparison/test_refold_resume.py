"""Regression tests for refold `--resume`: the skip set must be keyed on sequence.

2026-10-28, PD-L1 campaign. `refold-boltz2` is the only engine evaluate.sh invokes
without `--output-dir`, so its structures and its `refold_designs.csv` land in the
CWD-relative default `./refold_boltz2/` — one directory shared by every run against
every target. Resume then read that CSV's positional `idx` column, so 1003 rows left
by earlier pools produced `skip_indices = {1..1003}`, which covers every index in a
65-design pool. Boltz-2 printed:

    [boltz2] Resuming — skipping 1003 already-completed binders
    Processed 0 binder(s).
    [Boltz-2] ok -- 1003 new row(s)

…refolded nothing, and the report ranked 1003 off-pool designs. Zero of the 65 pool
sequences had a Boltz-2 row, so no design cleared the 3-engine gate.

`idx` is a position in *this* invocation's FASTA, not an identity. These tests pin
the skip set to the binder sequence, which is what the CSVs actually join on
(`comparison/merger.py` merges every engine on `sequence`).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from binder_comparison.refolding.resume import completed_sequences, skip_indices_for_pool


def _write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> Path:
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return path


class TestCompletedSequences:
    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert completed_sequences(tmp_path / "nope.csv") == set()

    def test_header_only_is_empty(self, tmp_path: Path) -> None:
        csv_path = _write_csv(tmp_path / "r.csv", [], ["idx", "sequence"])
        assert completed_sequences(csv_path) == set()

    def test_reads_the_sequence_column(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "r.csv",
            [{"idx": "1", "sequence": "AAAA"}, {"idx": "2", "sequence": "CCCC"}],
            ["idx", "sequence"],
        )
        assert completed_sequences(csv_path) == {"AAAA", "CCCC"}

    def test_sequences_are_whitespace_and_case_normalised(self, tmp_path: Path) -> None:
        """Boltz-2 appends rows written by different code paths; don't miss a match on padding."""
        csv_path = _write_csv(tmp_path / "r.csv", [{"idx": "1", "sequence": " aaaa \n"}], ["idx", "sequence"])
        assert completed_sequences(csv_path) == {"AAAA"}

    def test_a_csv_without_a_sequence_column_resumes_nothing(self, tmp_path: Path) -> None:
        """Refusing to skip is the safe failure: it costs GPU time, not correctness."""
        csv_path = _write_csv(tmp_path / "r.csv", [{"idx": "1"}], ["idx"])
        assert completed_sequences(csv_path) == set()

    def test_blank_sequence_cells_are_ignored(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "r.csv",
            [{"idx": "1", "sequence": ""}, {"idx": "2", "sequence": "CCCC"}],
            ["idx", "sequence"],
        )
        assert completed_sequences(csv_path) == {"CCCC"}


class TestSkipIndicesForPool:
    def test_indices_are_one_based_positions_in_this_pool(self) -> None:
        """The downstream contract is unchanged: refold_batch still takes 1-based indices."""
        assert skip_indices_for_pool(["AAAA", "CCCC", "GGGG"], {"CCCC"}) == {2}

    def test_nothing_completed_skips_nothing(self) -> None:
        assert skip_indices_for_pool(["AAAA", "CCCC"], set()) == set()

    def test_all_completed_skips_everything(self) -> None:
        assert skip_indices_for_pool(["AAAA", "CCCC"], {"AAAA", "CCCC"}) == {1, 2}

    def test_the_pdl1_regression_off_pool_rows_skip_nothing(self) -> None:
        """The actual 2026-10-28 failure: a large stale cache, disjoint from the pool.

        Under the old positional rule this returned {1..65}; the pool must now be
        refolded in full because none of its sequences appear in that cache.
        """
        stale = {f"STALE{i:04d}" for i in range(1003)}
        pool = [f"POOL{i:04d}" for i in range(65)]
        assert skip_indices_for_pool(pool, stale) == set()

    def test_a_reordered_pool_skips_the_same_designs_not_the_same_slots(self) -> None:
        """Positional resume broke here too: tool order changes between extract runs."""
        completed = {"AAAA", "GGGG"}
        assert skip_indices_for_pool(["AAAA", "CCCC", "GGGG"], completed) == {1, 3}
        assert skip_indices_for_pool(["GGGG", "CCCC", "AAAA"], completed) == {1, 3}
        assert skip_indices_for_pool(["CCCC", "AAAA", "GGGG"], completed) == {2, 3}

    def test_pool_sequences_are_normalised_the_same_way(self) -> None:
        assert skip_indices_for_pool([" aaaa ", "CCCC"], {"AAAA"}) == {1}

    def test_a_duplicated_pool_sequence_skips_every_occurrence(self) -> None:
        assert skip_indices_for_pool(["AAAA", "CCCC", "AAAA"], {"AAAA"}) == {1, 3}


class TestEveryRunnerUsesTheSharedHelper:
    """Three runners had three private copies of the positional rule; one must remain."""

    RUNNERS = ("boltz2_runner", "af3_runner", "esmfold2_runner")

    @pytest.mark.parametrize("runner", RUNNERS)
    def test_runner_imports_the_shared_resume_helper(self, runner: str) -> None:
        src = (
            Path(__file__).resolve().parents[2] / "Evaluator" / "binder_comparison" / "refolding" / f"{runner}.py"
        ).read_text()
        assert "from .resume import" in src or "from binder_comparison.refolding.resume import" in src

    @pytest.mark.parametrize("runner", RUNNERS)
    def test_runner_no_longer_defines_the_positional_rule(self, runner: str) -> None:
        src = (
            Path(__file__).resolve().parents[2] / "Evaluator" / "binder_comparison" / "refolding" / f"{runner}.py"
        ).read_text()
        assert "_load_completed_indices" not in src, (
            f"{runner} still carries the positional-idx resume helper that lost the PD-L1 Boltz-2 pool on 2026-10-28"
        )
