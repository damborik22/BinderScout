"""CLI subcommand: binder-compare epitope (Item 2).

Compute the per-design ``epitope_match_fraction`` against an intended hotspot
list and write a CSV the report can join. **Advisory** — never reorders or
drops designs in the report; just surfaces whether each design's refolded
interface lands on the campaign's intended epitope.

Usage:
    binder-compare epitope \\
        --hotspots "A15,A18,A19,A22,A232,A240,A242,A260,A263,A264,A267,A366,A368,A371" \\
        --metrics  report/top30_candidates.csv \\
        --structures-dir runs/2VDY-BM1/refold_boltz2/ \\
        -o epitope.csv

Then pass the result to ``binder-compare report --epitope-results epitope.csv``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..comparison.epitope import (
    epitope_match,
    extract_interface_residues,
    parse_hotspots,
)
from ..io.read import read_csv_safe

_ID_COLS = ("binder_id", "design_id", "id")


def run(args: argparse.Namespace) -> None:
    metrics_path = Path(args.metrics)
    if not metrics_path.exists():
        print(f"Error: metrics CSV not found: {metrics_path}", file=sys.stderr)
        sys.exit(1)
    metrics = read_csv_safe(metrics_path)
    metrics_id = next((c for c in _ID_COLS if c in metrics.columns), None)
    if metrics_id is None:
        print(f"Error: no id column ({'/'.join(_ID_COLS)}) in {metrics_path}.", file=sys.stderr)
        sys.exit(1)

    hotspots = parse_hotspots(args.hotspots) if args.hotspots else []
    if not hotspots:
        print(
            "Error: --hotspots is empty or unparseable. Example: --hotspots 'A15,A18,A232,A263'",
            file=sys.stderr,
        )
        sys.exit(1)

    structures_dir = Path(args.structures_dir)
    if not structures_dir.is_dir():
        print(f"Error: --structures-dir not a directory: {structures_dir}", file=sys.stderr)
        sys.exit(1)

    binder_chain = args.binder_chain.upper()
    target_chain = args.target_chain.upper() if args.target_chain else None
    cutoff = float(args.cutoff)

    rows: list[dict] = []
    n_found = 0
    n_missing = 0
    for binder_id in metrics[metrics_id].astype(str):
        pdb = _locate_structure(structures_dir, binder_id)
        if pdb is None:
            n_missing += 1
            rows.append(
                {
                    "binder_id": binder_id,
                    "epitope_match_fraction": "",
                    "epitope_match_n": "",
                    "epitope_n_interface": "",
                    "epitope_off_target_residues": "",
                    "epitope_matched_residues": "",
                    "epitope_status": "NO_STRUCTURE",
                }
            )
            continue
        interface = extract_interface_residues(pdb, binder_chain, target_chain, cutoff=cutoff)
        fraction, matched, off_target = epitope_match(interface, hotspots)
        n_found += 1
        rows.append(
            {
                "binder_id": binder_id,
                "epitope_match_fraction": f"{fraction:.3f}" if fraction == fraction else "",
                "epitope_match_n": len(matched),
                "epitope_n_interface": len(interface),
                "epitope_off_target_residues": ",".join(
                    f"{c}{r}" if c else str(r) for c, r in sorted(off_target, key=lambda x: (x[0], x[1]))
                ),
                "epitope_matched_residues": ",".join(
                    f"{c}{r}" if c else str(r) for c, r in sorted(matched, key=lambda x: (x[0], x[1]))
                ),
                "epitope_status": ("OK" if fraction >= args.flag_threshold else "OFF_TARGET"),
            }
        )

    # Write CSV (stdlib — keeps the script lightweight for ad-hoc shell use).
    import csv

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "binder_id",
                "epitope_match_fraction",
                "epitope_match_n",
                "epitope_n_interface",
                "epitope_off_target_residues",
                "epitope_matched_residues",
                "epitope_status",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"[epitope] {out_path}: {n_found} designs scored, {n_missing} missing structures. "
        f"Hotspots: {len(hotspots)} positions ({', '.join(f'{h.chain_id}{h.resnum}' if h.chain_id else str(h.resnum) for h in hotspots[:5])}{'…' if len(hotspots) > 5 else ''}). "
        f"Flag threshold: {args.flag_threshold:g}.",
        file=sys.stderr,
    )


def _locate_structure(structures_dir: Path, binder_id: str) -> Path | None:
    """Find the PDB/CIF for *binder_id* in the structures dir.

    Searches for the binder_id as either a stem or substring of any
    .pdb/.cif file in the directory. Returns the first match.
    """
    bid = str(binder_id).strip()
    if not bid:
        return None
    # Exact-stem match first (cheapest)
    for ext in (".pdb", ".cif"):
        p = structures_dir / f"{bid}{ext}"
        if p.exists():
            return p
    # Fallback: any file whose stem contains the binder_id
    for ext in (".pdb", ".cif"):
        for p in structures_dir.glob(f"*{ext}"):
            if bid in p.stem:
                return p
    return None


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "epitope",
        help="Compute epitope_match_fraction against an intended hotspot list (advisory).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--metrics", required=True, metavar="CSV", help="Shortlist CSV with an id column")
    p.add_argument(
        "--hotspots",
        required=True,
        metavar="LIST",
        help="Comma-delimited hotspot residues, e.g. 'A15,A18,A22' or '15,18,22'.",
    )
    p.add_argument(
        "--structures-dir",
        required=True,
        metavar="DIR",
        help="Directory of refolded complex PDB/CIF files (matched by binder_id).",
    )
    p.add_argument(
        "--binder-chain",
        default="B",
        metavar="CH",
        help="Binder chain ID in the complex (default B for AF3/ESMFold2; pass A for Boltz-2).",
    )
    p.add_argument(
        "--target-chain",
        default=None,
        metavar="CH",
        help="Target chain ID (default: any chain that isn't --binder-chain).",
    )
    p.add_argument(
        "--cutoff",
        type=float,
        default=8.0,
        help="Cα-Cα distance cutoff in Å for interface residue contact (default 8.0).",
    )
    p.add_argument(
        "--flag-threshold",
        type=float,
        default=0.30,
        help="Below this fraction, epitope_status is OFF_TARGET (default 0.30).",
    )
    p.add_argument("--output", "-o", required=True, metavar="CSV", help="Output CSV (joinable by binder_id)")
    p.set_defaults(func=run)
