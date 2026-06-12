"""CLI subcommand: binder-compare autosize

Decide whether enough INDEPENDENT designs (backbones, not sequences) have cleared
the ESMFold2 chain-pair interface iPTM gate, and how many more to generate if not.

This is the deployment-agnostic verdict step. It consumes an ESMFold2 refold CSV
(``binder-compare refold-esmfold2`` output) and prints a JSON Verdict. The loop
wrapper (generate the suggested batch locally, or write the "need M more" signal
into PROGRESS.md for a remote worker) calls this each round.

Usage:
    binder-compare autosize \\
        --esmfold2-results esmfold2_results.csv \\
        --designs          sequences_native_metrics.csv  \\  # for backbone dedup
        --n-target 50 --threshold 0.75 \\
        --budget-spent 12.5 --budget-cap 80
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..comparison.autosize import autosize_decision, count_independent_passers
from ..comparison.scoring import add_chain_iptm_interface, add_design_groups
from ..io.read import read_csv_safe

DEFAULT_SCORE_COL = "chain_iptm_interface"


def run(args: argparse.Namespace) -> None:
    results_path = Path(args.esmfold2_results)
    if not results_path.exists():
        print(f"Error: ESMFold2 results not found: {results_path}", file=sys.stderr)
        sys.exit(1)

    df = read_csv_safe(results_path)
    # Derive the gate metric from the raw refold columns (iptm_pair / iptm_pair_min).
    df = add_chain_iptm_interface(df, prefix="")
    if args.score_col not in df.columns:
        print(
            f"Error: score column '{args.score_col}' not in results and could not be derived "
            f"(need iptm_pair/iptm_pair_min for the default). Columns: {list(df.columns)}",
            file=sys.stderr,
        )
        sys.exit(1)

    df = _attach_design_groups(df, args.designs)

    passers, n_independent = count_independent_passers(
        df, threshold=args.threshold, score_col=args.score_col, group_col="design_group"
    )
    verdict = autosize_decision(
        have=passers,
        n_independent=n_independent,
        n_target=args.n_target,
        budget_spent=args.budget_spent,
        budget_cap=args.budget_cap,
        margin=args.margin,
    )

    payload = verdict.to_dict()
    payload["threshold"] = args.threshold
    payload["score_col"] = args.score_col
    print(json.dumps(payload, indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2))


def _attach_design_groups(df, designs_csv: str | None):
    """Add a ``design_group`` column so the count is per backbone, not per sequence.

    Prefers an extract sidecar CSV (``--designs``: sequence, binder_id, source_tool)
    joined by sequence; falls back to binder_id already on the frame; else counts
    per-row (no dedup) with a warning.
    """
    if "binder_id" not in df.columns and designs_csv:
        designs = read_csv_safe(designs_csv)
        if "sequence" in designs.columns and "binder_id" in designs.columns:
            keep = ["sequence", "binder_id"] + (["source_tool"] if "source_tool" in designs.columns else [])
            df = df.merge(designs[keep].drop_duplicates("sequence"), on="sequence", how="left")

    if "binder_id" in df.columns:
        return add_design_groups(df)

    print(
        "[autosize] WARNING: no binder_id (pass --designs with the extract sidecar) — "
        "counting per-row, so multiple sequences of one backbone are NOT collapsed.",
        file=sys.stderr,
    )
    df = df.copy()
    df["design_group"] = [str(i) for i in range(len(df))]
    return df


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "autosize",
        help="Decide whether enough independent designs cleared the ESMFold2 gate; size the next batch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--esmfold2-results", required=True, metavar="CSV", help="ESMFold2 refold CSV (binder-compare refold-esmfold2)"
    )
    p.add_argument(
        "--designs",
        metavar="CSV",
        help="Extract sidecar (sequence, binder_id, source_tool) for backbone dedup. "
        "Without it, designs are counted per-row.",
    )
    p.add_argument("--n-target", type=int, required=True, metavar="N", help="Target number of INDEPENDENT designs")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        metavar="X",
        help="Gate cutoff on the score column (default 0.75; calibrate per target — see Phase 2).",
    )
    p.add_argument(
        "--score-col",
        default=DEFAULT_SCORE_COL,
        metavar="COL",
        help=f"Gate metric column (default {DEFAULT_SCORE_COL}, the ESMFold2 chain-pair interface iPTM).",
    )
    p.add_argument("--budget-spent", type=float, default=0.0, metavar="H", help="GPU-hours spent so far (default 0)")
    p.add_argument(
        "--budget-cap", type=float, default=None, metavar="H", help="GPU-hour cap; stop with 'budget' if reached"
    )
    p.add_argument(
        "--margin", type=float, default=1.2, metavar="F", help="Safety factor on the next batch (default 1.2)"
    )
    p.add_argument("--output", "-o", metavar="JSON", help="Also write the Verdict JSON here")
    p.set_defaults(func=run)
