"""Shared `--<tool> DIR` argparse group for the subcommands that ingest tool output.

`extract` and `run` each declared their own tool flags, and they drifted: `run`
offered only --bindcraft/--boltzgen/--mosaic/--pxdesign, so the advertised
single-command path silently omitted every design from RFD3, Protein-Hunter and
Proteina-Complexa — the Part L and Part M additions — and passing --rfd3 to it was
rejected outright by argparse with no hint that `extract` supported it.

One definition, used by both, so a newly wired tool cannot reach one and not the
other. The order here matches the canonical tool order used elsewhere in the
report and in the configurator's TOOL_SEQUENCE.
"""

from __future__ import annotations

import argparse

# (flag, argparse dest, help text). dest is explicit so the hyphenated flags keep
# their underscore attribute names regardless of argparse version behaviour.
TOOL_FLAGS: list[tuple[str, str, str]] = [
    ("--bindcraft", "bindcraft", "BindCraft output directory"),
    ("--boltzgen", "boltzgen", "BoltzGen output directory"),
    ("--mosaic", "mosaic", "Mosaic output directory (containing designs.csv)"),
    ("--pxdesign", "pxdesign", "PXDesign output directory (containing summary.csv)"),
    (
        "--proteina-complexa",
        "proteina_complexa",
        "Proteina-Complexa output directory (containing sequences.csv)",
    ),
    (
        "--protein-hunter",
        "protein_hunter",
        "Protein-Hunter output directory (containing summary_high_iptm.csv)",
    ),
    ("--rfd3", "rfd3", "RFD3 / foundry output directory (containing sequences.csv)"),
]

TOOL_DESTS: tuple[str, ...] = tuple(dest for _flag, dest, _help in TOOL_FLAGS)


def add_tool_args(parser: argparse.ArgumentParser) -> None:
    """Add one `--<tool> DIR` option per design tool."""
    for flag, dest, help_text in TOOL_FLAGS:
        parser.add_argument(flag, dest=dest, metavar="DIR", help=help_text)


def requested_tools(args: argparse.Namespace) -> list[tuple[str, str]]:
    """(dest, directory) for every tool flag the caller actually passed."""
    return [(dest, getattr(args, dest)) for dest in TOOL_DESTS if getattr(args, dest, None)]
