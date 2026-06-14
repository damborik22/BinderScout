"""CLI subcommand: binder-compare monomer

Flag context-dependent binder folds. Compares each binder's conformation in the complex
(``--complex-dir``) against the same binder refolded alone (``--monomer-dir``, a GPU step
run beforehand), by Cα RMSD. RMSD above the threshold = target-stabilized fold (a risk).

Usage:
    binder-compare monomer --complex-dir runs/X/structures --monomer-dir runs/X/monomer \\
        --binder-chain B -o monomer_validation.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from ..comparison.monomer import (
    CONTEXT_DEPENDENT_RMSD,
    ca_coords_from_pdb,
    classify_fold_robustness,
    kabsch_rmsd,
)


def run(args: argparse.Namespace) -> None:
    complex_dir = Path(args.complex_dir)
    monomer_dir = Path(args.monomer_dir)
    for d in (complex_dir, monomer_dir):
        if not d.is_dir():
            print(f"Error: directory not found: {d}", file=sys.stderr)
            sys.exit(1)

    complex_by_stem = {p.stem: p for p in complex_dir.glob("*.pdb")}
    rows: list[dict] = []
    for mono in sorted(monomer_dir.glob("*.pdb")):
        comp = complex_by_stem.get(mono.stem)
        if comp is None:
            print(f"[monomer] no complex match for {mono.name} — skipped", file=sys.stderr)
            continue
        binder_in_complex = ca_coords_from_pdb(comp.read_text(), chain=args.binder_chain)
        binder_alone = ca_coords_from_pdb(mono.read_text(), chain=args.monomer_chain)
        if binder_in_complex.shape[0] == 0 or binder_in_complex.shape != binder_alone.shape:
            print(
                f"[monomer] residue-count mismatch for {mono.stem} "
                f"(complex {binder_in_complex.shape[0]} vs monomer {binder_alone.shape[0]}) — skipped",
                file=sys.stderr,
            )
            continue
        rmsd = kabsch_rmsd(binder_alone, binder_in_complex)
        rows.append(
            {
                "design_id": mono.stem,
                "monomer_rmsd": round(rmsd, 3),
                "fold_robust": classify_fold_robustness(rmsd, args.threshold),
            }
        )

    if not rows:
        print("[monomer] no comparable pairs found.", file=sys.stderr)
        sys.exit(1)

    out = Path(args.output)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["design_id", "monomer_rmsd", "fold_robust"])
        w.writeheader()
        w.writerows(rows)
    n_robust = sum(1 for r in rows if r["fold_robust"])
    print(f"[monomer] {out}: {n_robust}/{len(rows)} folds robust (RMSD <= {args.threshold} Å)")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "monomer",
        help="Flag context-dependent binder folds (binder-alone vs in-complex Cα RMSD).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--complex-dir", required=True, metavar="DIR", help="PDBs of the binder-in-complex structures")
    p.add_argument("--monomer-dir", required=True, metavar="DIR", help="PDBs of the binder refolded alone")
    p.add_argument("--binder-chain", default="B", metavar="C", help="Binder chain id in the complex (default B)")
    p.add_argument("--monomer-chain", default=None, metavar="C", help="Chain id in the monomer PDB (default: any)")
    p.add_argument(
        "--threshold", type=float, default=CONTEXT_DEPENDENT_RMSD, metavar="Å", help="RMSD cutoff (default 3.0)"
    )
    p.add_argument("--output", "-o", required=True, metavar="CSV", help="Write per-design RMSD + robustness here")
    p.set_defaults(func=run)
