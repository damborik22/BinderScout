"""The Foldseek runner's decisions, tested without needing Foldseek installed.

The subprocess call itself is not unit-tested -- it is exercised end to end against real
structures. What is tested here is everything that has bitten before: which chain gets
compared, and what happens when the tool or the structures are absent.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.foldseek import (  # noqa: E402
    _binder_only_pdb,
    build_tm_lookup,
    find_foldseek,
)

# Boltz-2 convention: binder in A, target in B. AF3/ESMFold2 invert it.
_PDB = """ATOM      1  N   MET A   1      11.104  13.207  10.000  1.00 90.00           N
ATOM      2  CA  MET A   1      12.104  13.207  10.000  1.00 90.00           C
ATOM      3  CA  LYS A   2      13.104  13.207  10.000  1.00 90.00           C
ATOM      4  CA  THR A   3      14.104  13.207  10.000  1.00 90.00           C
ATOM      5  CA  GLU B   1      20.104  13.207  10.000  1.00 90.00           C
ATOM      6  CA  ASP B   2      21.104  13.207  10.000  1.00 90.00           C
END
"""


def test_the_binder_chain_is_found_by_sequence_not_by_letter():
    """Boltz-2 puts the binder in A, AF3/ESMFold2 in B. Matching the letter would compare
    the target on half the engines — CLAUDE.md lists that mismatch as a live bug source."""
    out = _binder_only_pdb(_PDB, "MKT")
    assert out is not None
    chains = {ln[21] for ln in out.splitlines() if ln.startswith("ATOM")}
    assert chains == {"A"}, f"expected only the MKT chain, got {chains}"


def test_the_other_chain_is_selectable_by_its_own_sequence():
    """Same file, different requested sequence, different chain — proving the letter
    plays no part."""
    out = _binder_only_pdb(_PDB, "ED")
    chains = {ln[21] for ln in out.splitlines() if ln.startswith("ATOM")}
    assert chains == {"B"}


def test_an_unidentifiable_binder_is_skipped_not_guessed():
    assert _binder_only_pdb(_PDB, "WWWWWWWW") is None
    assert _binder_only_pdb(_PDB, "") is None


def test_no_foldseek_means_no_lookup_not_an_exception(monkeypatch, tmp_path):
    """Foldseek is x86-only and lives in another tool's venv; aarch64 has none."""
    monkeypatch.setattr("binder_comparison.comparison.foldseek.find_foldseek", lambda *a, **k: None)
    d = pd.DataFrame({"binder_id": ["a", "b"], "sequence": ["MKT", "MKT"], "boltz_pdb": ["x", "y"]})
    assert build_tm_lookup(d, base_dir=tmp_path) is None


def test_too_few_structures_means_no_lookup(tmp_path):
    d = pd.DataFrame({"binder_id": ["a"], "sequence": ["MKT"], "boltz_pdb": ["x"]})
    assert build_tm_lookup(d, base_dir=tmp_path, foldseek_bin="/nonexistent") is None


def test_unresolvable_structures_mean_no_lookup(tmp_path):
    """Paths recorded on another machine that do not resolve here."""
    d = pd.DataFrame({"binder_id": ["a", "b"], "sequence": ["MKT", "MKT"], "boltz_pdb": ["/gone/a.pdb", "/gone/b.pdb"]})
    assert build_tm_lookup(d, base_dir=tmp_path, foldseek_bin="/nonexistent") is None


def test_the_env_override_is_honoured(monkeypatch, tmp_path):
    fake = tmp_path / "foldseek"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("FOLDSEEK_BIN", str(fake))
    assert find_foldseek() == str(fake)


def test_a_bogus_env_override_falls_through(monkeypatch):
    monkeypatch.setenv("FOLDSEEK_BIN", "/definitely/not/here")
    found = find_foldseek()
    assert found != "/definitely/not/here", "a non-existent override must not be returned"
