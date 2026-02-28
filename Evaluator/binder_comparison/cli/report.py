"""CLI subcommand: binder-compare report

Merge Boltz2 and AF2 refolding results, compute ensemble metrics,
z-score normalise, and generate the comparison report.

Usage:
    binder-compare report \\
        --boltz2-results boltz2_results.csv \\
        --af2-results    af2_results.csv \\
        --sequences      sequences.fasta \\
        --weights        af2=0.6,boltz2=0.4 \\
        --output         ./comparison_report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from ..comparison.merger import merge_refold_results
from ..comparison.ensemble import compute_ensemble_metrics
from ..comparison.statistics import compute_statistics, overall_rank
from ..comparison.scoring import (
    add_af2_ipsae_from_files,
    add_boltz_ipsae_from_files,
    apply_screening_thresholds,
    compute_composite_scores,
    rank_by_adaptyv_method,
)
from ..visualization.report import generate_report
from ..io.write import write_csv, write_json


def run(args: argparse.Namespace) -> None:
    af2_weight, boltz2_weight = _parse_weights(args.weights)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Merge
    print("[report] Merging refolding results…")
    df = merge_refold_results(
        boltz2_csv=args.boltz2_results,
        af2_csv=args.af2_results,
        sequences_fasta=args.sequences,
    )

    # Attach native metrics from BindCraft CSV if provided
    if args.native_metrics:
        df = _attach_native_metrics(df, args.native_metrics)

    # Step 2: Ensemble
    print("[report] Computing ensemble metrics…")
    df = compute_ensemble_metrics(df, af2_weight=af2_weight, boltz2_weight=boltz2_weight)

    # Step 2b: Compute ipSAE from PAE files using DunbrackLab formula.
    # This gives the correct evaluation metric (mean over qualifying residues)
    # with model-specific PAE cutoffs (10 Å Boltz-2, 15 Å AF2).
    # base_dir helps resolve relative PAE paths in older CSVs where the runner
    # didn't write absolute paths.  The CSV's parent dir is the best guess.
    boltz_base = Path(args.boltz2_results).resolve().parent if args.boltz2_results else None
    af2_base = Path(args.af2_results).resolve().parent if args.af2_results else None

    if "boltz_pae_file" in df.columns:
        print("[report] Computing Boltz-2 ipSAE from PAE files (DunbrackLab, cutoff=10 Å)…")
        df = add_boltz_ipsae_from_files(df, pae_file_col="boltz_pae_file", base_dir=boltz_base)

    if "af2_pae_file" in df.columns:
        print("[report] Computing AF2 ipSAE from PAE files (DunbrackLab, cutoff=15 Å)…")
        df = add_af2_ipsae_from_files(df, pae_file_col="af2_pae_file", base_dir=af2_base)

    # Promote DunbrackLab PAE-based ipsae_min as the primary ranking column.
    # Prefer Boltz-2 PAE-based; fall back to AF2 PAE-based.
    if "boltz_pae_ipsae_min" in df.columns:
        df["ipsae_min"] = df["boltz_pae_ipsae_min"]
        print("[report] Using boltz_pae_ipsae_min as primary ipsae_min for ranking")
    elif "af2_ipsae_min" in df.columns:
        df["ipsae_min"] = df["af2_ipsae_min"]
        print("[report] Using af2_ipsae_min as primary ipsae_min for ranking")

    # Step 3: Statistics + z-scores
    print("[report] Computing statistics…")
    stats = compute_statistics(df)
    df = stats["df_with_zscores"]
    summary = stats["summary"]

    # Step 3b: Adaptyv scoring pipeline (Overath et al. 2025 methodology)
    print("[report] Applying Adaptyv screening thresholds (ipSAE_min > 0.61)…")
    df = apply_screening_thresholds(df)
    df = compute_composite_scores(df)
    df = rank_by_adaptyv_method(df)

    # Composite z-score rank (secondary ordering within tiers)
    df["composite_score"] = overall_rank(df)
    df = df.sort_values(
        ["adaptyv_rank"], ascending=[True]
    ).reset_index(drop=True)

    # Step 4: Write outputs
    write_csv(df, output_dir / "metrics.csv")

    z_cols = [c for c in df.columns if c.endswith("_z")]
    id_cols = [c for c in ["binder_id", "sequence", "source_tool"] if c in df.columns]
    write_csv(df[id_cols + z_cols], output_dir / "metrics_zscore.csv")

    write_json(summary, output_dir / "summary.json")

    # Step 5: HTML report
    generate_report(
        df=df,
        summary=summary,
        output_path=output_dir / "report.html",
        af2_weight=af2_weight,
        boltz2_weight=boltz2_weight,
    )

    print(f"\n[report] Done. Output → {output_dir}/")
    print(f"  metrics.csv        — all metrics")
    print(f"  metrics_zscore.csv — z-scored metrics")
    print(f"  summary.json       — per-tool statistics")
    print(f"  report.html        — interactive report")


def _parse_weights(weights_str: str) -> tuple[float, float]:
    """Parse 'af2=0.6,boltz2=0.4' → (0.6, 0.4)."""
    af2_w, boltz2_w = 0.6, 0.4
    if not weights_str:
        return af2_w, boltz2_w
    for part in weights_str.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), float(v.strip())
        if k == "af2":
            af2_w = v
        elif k in ("boltz2", "boltz"):
            boltz2_w = v
    return af2_w, boltz2_w


def _attach_native_metrics(df: pd.DataFrame, native_csv: str) -> pd.DataFrame:
    """Left-join BindCraft native metrics (dG, dSASA, etc.) onto df by sequence."""
    from ..io.read import read_csv_safe
    from ..extractors.bindcraft import _NATIVE_COL_MAP, _SEQUENCE_COL

    native_df = read_csv_safe(native_csv)
    if native_df.empty or _SEQUENCE_COL not in native_df.columns:
        return df

    cols_to_join = {_SEQUENCE_COL: "sequence"}
    for out_name, src_col in _NATIVE_COL_MAP.items():
        if src_col in native_df.columns:
            cols_to_join[src_col] = f"native_{out_name}"

    native_sub = native_df[list(cols_to_join.keys())].rename(columns=cols_to_join)
    native_sub["sequence"] = native_sub["sequence"].str.strip().str.upper()
    return pd.merge(df, native_sub, on="sequence", how="left")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "report",
        help="Merge refolding results and generate the comparison report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--boltz2-results", metavar="CSV",
                   help="Output from 'refold-boltz2' (boltz2_results.csv)")
    p.add_argument("--af2-results", metavar="CSV",
                   help="Output from 'refold-af2' (af2_results.csv)")
    p.add_argument("--sequences", metavar="FASTA",
                   help="FASTA from 'extract' step (for binder_id and source_tool tags)")
    p.add_argument("--native-metrics", metavar="CSV",
                   help="BindCraft final_design_stats.csv to attach dG/dSASA/ShapeComp")
    p.add_argument("--af2-pae-dir", metavar="DIR",
                   help="Deprecated — PAE file paths are now recorded in af2_results.csv "
                        "automatically by refold_Version6. This flag is ignored.")
    p.add_argument("--weights", default="af2=0.6,boltz2=0.4",
                   help="Ensemble weights, e.g. 'af2=0.7,boltz2=0.3' (default: af2=0.6,boltz2=0.4)")
    p.add_argument("--output", "-o", required=True, metavar="DIR",
                   help="Output directory for all report files")
    p.set_defaults(func=run)
