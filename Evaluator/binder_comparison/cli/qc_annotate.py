"""CLI subcommand: binder-compare qc-annotate

ADVISORY interface-quality annotation for a binder shortlist. Relaxes + scores the
BindCraft interface panel (shape complementarity, packstat, ΔG, # interface H-bonds,
# buried unsatisfied H-bonds, # interface residues, hydrophobicity) and annotates
each design with ``qc_pass`` + ``qc_fail_reasons`` + the panel values — WITHOUT
dropping or reordering rows. A human reviews the flagged designs (especially extreme
pathologies: positive ΔG, grossly high unsatisfied H-bonds) before ordering.

WHY advisory, not a hard filter: on the 4-target Adaptyv benchmark, hard-gating with
BindCraft's default thresholds removed ~2/3 of true binders from the shortlist (the
panel is a ~0.52-AUC binder classifier on PREDICTED structures — BindCraft's cuts are
tuned for its own AF2-optimised designs). So the panel flags QUALITY, but must not
auto-drop. Pass ``--drop-failures`` to hard-filter anyway (off by default).

Either pass a precomputed panel CSV (``--panel``) or relax+score a structures dir in
the BindCraft conda env (``--structures-dir --run-rosetta``).

Usage:
    binder-compare qc-annotate --metrics report/top20_candidates.csv \\
        --structures-dir runs/X/refold_esmfold2 --run-rosetta --binder-chain B -o annotated.csv
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from ..io.read import read_csv_safe

_ID_COLS = ("binder_id", "design_id", "id")
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "interface_qc.py"

# BindCraft default interface filters (settings_filters/default_filters.json)
DEFAULT_QC = {"dg_max": 0.0, "sc_min": 0.55, "hbonds_min": 3, "unsat_max": 4, "nres_min": 7}


def _evaluate(row, th) -> tuple[bool, str]:
    """Return (pass, reasons) for one design against the QC thresholds."""
    reasons = []
    checks = [
        ("interface_dG", lambda v: v <= th["dg_max"], f"dG>{th['dg_max']}"),
        ("interface_sc", lambda v: v >= th["sc_min"], f"sc<{th['sc_min']}"),
        ("interface_interface_hbonds", lambda v: v >= th["hbonds_min"], f"hbonds<{th['hbonds_min']}"),
        ("interface_delta_unsat_hbonds", lambda v: v <= th["unsat_max"], f"unsat_hbonds>{th['unsat_max']}"),
        ("interface_nres", lambda v: v >= th["nres_min"], f"nres<{th['nres_min']}"),
    ]
    for col, ok, why in checks:
        v = row.get(col)
        if v is None or (isinstance(v, float) and v != v) or v == "":
            reasons.append(f"{col}=NA")
        elif not ok(float(v)):
            reasons.append(why)
    return (len(reasons) == 0, ";".join(reasons))


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

    panel = read_csv_safe(_resolve_panel(args))
    if "design_id" not in panel.columns:
        print("Error: panel CSV needs a 'design_id' column to join.", file=sys.stderr)
        sys.exit(1)

    merged = metrics.merge(panel, left_on=metrics_id, right_on="design_id", how="left", suffixes=("", "_panel"))
    th = {
        "dg_max": args.dg_max, "sc_min": args.sc_min, "hbonds_min": args.hbonds_min,
        "unsat_max": args.unsat_max, "nres_min": args.nres_min,
    }
    verdicts = merged.apply(lambda r: _evaluate(r, th), axis=1)
    merged["qc_pass"] = [v[0] for v in verdicts]
    merged["qc_fail_reasons"] = [v[1] for v in verdicts]

    # ADVISORY by default: preserve the input ranking, annotate only. Opt-in hard filter.
    if args.drop_failures:
        merged = merged[merged["qc_pass"]]

    merged.to_csv(args.output, index=False)
    scored = int(merged["interface_dG"].notna().sum()) if "interface_dG" in merged else 0
    flagged = int((~merged["qc_pass"]).sum())
    mode = "DROPPED (hard filter)" if args.drop_failures else "kept (advisory — not dropped)"
    print(f"[qc-annotate] {args.output}: {scored} scored on the interface panel; "
          f"{flagged} flagged qc_pass=False, {mode}. "
          f"Thresholds: dG≤{th['dg_max']}, sc≥{th['sc_min']}, hbonds≥{th['hbonds_min']}, "
          f"unsat≤{th['unsat_max']}, nres≥{th['nres_min']}.")


def _resolve_panel(args: argparse.Namespace) -> Path:
    if args.panel:
        p = Path(args.panel)
        if not p.exists():
            print(f"Error: panel CSV not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p
    if not (args.structures_dir and args.run_rosetta):
        print("Error: supply --panel, or --structures-dir with --run-rosetta.", file=sys.stderr)
        sys.exit(1)
    out = Path(args.panel_out) if args.panel_out else Path(tempfile.mkdtemp()) / "interface_panel.csv"
    cmd = [
        "conda", "run", "-n", args.bindcraft_env, "--no-capture-output",
        "python", str(_SCRIPT),
        "--structures-dir", str(args.structures_dir),
        "--binder-chain", args.binder_chain,
        "-o", str(out),
    ]  # fmt: skip
    print(f"[qc-annotate] relax + interface panel in '{args.bindcraft_env}' (shortlist only — FastRelax is slow)…",
          file=sys.stderr)
    subprocess.run(cmd, check=True)
    return out


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "qc-annotate",
        help="Advisory interface-quality annotation of a shortlist (BindCraft panel; relax + Rosetta). Does not drop.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--metrics", required=True, metavar="CSV", help="Shortlist CSV with an id column")
    p.add_argument("--panel", metavar="CSV", help="Precomputed interface-panel CSV (from interface_qc.py)")
    p.add_argument("--structures-dir", metavar="DIR", help="Complex PDBs (with --run-rosetta)")
    p.add_argument("--run-rosetta", action="store_true", help="Relax + score the panel in the BindCraft env")
    p.add_argument("--binder-chain", default="B", metavar="CH", help="Binder chain (B AF3/ESMFold2/RFD3, A Boltz-2)")
    p.add_argument("--bindcraft-env", default="BindCraft", metavar="ENV", help="Conda env with PyRosetta")
    p.add_argument("--panel-out", metavar="CSV", help="Where to save the computed panel (default: temp)")
    p.add_argument("--dg-max", type=float, default=DEFAULT_QC["dg_max"], help="Max interface ΔG (REU)")
    p.add_argument("--sc-min", type=float, default=DEFAULT_QC["sc_min"], help="Min shape complementarity")
    p.add_argument("--hbonds-min", type=int, default=DEFAULT_QC["hbonds_min"], help="Min interface H-bonds")
    p.add_argument("--unsat-max", type=int, default=DEFAULT_QC["unsat_max"], help="Max buried unsatisfied H-bonds")
    p.add_argument("--nres-min", type=int, default=DEFAULT_QC["nres_min"], help="Min interface residues")
    p.add_argument("--drop-failures", action="store_true",
                   help="Hard-filter: drop qc_pass=False rows (OFF by default; culls binders on predicted structures)")
    p.add_argument("--output", "-o", required=True, metavar="CSV", help="Annotated output CSV")
    p.set_defaults(func=run)
