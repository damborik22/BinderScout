"""Protein-Hunter's cycle collapse must keep each run's BEST cycle, not merely one of them.

`summary_high_iptm.csv` has a row for every cycle that crossed `--high_iptm_threshold`, so a
run appears several times (CLAUDE.md: CALCA gave 133 rows from 100 designs). The cycles are
snapshots of one hallucination trajectory, so `ProteinHunterExtractor` collapses them to one
design per `run_id`, the highest-ipTM cycle:

    .sort_values("_r", ascending=False).drop_duplicates("run_id", keep="first")

Which cycle survives is the whole point of that expression, and the one thing about it that
fails without a sound. Flip the sort and every multi-cycle run is represented by its WORST
snapshot. Nothing raises, the design count is unchanged, the warning is byte-for-byte the
same ("collapsed 6 cycle-rows → 3 runs (best cycle per run)"), and because Protein-Hunter has
already ipTM-filtered the file every cycle still looks like a respectable design. The pool
handed to the refold engines just holds weaker sequences than the tool produced. That is the
shape of the project's shipped ingestion bugs (exit 0, a plausible full-sized pool, no error
anywhere), though this one has not shipped: it is pinned ahead of time.

Before this file nothing pinned it. `test_extractors.py::TestProteinHunter` collapses two
cycles of run 107 and checks that one row is left whose id starts with `protein_hunter_107`,
a prefix both cycles share, so it passes whichever cycle was kept. BindCraft's collapse is
asserted by value (`test_collapses_mpnn_variants_to_best_per_trajectory` checks the
sequence); Protein-Hunter's was the asymmetry.

The fixture is built so the right answer is never what an easy wrong rule would pick. Run
107's best cycle is not its first row, its last row, its highest or lowest cycle number, or
its best pLDDT, so "keep the first", "keep the last", "keep the latest cycle", "keep the best
pLDDT" and "keep the worst ipTM" each leave a different sequence behind. Runs are interleaved,
so the collapse must key on `run_id` rather than on adjacency, and one run has a single cycle
that must come through untouched however weak it is next to the others.

The last test drives the real `binder-compare extract`, because the FASTA it writes is the
input the refold stage reads.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from binder_comparison.extractors.protein_hunter import ProteinHunterExtractor
from binder_comparison.io.read import read_fasta
from binder_comparison.main import main

_BASE = "ACDEFGHIKLMNPQRSTVWY" * 3  # 60 aa, standard residues only


def _seq(shift: int) -> str:
    """A distinct 60-aa binder per shift, so the pool shows exactly which cycle survived."""
    return _BASE[shift:] + _BASE[:shift]


_R107_C4, _R107_C6, _R107_C7 = _seq(1), _seq(2), _seq(3)
_R108_C2 = _seq(4)
_R109_C3, _R109_C5 = _seq(5), _seq(6)

# In the order Protein-Hunter appends them. Every ipTM is above 0.70, the run template's example
# `--high_iptm_threshold`, as it must be for a row to be in this file at all.
#   run 107  the best cycle (6, ipTM 0.88) is mid-file, mid-range by cycle number and has the
#            LOWEST pLDDT of its run, so no positional or pLDDT rule lands on it by accident.
#   run 108  a single cycle, and the weakest ipTM in the file: it must pass through untouched.
#   run 109  the best cycle (3, ipTM 0.93) comes first and the weaker one (5) trails it.
_ROWS = [
    {"run_id": 107, "cycle": 4, "iptm": 0.80, "plddt": 0.91, "sequence": _R107_C4},
    {"run_id": 108, "cycle": 2, "iptm": 0.71, "plddt": 0.80, "sequence": _R108_C2},
    {"run_id": 107, "cycle": 6, "iptm": 0.88, "plddt": 0.84, "sequence": _R107_C6},
    {"run_id": 109, "cycle": 3, "iptm": 0.93, "plddt": 0.86, "sequence": _R109_C3},
    {"run_id": 107, "cycle": 7, "iptm": 0.74, "plddt": 0.95, "sequence": _R107_C7},
    {"run_id": 109, "cycle": 5, "iptm": 0.90, "plddt": 0.92, "sequence": _R109_C5},
]

# What a correct collapse leaves: (binder_id, sequence) of the best cycle of every run. The cycle
# number is part of the id, so the id alone says which cycle was kept.
_BEST_CYCLES = [
    ("protein_hunter_107_c6", _R107_C6),
    ("protein_hunter_108_c2", _R108_C2),
    ("protein_hunter_109_c3", _R109_C3),
]


def _write_summary(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(_ROWS).to_csv(directory / "summary_high_iptm.csv", index=False)
    return directory


def _collapsed_pool(directory: Path):
    with pytest.warns(UserWarning, match="collapsed"):
        return ProteinHunterExtractor(collapse_variants=True).extract(directory)


def test_each_run_is_represented_by_its_highest_iptm_cycle(tmp_path):
    ph = _write_summary(tmp_path)
    # Uncollapsed, all six cycles are valid pool members - so every sequence missing from the
    # collapsed pool below was removed by the collapse, and the collapse alone chose who stayed.
    assert len(ProteinHunterExtractor(collapse_variants=False).extract(ph)) == len(_ROWS)

    got = _collapsed_pool(ph)

    assert sorted((b.binder_id, b.sequence) for b in got) == _BEST_CYCLES


def test_the_surviving_cycle_keeps_its_own_native_metrics(tmp_path):
    """The ipTM and pLDDT shown next to a design must be the ones of the cycle that was kept."""
    got = _collapsed_pool(_write_summary(tmp_path))

    native = {b.binder_id: (b.native.protein_hunter_iptm_cycle, b.native.protein_hunter_plddt) for b in got}

    assert native == {
        "protein_hunter_107_c6": pytest.approx((0.88, 0.84)),
        "protein_hunter_108_c2": pytest.approx((0.71, 0.80)),
        "protein_hunter_109_c3": pytest.approx((0.93, 0.86)),
    }


def test_the_extract_command_writes_the_best_cycle_of_each_run_to_the_refold_fasta(tmp_path):
    ph = _write_summary(tmp_path / "protein_hunter")
    fasta = tmp_path / "sequences.fasta"

    with pytest.warns(UserWarning, match="collapsed"):
        main(["extract", "--protein-hunter", str(ph), "--output", str(fasta)])

    pool = sorted((header.split()[0], seq) for header, seq in read_fasta(fasta))
    assert pool == _BEST_CYCLES
