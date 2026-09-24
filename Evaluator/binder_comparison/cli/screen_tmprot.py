"""CLI subcommand: binder-compare screen-tmprot

Predict a melting temperature for every binder in a FASTA with TmProt 1.0
(Loschmidt Lab, github.com/loschmidt/TmProt) and write a per-sequence CSV.
Sequence-only: no GPU, no refolding. Run inside the ``binder-eval-tmprot``
conda env.

It is called *screen*-tmprot rather than *filter*-tmprot on purpose. SoluProt
has a ``--soluprot-filter`` mode that drops sub-threshold designs before any GPU
work; TmProt has no equivalent and should not grow one. Item D1 of the 2.0
assessment: "proceed as a screen, never a ranking term", because Tm predictors
are trained on natural proteins and are out of domain on the hyperstable de novo
miniproteins this pipeline produces. Every input sequence gets a row.

Usage:
    conda run -n binder-eval-tmprot binder-compare screen-tmprot \\
        --sequences sequences.fasta \\
        --output    tmprot_results.csv \\
        [--threshold 60.0]

Then pass the CSV to the report:
    binder-compare report ... --tmprot-results tmprot_results.csv
"""

from __future__ import annotations

import argparse
import sys

from ..io.read import read_fasta
from ..refolding.tmprot_runner import DEFAULT_THRESHOLD, run_tmprot_screen


def run(args: argparse.Namespace) -> None:
    entries = read_fasta(args.sequences)
    if not entries:
        print(f"[screen-tmprot] ERROR: no sequences in {args.sequences}", file=sys.stderr)
        sys.exit(1)

    binder_ids = [hdr for hdr, _ in entries]
    sequences = [seq for _, seq in entries]
    print(f"[screen-tmprot] loaded {len(sequences)} sequence(s) from {args.sequences}")
    print(f"[screen-tmprot] thermostable threshold = {args.threshold} °C")

    try:
        run_tmprot_screen(
            sequences=sequences,
            output_csv=args.output,
            threshold=args.threshold,
            binder_ids=binder_ids,
            tmprot_bin=args.tmprot_bin,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"[screen-tmprot] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "screen-tmprot",
        help="Predict melting temperature with TmProt (sequence-only screen; run in 'binder-eval-tmprot' env).",
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
        help="Output CSV, one row per sequence (tmprot_tm, tmprot_thermostable, tmprot_threshold)",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        metavar="C",
        help=(
            f"Melting temperature (°C) at or above which a sequence is flagged "
            f"thermostable (default: {DEFAULT_THRESHOLD}, the cutoff TmProt's own "
            "AUC of 0.75–0.77 is reported against). The flag is advisory: it is "
            "never used to drop a design or to rank one."
        ),
    )
    p.add_argument(
        "--tmprot-bin",
        default=None,
        metavar="BIN",
        help="Path to the 'tmprot' console script. Falls back to $TMPROT_BIN, then PATH.",
    )
    p.set_defaults(func=run)
