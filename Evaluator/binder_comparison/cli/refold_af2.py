"""CLI subcommand: binder-compare refold-af2

Refold sequences from a FASTA file using AlphaFold2 (ColabDesign).
Run this in the 'bindcraft_pr' conda environment.

Usage:
    conda run -n bindcraft_pr binder-compare refold-af2 \\
        --sequences sequences.fasta \\
        --target-pdb target.pdb \\
        --output af2_results.csv \\
        --output-dir ./refold_af2/
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.af2_runner import run_af2_refold


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[refold-af2] ERROR: no sequences found in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    sequences = [seq for _, seq in entries]
    print(f"[refold-af2] Loaded {len(sequences)} sequences from {args.sequences}")
    print(f"[refold-af2] Target PDB: {args.target_pdb}")

    models = [int(m) for m in args.models.split(",") if m.strip()]

    run_af2_refold(
        sequences=sequences,
        target_pdb_path=args.target_pdb,
        output_dir=args.output_dir,
        output_csv=args.output,
        models=models,
        num_recycles=args.num_recycles,
        mosaic_path=args.mosaic_path,
        resume=args.resume,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "refold-af2",
        help="Refold sequences with AF2 (run in 'bindcraft_pr' conda env).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--sequences", "-s", required=True, metavar="FASTA",
                   help="Input FASTA (e.g. from 'binder-compare extract')")
    p.add_argument("--target-pdb", required=True, metavar="PDB",
                   help="Target PDB file path (chain A is used)")
    p.add_argument("--output", "-o", required=True, metavar="CSV",
                   help="Output CSV path for metrics (e.g. af2_results.csv)")
    p.add_argument("--output-dir", default="./refold_af2", metavar="DIR",
                   help="Directory for structure PDB files (default: ./refold_af2)")
    p.add_argument("--models", default="1", metavar="N[,N]",
                   help="Comma-separated AF2 model indices (default: 1)")
    p.add_argument("--num-recycles", type=int, default=3, metavar="N",
                   help="AF2 recycling iterations (default: 3)")
    p.add_argument("--mosaic-path", default=None, metavar="DIR",
                   help="Path to Mosaic repo root (auto-detected if not set)")
    p.add_argument("--resume", action="store_true",
                   help="Skip binders already present in existing output CSV")
    p.set_defaults(func=run)
