"""Entry point for the binder-compare CLI.

Subcommands:
    extract         — pull sequences from tool outputs
    parse-seqs      — convert sequences from any format to FASTA
    refold-boltz2   — refold with Boltz-2 (run in Mosaic venv)
    refold-protenix — refold with Protenix v0.5.0 (run in bindmaster_pxdesign env)
    refold-af3      — refold with AlphaFold 3 v3.0.2 (run in binder-eval-af3 env, aarch64)
    report          — merge, normalise, generate HTML report
    run             — full pipeline orchestrator
    validate        — sanity-check input sequences before refolding
"""

from __future__ import annotations

import argparse

from .cli import extract, parse_seqs, refold_af3, refold_boltz2, refold_protenix, report, run, validate


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="binder-compare",
        description="Compare binder designs from BindCraft, BoltzGen, Mosaic, "
        "PXDesign, Proteina-Complexa, and Protein Hunter.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    extract.add_parser(subparsers)
    parse_seqs.add_parser(subparsers)
    refold_boltz2.add_parser(subparsers)
    refold_protenix.add_parser(subparsers)
    refold_af3.add_parser(subparsers)
    report.add_parser(subparsers)
    run.add_parser(subparsers)
    validate.add_parser(subparsers)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
