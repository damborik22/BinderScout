"""`cif_to_pdb_atoms` must emit a PDB this project can read back (BUG-19).

The writer omitted the PDB altLoc column (17), so resName, chainID and resSeq all sat
one column left of the fixed-format spec. Nothing raised: the file looked like a PDB,
and every consumer that reads fixed columns got the wrong field. The project's own
`extract_sequence_from_pdb` returned None on the converter's output, and
`available_chains` returned [] — for mmCIF, which is the default RCSB download format.

The assertion that would have caught it at the time is a round trip: convert, then read
the sequence back out of the converted file and compare it with the sequence read from
the mmCIF. That is what this module does, against a real mmCIF in the tree rather than a
hand-built one, plus the coordinate-sign case the shift also broke.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

# A real two-chain mmCIF written by ESMFold2, kept in the tree as refold golden data.
REAL_CIF = (
    Path(__file__).resolve().parents[1] / "integration" / "golden_pool" / "esmfold2_out" / "esmfold2_0002_model.cif"
)


def test_the_converted_pdb_is_readable_by_this_project(tmp_path):
    """The round trip, per chain: mmCIF sequence in, same sequence back out of the PDB."""
    out = tmp_path / "converted.pdb"
    assert conf.cif_to_pdb_atoms(str(REAL_CIF), str(out))
    for chain in ("A", "B"):
        from_cif = conf.extract_sequence_from_cif(str(REAL_CIF), chain)
        assert from_cif, f"fixture has no chain {chain}"
        assert conf.extract_sequence_from_pdb(str(out), chain) == from_cif


def test_available_chains_sees_the_chains_of_an_mmcif():
    """available_chains routes CIF through the converter and parses line[21], so it
    inherited the shift: it answered [] for essentially every mmCIF, and the wizard's
    wrong-chain-letter rescue printed "No chains could be parsed from that file."
    """
    assert conf.available_chains(str(REAL_CIF)) == ["A", "B"]


def test_the_sign_of_a_full_width_coordinate_survives(tmp_path):
    """-123.456 fills all eight columns of the x field, so one column of shift pushed the
    minus sign out of it and the atom came back at +123.456. Small coordinates hid this,
    because the `{seq_id:4d}    ` run absorbed the shift.
    """
    cif = tmp_path / "wide.cif"
    cif.write_text(
        "data_T\n"
        "loop_\n"
        "_atom_site.group_PDB\n"
        "_atom_site.id\n"
        "_atom_site.label_atom_id\n"
        "_atom_site.label_comp_id\n"
        "_atom_site.label_asym_id\n"
        "_atom_site.label_seq_id\n"
        "_atom_site.Cartn_x\n"
        "_atom_site.Cartn_y\n"
        "_atom_site.Cartn_z\n"
        "ATOM 1 CA GLY A 1 -123.456 1.000 2.000\n"
        "#\n"
    )
    out = tmp_path / "wide.pdb"
    assert conf.cif_to_pdb_atoms(str(cif), str(out))
    line = out.read_text().splitlines()[0]
    assert float(line[30:38]) == -123.456
    assert line[17:20] == "GLY"
    assert line[21] == "A"
    assert line[22:26].strip() == "1"
