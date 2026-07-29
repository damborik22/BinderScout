"""Entry point for the binder-compare CLI.

Subcommands:
    extract          — pull sequences from tool outputs
    parse-seqs       — convert sequences from any format to FASTA
    refold-boltz2    — refold with Boltz-2 (run in Mosaic venv)
    refold-af3       — refold with AlphaFold 3 v3.0.2 (run in binder-eval-af3 env; needs >=100 GB GPU memory)
    refold-esmfold2  — refold with ESMFold2 (biohub; run in binder-eval-esmfold2 env)
    filter-soluprot  — score sequence solubility with SoluProt 1.0 (run in binder-eval-soluprot env; no GPU)
    report           — merge, normalise, generate HTML report
    run              — full pipeline orchestrator
    validate         — sanity-check input sequences before refolding
"""

from __future__ import annotations

import argparse

from .cli import (
    affinity,
    analyze_target,
    autosize,
    beta_check,
    diversity,
    epitope,
    epitope_map,
    extract,
    filter_soluprot,
    hits,
    mature,
    monomer,
    parse_seqs,
    prefilter,
    qc_annotate,
    refold_af3,
    refold_boltz2,
    refold_esmfold2,
    report,
    run,
    validate,
    wetlab,
)


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
    refold_af3.add_parser(subparsers)
    refold_esmfold2.add_parser(subparsers)
    filter_soluprot.add_parser(subparsers)
    prefilter.add_parser(subparsers)
    report.add_parser(subparsers)
    run.add_parser(subparsers)
    validate.add_parser(subparsers)
    autosize.add_parser(subparsers)
    wetlab.add_parser(subparsers)
    mature.add_parser(subparsers)
    monomer.add_parser(subparsers)
    affinity.add_parser(subparsers)
    qc_annotate.add_parser(subparsers)
    analyze_target.add_parser(subparsers)
    epitope_map.add_parser(subparsers)
    beta_check.add_parser(subparsers)
    epitope.add_parser(subparsers)
    diversity.add_parser(subparsers)
    hits.add_parser(subparsers)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
