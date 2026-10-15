"""A space inside a design id must never reach a structure filename unnoticed.

2026-10-14: a hand-written FASTA with ids like ``CALCA-Protein Hunter-01`` was refolded
cleanly -- exit 0, every row scored -- yet 12 designs came out as ``CALCA-Protein_af3.pdb``
and ``__2``..``__6``, because the id is the header's first whitespace token. The metrics
CSV was fine (it joins on sequence); only the structures were unfindable.
"""

from __future__ import annotations

import pytest
from binder_comparison.io.design_ids import header_binder_id, structure_stems
from binder_comparison.io.read import read_fasta
from binder_comparison.io.write import write_fasta


def test_extract_style_header_still_parses():
    assert header_binder_id("bc_l28_s3  source=bindcraft  length=28") == "bc_l28_s3"


def test_bare_and_empty_headers_are_unchanged():
    assert header_binder_id("seq_1") == "seq_1"
    assert header_binder_id("") is None


def test_a_space_inside_the_id_is_refused_not_truncated():
    with pytest.raises(ValueError, match="space inside its id"):
        header_binder_id("CALCA-Protein Hunter-01")


def test_the_id_with_a_space_and_tags_is_also_refused():
    with pytest.raises(ValueError, match="space inside its id"):
        header_binder_id("CALCA-Protein Hunter-01  source=x")


def test_the_writer_keeps_a_spaced_id_whole(tmp_path):
    out = tmp_path / "s.fasta"
    write_fasta(
        ["AAAA", "CCCC"],
        out,
        headers=["CALCA-Protein Hunter-01", "CALCA-Protein Hunter-02"],
        tags=[{"source": "ph"}] * 2,
    )
    ids = [header_binder_id(h) for h, _ in read_fasta(out)]
    assert ids == ["CALCA-Protein_Hunter-01", "CALCA-Protein_Hunter-02"]
    assert len(set(structure_stems(ids, ["a", "b"], engine="af3"))) == 2
    assert all("__" not in s for s in structure_stems(ids, ["a", "b"], engine="af3"))
