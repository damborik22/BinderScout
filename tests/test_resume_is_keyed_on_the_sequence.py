"""Resume must identify a design by its binder sequence, not its row position.

Two separate defects, one per branch, and this module is the port that carries
both fixes at once:

  - master keyed on the sequence (right) but counted any row holding a sequence
    as finished, so a blank row from a partial OOM was never retried;
  - v2.0.x gated on the score (right) but keyed on the positional ``idx``.

The positional key is not a theoretical risk. 2026-10-28, recorded in master's
own module docstring: ``refold-boltz2`` defaulted its output to the CWD-relative
``./refold_boltz2/`` shared by every run against every target, resume read 1003
``idx`` values out of it, and a 65-design PD-L1 pool had every index "completed".
Boltz-2 refolded 0 of 65 and reported success; nothing in that pool had a
Boltz-2 row to clear the 3-engine gate.

`test_a_foreign_csv_skips_nothing` is that failure, reproduced.
"""

from __future__ import annotations

import csv

from binder_comparison.refolding.resume import (
    completed_sequences,
    partition_sequences,
    resume_plan,
    skip_indices_for_pool,
)

A, B, C = "AAAAKKKK", "CCCCDDDD", "EEEEFFFF"


def _csv(path, rows, cols=("idx", "run_id", "sequence", "iptm")):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cols))
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})
    return path


def test_a_scored_sequence_is_complete(tmp_path):
    p = _csv(tmp_path / "e.csv", [{"idx": 1, "sequence": A, "iptm": "0.8"}])
    assert completed_sequences(p) == {A}


def test_a_blank_row_is_not_complete(tmp_path):
    """The v2.0.x half of the fix: a row without a score is unfinished work."""
    p = _csv(tmp_path / "e.csv", [{"idx": 1, "sequence": A, "iptm": ""}])
    scored, blank = partition_sequences(p)
    assert scored == set()
    assert blank == {A}


def test_a_retry_supersedes_its_own_failed_row(tmp_path):
    """Append-mode CSVs hold the failure AND the retry. Scored wins."""
    p = _csv(tmp_path / "e.csv", [{"idx": 1, "sequence": A, "iptm": ""}, {"idx": 1, "sequence": A, "iptm": "0.9"}])
    scored, blank = partition_sequences(p)
    assert scored == {A}
    assert blank == set(), "a sequence that was later scored must not also count as blank"


def test_a_foreign_csv_skips_nothing(tmp_path):
    """The 2026-10-28 failure, reproduced: 1003 foreign rows, a 65-design pool.

    Under the positional key every one of the 65 indices was 'completed' and the
    engine folded nothing while exiting 0. Keyed on the sequence, a CSV written
    for a different pool is simply irrelevant and the whole pool is folded.
    """
    foreign = [{"idx": i, "sequence": f"FOREIGN{i:04d}SEQ", "iptm": "0.7"} for i in range(1, 1004)]
    p = _csv(tmp_path / "shared.csv", foreign)
    pool = [f"POOLSEQ{i:04d}" for i in range(65)]

    skip, rerun = resume_plan(p, pool)
    assert skip == set(), (
        f"{len(skip)} of 65 designs were skipped against a CSV from an unrelated pool. "
        "This is the bug: Boltz-2 refolded 0 of 65 and reported success."
    )
    assert rerun == 0


def test_positions_are_one_based_and_follow_the_sequence(tmp_path):
    """All three engines enumerate(binder_sequences, start=1)."""
    p = _csv(tmp_path / "e.csv", [{"idx": 99, "sequence": B, "iptm": "0.8"}])
    # B sits third in this pool; its stored idx of 99 is irrelevant.
    assert skip_indices_for_pool([A, C, B], completed_sequences(p)) == {3}


def test_reordering_the_pool_moves_the_skip_with_the_design(tmp_path):
    """The property the positional key lacked: identity travels with the design."""
    p = _csv(tmp_path / "e.csv", [{"idx": 1, "sequence": A, "iptm": "0.8"}])
    done = completed_sequences(p)
    assert skip_indices_for_pool([A, B, C], done) == {1}
    assert skip_indices_for_pool([C, B, A], done) == {3}


def test_case_and_whitespace_do_not_create_a_second_identity(tmp_path):
    p = _csv(tmp_path / "e.csv", [{"idx": 1, "sequence": f"  {A.lower()} ", "iptm": "0.8"}])
    assert skip_indices_for_pool([A], completed_sequences(p)) == {1}


def test_whitespace_is_not_a_score(tmp_path):
    p = _csv(tmp_path / "e.csv", [{"idx": 1, "sequence": A, "iptm": "   "}])
    assert completed_sequences(p) == set()


def test_resume_plan_counts_the_blanks_it_is_repairing(tmp_path):
    """The number that distinguishes "resumed cleanly" from "repairing a failure"."""
    rows = [{"idx": 1, "sequence": A, "iptm": "0.8"}, {"idx": 2, "sequence": B, "iptm": ""}]
    skip, rerun = resume_plan(_csv(tmp_path / "e.csv", rows), [A, B, C])
    assert skip == {1}
    assert rerun == 1, "B's row is blank, so B is being re-run, not resumed"


def test_a_missing_or_junk_csv_means_nothing_is_complete(tmp_path):
    assert completed_sequences(tmp_path / "nope.csv") == set()
    noseq = _csv(tmp_path / "noseq.csv", [{"idx": 1, "iptm": "0.8"}], cols=("idx", "iptm"))
    assert completed_sequences(noseq) == set(), "a CSV with no sequence column cannot identify anything"


def test_a_read_that_fails_part_way_through_completes_nothing(tmp_path):
    """A truncated read must not hand back the rows it managed to parse.

    A NUL byte makes `csv` raise mid-iteration, after the first row is already in
    the set. Returning that partial set would skip designs on the strength of a
    file we could not finish reading -- the same class of error as trusting a
    foreign CSV, arrived at from the other direction. Refusing to skip costs GPU
    time; skipping wrongly costs the pool.
    """
    bad = tmp_path / "truncated.csv"
    bad.write_bytes(b"idx,sequence,iptm\n1," + A.encode() + b",0.9\n2,CCC\x00DDD,0.8\n")
    scored, blank = partition_sequences(bad)
    assert scored == set(), (
        f"a partial read returned {scored}. The first row parsed before the error, so a mutation "
        "that drops the except-branch return would skip that design on a file it never finished."
    )
    assert blank == set()


def test_boltz2s_iptm_aux_is_not_mistaken_for_the_score(tmp_path):
    """Boltz-2's CSV carries both `iptm_aux` and `iptm`; only `iptm` decides."""
    p = _csv(
        tmp_path / "b.csv",
        [{"idx": 1, "sequence": A, "iptm_aux": "0.9", "iptm": ""}],
        cols=("idx", "sequence", "iptm_aux", "iptm"),
    )
    assert completed_sequences(p) == set()
