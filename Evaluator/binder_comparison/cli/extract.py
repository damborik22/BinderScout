"""CLI subcommand: binder-compare extract

Pulls sequences from one or more tool output directories, deduplicates,
tags each with its source tool, and writes a unified FASTA file.

Usage:
    binder-compare extract [--bindcraft DIR] [--boltzgen DIR] [--mosaic DIR]
                           --output sequences.fasta [--keep-duplicates]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core.schema import ExtractedBinder
from ..extractors import (
    BindCraftExtractor,
    BoltzGenExtractor,
    MosaicExtractor,
    ProteinaComplexaExtractor,
    ProteinHunterExtractor,
    PXDesignExtractor,
    RFD3Extractor,
)
from ..io.write import write_fasta


def run(args: argparse.Namespace) -> None:
    all_binders: list[ExtractedBinder] = []

    if args.bindcraft:
        print(f"[extract] BindCraft: {args.bindcraft}")
        extracted = BindCraftExtractor().extract(args.bindcraft)
        print(f"  → {len(extracted)} sequences")
        all_binders.extend(extracted)

    if args.boltzgen:
        print(f"[extract] BoltzGen: {args.boltzgen}")
        extracted = BoltzGenExtractor().extract(args.boltzgen)
        print(f"  → {len(extracted)} sequences")
        all_binders.extend(extracted)

    if args.mosaic:
        print(f"[extract] Mosaic: {args.mosaic}")
        top_only = not getattr(args, "all_mosaic_designs", False)
        extracted = MosaicExtractor(top_only=top_only).extract(args.mosaic)
        print(f"  → {len(extracted)} sequences")
        all_binders.extend(extracted)

    if args.pxdesign:
        print(f"[extract] PXDesign: {args.pxdesign}")
        extracted = PXDesignExtractor().extract(args.pxdesign)
        print(f"  → {len(extracted)} sequences")
        all_binders.extend(extracted)

    if args.rfd3:
        print(f"[extract] RFD3: {args.rfd3}")
        extracted = RFD3Extractor().extract(args.rfd3)
        print(f"  → {len(extracted)} sequences")
        all_binders.extend(extracted)

    if args.proteina_complexa:
        print(f"[extract] Proteina-Complexa: {args.proteina_complexa}")
        extracted = ProteinaComplexaExtractor().extract(args.proteina_complexa)
        print(f"  → {len(extracted)} sequences")
        all_binders.extend(extracted)

    if args.protein_hunter:
        print(f"[extract] Protein-Hunter: {args.protein_hunter}")
        all_runs = getattr(args, "all_protein_hunter_designs", False)
        extracted = ProteinHunterExtractor(all_runs=all_runs).extract(args.protein_hunter)
        print(f"  → {len(extracted)} sequences")
        all_binders.extend(extracted)

    if not all_binders:
        print("[extract] ERROR: no binders found. Check input directories.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate by sequence (keep first occurrence, preserving source order)
    if not args.keep_duplicates:
        seen: set[str] = set()
        deduped: list[ExtractedBinder] = []
        n_dupes = 0
        for b in all_binders:
            if b.sequence not in seen:
                seen.add(b.sequence)
                deduped.append(b)
            else:
                n_dupes += 1
        if n_dupes:
            print(f"[extract] Removed {n_dupes} duplicate sequence(s).")
        all_binders = deduped

    print(f"[extract] Total: {len(all_binders)} unique binders")

    headers = [b.binder_id for b in all_binders]
    sequences = [b.sequence for b in all_binders]
    tags = [{"source": b.source_tool, "length": len(b.sequence)} for b in all_binders]

    output = Path(args.output)
    write_fasta(sequences, output, headers=headers, tags=tags)
    print(f"[extract] Written → {output}")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "extract",
        help="Extract binder sequences from tool outputs into a unified FASTA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--bindcraft", metavar="DIR", help="BindCraft output directory")
    p.add_argument("--boltzgen", metavar="DIR", help="BoltzGen output directory")
    p.add_argument("--mosaic", metavar="DIR", help="Mosaic output directory (containing designs.csv)")
    p.add_argument("--pxdesign", metavar="DIR", help="PXDesign output directory (containing summary.csv)")
    p.add_argument("--rfd3", metavar="DIR", help="RFD3 / foundry output directory")
    p.add_argument(
        "--proteina-complexa",
        metavar="DIR",
        dest="proteina_complexa",
        help="Proteina-Complexa output directory (containing sequences.csv)",
    )
    p.add_argument(
        "--protein-hunter",
        metavar="DIR",
        dest="protein_hunter",
        help="Protein-Hunter output directory (containing summary_high_iptm.csv)",
    )
    p.add_argument("--output", "-o", required=True, metavar="FILE", help="Output FASTA path (e.g. sequences.fasta)")
    p.add_argument("--keep-duplicates", action="store_true", help="Do not deduplicate identical sequences across tools")
    p.add_argument(
        "--all-mosaic-designs",
        action="store_true",
        help="Include all Mosaic designs (default: only is_top=1 refolded designs)",
    )
    p.add_argument(
        "--all-protein-hunter-designs",
        action="store_true",
        help="Include all Protein-Hunter designs (default: only summary_high_iptm.csv rows)",
    )
    p.set_defaults(func=run)
