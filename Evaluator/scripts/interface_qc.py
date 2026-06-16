"""Relax (FastRelax) + full BindCraft interface panel for QC-gating a shortlist.

Emits one CSV row per complex PDB: design_id + the BindCraft interface-quality
panel (shape complementarity, packstat, dG, dSASA, # interface H-bonds, # buried
unsatisfied H-bonds, # interface residues, hydrophobicity, …). Unlike
``interface_energy.py`` this RELAXES first (predicted structures carry clashes),
so the panel is meaningful. Run in the BindCraft conda env (PyRosetta + DAlphaBall).

Intended for a SHORTLIST (top-N), not a whole pool — FastRelax is ~0.5-several min
per complex.
"""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path

PANEL = [
    "interface_sc", "interface_packstat", "interface_dG", "interface_dSASA",
    "interface_dG_SASA_ratio", "interface_nres", "interface_interface_hbonds",
    "interface_delta_unsat_hbonds", "interface_hydrophobicity", "surface_hydrophobicity",
]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Relax + BindCraft interface panel for QC gating")
    ap.add_argument("--structures-dir", required=True, help="Directory of complex PDBs")
    ap.add_argument("--binder-chain", default="B", help="Binder chain id (B for AF3/ESMFold2/RFD3, A for Boltz-2)")
    ap.add_argument("--bindcraft-dir", default=str(Path(__file__).resolve().parents[2] / "BindCraft"),
                    help="BindCraft repo (for functions/ + DAlphaBall.gcc)")
    ap.add_argument("--output", "-o", required=True, help="Output panel CSV")
    args = ap.parse_args(argv)

    bc = Path(args.bindcraft_dir)
    dalphaball = bc / "functions" / "DAlphaBall.gcc"
    sys.path.insert(0, str(bc))

    import pyrosetta as pr

    pr.init(f"-ignore_unrecognized_res -ignore_zero_occupancy -mute all "
            f"-holes:dalphaball {dalphaball} -corrections::beta_nov16 true -relax:default_repeats 1")
    from functions.pyrosetta_utils import pr_relax, score_interface

    pdbs = sorted(Path(args.structures_dir).glob("*.pdb"))
    if not pdbs:
        print(f"No .pdb files in {args.structures_dir}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with tempfile.TemporaryDirectory() as td:
        for pdb in pdbs:
            try:
                relaxed = str(Path(td) / f"{pdb.stem}_relaxed.pdb")
                pr_relax(str(pdb), relaxed)
                scores, _, _ = score_interface(relaxed, binder_chain=args.binder_chain)
                rows.append({"design_id": pdb.stem, **{k: scores.get(k) for k in PANEL}})
            except Exception as exc:  # one bad structure shouldn't sink the shortlist
                print(f"[interface_qc] {pdb.name}: {exc}", file=sys.stderr)
                rows.append({"design_id": pdb.stem, **{k: "" for k in PANEL}})
            print(f"[interface_qc] {pdb.stem}", file=sys.stderr)

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["design_id", *PANEL])
        w.writeheader()
        w.writerows(rows)
    print(f"[interface_qc] wrote {len(rows)} rows → {args.output}")


if __name__ == "__main__":
    main()
