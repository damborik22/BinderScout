"""CLI subcommand: binder-compare beta-check.

Flag designs whose binder threads a β-strand into the target's β-sheet
(β-augmentation / intercalation) — a non-physical gaming mode that inflates
iPTM on β-sheet-rich targets (serpins, Ig folds). Emits a CSV joinable by
binder_id; pass to ``report --beta-results`` to add the advisory column and
(with ``--exclude-intercalators``) drop them from the ranked pool.

Usage:
    binder-compare beta-check --metrics report/metrics.csv \\
        --pdb-col af3_pdb --target-chain A --binder-chain B -o beta.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from ..comparison.beta_intercalation import count_cross_chain_bridges, is_intercalating
from ..io.read import read_csv_safe


def run(args: argparse.Namespace) -> None:
    metrics_path = Path(args.metrics)
    if not metrics_path.exists():
        print(f"Error: metrics CSV not found: {metrics_path}", file=sys.stderr)
        sys.exit(1)
    m = read_csv_safe(metrics_path)
    id_col = next((c for c in ("binder_id", "design_id", "id") if c in m.columns), None)
    if id_col is None or args.pdb_col not in m.columns:
        print(f"Error: need an id column and '{args.pdb_col}' in {metrics_path}.", file=sys.stderr)
        sys.exit(1)

    tc, bc = args.target_chain.upper(), args.binder_chain.upper()
    rows, n_inter, n_fail = [], 0, 0
    for _, r in m.iterrows():
        pdb = str(r.get(args.pdb_col, "")).strip()
        if not pdb or pdb == "nan" or not Path(pdb).is_file():
            rows.append({"binder_id": r[id_col], "n_xbridge": "", "n_xbridge2": "", "beta_intercalates": ""})
            n_fail += 1
            continue
        n1, n2, _ = count_cross_chain_bridges(pdb, tc, bc)
        inter = is_intercalating(n1, n2, min_xbridge=args.min_xbridge, min_both_side=args.min_both_side)
        n_inter += int(inter)
        rows.append(
            {
                "binder_id": r[id_col],
                "n_xbridge": n1,
                "n_xbridge2": n2,
                "beta_intercalates": "true" if inter else "false",
            }
        )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["binder_id", "n_xbridge", "n_xbridge2", "beta_intercalates"])
        w.writeheader()
        w.writerows(rows)
    print(
        f"[beta-check] {out}: {len(rows) - n_fail} scored, {n_fail} unscored (no {args.pdb_col}); "
        f"{n_inter} intercalating (both-side≥{args.min_both_side}"
        + (f" or single-side≥{args.min_xbridge}" if args.min_xbridge is not None else "")
        + ").",
        file=sys.stderr,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "beta-check",
        help="Flag binder→target β-sheet intercalation (β-augmentation) via DSSP cross-chain bridges.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--metrics", required=True, metavar="CSV", help="Report metrics.csv (or any CSV with id + a pdb col)."
    )
    p.add_argument("--pdb-col", default="af3_pdb", help="Column holding the complex PDB path (default af3_pdb).")
    p.add_argument("--target-chain", default="A", metavar="CH", help="Target chain (default A for AF3).")
    p.add_argument("--binder-chain", default="B", metavar="CH", help="Binder chain (default B for AF3).")
    p.add_argument("--min-both-side", type=int, default=2,
                   help="Intercalating if ≥ this many binder residues β-bridge the target on BOTH sides "
                        "(interior threading; the mechanistic augmentation signal). Default 2.")
    p.add_argument("--min-xbridge", type=int, default=None,
                   help="Opt-in: also flag if ≥ this many residues bridge on one side (edge contacts). "
                        "Off by default — edge β-pairing is a normal binding mode, not augmentation.")
    p.add_argument("--output", "-o", required=True, metavar="CSV", help="Output CSV (joinable by binder_id).")
    p.set_defaults(func=run)
