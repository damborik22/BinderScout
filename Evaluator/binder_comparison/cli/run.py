"""CLI subcommand: binder-compare run

Full orchestrator: extract → refold-boltz2 → report.
Additional refolding engines (Protenix on x86, AF3 on aarch64) will be wired
in in later refactor parts.

Usage:
    binder-compare run \\
        --bindcraft  ./bindcraft_results \\
        --boltzgen   ./boltzgen_results \\
        --mosaic     ./mosaic_results \\
        --target-seq "MKTAYIAKQRQ..." \\
        --output     ./comparison_report

Environment requirements:
    Boltz-2 refolding: uv venv at ~/BindMaster/Mosaic/.venv (preferred)
                       OR conda env 'mosaic' if populated
    Other steps:       any env with binder_comparison installed

Boltz-2 environment selection (in order of precedence):
    --boltz2-python /path/to/.venv/bin/python   (direct Python; skips conda)
    --boltz2-env    mosaic                       (conda run -n <env>)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(args: argparse.Namespace) -> None:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    sequences_fasta = output_dir / "sequences.fasta"
    boltz2_csv = output_dir / "boltz2_results.csv"

    # ------------------------------------------------------------------
    # Step 1: Extract sequences
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 1/3 — Extracting sequences")
    print("=" * 60)

    extract_cmd = [sys.executable, "-m", "binder_comparison", "extract"]
    if args.bindcraft:
        extract_cmd += ["--bindcraft", args.bindcraft]
    if args.boltzgen:
        extract_cmd += ["--boltzgen", args.boltzgen]
    if args.mosaic:
        extract_cmd += ["--mosaic", args.mosaic]
    if args.pxdesign:
        extract_cmd += ["--pxdesign", args.pxdesign]
    if args.proteina_complexa:
        extract_cmd += ["--proteina-complexa", args.proteina_complexa]
    extract_cmd += ["--output", str(sequences_fasta)]
    if getattr(args, "all_mosaic_designs", False):
        extract_cmd += ["--all-mosaic-designs"]

    _run_step(extract_cmd, "extract")

    # ------------------------------------------------------------------
    # Step 2: Refold with Boltz-2  (Mosaic uv venv or conda env)
    # ------------------------------------------------------------------
    boltz2_label = f"[python: {args.boltz2_python}]" if args.boltz2_python else f"[conda: {args.boltz2_env}]"
    print("\n" + "=" * 60)
    print(f"STEP 2/3 — Boltz-2 refolding  {boltz2_label}")
    print("=" * 60)

    _boltz2_inner = [
        "binder-compare",
        "refold-boltz2",
        "--sequences",
        str(sequences_fasta),
        "--target-seq",
        args.target_seq,
        "--output",
        str(boltz2_csv),
        "--output-dir",
        str(output_dir / "refold_boltz2"),
    ] + (["--mosaic-path", args.mosaic_path] if args.mosaic_path else [])

    if args.boltz2_python:
        boltz2_cmd = [args.boltz2_python, "-m", "binder_comparison"] + _boltz2_inner[1:]
    else:
        boltz2_cmd = _conda_cmd(args.boltz2_env, ["python", "-m", "binder_comparison"] + _boltz2_inner[1:])

    _run_step(boltz2_cmd, "refold-boltz2")

    # ------------------------------------------------------------------
    # Step 3: Report
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 3/3 — Generating comparison report")
    print("=" * 60)

    report_cmd = [
        sys.executable,
        "-m",
        "binder_comparison",
        "report",
        "--boltz2-results",
        str(boltz2_csv),
        "--sequences",
        str(sequences_fasta),
        "--output",
        str(output_dir / "report"),
    ]
    if args.bindcraft:
        bindcraft_dir = Path(args.bindcraft)
        final_csv = next(bindcraft_dir.glob("final_design_stats.csv"), None)
        if final_csv:
            report_cmd += ["--native-metrics", str(final_csv)]

    _run_step(report_cmd, "report")

    print(f"\n{'=' * 60}")
    print("All steps complete.")
    print(f"Report → {output_dir / 'report' / 'report.html'}")


def _conda_cmd(env_name: str, inner_cmd: list[str]) -> list[str]:
    """Wrap a command with 'conda run -n {env}'."""
    return ["conda", "run", "-n", env_name, "--no-capture-output"] + inner_cmd


def _run_step(cmd: list[str], name: str) -> None:
    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"\n[run] ERROR: step '{name}' exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "run",
        help="Full pipeline: extract → refold-boltz2 → report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    # Inputs
    p.add_argument("--bindcraft", metavar="DIR", help="BindCraft output directory")
    p.add_argument("--boltzgen", metavar="DIR", help="BoltzGen output directory")
    p.add_argument("--mosaic", metavar="DIR", help="Mosaic output directory")
    p.add_argument("--pxdesign", metavar="DIR", help="PXDesign output directory (containing summary.csv)")
    p.add_argument(
        "--proteina-complexa",
        metavar="DIR",
        dest="proteina_complexa",
        help="Proteina-Complexa output directory (containing sequences.csv)",
    )
    # Refolding targets
    p.add_argument("--target-seq", required=True, metavar="SEQ", help="Target protein sequence (for Boltz-2 refolding)")
    # Output
    p.add_argument("--output", "-o", required=True, metavar="DIR", help="Output directory for all results")
    # Environment selection for Boltz-2 refolding
    boltz2_grp = p.add_mutually_exclusive_group()
    boltz2_grp.add_argument(
        "--boltz2-python",
        default=None,
        metavar="PYTHON",
        help=(
            "Direct Python executable for Boltz-2 refolding — use this for the "
            "uv venv (e.g. ~/BindMaster/Mosaic/.venv/bin/python). "
            "Takes precedence over --boltz2-env."
        ),
    )
    boltz2_grp.add_argument(
        "--boltz2-env",
        default="mosaic",
        metavar="ENV",
        help="Conda env for Boltz-2 refolding (default: mosaic)",
    )
    p.add_argument("--mosaic-path", default=None, metavar="DIR", help="Mosaic repo path (auto-detected if not set)")
    p.add_argument(
        "--all-mosaic-designs",
        action="store_true",
        help="Include all Mosaic designs (default: only is_top=1 refolded designs)",
    )
    p.set_defaults(func=run)
