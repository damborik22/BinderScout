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
import os
import sys
import tempfile
from pathlib import Path

PANEL = [
    "interface_sc",
    "interface_packstat",
    "interface_dG",
    "interface_dSASA",
    "interface_dG_SASA_ratio",
    "interface_nres",
    "interface_interface_hbonds",
    "interface_delta_unsat_hbonds",
    "interface_hydrophobicity",
    "surface_hydrophobicity",
]


def _ensure_dalphaball_can_link() -> None:
    """Put the active conda env's lib dir on LD_LIBRARY_PATH.

    Rosetta shells out to ``DAlphaBall.gcc`` for packstat and the buried-unsat
    H-bond count, and that binary links ``libgfortran.so.5``. The library is
    installed in the env, but the subprocess does not search there by default,
    so it fails with "error while loading shared libraries" -- and Rosetta then
    reports ``DALPHABALL output nan`` and aborts scoring for that structure.

    The cost of getting this wrong is an all-empty panel row, which is
    indistinguishable from a structure that could not be scored.
    """
    lib = Path(sys.prefix) / "lib"
    if not (lib / "libgfortran.so.5").exists():
        return
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if str(lib) not in current.split(os.pathsep):
        os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(p for p in (str(lib), current) if p)


def _patch_set_interface_for_strings() -> None:
    """Let BindCraft's ``score_interface`` keep passing a string.

    Recent PyRosetta made ``InterfaceAnalyzerMover.set_interface`` take a
    ``core.pose.DockingPartners`` instead of a string, and BindCraft's
    ``functions/pyrosetta_utils.py`` calls ``iam.set_interface("A_B")``. That
    raises TypeError, which the per-structure ``except`` below turned into an
    empty row for every design -- so the panel produced nothing at all.

    BindCraft is a gitignored upstream checkout, so this wraps the method here
    rather than editing it there. On an older PyRosetta the string still works
    and this is a no-op.
    """
    from pyrosetta.rosetta.protocols.analysis import InterfaceAnalyzerMover

    try:
        from pyrosetta.rosetta.core.pose import DockingPartners
    except ImportError:
        return  # older PyRosetta: the string form is native

    original = InterfaceAnalyzerMover.set_interface

    def set_interface(self, interface):
        if isinstance(interface, str):
            interface = DockingPartners.docking_partners_from_string(interface)
        return original(self, interface)

    InterfaceAnalyzerMover.set_interface = set_interface


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Relax + BindCraft interface panel for QC gating")
    ap.add_argument("--structures-dir", required=True, help="Directory of complex PDBs")
    ap.add_argument("--binder-chain", default="B", help="Binder chain id (B for AF3/ESMFold2/RFD3, A for Boltz-2)")
    ap.add_argument(
        "--bindcraft-dir",
        default=str(Path(__file__).resolve().parents[2] / "BindCraft"),
        help="BindCraft repo (for functions/ + DAlphaBall.gcc)",
    )
    ap.add_argument("--output", "-o", required=True, help="Output panel CSV")
    args = ap.parse_args(argv)

    bc = Path(args.bindcraft_dir)
    dalphaball = bc / "functions" / "DAlphaBall.gcc"
    sys.path.insert(0, str(bc))

    _ensure_dalphaball_can_link()

    import pyrosetta as pr

    pr.init(
        f"-ignore_unrecognized_res -ignore_zero_occupancy -mute all "
        f"-holes:dalphaball {dalphaball} -corrections::beta_nov16 true -relax:default_repeats 1"
    )
    _patch_set_interface_for_strings()
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
