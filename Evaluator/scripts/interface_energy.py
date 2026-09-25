"""Compute Rosetta interface ΔG and ΔSASA for a directory of complex PDBs.

Runs in the ``BindCraft`` conda env (PyRosetta is installed there on every platform we run
BindCraft on — x86_64 AND aarch64 / DGX Spark — so this is intentionally not x86-gated).
Emits one CSV row per PDB: design_id, interface_dG (REU), interface_dSASA (Å²). The
evaluator's ``binder-compare affinity`` gates on ``ipsae_min`` and then ranks survivors
by ``|dG/dSASA|`` (Part N).

**Structures are RELAXED before scoring**, as BindCraft does, and this is not optional
in practice. Scoring a predicted complex as-is measures clash energy, not interface
energy: on one AF3 structure from the golden pool, dG is +213.8 REU unrelaxed and
−89.5 REU after FastRelax — a 303 REU swing that flips the sign. BindCraft's own gate
is dG ≤ 0, so an unrelaxed number is not comparable to any published threshold. Relax
costs roughly a minute per structure; ``--no-relax`` skips it for debugging only.

Usage (driven by `binder-compare affinity --run-rosetta`):
    conda run -n BindCraft python interface_energy.py \\
        --structures-dir runs/X/structures --interface B_A -o interface_energy.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path


def _interface_analyzer(spec):
    """An InterfaceAnalyzerMover with its interface set, across PyRosetta versions.

    Recent PyRosetta replaced both the string constructor overload and the
    string ``set_interface`` with a ``core.pose.DockingPartners`` object, so
    ``InterfaceAnalyzerMover("B_A")`` raises TypeError. Older builds on the
    fleet still take the string, so try the new form and fall back rather than
    pinning either one.
    """
    from pyrosetta.rosetta.protocols.analysis import InterfaceAnalyzerMover

    iam = InterfaceAnalyzerMover()
    try:
        from pyrosetta.rosetta.core.pose import DockingPartners

        iam.set_interface(DockingPartners.docking_partners_from_string(spec))
    except (ImportError, AttributeError, TypeError):
        iam.set_interface(spec)  # older PyRosetta
    return iam


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Rosetta interface ΔG / ΔSASA over a directory of complex PDBs.")
    ap.add_argument("--structures-dir", required=True, help="Directory of complex .pdb files")
    ap.add_argument(
        "--interface",
        default="B_A",
        help="Rosetta interface spec, <binder>_<target> chain ids (default B_A, RFD3 convention)",
    )
    ap.add_argument(
        "--bindcraft-dir",
        default=str(Path(__file__).resolve().parents[2] / "BindCraft"),
        help="BindCraft repo (for functions/pr_relax + DAlphaBall.gcc)",
    )
    ap.add_argument(
        "--no-relax",
        action="store_true",
        help="Score the structures as-is. Interface dG is then dominated by clash energy and is "
        "NOT comparable to any published threshold — see the module docstring.",
    )
    ap.add_argument("--output", "-o", required=True, help="Output CSV path")
    args = ap.parse_args(argv)

    bc = Path(args.bindcraft_dir)
    sys.path.insert(0, str(bc))

    import pyrosetta

    pyrosetta.init(
        f"-ignore_unrecognized_res -ignore_zero_occupancy -mute all "
        f"-holes:dalphaball {bc / 'functions' / 'DAlphaBall.gcc'} "
        f"-corrections::beta_nov16 true -relax:default_repeats 1"
    )
    pr_relax = None
    if not args.no_relax:
        from functions.pyrosetta_utils import pr_relax

    structures = sorted(Path(args.structures_dir).glob("*.pdb"))
    if not structures:
        print(f"No .pdb files in {args.structures_dir}", file=sys.stderr)
        sys.exit(1)

    rows = []
    with tempfile.TemporaryDirectory() as td:
        for pdb in structures:
            try:
                target = str(pdb)
                if pr_relax is not None:
                    target = str(Path(td) / f"{pdb.stem}_relaxed.pdb")
                    pr_relax(str(pdb), target)
                pose = pyrosetta.pose_from_pdb(target)
                iam = _interface_analyzer(args.interface)
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

    # Per-structure tolerance is for the occasional bad structure. When NOTHING
    # scored, the cause is environmental (a PyRosetta API change, a missing
    # shared library) and every row is empty — writing that file lets a caller
    # spend hours joining nothing, which is exactly how the string-constructor
    # TypeError stayed invisible.
    # A row counts as scored only if an interface was actually FOUND. A wrong
    # --interface spec does not raise -- PyRosetta returns dG 0.0 and dSASA 0.0
    # for chains that do not exist -- so counting non-empty cells let a full
    # panel of zeros pass this guard. Measured on a real 2-chain pose: B_A gives
    # dSASA 4469, a bogus Z_Q gives 0.0 with no exception.
    def _scored(r) -> bool:
        try:
            return r["interface_dG"] != "" and float(r["interface_dSASA"]) > 0.0
        except (TypeError, ValueError):
            return False

    n_scored = sum(1 for r in rows if _scored(r))
    if rows and n_scored == 0:
        print(
            f"[interface_energy] ERROR: 0 of {len(rows)} structures yielded an interface "
            f"(every dSASA is 0). Either --interface {args.interface!r} names chains these "
            "structures do not have, or this is an environment/API problem. Refusing to write "
            "a panel of zeros.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(args.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["design_id", "interface_dG", "interface_dSASA"])
        w.writeheader()
        w.writerows(rows)
    print(f"[interface_energy] wrote {len(rows)} rows ({n_scored} scored) → {args.output}")


if __name__ == "__main__":
    main()
