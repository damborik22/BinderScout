"""CLI subcommand: binder-compare refold-esmfold2

Refold sequences from a FASTA file using ESMFold2 (biohub).
Run this in the 'binder-eval-esmfold2' conda environment.

Usage:
    conda run -n binder-eval-esmfold2 binder-compare refold-esmfold2 \\
        --sequences sequences.fasta \\
        --target-seq "MKTAYIAKQRQ..." \\
        --output esmfold2_results.csv \\
        --output-dir ./refold_esmfold2/
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.esmfold2_runner import run_esmfold2_refold


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[refold-esmfold2] ERROR: no sequences found in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    sequences = [seq for _, seq in entries]
    print(f"[refold-esmfold2] Loaded {len(sequences)} sequences from {args.sequences}")

    run_esmfold2_refold(
        sequences=sequences,
        target_sequence=args.target_seq,
        output_dir=args.output_dir,
        output_csv=args.output,
        model_name=args.model,
        num_loops=args.num_loops,
        num_sampling_steps=args.num_sampling_steps,
        num_diffusion_samples=args.num_diffusion_samples,
        seed=args.seed,
        scripts_path=args.scripts_path,
        resume=args.resume,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "refold-esmfold2",
        help="Refold sequences with ESMFold2 (biohub). Run in 'binder-eval-esmfold2' conda env.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--sequences", "-s", required=True, metavar="FASTA", help="Input FASTA (e.g. from 'binder-compare extract')"
    )
    p.add_argument("--target-seq", required=True, metavar="SEQ", help="Target protein amino acid sequence")
    p.add_argument(
        "--output",
        "-o",
        required=True,
        metavar="CSV",
        help="Output CSV path for metrics (e.g. esmfold2_results.csv)",
    )
    p.add_argument(
        "--output-dir",
        default="./refold_esmfold2",
        metavar="DIR",
        help="Directory for predicted structures and PAE files (default: ./refold_esmfold2)",
    )
    p.add_argument(
        "--model",
        default="fast",
        choices=("fast", "full"),
        help="ESMFold2 checkpoint: 'fast' (biohub/ESMFold2-Fast, default) or 'full' (biohub/ESMFold2)",
    )
    p.add_argument("--num-loops", type=int, default=3, metavar="N", help="Recycling loops (default: 3)")
    p.add_argument(
        "--num-sampling-steps", type=int, default=50, metavar="N", help="Diffusion sampling steps (default: 50)"
    )
    p.add_argument(
        "--num-diffusion-samples", type=int, default=1, metavar="N", help="Diffusion samples per call (default: 1)"
    )
    p.add_argument("--seed", type=int, default=0, metavar="N", help="Random seed (default: 0)")
    p.add_argument(
        "--scripts-path", default=None, metavar="DIR", help="Path to scripts/ directory (auto-detected if not set)"
    )
    p.add_argument("--resume", action="store_true", help="Skip binders already present in existing output CSV")
    p.set_defaults(func=run)
