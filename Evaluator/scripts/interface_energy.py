"""Compute Rosetta interface ΔG and ΔSASA for a directory of complex PDBs.

Runs in the ``BindCraft`` conda env (PyRosetta is installed there on every platform we run
BindCraft on — x86_64 AND aarch64 / DGX Spark — so this is intentionally not x86-gated).
Emits one CSV row per PDB: design_id, interface_dG (REU), interface_dSASA (Å²). The
evaluator's ``binder-compare affinity`` then folds these into the ``ipsae_min × |dG/dSASA|``
affinity composite (Part N).

Usage (driven by `binder-compare affinity --run-rosetta`):
    conda run -n BindCraft python interface_energy.py \\
        --structures-dir runs/X/structures --interface B_A -o interface_energy.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Rosetta interface ΔG / ΔSASA over a directory of complex PDBs.")
    ap.add_argument("--structures-dir", required=True, help="Directory of complex .pdb files")
    ap.add_argument(
        "--interface",
        default="B_A",
        help="Rosetta interface spec, <binder>_<target> chain ids (default B_A, RFD3 convention)",
    )
    ap.add_argument("--output", "-o", required=True, help="Output CSV path")
    args = ap.parse_args(argv)

    import pyrosetta
    from pyrosetta.rosetta.protocols.analysis import InterfaceAnalyzerMover

    pyrosetta.init("-mute all")

    structures = sorted(Path(args.structures_dir).glob("*.pdb"))
    if not structures:
        print(f"No .pdb files in {args.structures_dir}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for pdb in structures:
        try:
            pose = pyrosetta.pose_from_pdb(str(pdb))
            iam = InterfaceAnalyzerMover(args.interface)
            iam.set_compute_packstat(False)
            iam.set_pack_separated(True)
            iam.apply(pose)
            rows.append(
                {
                    "design_id": pdb.stem,
                    "interface_dG": round(iam.get_interface_dG(), 3),
                    "interface_dSASA": round(iam.get_interface_delta_sasa(), 3),
                }
            )
        except Exception as exc:  # one bad structure shouldn't sink the batch
            print(f"[interface_energy] {pdb.name}: {exc}", file=sys.stderr)
            rows.append({"design_id": pdb.stem, "interface_dG": "", "interface_dSASA": ""})

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["design_id", "interface_dG", "interface_dSASA"])
        w.writeheader()
        w.writerows(rows)
    print(f"[interface_energy] wrote {len(rows)} rows → {args.output}")


if __name__ == "__main__":
    main()
