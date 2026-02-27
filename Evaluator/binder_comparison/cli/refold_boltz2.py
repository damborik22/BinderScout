"""CLI subcommand: binder-compare refold-boltz2

Refold sequences from a FASTA file using Boltz2.
Run this in the 'binder-eval-boltz2' conda environment.

Usage:
    conda run -n binder-eval-boltz2 binder-compare refold-boltz2 \\
        --sequences sequences.fasta \\
        --target-seq "MKTAYIAKQRQ..." \\
        --output boltz2_results.csv \\
        --output-dir ./refold_boltz2/
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.boltz2_runner import run_boltz2_refold


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[refold-boltz2] ERROR: no sequences found in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    sequences = [seq for _, seq in entries]
    print(f"[refold-boltz2] Loaded {len(sequences)} sequences from {args.sequences}")
    print(f"[refold-boltz2] Target length: {len(args.target_seq)} aa")

    run_boltz2_refold(
        sequences=sequences,
        target_sequence=args.target_seq,
        output_dir=args.output_dir,
        output_csv=args.output,
        scripts_path=args.scripts_path,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "refold-boltz2",
        help="Refold sequences with Boltz2 (run in 'binder-eval-boltz2' conda env).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--sequences", "-s", required=True, metavar="FASTA",
                   help="Input FASTA (e.g. from 'binder-compare parse-seqs')")
    p.add_argument("--target-seq", required=True, metavar="SEQ",
                   help="Target protein sequence (amino acid string)")
    p.add_argument("--output", "-o", required=True, metavar="CSV",
                   help="Output CSV path for metrics (e.g. boltz2_results.csv)")
    p.add_argument("--output-dir", default="./refold_boltz2", metavar="DIR",
                   help="Directory for structure files (default: ./refold_boltz2)")
    p.add_argument("--scripts-path", default=None, metavar="DIR",
                   help="Path to scripts/ directory (auto-detected if not set)")
    p.set_defaults(func=run)
