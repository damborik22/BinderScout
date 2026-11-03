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

from ..io.read import parse_sequences_any_format, split_fasta_header
from ..io.write import write_fasta


def run(args: argparse.Namespace) -> None:
    entries = parse_sequences_any_format(args.input)

    if not entries:
        print(f"[parse-seqs] No valid sequences found in {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[parse-seqs] Found {len(entries)} sequences in {Path(args.input).name}")

    # A FASTA header is 'id  key=value ...': split it so the tags are re-emitted as tags. Passing
    # the whole line as the id welds them into it, and a second pass (the output is also the next
    # run's input) would corrupt an `extract` FASTA.
    split = [split_fasta_header(h) for h, _ in entries]
    write_fasta(
        [s for _, s in entries],
        args.output,
        headers=[i for i, _ in split],
        tags=[t for _, t in split],
    )
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
