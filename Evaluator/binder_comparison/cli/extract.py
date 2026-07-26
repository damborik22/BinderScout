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
from ._tool_args import add_tool_args


def run(args: argparse.Namespace) -> None:
    all_binders: list[ExtractedBinder] = []
    per_tool: dict[str, int] = {}

    def _take(dest: str, extracted: list[ExtractedBinder]) -> None:
        """Record and absorb one tool's extraction result."""
        print(f"  → {len(extracted)} sequences")
        per_tool[dest] = len(extracted)
        all_binders.extend(extracted)

    # "Best design, not multiple sequences per design" — default on. Collapses
    # BindCraft MPNN variants to best per trajectory and Protein-Hunter cycles to
    # best per run, so the refold pool is clean from the start.
    collapse = not getattr(args, "no_collapse_variants", False)

    if args.bindcraft:
        print(f"[extract] BindCraft: {args.bindcraft}")
        extracted = BindCraftExtractor(collapse_variants=collapse).extract(args.bindcraft)
        _take("bindcraft", extracted)

    if args.boltzgen:
        print(f"[extract] BoltzGen: {args.boltzgen}")
        extracted = BoltzGenExtractor().extract(args.boltzgen)
        _take("boltzgen", extracted)

    if args.mosaic:
        print(f"[extract] Mosaic: {args.mosaic}")
        top_only = not getattr(args, "all_mosaic_designs", False)
        extracted = MosaicExtractor(top_only=top_only).extract(args.mosaic)
        _take("mosaic", extracted)

    if args.pxdesign:
        print(f"[extract] PXDesign: {args.pxdesign}")
        extracted = PXDesignExtractor().extract(args.pxdesign)
        _take("pxdesign", extracted)

    if args.rfd3:
        print(f"[extract] RFD3: {args.rfd3}")
        extracted = RFD3Extractor().extract(args.rfd3)
        _take("rfd3", extracted)

    if args.proteina_complexa:
        print(f"[extract] Proteina-Complexa: {args.proteina_complexa}")
        extracted = ProteinaComplexaExtractor().extract(args.proteina_complexa)
        _take("proteina_complexa", extracted)

    if args.protein_hunter:
        print(f"[extract] Protein-Hunter: {args.protein_hunter}")
        all_runs = getattr(args, "all_protein_hunter_designs", False)
        extracted = ProteinHunterExtractor(all_runs=all_runs, collapse_variants=collapse).extract(args.protein_hunter)
        _take("protein_hunter", extracted)

    # A requested tool that yielded nothing is an ERROR, not a shrug. The old guard
    # only fired when EVERY tool came up empty, so a typo in one of four --tool paths
    # (or a tool whose run died before writing its CSV) printed "→ 0 sequences" and
    # exited 0 — and run_evaluate.sh under `set -e` then spent hours of Boltz-2 + AF3 +
    # ESMFold2 GPU time on a silently partial pool that looked complete in the report.
    empty = [dest for dest, n in per_tool.items() if n == 0]
    if empty and not getattr(args, "allow_empty", False):
        print(
            f"[extract] ERROR: {', '.join(sorted(empty))} produced 0 sequences. "
            f"Check the directory path, and that the run finished and wrote its output. "
            f"Pass --allow-empty to continue anyway.",
            file=sys.stderr,
        )
        sys.exit(1)

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

    # Sidecar: per-binder native (design-time) metrics. The report step
    # auto-detects this file next to the FASTA and left-joins onto the merged
    # refold results so the final CSV / HTML show "what the tool said about
    # its own design" next to "what the refold engines say".
    _write_native_metrics_sidecar(all_binders, output)

    # Optionally collect each design's ORIGINAL complex structure into DIR/<tool>/
    # so the report can show the tool's own design (matched by binder sequence).
    if getattr(args, "collect_structures", None):
        from ..structures import collect_design_structures

        tool_dir = {
            "bindcraft": args.bindcraft,
            "boltzgen": args.boltzgen,
            "mosaic": args.mosaic,
            "pxdesign": args.pxdesign,
            "rfd3": args.rfd3,
            "proteina_complexa": args.proteina_complexa,
            "protein_hunter": args.protein_hunter,
        }
        by_tool: dict[str, list[str]] = {}
        for b in all_binders:
            by_tool.setdefault(b.source_tool, []).append(b.sequence)
        cdir = Path(args.collect_structures)
        for tool, seqs in by_tool.items():
            idir = tool_dir.get(tool)
            if not idir:
                continue
            n = collect_design_structures(idir, seqs, cdir / tool)
            print(f"[extract] {tool}: collected {n}/{len(seqs)} original structures → {cdir / tool}")


def _write_native_metrics_sidecar(binders: list[ExtractedBinder], fasta_path: Path) -> None:
    """Write a CSV next to the extracted FASTA with one row per binder containing
    `sequence`, `source_tool`, `binder_id`, and every NativeMetrics field
    (column-named `native_<field>` to match `MetricResult.to_flat_dict()`).
    """
    from dataclasses import asdict

    from ..core.schema import NativeMetrics

    sidecar = fasta_path.with_name(fasta_path.stem + "_native_metrics.csv")
    field_names = list(NativeMetrics.__dataclass_fields__)

    import csv

    with sidecar.open("w", newline="") as fh:
        writer = csv.writer(fh)
        header = ["sequence", "source_tool", "binder_id"] + [f"native_{f}" for f in field_names]
        writer.writerow(header)
        for b in binders:
            native_d = asdict(b.native)
            row = [b.sequence, b.source_tool, b.binder_id]
            for f in field_names:
                v = native_d.get(f)
                row.append("" if v is None else v)
            writer.writerow(row)
    print(f"[extract] Native metrics → {sidecar}")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "extract",
        help="Extract binder sequences from tool outputs into a unified FASTA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    add_tool_args(p)
    p.add_argument("--output", "-o", required=True, metavar="FILE", help="Output FASTA path (e.g. sequences.fasta)")
    p.add_argument("--keep-duplicates", action="store_true", help="Do not deduplicate identical sequences across tools")
    p.add_argument(
        "--allow-empty",
        action="store_true",
        help="Continue when a requested --<tool> directory yields 0 sequences (default: error out, "
        "so a mistyped path cannot silently shrink the pool before hours of GPU refolding)",
    )
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
    p.add_argument(
        "--no-collapse-variants",
        action="store_true",
        help="Disable the default 'best design, not multiple sequences per design' collapse "
        "(BindCraft MPNN variants → best per trajectory; Protein-Hunter cycles → best per run).",
    )
    p.add_argument(
        "--collect-structures",
        metavar="DIR",
        help="Copy each design's ORIGINAL complex structure (matched by binder sequence) into "
        "DIR/<tool>/ next to the FASTA, for the report's --tool-pdb-dir <tool>=DIR/<tool>. "
        "Filename/folder-agnostic; cif/.gz converted to PDB. Tools whose structures lack the "
        "design sequence (e.g. RFD3 backbones) collect nothing and fall back to refold.",
    )
    p.set_defaults(func=run)
