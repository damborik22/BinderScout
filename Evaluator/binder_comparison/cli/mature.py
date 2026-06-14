"""CLI subcommand: binder-compare mature

Pick the next maturation round from binding results. Reads a CSV of designs with an
affinity column (experimental Kd in nM, or an in-silico proxy mapped to nM), and emits a
JSON MaturationPlan: which strategy (partial diffusion / MPNN redesign / mutation scan /
done) and which parent designs to carry forward.

Usage:
    binder-compare mature --designs results.csv --affinity-col kd_nM \\
        --round 2 --top-k 5 --target-affinity 10 -o maturation_round.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..comparison.maturation import plan_maturation
from ..io.read import read_csv_safe

_ID_COLS = ("binder_id", "id", "design_id")


def run(args: argparse.Namespace) -> None:
    import pandas as pd

    path = Path(args.designs)
    if not path.exists():
        print(f"Error: designs CSV not found: {path}", file=sys.stderr)
        sys.exit(1)

    df = read_csv_safe(path)
    if args.affinity_col not in df.columns:
        print(f"Error: affinity column '{args.affinity_col}' not in {path}.", file=sys.stderr)
        sys.exit(1)
    id_col = next((c for c in _ID_COLS if c in df.columns), None)

    affinities: dict[str, float] = {}
    for i, row in df.iterrows():
        val = pd.to_numeric(row[args.affinity_col], errors="coerce")
        if pd.isna(val):
            continue
        did = str(row[id_col]) if id_col else f"design_{i + 1}"
        affinities[did] = float(val)

    plan = plan_maturation(
        affinities,
        round_number=args.round,
        top_k=args.top_k,
        target_affinity_nM=args.target_affinity,
        partial_threshold_nM=args.partial_threshold,
        mpnn_threshold_nM=args.mpnn_threshold,
    )

    payload = plan.to_dict()
    print(json.dumps(payload, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2))


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "mature",
        help="Choose the next maturation round (strategy + parents) from binding results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--designs", required=True, metavar="CSV", help="Designs CSV with an affinity column")
    p.add_argument(
        "--affinity-col", default="kd_nM", metavar="COL", help="Affinity column, nM, lower=tighter (default kd_nM)"
    )
    p.add_argument("--round", type=int, default=1, metavar="N", help="Maturation round number (default 1)")
    p.add_argument("--top-k", type=int, default=5, metavar="K", help="Parents to carry into backbone/seq rounds (5)")
    p.add_argument(
        "--target-affinity", type=float, default=None, metavar="NM", help="Stop when best affinity <= this (nM)"
    )
    p.add_argument("--partial-threshold", type=float, default=500.0, metavar="NM", help="Weak cutoff (default 500 nM)")
    p.add_argument("--mpnn-threshold", type=float, default=50.0, metavar="NM", help="Moderate cutoff (default 50 nM)")
    p.add_argument("--output", "-o", metavar="JSON", help="Also write the plan JSON here")
    p.set_defaults(func=run)
