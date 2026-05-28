"""CLI subcommand: binder-compare refold-af3

Refold sequences from a FASTA file using AlphaFold 3 v3.0.2 (Google DeepMind).
Run this in the 'binder-eval-af3' conda environment. Needs a host with
>=100 GB GPU memory (H200, GH200, DGX Spark) — full AF3 inference will OOM on
consumer 24 GB GPUs.

Usage:
    conda run -n binder-eval-af3 binder-compare refold-af3 \\
        --sequences sequences.fasta \\
        --target-seq "MKTAYIAKQRQ..." \\
        --output af3_results.csv \\
        --output-dir ./refold_af3/
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.af3_runner import run_af3_refold


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[refold-af3] ERROR: no sequences found in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    sequences = [seq for _, seq in entries]
    print(f"[refold-af3] Loaded {len(sequences)} sequences from {args.sequences}")

    run_af3_refold(
        sequences=sequences,
        target_sequence=args.target_seq,
        output_dir=args.output_dir,
        output_csv=args.output,
        num_seeds=args.num_seeds,
        num_samples=args.num_samples,
        model_dir=args.model_dir,
        scripts_path=args.scripts_path,
        resume=args.resume,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "refold-af3",
        help="Refold sequences with AlphaFold 3 v3.0.2 (run in 'binder-eval-af3' conda env; needs >=100 GB GPU memory).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--sequences", "-s", required=True, metavar="FASTA", help="Input FASTA (e.g. from 'binder-compare extract')"
    )
    p.add_argument("--target-seq", required=True, metavar="SEQ", help="Target protein amino acid sequence")
    p.add_argument(
        "--output", "-o", required=True, metavar="CSV", help="Output CSV path for metrics (e.g. af3_results.csv)"
    )
    p.add_argument(
        "--output-dir",
        default="./refold_af3",
        metavar="DIR",
        help="Directory for AF3 predictions and structure files (default: ./refold_af3)",
    )
    p.add_argument("--num-seeds", type=int, default=1, metavar="N", help="Number of random seeds (default: 1)")
    p.add_argument("--num-samples", type=int, default=5, metavar="N", help="Diffusion samples per seed (default: 5)")
    p.add_argument(
        "--model-dir",
        default=None,
        metavar="DIR",
        help="AF3 model parameters directory (default: $AF3_MODEL_DIR or ~/.alphafold3/models)",
    )
    p.add_argument(
        "--scripts-path", default=None, metavar="DIR", help="Path to scripts/ directory (auto-detected if not set)"
    )
    p.add_argument("--resume", action="store_true", help="Skip binders already present in existing output CSV")
    p.set_defaults(func=run)
