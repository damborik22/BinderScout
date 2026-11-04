"""Shared ``--resume`` bookkeeping for the three refolding engines.

A design is "already done" when its BINDER SEQUENCE appears in the CSV with a
SCORE. Both halves of that sentence are load-bearing, and each was got wrong on
a different branch -- this module is the port that carries both.

**Key on the sequence, not the row position.** ``idx`` is a position in one
invocation's FASTA, so it means "already done" only while the pool is
byte-identical to the one that wrote the CSV. On 2026-10-28 it was not:
``refold-boltz2`` defaulted its output to the CWD-relative ``./refold_boltz2/``,
shared by every run against every target, and resume read 1003 ``idx`` values out
of it. A 65-design PD-L1 pool therefore had every index "completed" --
**Boltz-2 refolded 0 of 65 while reporting success**, and no design in that pool
had a Boltz-2 row to clear the 3-engine gate. Sequence is also the identity
``comparison/merger.py`` joins the engine CSVs on downstream, so keying resume on
it asks the same question the report later asks.

**Gate on the score, not on the row's existence.** A failed design still gets a
row: ``_empty_row()`` in the AF3 and ESMFold2 runners writes its idx and sequence
with every metric column empty. Counting those as finished skips exactly the
designs a resume exists to repair, so the retry after a partial OOM reproduces
the gap and exits 0. Measured 2026-10-31 on the TfR1 pool, where an ESMFold2 run
OOMed from binder #12 and left 92 blank rows of 100. (Boltz-2 omits a failed
design's row entirely rather than blanking it, so for that engine the gate is
currently a no-op -- kept anyway, because three copies of this logic that
disagree about what "completed" means is how the divergence arose.)

Refusing to skip costs GPU time; skipping wrongly costs the pool. Every failure
path here therefore returns "nothing is complete" rather than guessing.
"""

from __future__ import annotations

import csv
from pathlib import Path

#: The column that decides whether a row is scored. All three engine CSVs carry
#: an engine-neutral ``iptm``; the merger is what prefixes it per engine. Note
#: Boltz-2's CSV also has a separate ``iptm_aux``, which is NOT this column.
SCORE_COL = "iptm"


def _normalise(seq: str) -> str:
    """Canonical form for comparing sequences across CSVs written by different paths."""
    return seq.strip().upper()


def partition_sequences(csv_path: str | Path, score_col: str = SCORE_COL) -> tuple[set[str], set[str]]:
    """``(scored, blank)`` binder sequences present in *csv_path*.

    A sequence appearing both scored and blank -- an append-mode CSV holding a
    failure and its later retry -- counts as scored, which is why the two sets
    are built together rather than by two passes with different predicates.

    Returns two empty sets when the file is missing, unreadable, or has no
    ``sequence`` column.
    """
    path = Path(csv_path)
    if not path.exists():
        return set(), set()
    scored: set[str] = set()
    blank: set[str] = set()
    try:
        with open(path) as fh:
            for row in csv.DictReader(fh):
                raw = row.get("sequence")
                if not raw:
                    continue
                seq = _normalise(raw)
                if not seq:
                    continue
                if (row.get(score_col) or "").strip():
                    scored.add(seq)
                else:
                    blank.add(seq)
    except Exception:
        return set(), set()
    return scored, blank - scored


def completed_sequences(csv_path: str | Path, score_col: str = SCORE_COL) -> set[str]:
    """Binder sequences already present in *csv_path* WITH a score."""
    return partition_sequences(csv_path, score_col)[0]


def skip_indices_for_pool(sequences: list[str], completed: set[str]) -> set[int]:
    """1-based positions in *sequences* whose binder is already in *completed*.

    1-based because that is the contract ``refold_batch(skip_indices=...)`` has
    always had in all three engines; only the way the set is derived changes.
    """
    return {i for i, seq in enumerate(sequences, start=1) if _normalise(seq) in completed}


def resume_plan(csv_path: str | Path, sequences: list[str], score_col: str = SCORE_COL) -> tuple[set[int], int]:
    """``(skip_indices, n_rerun)`` for *sequences* against an existing *csv_path*.

    The one call an engine needs: which 1-based positions to skip, and how many
    of this pool's designs are being re-run because their previous row was blank.
    That second number is worth printing -- it is the difference between "resumed
    cleanly" and "repairing a partial failure", which otherwise look identical.
    """
    scored, blank = partition_sequences(csv_path, score_col)
    skip = skip_indices_for_pool(sequences, scored)
    rerun = sum(1 for seq in sequences if _normalise(seq) in blank)
    return skip, rerun


class ResumeTargetMismatch(ValueError):
    """The CSV being resumed holds scores for these designs against ANOTHER target."""


def sequences_scored_by_target(
    csv_path: str | Path, target_sequence: str, score_col: str = SCORE_COL
) -> tuple[set[str], set[str]]:
    """``(scored_here, scored_elsewhere)`` binder sequences in *csv_path*.

    ``scored_here`` is the sequence-plus-score key of :func:`completed_sequences`, narrowed by the
    row's ``target_sequence`` when the CSV has that column: a row folded against another target is
    not a result for this run. A CSV with no such column cannot be checked and counts, as it does
    in ``evaluate.sh``'s ``pool_coverage`` (which this mirrors, cell for cell). ``scored_elsewhere``
    holds the sequences scored ONLY against a different, non-blank target. A sequence scored
    against both is "here". Any failure to read returns two empty sets: nothing is complete.
    """
    path = Path(csv_path)
    if not path.exists():
        return set(), set()
    target = _normalise(target_sequence)
    here: set[str] = set()
    elsewhere: set[str] = set()
    try:
        with open(path) as fh:
            reader = csv.DictReader(fh)
            has_target = "target_sequence" in (reader.fieldnames or [])
            for row in reader:
                seq = _normalise(row.get("sequence") or "")
                if not seq or not (row.get(score_col) or "").strip():
                    continue
                if not has_target:
                    here.add(seq)
                    continue
                row_target = "".join(_normalise(row.get("target_sequence") or "").split())
                if row_target == "".join(target.split()):
                    here.add(seq)
                elif row_target:
                    elsewhere.add(seq)
    except Exception:
        return set(), set()
    return here, elsewhere - here


def pool_resume_state(
    csv_path: str | Path, sequences: list[str], target_sequence: str, score_col: str = SCORE_COL
) -> tuple[bool, int]:
    """``(complete, n_foreign)`` for *sequences* against an existing *csv_path*.

    ``complete``: the pool is non-empty and EVERY design has a scored row against this target, so a
    refold has nothing to do and must not load a model to find that out. A design with no score
    (absent or blank row) makes it False -- that is the design a resume exists to fold.

    ``n_foreign``: pool designs whose only scored rows are against ANOTHER target. Resume keys on
    the sequence, so it would skip them and publish that other target's scores as this run's;
    a caller must refuse rather than carry on.
    """
    here, elsewhere = sequences_scored_by_target(csv_path, target_sequence, score_col)
    pool = [_normalise(s) for s in sequences]
    complete = bool(pool) and all(s in here for s in pool)
    n_foreign = sum(1 for s in pool if s in elsewhere)
    return complete, n_foreign
