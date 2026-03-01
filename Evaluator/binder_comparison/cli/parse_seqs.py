"""CLI subcommand: binder-compare parse-seqs

Convert binder sequences from any common format to a clean FASTA file.

Accepted input formats (auto-detected):
  - FASTA
  - One sequence per line
  - Comma-separated sequences
  - Semicolon-separated sequences
  - CSV / TSV with a 'sequence' column

Usage:
    binder-compare parse-seqs --input sequences.txt --output sequences.fasta
    binder-compare parse-seqs --input sequences.csv -o sequences.fasta
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..io.read import parse_sequences_any_format
from ..io.write import write_fasta


def run(args: argparse.Namespace) -> None:
    entries = parse_sequences_any_format(args.input)

    if not entries:
        print(f"[parse-seqs] No valid sequences found in {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[parse-seqs] Found {len(entries)} sequences in {Path(args.input).name}")

    headers, sequences = zip(*entries)
    write_fasta(sequences, args.output, headers=headers)
    print(f"[parse-seqs] Written → {args.output}")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "parse-seqs",
        help="Convert sequences from any format (FASTA, one-per-line, CSV, comma-separated) to FASTA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--input", "-i", required=True, metavar="FILE", help="Input file in any supported format")
    p.add_argument("--output", "-o", required=True, metavar="FASTA", help="Output FASTA file")
    p.set_defaults(func=run)
