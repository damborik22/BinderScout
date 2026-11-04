"""RFD3 designs were collected by sequence, and the diffusion backbone never carries it.

RFD3 writes a backbone (``diffusion/<stem>.cif.gz``, no side chains) and ProteinMPNN designs the
sequence afterwards, so `extract --collect-structures` looked the MPNN sequence up in structures that
hold something else and reported ``0/N`` collected. The extractor knows which backbone each row came
from (``design_id``), so it now hands that to the collector as a hint.
"""

from __future__ import annotations

from binder_comparison.extractors.rfd3 import RFD3Extractor
from binder_comparison.structures import collect_design_structures

BINDER = "MKVLAAGIVG"
GLY = "G" * len(BINDER)
GLY3 = {"G": "GLY"}


def _pdb(seq3: str) -> str:
    lines = []
    for i in range(1, len(BINDER) + 1):
        lines.append(f"ATOM  {i:5d}  CA  {seq3} B{i:4d}    {i * 3.8:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C")
    return "\n".join(lines) + "\n"


def _pool(tmp_path):
    root = tmp_path / "rfd3"
    (root / "diffusion").mkdir(parents=True)
    (root / "diffusion" / "binder_spec_x_0_model_0.pdb").write_text(_pdb("GLY"))
    (root / "sequences.csv").write_text(
        "design_id,sequence,length,backbone\n"
        f"rfd3_binder_spec_x_0_model_0,{BINDER},{len(BINDER)},binder_spec_x_0_model_0\n"
        f"rfd3_binder_spec_x_1_model_0,{BINDER[::-1]},{len(BINDER)},binder_spec_x_1_model_0\n"
    )
    return root


def test_the_extractor_names_the_backbone_it_came_from(tmp_path):
    binders = RFD3Extractor().extract(_pool(tmp_path))
    by_seq = {b.sequence: b for b in binders}
    assert by_seq[BINDER].structure_path and by_seq[BINDER].structure_path.endswith("binder_spec_x_0_model_0.pdb")
    assert by_seq[BINDER[::-1]].structure_path is None, "no backbone on disk -> no hint, not a guess"


def test_collection_uses_the_hint_when_the_sequence_does_not_match(tmp_path):
    root = _pool(tmp_path)
    binders = RFD3Extractor().extract(root)
    seqs = [b.sequence for b in binders]
    hints = {b.sequence: b.structure_path for b in binders if b.structure_path}

    # Control: by sequence alone nothing matches (the backbone is poly-Gly), which is the bug.
    assert collect_design_structures(root, seqs, tmp_path / "without") == 0
    # With the hint the design with a backbone is collected, the one without is not.
    assert collect_design_structures(root, seqs, tmp_path / "with", hints=hints) == 1
    assert (tmp_path / "with" / "manifest.csv").read_text().count(BINDER) == 1


def test_a_hint_to_a_missing_file_collects_nothing_and_does_not_raise(tmp_path):
    root = _pool(tmp_path)
    assert collect_design_structures(root, [BINDER], tmp_path / "o", hints={BINDER: tmp_path / "nope.pdb"}) == 0


def test_the_extract_command_passes_the_hints_through(tmp_path, capsys):
    """Mutating the CALL SITE: the helper working is not the command using it."""
    import argparse

    from binder_comparison.cli import extract as extract_cli

    root = _pool(tmp_path)
    ap = argparse.ArgumentParser()
    extract_cli.add_parser(ap.add_subparsers())
    args = ap.parse_args(
        ["extract", "--rfd3", str(root), "-o", str(tmp_path / "s.fasta"), "--collect-structures", str(tmp_path / "c")]
    )
    extract_cli.run(args)
    assert "rfd3: collected 1/2 original structures" in capsys.readouterr().out
    assert (tmp_path / "c" / "rfd3" / "design_0000.pdb").is_file()
