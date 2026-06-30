"""CLI subcommand: binder-compare diversity (Item 1).

Cluster designs into 'families' by sequence identity (and optionally
structural RMSD), so the report can flag redundant top-30 entries.

Usage:
    binder-compare diversity \\
        --metrics report/top30_candidates.csv \\
        --output  diversity.csv \\
        --threshold 0.70

Then pass the result to ``binder-compare report --diversity-results diversity.csv``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..comparison.diversity import cluster_sequences_df
from ..io.read import read_csv_safe

_ID_COLS = ("binder_id", "design_id", "id")
_SEQUENCE_COLS = ("sequence", "designed_chain_sequence", "Sequence")


def run(args: argparse.Namespace) -> None:
    metrics_path = Path(args.metrics)
    if not metrics_path.exists():
        print(f"Error: --metrics file not found: {metrics_path}", file=sys.stderr)
        sys.exit(1)
    metrics = read_csv_safe(metrics_path)
    seq_col = next((c for c in _SEQUENCE_COLS if c in metrics.columns), None)
    if seq_col is None:
        print(
            f"Error: --metrics CSV needs a sequence column (one of {', '.join(_SEQUENCE_COLS)}); "
            f"found columns: {list(metrics.columns[:10])}",
            file=sys.stderr,
        )
        sys.exit(1)
    id_col = next((c for c in _ID_COLS if c in metrics.columns), None)
    out = cluster_sequences_df(
        metrics,
        sequence_col=seq_col,
        threshold=args.threshold,
        k=args.k,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Write only the columns the report needs, keyed by id.
    keep = [id_col] if id_col else []
    keep += [c for c in ("family_id", "family_size", "family_rank") if c in out.columns]
    if seq_col not in keep:
        keep.append(seq_col)
    out[keep].to_csv(out_path, index=False)
    n_families = int(out["family_id"].nunique())
    largest = int(out["family_size"].max()) if not out.empty else 0
    print(
        f"[diversity] {out_path}: {len(out)} designs → {n_families} families "
        f"(largest = {largest}, threshold = {args.threshold:g} Jaccard on {args.k}-mers).",
        file=sys.stderr,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "diversity",
        help="Cluster designs into families by sequence identity (CD-HIT-style greedy).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--metrics", required=True, metavar="CSV", help="CSV with at least an id + sequence column")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Jaccard similarity threshold for merging into an existing family (default 0.7).",
    )
    p.add_argument("--k", type=int, default=4, help="k-mer length for the Jaccard similarity (default 4).")
    p.add_argument("--output", "-o", required=True, metavar="CSV", help="Output CSV (joinable by binder_id)")
    p.set_defaults(func=run)
