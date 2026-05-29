"""CLI subcommand: binder-compare filter-soluprot

Score every binder in a FASTA with SoluProt 1.0 (Hon et al. 2021) and
write a per-sequence CSV. SoluProt is a sequence-only solubility
screen — no GPU, no refolding, no structural output. Run inside the
``binder-eval-soluprot`` conda env.

Usage:
    conda run -n binder-eval-soluprot binder-compare filter-soluprot \\
        --sequences sequences.fasta \\
        --output    soluprot_results.csv \\
        [--threshold 0.5] \\
        [--scripts-path /path/to/soluprot]
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.soluprot_runner import DEFAULT_THRESHOLD, run_soluprot_filter


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[filter-soluprot] ERROR: no sequences in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    binder_ids = [hdr for hdr, _ in entries]
    sequences = [seq for _, seq in entries]
    print(f"[filter-soluprot] loaded {len(sequences)} sequence(s) from {args.sequences}")
    print(f"[filter-soluprot] threshold = {args.threshold}")

    run_soluprot_filter(
        sequences=sequences,
        output_csv=args.output,
        threshold=args.threshold,
        scripts_path=args.scripts_path,
        binder_ids=binder_ids,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "filter-soluprot",
        help="Score sequences with SoluProt (sequence-only solubility screen; run in 'binder-eval-soluprot' env).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--sequences",
        "-s",
        required=True,
        metavar="FASTA",
        help="Input FASTA (e.g. from 'binder-compare extract')",
    )
    p.add_argument(
        "--output",
        "-o",
        required=True,
        metavar="CSV",
        help="Output CSV with one row per sequence (soluprot_score, soluprot_passes, soluprot_threshold)",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        metavar="N",
        help=(
            f"Score (0–1) at or above which a sequence is flagged as soluble "
            f"(default: {DEFAULT_THRESHOLD}, the SoluProt paper value). Binders "
            "are short and atypical; consider tuning after seeing the score "
            "distribution on a real run."
        ),
    )
    p.add_argument(
        "--scripts-path",
        default=None,
        metavar="DIR",
        help=(
            "Path to the unpacked SoluProt distribution (the directory "
            "containing soluprot.py). Falls back to $SOLUPROT_HOME, then to "
            "Evaluator/tools/soluprot/ inside the BinderScout repo."
        ),
    )
    p.set_defaults(func=run)
