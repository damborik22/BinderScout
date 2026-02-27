"""Entry point for the binder-compare CLI.

Subcommands:
    extract       — pull sequences from tool outputs
    refold-boltz2 — refold with Boltz2 (run in 'mosaic' env)
    refold-af2    — refold with AF2 (run in 'bindcraft_pr' env)
    report        — merge, ensemble, normalise, generate HTML report
    run           — full pipeline orchestrator
"""

from __future__ import annotations

import argparse
import sys

from .cli import extract, parse_seqs, refold_boltz2, refold_af2, report, run


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="binder-compare",
        description="Compare binder designs from BindCraft, BoltzGen, and Mosaic.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    extract.add_parser(subparsers)
    parse_seqs.add_parser(subparsers)
    refold_boltz2.add_parser(subparsers)
    refold_af2.add_parser(subparsers)
    report.add_parser(subparsers)
    run.add_parser(subparsers)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
