"""RFD4: the preserved contig does not carry the structure's expression tag.

5O45 (PD-L1) chain A is the crystallised CONSTRUCT: label_seq_id 1-129, whose last eleven
residues (119-129, author 135-145) are AAALE + His6, flagged 'expression tag' in the
depositor's own `_struct_ref_seq_dif` rows. The RFD4 contig used to be the chain's whole
label range, `A1-129`, so the tag was preserved as target and RFD4 designed against a
cloning linker. The PDB path already trims it (prepare_target_pdb) when the user accepts
the offer or sets `trim_construct_tag`; the RFD4 path ignored both.

The fixture below reproduces the real entry's chain A (sequence, numbering and annotation
rows as deposited). It was also checked against the real RCSB file and a real
`rfd4-generate` run: contig `A1-118, /0, 60-80` generates, and the output chain A ends in
...KVNAPY.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))
import configurator as conf

# 5O45 chain A, label_seq_id 1..129 (the last 11 are the construct tag).
_NATIVE = "NAFTVTVPKDLYVVEYGSNMTIECKFPVEKQLDLAALIVYWEMEDKNIIQFVHGEEDLKVQHSSYRQRARLLKDQLSLGNAALQITDVKLQDAGVYRCMISYGGADYKRITVKVNAPY"
_TAG = "AAALEHHHHHH"
_FULL = _NATIVE + _TAG
_AUTH_OFFSET = 16  # label 1 == author 17, as deposited

_THREE = {v: k for k, v in conf.AA3TO1.items() if k != "MSE"}

_COLS = (
    "group_PDB",
    "id",
    "type_symbol",
    "label_atom_id",
    "label_comp_id",
    "label_asym_id",
    "label_seq_id",
    "Cartn_x",
    "Cartn_y",
    "Cartn_z",
    "occupancy",
    "B_iso_or_equiv",
    "auth_seq_id",
    "auth_asym_id",
    "pdbx_PDB_model_num",
)


def _5o45_like(path: Path) -> Path:
    atoms = "\n".join(
        f"ATOM {i} C CA {_THREE[aa]} A {i} 0.0 0.0 {i}.0 1.00 30.0 {i + _AUTH_OFFSET} A 1"
        for i, aa in enumerate(_FULL, start=1)
    )
    n_native = len(_NATIVE)
    dif = "\n".join(
        f"{k} 5O45 {_THREE[aa]} A {n_native + k} ? 'expression tag' {n_native + k + _AUTH_OFFSET}"
        for k, aa in enumerate(_TAG, start=1)
    )
    path.write_text(
        "data_5O45\n#\nloop_\n"
        + "".join(f"_atom_site.{c}\n" for c in _COLS)
        + atoms
        + "\n#\nloop_\n"
        + "".join(
            f"_struct_ref_seq_dif.{c}\n"
            for c in (
                "align_id",
                "pdbx_pdb_id_code",
                "mon_id",
                "pdbx_pdb_strand_id",
                "seq_num",
                "pdbx_pdb_ins_code",
                "details",
                "pdbx_auth_seq_num",
            )
        )
        + dif
        + "\n#\n"
    )
    return path


@pytest.fixture
def cfg(tmp_path):
    cif = _5o45_like(tmp_path / "5o45.cif")
    return {
        "name": "pdl1",
        "run_dir": tmp_path / "run",
        "target_pdb": tmp_path / "pdl1.pdb",
        "target_pdb_src": str(cif),
        "target_cif": cif,
        "target_sequence": _FULL,
        "chains": "A",
        "min_length": 60,
        "max_length": 100,
        "n_designs": 4,
    }


def _contig(tmp_path, cfg) -> str:
    spec = tmp_path / "rfd4" / "input.yaml"
    conf.write_rfd4_input_yaml(spec, cfg)
    return next(line.split('"')[1] for line in spec.read_text().splitlines() if line.startswith("  contig: "))


def test_the_fixture_is_the_real_entrys_shape(cfg):
    """Control: chain A is label 1-129 / author 17-145 and the depositor flags 119-129."""
    info = conf.cif_chain_numbering(str(cfg["target_cif"]), "A")
    assert (info["label_lo"], info["label_hi"], info["auth_lo"], info["auth_hi"]) == (1, 129, 17, 145)
    flagged = conf._cif_seqdif_construct(Path(cfg["target_cif"]).read_text(), "A")
    assert sorted(flagged) == list(range(119, 130))


def test_a_trimmed_target_sequence_trims_the_contig_and_says_so(cfg, tmp_path, capsys):
    cfg["target_sequence"] = _NATIVE  # what the wizard's "Trim 11 residues? yes" leaves behind
    contig = _contig(tmp_path, cfg)
    out = capsys.readouterr().out
    assert contig == "A1-118, /0, 60-100", "label_seq_id numbering is kept, the tag is gone"
    assert "trimmed 11 residue(s) AAALEHHHHHH" in out
    assert "119-129" in out


def test_trim_construct_tag_in_a_headless_config_reaches_the_contig(cfg, tmp_path, capsys):
    cfg["trim_construct_tag"] = True
    conf.apply_headless_tag_trim(cfg)
    assert cfg["target_sequence"] == _NATIVE, "control: the switch trimmed the sequence"
    assert _contig(tmp_path, cfg) == "A1-118, /0, 60-100"


def test_without_the_switch_the_tag_stays_and_the_user_is_told(cfg, tmp_path, capsys):
    cfg["trim_construct_tag"] = False
    conf.apply_headless_tag_trim(cfg)
    assert cfg["target_sequence"] == _FULL, "control: nothing was trimmed"
    contig = _contig(tmp_path, cfg)
    out = capsys.readouterr().out
    assert contig == "A1-129, /0, 60-100", "an untrimmed target is the user's decision; the contig follows it"
    assert "KEEPS 11 residue(s)" in out and "119-129" in out
    assert "trim_construct_tag" in out


def test_a_target_sequence_that_is_not_part_of_the_chain_does_not_guess(cfg, tmp_path, capsys):
    cfg["target_sequence"] = "WWWWWWWWWW"
    assert _contig(tmp_path, cfg) == "A1-129, /0, 60-100"
    assert "not a contiguous part of chain A" in capsys.readouterr().out
