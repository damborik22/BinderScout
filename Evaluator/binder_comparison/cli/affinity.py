"""CLI subcommand: binder-compare affinity

Rank affinity *among binders* (Part N). Scores each design on the interface energy density
``|dG/dSASA|`` (Rosetta interface energy) and GATES on ``ipsae_min`` to cull non-binders —
ipsae_min is a binder gate, NOT a ranking multiplier (it carries no affinity signal among
binders; see comparison/affinity.py). Either supply a precomputed energy CSV (``--energy``)
or let this run InterfaceAnalyzer over a structures directory in the BindCraft conda env
(``--structures-dir --run-rosetta``) — PyRosetta is available there on every BindCraft
platform, including aarch64 / Spark.

Usage:
    binder-compare affinity --metrics report/metrics.csv --energy interface_energy.csv -o affinity.csv
    binder-compare affinity --metrics report/metrics.csv --structures-dir runs/X/structures \\
        --run-rosetta --interface B_A -o affinity.csv
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ..comparison.affinity import DEFAULT_AFFINITY_GATE, add_affinity_ranking
from ..io.read import read_csv_safe

_ID_COLS = ("binder_id", "design_id", "id")

# report.py:533 exports the top-N structures as rank{NN}_{binder_id}.pdb.
_RANK_PREFIX = re.compile(r"^rank\d+_")
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "interface_energy.py"


def run(args: argparse.Namespace) -> None:
    metrics_path = Path(args.metrics)
    if not metrics_path.exists():
        print(f"Error: metrics CSV not found: {metrics_path}", file=sys.stderr)
        sys.exit(1)
    metrics = read_csv_safe(metrics_path)
    if args.ipsae_col not in metrics.columns:
        print(f"Error: ipsae column '{args.ipsae_col}' not in {metrics_path}.", file=sys.stderr)
        sys.exit(1)

    energy_path = _resolve_energy(args)
    energy = read_csv_safe(energy_path)

    metrics_id = next((c for c in _ID_COLS if c in metrics.columns), None)
    if metrics_id is None or "design_id" not in energy.columns:
        print("Error: need an id column in metrics and 'design_id' in the energy CSV to join.", file=sys.stderr)
        sys.exit(1)

    # interface_energy.py keys rows by the structure filename stem, and the
    # structures this is pointed at are the report's rank{NN}_{binder_id}.pdb
    # export — so the id carries a rank prefix the metrics table does not have.
    energy = energy.copy()
    energy["_join_id"] = energy["design_id"].astype(str).str.replace(_RANK_PREFIX, "", regex=True).str.strip()

    merged = metrics.merge(
        energy[["_join_id", "interface_dG", "interface_dSASA"]],
        left_on=metrics_id,
        right_on="_join_id",
        how="left",
    )

    # Matching nothing is a keying bug, not "these designs have no energy". Left
    # unchecked it silently degrades the Part N ranking to the ipsae gate alone
    # while reporting "0/N designs scored" and exiting 0.
    if len(energy) and not merged["_join_id"].notna().any():
        print(
            f"Error: the energy CSV has {len(energy)} row(s) but none of its design_id values "
            f"match '{metrics_id}' in the metrics table.\n"
            f"  energy design_id e.g.: {energy['design_id'].iloc[0]!r}\n"
            f"  metrics {metrics_id} e.g.: {metrics[metrics_id].iloc[0]!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    merged = merged.drop(columns=["_join_id"])
    merged = add_affinity_ranking(
        merged,
        ipsae_col=args.ipsae_col,
        dg_col="interface_dG",
        dsasa_col="interface_dSASA",
        gate_threshold=args.gate_threshold,
    )
    # Gate culls non-binders (ipsae_min ≥ threshold), density ranks the survivors.
    merged = merged.sort_values(
        ["passes_affinity_gate", "affinity_energy_density"], ascending=[False, False], na_position="last"
    )

    merged.to_csv(args.output, index=False)
    scored = int(merged["affinity_energy_density"].notna().sum())
    gated = int(merged["passes_affinity_gate"].sum())
    print(
        f"[affinity] {args.output}: {scored}/{len(merged)} designs scored on |dG/dSASA|; "
        f"{gated} pass the ipsae_min≥{args.gate_threshold} binder gate (ranked first)"
    )


def _resolve_energy(args: argparse.Namespace) -> Path:
    """Return a path to the interface-energy CSV, running Rosetta first if requested."""
    if args.energy:
        p = Path(args.energy)
        if not p.exists():
            print(f"Error: energy CSV not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p
    if not (args.structures_dir and args.run_rosetta):
        print("Error: supply --energy, or --structures-dir with --run-rosetta.", file=sys.stderr)
        sys.exit(1)

    out = Path(args.energy_out) if args.energy_out else Path(tempfile.mkdtemp()) / "interface_energy.csv"
    cmd = [
        "conda", "run", "-n", args.bindcraft_env, "--no-capture-output",
        "python", str(_SCRIPT),
        "--structures-dir", str(args.structures_dir),
        "--interface", args.interface,
        "-o", str(out),
    ]  # fmt: skip
    print(f"[affinity] running Rosetta InterfaceAnalyzer in '{args.bindcraft_env}'…", file=sys.stderr)
    subprocess.run(cmd, check=True)
    return out


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "affinity",
        help="Rank affinity among binders via |dG/dSASA| gated by ipsae_min (Rosetta interface energy, Part N).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--metrics", required=True, metavar="CSV", help="Metrics CSV with an ipsae_min column + an id")
    p.add_argument(
        "--ipsae-col",
        default="ipsae_min",
        metavar="COL",
        help="ipSAE column used as the binder GATE (default ipsae_min)",
    )
    p.add_argument(
        "--gate-threshold",
        type=float,
        default=DEFAULT_AFFINITY_GATE,
        metavar="X",
        help=f"ipsae_min binder gate: designs below X are ranked after gated-in binders (default {DEFAULT_AFFINITY_GATE}).",
    )
    p.add_argument("--energy", metavar="CSV", help="Precomputed interface-energy CSV (design_id,interface_dG,dSASA)")
    p.add_argument("--structures-dir", metavar="DIR", help="Complex PDBs (with --run-rosetta) to compute energy from")
    p.add_argument("--run-rosetta", action="store_true", help="Run InterfaceAnalyzer in the BindCraft env")
    p.add_argument("--interface", default="B_A", metavar="SPEC", help="Rosetta interface chains binder_target (B_A)")
    p.add_argument("--bindcraft-env", default="BindCraft", metavar="ENV", help="Conda env with PyRosetta (BindCraft)")
    p.add_argument("--energy-out", metavar="CSV", help="Where to save computed energies (default: temp)")
    p.add_argument("--output", "-o", required=True, metavar="CSV", help="Ranked output CSV")
    p.set_defaults(func=run)
