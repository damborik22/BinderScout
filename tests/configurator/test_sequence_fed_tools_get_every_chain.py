"""A tool fed a target SEQUENCE must be fed every targeted chain, or refuse.

``cfg["target_sequence"]`` is the primary chain alone. The tools that take a
target structure get all of it; the two that take a sequence used to get a third
of it, with nothing downstream able to notice.

Measured 2026-10-30 (campaign P-59): Protein-Hunter completed 400 designs against
a three-chain pMHC whose Boltz-2 inputs contained only the 276-aa HLA heavy chain
-- ``grep -c VVVGADGVGK`` over every high-ipTM YAML returned 0, as did the
beta-2-microglobulin motif. The peptide whose single-atom difference the campaign
exists to discriminate was never in the complex, and the arm still reported
ipTM 0.82 and cost ~9 h. Mosaic was configured identically and caught first.

The two tools differ in what they can be given, so they are fixed differently:

* Protein-Hunter CAN take them all -- ``boltz_ph`` splits ``--protein_seqs`` with
  ``model_utils.smart_split`` and assigns chain ids B, C, D... So multi-chain was
  always expressible and we simply passed one sequence.
* Mosaic's template cannot: ``TARGET_SEQUENCE`` feeds one ``TargetChain``, the
  target-MSA cache key and the epitope indices. It refuses rather than quietly
  dropping chains.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "configurator"))

from configurator import (
    cfg_target_chain_sequences,
    extract_sequence_from_structure,
    target_chain_sequences,
    write_mosaic_hallucinate,
    write_run_protein_hunter,
)

HLA = "GSHSMRYFYTSVSRPGRGEPRFIAVGYVDDTQFVRFDSDAASQRMEPRAPWIEQEG"
B2M = "IQRTPKIQVYSRHPAENGKSNFLNCYVSGFHPSDIEVDLL"
PEPTIDE = "VVVGADGVGK"  # KRAS G12D 10-mer -- the discriminating chain


def _three_chain_pdb(tmp_path: Path) -> Path:
    """A PDB whose three chains have distinguishable sequences."""
    aa3 = {
        "A": "ALA",
        "R": "ARG",
        "N": "ASN",
        "D": "ASP",
        "C": "CYS",
        "Q": "GLN",
        "E": "GLU",
        "G": "GLY",
        "H": "HIS",
        "I": "ILE",
        "L": "LEU",
        "K": "LYS",
        "M": "MET",
        "F": "PHE",
        "P": "PRO",
        "S": "SER",
        "T": "THR",
        "W": "TRP",
        "Y": "TYR",
        "V": "VAL",
    }
    out, n = [], 0
    for chain, seq in (("A", HLA), ("B", B2M), ("C", PEPTIDE)):
        for i, one in enumerate(seq, 1):
            n += 1
            out.append(
                f"ATOM  {n:5d}  CA  {aa3[one]} {chain}{i:4d}    "
                f"{float(i):8.3f}{10.0:8.3f}{10.0:8.3f}  1.00  0.00           C"
            )
    path = tmp_path / "pmhc.pdb"
    path.write_text("\n".join(out) + "\nEND\n")
    return path


def _cfg(tmp_path: Path, chains: str = "A,B,C") -> dict:
    pdb = _three_chain_pdb(tmp_path)
    primary = extract_sequence_from_structure(str(pdb), chains.split(",")[0].strip())
    return {
        "name": "pmhc",
        "run_dir": str(tmp_path / "run"),
        "target_pdb": str(pdb),
        "target_pdb_src": str(pdb),
        "target_sequence": primary,
        "target_chain_sequences": target_chain_sequences(str(pdb), chains, primary),
        "chains": chains,
        "hotspots": "5,9,12",
        "min_length": 60,
        "max_length": 150,
        "n_designs": 50,
    }


def test_every_targeted_chain_is_extracted(tmp_path):
    cfg = _cfg(tmp_path)
    got = [(e["chain"], e["sequence"]) for e in cfg["target_chain_sequences"]]
    assert got == [("A", HLA), ("B", B2M), ("C", PEPTIDE)]


def test_an_untargeted_chain_is_not_included(tmp_path):
    cfg = _cfg(tmp_path, chains="A,C")
    assert [e["chain"] for e in cfg["target_chain_sequences"]] == ["A", "C"]


def test_protein_hunter_receives_the_peptide_chain(tmp_path):
    """The regression: the discriminating chain must reach the design engine."""
    cfg = _cfg(tmp_path)
    script = tmp_path / "run_ph.sh"
    write_run_protein_hunter(script, cfg)
    text = script.read_text()

    arg = text.split("--protein_seqs ")[1].split("\n")[0]
    assert PEPTIDE in arg, "the KRAS peptide never reached Protein-Hunter"
    assert B2M in arg
    assert HLA in arg
    # comma-separated, because smart_split prefers commas
    assert arg.count(",") == 2


def test_protein_hunter_hotspots_stay_on_the_primary_chain(tmp_path):
    """pipeline.py maps contact group i to chain id i, so one group => chain B.

    Splitting the hotspots across groups would put HLA residue numbers onto the
    99-residue beta-2m and the 10-residue peptide -- the same cross-chain hotspot
    bug already fixed in BoltzGen, Proteina-Complexa and PXDesign.
    """
    cfg = _cfg(tmp_path)
    script = tmp_path / "run_ph.sh"
    write_run_protein_hunter(script, cfg)
    contacts = script.read_text().split("--contact_residues ")[1].split("\n")[0]
    assert "|" not in contacts, "contacts were split across chains"


def test_protein_hunter_banner_names_the_chains(tmp_path):
    cfg = _cfg(tmp_path)
    script = tmp_path / "run_ph.sh"
    write_run_protein_hunter(script, cfg)
    text = script.read_text()
    assert "Target chains:" in text
    assert f"C:{len(PEPTIDE)}aa" in text


def test_mosaic_refuses_a_multi_chain_target(tmp_path):
    """Refusing beats designing against a third of the target."""
    cfg = _cfg(tmp_path)
    with pytest.raises(RuntimeError) as exc:
        write_mosaic_hallucinate(tmp_path / "hallucinate.py", cfg)
    msg = str(exc.value)
    assert "single target sequence" in msg
    # it must name what it would have dropped, not just complain
    assert "A (" in msg and "B (" in msg and "C (" in msg


def test_mosaic_still_accepts_a_single_chain_target(tmp_path):
    cfg = _cfg(tmp_path, chains="A")
    out = tmp_path / "hallucinate.py"
    write_mosaic_hallucinate(out, cfg)
    assert HLA in out.read_text()


def test_an_old_config_without_the_key_still_replays(tmp_path):
    """`--config` replay of a config written before this key existed must work,
    reproducing the old single-chain behaviour rather than guessing."""
    cfg = _cfg(tmp_path)
    del cfg["target_chain_sequences"]
    entries = cfg_target_chain_sequences(cfg)
    assert [e["chain"] for e in entries] == ["A"]
    assert entries[0]["sequence"] == HLA
