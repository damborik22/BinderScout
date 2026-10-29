"""CLI subcommand: binder-compare filter-tmprot

Predict a melting temperature for every binder in a FASTA with TmProt 1.0
(Pailozian, Kohout et al., Loschmidt Laboratories) and write a per-sequence
CSV. TmProt is a sequence-only thermostability screen — no GPU required,
no refolding, no structural output. Run inside the ``binder-eval-tmprot``
conda env.

The CSV it writes is what ``binder-compare report --tmprot-results`` ingests,
which adds ``native_tmprot_tm`` (°C) alongside the other design-time screens.

ADVISORY. A predicted Tm is a stability signal, not a binding signal: nothing
in the ranking reads this column. Use it to notice the bottom of the
distribution before committing synthesis money, not to separate 68 °C from
71 °C — the published binary task (Tm >= 60 °C) scores AUC 0.75.

Usage:
    conda run -n binder-eval-tmprot binder-compare filter-tmprot \\
        --sequences sequences.fasta \\
        --output    tmprot_results.csv \\
        [--threshold 60.0]

    binder-compare report … --tmprot-results tmprot_results.csv
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.tmprot_runner import DEFAULT_THRESHOLD, run_tmprot_filter


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[filter-tmprot] ERROR: no sequences in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    binder_ids = [hdr for hdr, _ in entries]
    sequences = [seq for _, seq in entries]
    print(f"[filter-tmprot] loaded {len(sequences)} sequence(s) from {args.sequences}")
    print(f"[filter-tmprot] thermostable label at Tm > {args.threshold} °C (advisory; nothing is dropped)")

    run_tmprot_filter(
        sequences=sequences,
        output_csv=args.output,
        binder_ids=binder_ids,
        threshold=args.threshold,
        tmprot_bin=args.tmprot_bin,
    )


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "filter-tmprot",
        help="Predict melting temperature with TmProt (sequence-only; run in 'binder-eval-tmprot' env).",
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
        help="Where to write the per-sequence Tm CSV (feed to 'report --tmprot-results')",
    )
    p.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"Thermostable Yes/No label cutoff in °C (default: {DEFAULT_THRESHOLD}). "
        "Labels only — no sequence is dropped at any threshold.",
    )
    p.add_argument(
        "--tmprot-bin",
        default="tmprot",
        metavar="PATH",
        help="TmProt executable (default: 'tmprot' on PATH)",
    )
    p.set_defaults(func=run)
