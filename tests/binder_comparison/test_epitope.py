"""Tests for Phase 3 Item 2 — epitope-match fraction (target-side interface overlap)."""

import math
from pathlib import Path

import pytest

pytest.importorskip("pandas")
from binder_comparison.comparison.epitope import (
    Hotspot,
    epitope_match,
    extract_interface_residues,
    parse_hotspots,
)


def _write_pdb(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "complex.pdb"
    p.write_text("\n".join(lines) + "\n")
    return p


def _ca_line(serial: int, chain: str, resnum: int, x: float, y: float, z: float) -> str:
    # PDB ATOM record. Columns: 1-6 ATOM  ; 7-11 serial; 13-16 atom; 17 altLoc;
    # 18-20 resname; 22 chain; 23-26 resseq; 31-38 x; 39-46 y; 47-54 z.
    return f"ATOM  {serial:>5d}  CA  ALA {chain}{resnum:>4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C"


# --- Hotspot parsing ----------------------------------------------------------


def test_parse_hotspots_letter_then_number():
    out = parse_hotspots("A15,A18,A22")
    assert [(h.chain_id, h.resnum) for h in out] == [("A", 15), ("A", 18), ("A", 22)]


def test_parse_hotspots_number_only():
    """No chain prefix means 'any chain'."""
    out = parse_hotspots("15,18,22")
    assert [(h.chain_id, h.resnum) for h in out] == [("", 15), ("", 18), ("", 22)]


def test_parse_hotspots_mixed_separators_and_garbage():
    out = parse_hotspots(" A15 ;  A20 \n; xx ; A30 ; ")
    # ';' is not in the separator regex; only commas + whitespace split, so the
    # 'A20 ; xx ; A30' chunk goes through as a single sub-token and fails to
    # parse. The leading/trailing whitespace-separated 'A15' parses fine.
    nums = [h.resnum for h in out]
    assert 15 in nums  # 'A15' parses; the malformed pieces are silently dropped


def test_parse_hotspots_empty():
    assert parse_hotspots("") == []
    assert parse_hotspots(None) == []  # type: ignore[arg-type]


# --- Hotspot.parse spec format -----------------------------------------------


def test_hotspot_parse_with_underscore_separator():
    assert Hotspot.parse("A_15") == Hotspot(chain_id="A", resnum=15)
    assert Hotspot.parse("A:15") == Hotspot(chain_id="A", resnum=15)


def test_hotspot_parse_invalid_returns_none():
    assert Hotspot.parse("XYZ") is None
    assert Hotspot.parse("") is None


# --- Interface residue extraction --------------------------------------------


def test_extract_interface_residues_finds_close_pairs(tmp_path):
    """Place binder CA at origin; target CA at (0,0,4) within 8 Å cutoff."""
    pdb = _write_pdb(
        tmp_path,
        [
            _ca_line(1, "B", 1, 0, 0, 0),  # binder
            _ca_line(2, "B", 2, 0, 0, 1),  # binder
            _ca_line(3, "A", 100, 0, 0, 4.0),  # target — within 8 Å
            _ca_line(4, "A", 200, 50, 50, 50),  # target — far
        ],
    )
    contacts = extract_interface_residues(pdb, binder_chain="B", target_chain="A", cutoff=8.0)
    assert contacts == {("A", 100)}


def test_extract_interface_residues_auto_target_chain(tmp_path):
    """target_chain=None means 'any chain that isn't the binder'."""
    pdb = _write_pdb(
        tmp_path,
        [
            _ca_line(1, "B", 1, 0, 0, 0),
            _ca_line(2, "A", 50, 0, 0, 3.0),
            _ca_line(3, "C", 99, 0, 0, 2.0),
        ],
    )
    contacts = extract_interface_residues(pdb, binder_chain="B", target_chain=None, cutoff=5.0)
    assert contacts == {("A", 50), ("C", 99)}


def test_extract_interface_residues_empty_when_chain_absent(tmp_path):
    pdb = _write_pdb(tmp_path, [_ca_line(1, "A", 1, 0, 0, 0)])
    assert extract_interface_residues(pdb, binder_chain="B", target_chain="A") == set()


def test_extract_interface_residues_skips_alt_loc_b(tmp_path):
    """Alt-loc B atom should be ignored (we keep blank or A only)."""
    pdb = _write_pdb(
        tmp_path,
        [
            "ATOM      1  CA AALA A   1       0.000   0.000   0.000  1.00  0.00           C",
            "ATOM      2  CA BALA A   1       3.000   0.000   0.000  1.00  0.00           C",
            _ca_line(3, "B", 9, 0.5, 0, 0),
        ],
    )
    # Only the A alt-loc target CA (at 0,0,0) should match the binder CA at
    # (0.5,0,0) — the B alt-loc at (3,0,0) is filtered.
    contacts = extract_interface_residues(pdb, binder_chain="B", target_chain="A", cutoff=2.0)
    assert contacts == {("A", 1)}


# --- epitope_match coverage --------------------------------------------------


def test_epitope_match_perfect_hit():
    interface = {("A", 15), ("A", 18), ("A", 22)}
    hotspots = parse_hotspots("A15,A18,A22")
    frac, matched, off = epitope_match(interface, hotspots)
    assert frac == 1.0
    assert matched == {("A", 15), ("A", 18), ("A", 22)}
    assert off == set()


def test_epitope_match_half_hit():
    interface = {("A", 15), ("A", 18), ("A", 99), ("A", 100)}
    hotspots = parse_hotspots("A15,A18,A22,A23")
    frac, _matched, off = epitope_match(interface, hotspots)
    assert frac == 0.5  # 2 of 4 hotspots matched
    assert ("A", 99) in off and ("A", 100) in off  # not in intended


def test_epitope_match_chain_agnostic_when_hotspot_chain_unset():
    """A hotspot without chain matches any chain at that residue number."""
    interface = {("X", 15), ("Y", 18)}
    hotspots = parse_hotspots("15,18,22")
    frac, _matched, _off = epitope_match(interface, hotspots)
    assert frac == pytest.approx(2 / 3)


def test_epitope_match_no_hotspots_returns_nan():
    interface = {("A", 100), ("A", 101)}
    frac, matched, off = epitope_match(interface, [])
    assert math.isnan(frac)
    assert matched == set()
    assert off == interface  # all interface residues are "off" if no intent declared
