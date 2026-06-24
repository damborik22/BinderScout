"""CLI subcommand: binder-compare wetlab

Turn ranked designs into a Markdown wet-lab plan — gene synthesis, expression, budget-
aware assay selection, characterization, controls, and a FASTA with computed properties.

Usage:
    binder-compare wetlab --designs report/top30_candidates.csv -o wetlab_plan.md \\
        --top 20 --budget 8000 --tag His6-TEV
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..comparison.wetlab import WetLabConfig, wetlab_plan_markdown
from ..io.read import read_csv_safe

_ID_COLS = ("binder_id", "id", "design_id")
_SEQ_COLS = ("sequence", "binder_sequence", "designed_chain_sequence")


def run(args: argparse.Namespace) -> None:
    path = Path(args.designs)
    if not path.exists():
        print(f"Error: designs CSV not found: {path}", file=sys.stderr)
        sys.exit(1)

    df = read_csv_safe(path)
    seq_col = next((c for c in _SEQ_COLS if c in df.columns), None)
    if seq_col is None:
        print(f"Error: no sequence column in {path} (looked for {_SEQ_COLS}).", file=sys.stderr)
        sys.exit(1)
    id_col = next((c for c in _ID_COLS if c in df.columns), None)

    designs: list[dict] = []
    for i, row in df.iterrows():
        designs.append(
            {
                "binder_id": str(row[id_col]) if id_col else f"design_{i + 1}",
                "sequence": str(row[seq_col]),
            }
        )

    cfg = WetLabConfig(
        organism=args.organism,
        budget_usd=args.budget,
        top_n=args.top,
        tag=args.tag,
    )
    md = wetlab_plan_markdown(designs, cfg)

    if args.output:
        Path(args.output).write_text(md)
        print(f"[wetlab] Plan → {args.output}  ({min(args.top, len(designs))} designs)")
    else:
        print(md)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "wetlab",
        help="Generate a Markdown wet-lab plan (synthesis / expression / assays / FASTA) from ranked designs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--designs", required=True, metavar="CSV", help="Ranked designs CSV (e.g. report top-N)")
    p.add_argument("--top", type=int, default=20, metavar="N", help="How many top designs to include (default 20)")
    p.add_argument("--budget", type=float, default=None, metavar="USD", help="Budget in USD (tunes assay selection)")
    p.add_argument("--organism", default="e_coli", metavar="ORG", help="Expression organism (default e_coli)")
    p.add_argument("--tag", default="His6-TEV", metavar="TAG", help="Construct tag (default His6-TEV)")
    p.add_argument("--output", "-o", metavar="MD", help="Write the plan here (default: stdout)")
    p.set_defaults(func=run)
