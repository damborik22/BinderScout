"""CLI subcommand: binder-compare analyze-target

Advisory target analysis to seed a campaign: parses a target chain, scores difficulty
(0–1), and suggests autosize parameters (per-tool N, gate tier, extra tools), a binder
length range, and candidate hotspots — from Cα neighbour density (a dependency-free SASA
proxy). Heuristic, not an oracle; see comparison/target_analysis.py.

Usage:
    binder-compare analyze-target --target target.pdb --chain A -o target_profile.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from ..comparison.target_analysis import (
    classify_difficulty,
    difficulty_score,
    flat_surface_fraction,
    neighbor_counts,
    pick_hotspots,
    suggest_binder_length,
    suggest_campaign,
)


def _ca_coords_and_resids(pdb_text: str, chain: str | None):
    """Return (coords (N,3), residue_ids) for Cα atoms of a chain."""
    coords, resids = [], []
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        if chain is not None and line[21:22].strip() != chain:
            continue
        coords.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        resids.append(line[21:22].strip() + line[22:26].strip())
    return np.asarray(coords, dtype=float).reshape(-1, 3), resids


def run(args: argparse.Namespace) -> None:
    target = Path(args.target)
    if not target.exists():
        print(f"Error: target not found: {target}", file=sys.stderr)
        sys.exit(1)
    if target.suffix.lower() not in (".pdb", ".ent"):
        print(f"Error: analyze-target needs a .pdb (got {target.suffix}); convert mmCIF first.", file=sys.stderr)
        sys.exit(1)

    coords, resids = _ca_coords_and_resids(target.read_text(), args.chain)
    if coords.shape[0] == 0:
        print(f"Error: no Cα atoms for chain {args.chain!r} in {target}.", file=sys.stderr)
        sys.exit(1)

    counts = neighbor_counts(coords, radius=args.radius)
    flat = flat_surface_fraction(counts)
    score = difficulty_score(length=coords.shape[0], disorder_fraction=0.0, flat_fraction=flat)
    hotspots = pick_hotspots(counts, resids, n=args.n_hotspots)
    lo, hi = suggest_binder_length(score)

    profile = {
        "target": target.name,
        "chain": args.chain,
        "length": int(coords.shape[0]),
        "flat_surface_fraction": round(flat, 3),
        "difficulty": score,
        "difficulty_band": classify_difficulty(score),
        "suggested_autosize": suggest_campaign(score),
        "suggested_binder_length": [lo, hi],
        "candidate_hotspots": hotspots,
        "note": "Advisory heuristic (disorder not modelled; Cα-density SASA proxy). Review before committing compute.",
    }
    print(json.dumps(profile, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(profile, indent=2))


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "analyze-target",
        help="Advisory target difficulty + autosize/length/hotspot suggestions from a PDB.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--target", required=True, metavar="PDB", help="Target structure (.pdb)")
    p.add_argument("--chain", default="A", metavar="C", help="Target chain id (default A)")
    p.add_argument("--radius", type=float, default=10.0, metavar="Å", help="Cα neighbour radius (default 10)")
    p.add_argument("--n-hotspots", type=int, default=4, metavar="N", help="Candidate hotspots to suggest (default 4)")
    p.add_argument("--output", "-o", metavar="JSON", help="Also write the profile JSON here")
    p.set_defaults(func=run)
