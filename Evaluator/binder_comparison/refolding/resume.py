"""Shared `--resume` bookkeeping for the three refolding engines.

The skip set is keyed on the **binder sequence**, never on a row's positional
``idx``. ``idx`` is a position in one invocation's FASTA, so it only means
"already done" when the pool is byte-identical to the one that wrote the CSV.

2026-10-28: it was not. ``refold-boltz2`` writes into the CWD-relative default
``./refold_boltz2/``, shared by every run against every target, and resume read
1003 ``idx`` values out of it. A 65-design PD-L1 pool therefore had every index
"completed", Boltz-2 refolded 0 of 65 while reporting success, and no design in
the pool had a Boltz-2 row to clear the 3-engine gate. Sequence is also what the
engine CSVs are merged on downstream (``comparison/merger.py``), so keying resume
on it is the same identity the report uses.
"""

from __future__ import annotations

import csv
from pathlib import Path


def _normalise(seq: str) -> str:
    """Canonical form for comparing sequences across CSVs written by different paths."""
    return seq.strip().upper()


def completed_sequences(csv_path: str | Path) -> set[str]:
    """Binder sequences already present in *csv_path*.

    Returns an empty set when the file is missing, unreadable, or has no
    ``sequence`` column — refusing to skip costs GPU time, never correctness.
    """
    path = Path(csv_path)
    if not path.exists():
        return set()
    try:
        with open(path) as f:
            return {
                _normalise(row["sequence"])
                for row in csv.DictReader(f)
                if row.get("sequence") and _normalise(row["sequence"])
            }
    except Exception:
        return set()


def skip_indices_for_pool(sequences: list[str], completed: set[str]) -> set[int]:
    """1-based positions in *sequences* whose binder is already in *completed*.

    1-based because that is the contract ``refold_batch(skip_indices=...)`` has
    always had; only the way the set is derived changes.
    """
    return {i for i, seq in enumerate(sequences, start=1) if _normalise(seq) in completed}
