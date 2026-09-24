"""Discovery rank must never be inferred from row position.

Item AD wants a per-design `generation_index` so a report can say how early in a
campaign a good design appeared. The plan assumed this was one line per
extractor -- glob the per-design files, take an mtime. The source investigation
(docs/INVESTIGATION_generation_index_2026-09-24.md) found otherwise: seven of
eight extractors read a single aggregate CSV, and **row position is not usable
for any tool**. Where the file happens to be in generation order the extractor
re-sorts before iterating; where it does not, the order is a quality sort.

So the index has to come from something the tool itself recorded, and for two
tools nothing was recorded at all. That makes `unavailable` a real answer rather
than a gap to paper over, and these tests exist to keep it one: a tool whose
output is quality-sorted must NOT emit a plausible-looking index, because a
quality-sorted index inverts the very thing the metric measures.

`generation_index_source` records which route produced the value, so a consumer
can tell a tool-recorded counter from a parsed identifier from nothing at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pandas")

from binder_comparison.core.schema import ExtractedBinder
from binder_comparison.extractors.mosaic import MosaicExtractor

# Columns a current Mosaic designs.csv carries, generation_index LAST (see
# tests/test_mosaic_csv_append_alignment.py for why the position is load-bearing).
MOSAIC_COLUMNS = [
    "worker_id",
    "rank",
    "is_top",
    "sequence",
    "target_sequence",
    "binder_length",
    "ranking_loss",
    "generation_index",
]

SEQS = ["MKTAYIAKQRQISFVK", "GGSGGSWELVKQRQIS", "AAKEWLNQRQISFVKA"]


def _write_mosaic_csv(tmp_path: Path, rows: list[dict], columns: list[str] | None = None) -> Path:
    columns = columns or MOSAIC_COLUMNS
    path = tmp_path / "designs.csv"
    with path.open("w") as fh:
        fh.write(",".join(columns) + "\n")
        for row in rows:
            fh.write(",".join(str(row.get(c, "")) for c in columns) + "\n")
    return path


def test_extracted_binder_carries_generation_provenance() -> None:
    """The schema must be able to say 'I do not know', and default to it."""
    binder = ExtractedBinder(binder_id="x", sequence="MKT", source_tool="mosaic")
    assert binder.generation_index is None
    assert binder.generation_index_source == "unavailable", (
        "the default must be the honest one -- a tool that records nothing must not "
        "silently inherit a source that implies it did"
    )


def test_mosaic_reads_its_recorded_generation_index(tmp_path: Path) -> None:
    """Mosaic captures the index at candidate append, BEFORE its two quality
    sorts, so the column is a true generation counter."""
    rows = [
        # rank order (quality) is deliberately the REVERSE of generation order,
        # so reading row position instead of the column would be detectable.
        {"worker_id": 0, "rank": 1, "is_top": 1, "sequence": SEQS[0], "ranking_loss": 0.1, "generation_index": 12},
        {"worker_id": 0, "rank": 2, "is_top": 1, "sequence": SEQS[1], "ranking_loss": 0.2, "generation_index": 5},
        {"worker_id": 0, "rank": 3, "is_top": 1, "sequence": SEQS[2], "ranking_loss": 0.3, "generation_index": 0},
    ]
    _write_mosaic_csv(tmp_path, rows)

    binders = MosaicExtractor().extract(tmp_path)

    assert len(binders) == 3
    by_seq = {b.sequence: b for b in binders}
    assert by_seq[SEQS[0]].generation_index == 12
    assert by_seq[SEQS[1]].generation_index == 5
    assert by_seq[SEQS[2]].generation_index == 0, (
        "generation_index must come from the column, not from row position -- "
        "row position here is the quality sort, which is its reverse"
    )
    assert all(b.generation_index_source == "explicit" for b in binders)


def test_mosaic_without_the_column_reports_unavailable(tmp_path: Path) -> None:
    """An older designs.csv predates the column. That is 'unavailable', not 0,
    and not the row number."""
    columns = [c for c in MOSAIC_COLUMNS if c != "generation_index"]
    rows = [
        {"worker_id": 0, "rank": 1, "is_top": 1, "sequence": SEQS[0], "ranking_loss": 0.1},
        {"worker_id": 0, "rank": 2, "is_top": 1, "sequence": SEQS[1], "ranking_loss": 0.2},
    ]
    _write_mosaic_csv(tmp_path, rows, columns=columns)

    binders = MosaicExtractor().extract(tmp_path)

    assert len(binders) == 2
    assert all(b.generation_index is None for b in binders)
    assert all(b.generation_index_source == "unavailable" for b in binders)


def test_mosaic_blank_generation_index_is_unavailable(tmp_path: Path) -> None:
    """A resumed run whose checkpoint predates the column writes the row with an
    empty generation_index. Per-row, that is unavailable."""
    rows = [
        {"worker_id": 0, "rank": 1, "is_top": 1, "sequence": SEQS[0], "ranking_loss": 0.1, "generation_index": 3},
        {"worker_id": 0, "rank": 2, "is_top": 1, "sequence": SEQS[1], "ranking_loss": 0.2, "generation_index": ""},
    ]
    _write_mosaic_csv(tmp_path, rows)

    binders = MosaicExtractor().extract(tmp_path)
    by_seq = {b.sequence: b for b in binders}

    assert by_seq[SEQS[0]].generation_index == 3
    assert by_seq[SEQS[0]].generation_index_source == "explicit"
    assert by_seq[SEQS[1]].generation_index is None
    assert by_seq[SEQS[1]].generation_index_source == "unavailable"


# --------------------------------------------------------------------------
# Protein-Hunter: run_id IS the generation counter (run_id = str(design_id)
# for design_id in range(num_designs)). But the extractor sorts by iptm and
# drops duplicates before iterating, so row position is emphatically not it.
# --------------------------------------------------------------------------

PH_HIGH_IPTM_COLUMNS = ["run_id", "cycle", "iptm", "plddt", "alanine_count", "sequence"]


def _write_ph_csv(tmp_path: Path, name: str, columns: list[str], rows: list[dict]) -> Path:
    path = tmp_path / name
    with path.open("w") as fh:
        fh.write(",".join(columns) + "\n")
        for row in rows:
            fh.write(",".join(str(row.get(c, "")) for c in columns) + "\n")
    return path


def test_protein_hunter_reads_run_id_not_row_position(tmp_path: Path) -> None:
    """The extractor re-sorts by iptm before iterating, so a row-position index
    would come out in quality order. run_id survives that sort."""
    from binder_comparison.extractors.protein_hunter import ProteinHunterExtractor

    rows = [
        # run 7 was generated last but scores best -- it sorts to the top.
        {"run_id": 0, "cycle": 1, "iptm": 0.62, "plddt": 0.81, "alanine_count": 1, "sequence": SEQS[0]},
        {"run_id": 3, "cycle": 2, "iptm": 0.71, "plddt": 0.83, "alanine_count": 1, "sequence": SEQS[1]},
        {"run_id": 7, "cycle": 1, "iptm": 0.95, "plddt": 0.90, "alanine_count": 0, "sequence": SEQS[2]},
    ]
    _write_ph_csv(tmp_path, "summary_high_iptm.csv", PH_HIGH_IPTM_COLUMNS, rows)

    binders = ProteinHunterExtractor().extract(tmp_path)
    by_seq = {b.sequence: b for b in binders}

    assert by_seq[SEQS[2]].generation_index == 7, (
        "the best-scoring design was generated LAST; a row-position index would "
        "report it as 0 because the extractor sorts by iptm first"
    )
    assert by_seq[SEQS[0]].generation_index == 0
    assert by_seq[SEQS[1]].generation_index == 3
    assert all(b.generation_index_source == "explicit" for b in binders)


# --------------------------------------------------------------------------
# BoltzGen: the pool it reads is a budget-and-diversity selection sorted by
# final_rank, but the `id` column's trailing integer is BoltzGen's own
# global_idx (sample_idx * n_samples + n), zero-padded at write time.
# --------------------------------------------------------------------------

BG_COLUMNS = ["id", "designed_chain_sequence", "final_rank"]


def test_boltzgen_parses_global_idx_from_id(tmp_path: Path) -> None:
    from binder_comparison.extractors.boltzgen import BoltzGenExtractor

    path = tmp_path / "final_designs_metrics_100.csv"
    with path.open("w") as fh:
        fh.write(",".join(BG_COLUMNS) + "\n")
        # final_rank order is the file's order and is pure quality -- the
        # generation indices deliberately run the other way.
        fh.write(f"config_2416,{SEQS[0]},1\n")
        fh.write(f"config_0007,{SEQS[1]},2\n")
        fh.write(f"config_6401,{SEQS[2]},3\n")

    binders = BoltzGenExtractor().extract(tmp_path)
    by_seq = {b.sequence: b for b in binders}

    assert by_seq[SEQS[0]].generation_index == 2416
    assert by_seq[SEQS[1]].generation_index == 7, "zero-padding must not survive into the value"
    assert by_seq[SEQS[2]].generation_index == 6401
    assert all(b.generation_index_source == "parsed" for b in binders)


def test_boltzgen_id_without_a_trailing_integer_is_unavailable(tmp_path: Path) -> None:
    from binder_comparison.extractors.boltzgen import BoltzGenExtractor

    path = tmp_path / "final_designs_metrics_100.csv"
    with path.open("w") as fh:
        fh.write(",".join(BG_COLUMNS) + "\n")
        fh.write(f"some_design_name,{SEQS[0]},1\n")

    binders = BoltzGenExtractor().extract(tmp_path)
    assert binders[0].generation_index is None
    assert binders[0].generation_index_source == "unavailable"


# --------------------------------------------------------------------------
# RFD3: no column. The true order is (batch_id, model_idx) from the filename,
# and OUR OWN run script sorts those lexicographically -- so `_10_` lands
# before `_2_` for any run with >=10 batches. The templates use 88.
# --------------------------------------------------------------------------

RFD3_COLUMNS = ["design_id", "sequence", "length", "backbone", "source"]


def test_rfd3_orders_numerically_not_lexicographically(tmp_path: Path) -> None:
    from binder_comparison.extractors.rfd3 import RFD3Extractor

    path = tmp_path / "sequences.csv"
    rows = [
        # written in the lexicographic order our run script produces
        ("rfd3_helix_binder_10_model_0", SEQS[0]),
        ("rfd3_helix_binder_2_model_0", SEQS[1]),
        ("rfd3_helix_binder_2_model_1", SEQS[2]),
    ]
    with path.open("w") as fh:
        fh.write(",".join(RFD3_COLUMNS) + "\n")
        for design_id, seq in rows:
            fh.write(f"{design_id},{seq},{len(seq)},{design_id.removeprefix('rfd3_')},rfd3\n")

    binders = RFD3Extractor().extract(tmp_path)
    by_seq = {b.sequence: b for b in binders}

    # batch 2 precedes batch 10, whatever the file order said.
    assert by_seq[SEQS[1]].generation_index < by_seq[SEQS[0]].generation_index, (
        "batch 2 must precede batch 10 -- lexicographic order puts _10_ first"
    )
    assert by_seq[SEQS[1]].generation_index < by_seq[SEQS[2]].generation_index, (
        "within a batch, model_0 precedes model_1"
    )
    assert all(b.generation_index_source == "parsed" for b in binders)


def test_rfd3_unparseable_design_id_is_unavailable(tmp_path: Path) -> None:
    from binder_comparison.extractors.rfd3 import RFD3Extractor

    path = tmp_path / "sequences.csv"
    with path.open("w") as fh:
        fh.write(",".join(RFD3_COLUMNS) + "\n")
        fh.write(f"rfd3_handwritten_name,{SEQS[0]},{len(SEQS[0])},handwritten_name,rfd3\n")

    binders = RFD3Extractor().extract(tmp_path)
    assert binders[0].generation_index is None
    assert binders[0].generation_index_source == "unavailable"
