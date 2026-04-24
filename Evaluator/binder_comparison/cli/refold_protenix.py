"""CLI subcommand: binder-compare refold-protenix

Refold sequences from a FASTA file using Protenix v0.5.0.
Run this inside the ``bindmaster_pxdesign`` conda env.

Usage:
    conda run -n bindmaster_pxdesign binder-compare refold-protenix \\
        --sequences sequences.fasta \\
        --target-seq "MKTAYIAKQRQ..." \\
        --output protenix_results.csv \\
        --output-dir ./refold_protenix/
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.protenix_runner import run_protenix_refold


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[refold-protenix] ERROR: no sequences found in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    sequences = [seq for _, seq in entries]
    print(f"[refold-protenix] Loaded {len(sequences)} sequences from {args.sequences}")
    print(f"[refold-protenix] Target length: {len(args.target_seq)} aa")
    print(
        f"[refold-protenix] {args.num_samples} samples × {args.num_seeds} seed(s), "
        f"use_msa={args.use_msa}, n_cycle={args.n_cycle}, n_step={args.n_step}"
    )

    run_protenix_refold(
        sequences=sequences,
        target_sequence=args.target_seq,
        output_dir=args.output_dir,
        output_csv=args.output,
        num_samples=args.num_samples,
        num_seeds=args.num_seeds,
        use_msa=args.use_msa,
        n_cycle=args.n_cycle,
        n_step=args.n_step,
        scripts_path=args.scripts_path,
        resume=args.resume,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "refold-protenix",
        help="Refold sequences with Protenix v0.5.0 (run in 'bindmaster_pxdesign' conda env).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument(
        "--sequences",
        "-s",
        required=True,
        metavar="FASTA",
        help="Input FASTA (e.g. from 'binder-compare parse-seqs')",
    )
    p.add_argument("--target-seq", required=True, metavar="SEQ", help="Target protein sequence (amino acid string)")
    p.add_argument(
        "--output",
        "-o",
        required=True,
        metavar="CSV",
        help="Output CSV path for metrics (e.g. protenix_results.csv)",
    )
    p.add_argument(
        "--output-dir",
        default="./refold_protenix",
        metavar="DIR",
        help="Directory for structure files (default: ./refold_protenix)",
    )
    p.add_argument(
        "--num-samples",
        type=int,
        default=5,
        metavar="N",
        help="Protenix diffusion samples per seed (default: 5)",
    )
    p.add_argument(
        "--num-seeds",
        type=int,
        default=1,
        metavar="N",
        help="Number of random seeds (starts at 101; default: 1)",
    )
    p.add_argument(
        "--use-msa",
        action="store_true",
        help="Run ColabFold MMseqs2 MSA pipeline (slower; default is MSA-free)",
    )
    p.add_argument(
        "--n-cycle",
        type=int,
        default=10,
        metavar="N",
        help="Evoformer recycling iterations (default: 10)",
    )
    p.add_argument(
        "--n-step",
        type=int,
        default=200,
        metavar="N",
        help="Diffusion steps per sample (default: 200)",
    )
    p.add_argument(
        "--scripts-path",
        default=None,
        metavar="DIR",
        help="Path to scripts/ directory (auto-detected if not set)",
    )
    p.add_argument("--resume", action="store_true", help="Skip binders already present in existing output CSV")
    p.set_defaults(func=run)
