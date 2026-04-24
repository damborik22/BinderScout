"""CLI subcommand: binder-compare report

Load Boltz-2 refolding results (plus Protenix/AF3 when available in future
parts), promote Boltz-2 as the primary predictor, z-score normalise, and
generate the comparison report.

Usage:
    binder-compare report \\
        --boltz2-results boltz2_results.csv \\
        --sequences      sequences.fasta \\
        --output         ./comparison_report
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ..comparison.ensemble import compute_ensemble_metrics
from ..comparison.merger import merge_refold_results
from ..comparison.scoring import (
    add_boltz_ipsae_from_files,
    add_ipsae_from_pae_files,
    add_iptm_from_pae_files,
    apply_screening_thresholds,
    compute_agreement,
    compute_composite_scores,
    rank_by_adaptyv_method,
)
from ..comparison.statistics import compute_statistics
from ..io.write import write_csv, write_json
from ..visualization.report import generate_report


def run(args: argparse.Namespace) -> None:
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Load refolding results
    print("[report] Loading refolding results…")
    df = merge_refold_results(
        boltz2_csv=args.boltz2_results,
        sequences_fasta=args.sequences,
        protenix_csv=args.protenix_results,
        af3_csv=args.af3_results,
    )

    # Attach native metrics from BindCraft CSV if provided
    if args.native_metrics:
        df = _attach_native_metrics(df, args.native_metrics)

    # Step 2: Promote Boltz-2 as primary predictor
    print("[report] Promoting Boltz-2 metrics as primary…")
    df = compute_ensemble_metrics(df)

    # Step 2b: Compute ipSAE from PAE files using DunbrackLab formula.
    # Uniform 10 Å cutoff across engines so scores are directly comparable.
    # base_dir helps resolve relative PAE paths in older CSVs where the runner
    # didn't write absolute paths.  The CSV's parent dir is the best guess.
    boltz_base = Path(args.boltz2_results).resolve().parent if args.boltz2_results else None

    if "boltz_pae_file" in df.columns:
        print("[report] Computing Boltz-2 ipSAE from PAE files (DunbrackLab, cutoff=10 Å)…")
        df = add_boltz_ipsae_from_files(df, pae_file_col="boltz_pae_file", base_dir=boltz_base)
        print("[report] Computing Boltz-2 ipTM from PAE files…")
        df = add_iptm_from_pae_files(
            df, pae_file_col="boltz_pae_file", ordering="binder_target", prefix="boltz", base_dir=boltz_base
        )

    # Protenix: DunbrackLab ipSAE + independent ipTM from the saved PAE matrix
    protenix_base = Path(args.protenix_results).resolve().parent if args.protenix_results else None
    if "protenix_pae_file" in df.columns:
        print("[report] Computing Protenix ipSAE from PAE files (DunbrackLab, cutoff=10 Å)…")
        df = add_ipsae_from_pae_files(
            df,
            pae_file_col="protenix_pae_file",
            prefix="protenix",
            ordering="target_binder",
            base_dir=protenix_base,
        )
        df = add_iptm_from_pae_files(
            df, pae_file_col="protenix_pae_file", ordering="target_binder", prefix="protenix", base_dir=protenix_base
        )

    # AF3 (aarch64 / DGX Spark): identical treatment — Part K wires this up end-to-end.
    af3_base = Path(args.af3_results).resolve().parent if args.af3_results else None
    if "af3_pae_file" in df.columns:
        print("[report] Computing AF3 ipSAE from PAE files (DunbrackLab, cutoff=10 Å)…")
        df = add_ipsae_from_pae_files(
            df, pae_file_col="af3_pae_file", prefix="af3", ordering="target_binder", base_dir=af3_base
        )
        df = add_iptm_from_pae_files(
            df, pae_file_col="af3_pae_file", ordering="target_binder", prefix="af3", base_dir=af3_base
        )

    # Promote Boltz-2 DunbrackLab PAE-based ipsae_min as the primary ranking column.
    if "boltz_pae_ipsae_min" in df.columns:
        df["ipsae_min"] = df["boltz_pae_ipsae_min"]
        print("[report] Using boltz_pae_ipsae_min as primary ipsae_min for ranking")

    # Step 3: Statistics + z-scores
    print("[report] Computing statistics…")
    stats = compute_statistics(df)
    df = stats["df_with_zscores"]
    summary = stats["summary"]

    # Step 3b: Adaptyv scoring pipeline (Overath et al. 2025 methodology)
    print("[report] Applying Adaptyv screening thresholds (ipSAE_min > 0.61)…")
    df = apply_screening_thresholds(df)
    df = compute_composite_scores(df)
    df = compute_agreement(df)
    df = rank_by_adaptyv_method(df)

    df = df.sort_values(["adaptyv_rank"], ascending=[True]).reset_index(drop=True)

    # Step 4: Write outputs
    write_csv(df, output_dir / "metrics.csv")

    z_cols = [c for c in df.columns if c.endswith("_z")]
    id_cols = [c for c in ["binder_id", "sequence", "source_tool"] if c in df.columns]
    write_csv(df[id_cols + z_cols], output_dir / "metrics_zscore.csv")

    write_json(summary, output_dir / "summary.json")

    # Step 4b: Top-20 candidates CSV with key metrics + sequence
    _top_cols = [
        "binder_id",
        "source_tool",
        "sequence",
        "binder_length",
        "boltz_pae_ipsae_min",
        "boltz_pae_iptm",
        "boltz_pae_bt_ipsae",
        "boltz_pae_tb_ipsae",
        "plddt_binder_mean",
        "plddt_binder_min",
        "binder_ptm",
        "pae_bt_mean",
        "pae_tb_mean",
        "agreement_count",
        "adaptyv_rank",
    ]
    _available = [c for c in _top_cols if c in df.columns]
    top20 = df.head(20)[_available]
    write_csv(top20, output_dir / "top20_candidates.csv")
    print("  top20_candidates.csv — top 20 designs with sequences")

    # Step 4c: Copy top-20 refolded PDB structures for visual inspection
    structures_dir = output_dir / "top20_structures"
    structures_dir.mkdir(parents=True, exist_ok=True)
    pdb_cols = [c for c in ("boltz_pdb", "pdb") if c in df.columns]
    n_copied = 0
    for _, row in df.head(20).iterrows():
        rank = int(row.get("adaptyv_rank", 0))
        binder_id = row.get("binder_id", f"rank{rank}")
        for col in pdb_cols:
            src = row.get(col)
            if src and isinstance(src, str):
                src_path = Path(src)
                if not src_path.is_absolute() and args.boltz2_results:
                    src_path = Path(args.boltz2_results).resolve().parent / src
                if src_path.exists():
                    import shutil

                    dest = structures_dir / f"rank{rank:02d}_{binder_id}.pdb"
                    shutil.copy2(src_path, dest)
                    n_copied += 1
                    break
    if n_copied:
        print(f"  top20_structures/    — {n_copied} refolded PDB structures for visual inspection")
        _write_pymol_script(df.head(20), structures_dir)
        print("  top20_structures/    — view_top20.pml (open in PyMOL)")

    # Step 5: HTML report
    # Parse --tool-csv flags into dict
    tool_csvs = {}
    if args.tool_csv:
        for spec in args.tool_csv:
            if "=" in spec:
                tool_name, csv_path = spec.split("=", 1)
                tool_csvs[tool_name.strip()] = csv_path.strip()

    # Parse --tool-pdb-dir flags into dict
    tool_pdb_dirs = {}
    if args.tool_pdb_dir:
        for spec in args.tool_pdb_dir:
            if "=" in spec:
                tool_name, pdb_dir = spec.split("=", 1)
                tool_pdb_dirs[tool_name.strip()] = pdb_dir.strip()

    generate_report(
        df=df,
        summary=summary,
        output_path=output_dir / "report.html",
        tool_csvs=tool_csvs or None,
        tool_pdb_dirs=tool_pdb_dirs or None,
    )

    print(f"\n[report] Done. Output → {output_dir}/")
    print("  metrics.csv        — all metrics")
    print("  metrics_zscore.csv — z-scored metrics")
    print("  summary.json       — per-tool statistics")
    print("  report.html        — interactive report")


_TOOL_COLOURS_PYMOL = {
    "mosaic": "green",
    "pxdesign": "purple",
    "boltzgen": "orange",
    "bindcraft": "blue",
    "proteina_complexa": "teal",
    "rfaa": "firebrick",
    "protein_hunter": "cyan",
}

_TOOL_DISPLAY_PYMOL = {
    "mosaic": "Mosaic",
    "pxdesign": "PXDesign",
    "boltzgen": "BoltzGen",
    "bindcraft": "BindCraft",
    "proteina_complexa": "Proteina-Complexa",
    "rfaa": "RFAA",
    "protein_hunter": "Protein-Hunter",
}


def _write_pymol_script(top_df: pd.DataFrame, structures_dir: Path) -> None:
    """Generate a PyMOL .pml script to load and visualise top-20 refolded structures.

    Boltz-2 PDBs have binder as chain A, target as chain B.
    Each binder is coloured by source tool; target is grey.
    Structures are aligned on the target chain for easy comparison.
    """
    pml_lines = [
        "# BindMaster Evaluator — Top 20 refolded binder structures",
        "# Open this file in PyMOL: pymol view_top20.pml",
        "#",
        "# Binder = chain A (coloured by tool), Target = chain B (grey)",
        "# All structures aligned on target chain for comparison.",
        "",
        "bg_color white",
        "set cartoon_fancy_helices, 1",
        "set cartoon_smooth_loops, 1",
        "set ray_shadow, 0",
        "",
    ]

    pdb_files = sorted(structures_dir.glob("rank*.pdb"))
    if not pdb_files:
        return

    loaded = []
    for pdb in pdb_files:
        name = pdb.stem  # e.g. rank01_mosaic_e6b3d835_7
        pml_lines.append(f"load {pdb.name}, {name}")
        loaded.append(name)

    pml_lines.append("")
    pml_lines.append("# Show as cartoon")
    pml_lines.append("hide everything, all")
    pml_lines.append("show cartoon, all")
    pml_lines.append("")

    # Colour target chain grey for all
    pml_lines.append("# Target chain (B) in grey")
    pml_lines.append("color grey80, chain B")
    pml_lines.append("")

    # Colour each binder by source tool
    pml_lines.append("# Binder chain (A) coloured by source tool")
    for _, row in top_df.iterrows():
        rank = int(row.get("adaptyv_rank", 0))
        binder_id = row.get("binder_id", f"rank{rank}")
        tool = row.get("source_tool", "unknown")
        colour = _TOOL_COLOURS_PYMOL.get(tool, "white")
        name = f"rank{rank:02d}_{binder_id}"
        pml_lines.append(f"color {colour}, {name} and chain A")

    pml_lines.append("")

    # Align all on target chain of rank01
    if len(loaded) > 1:
        ref = loaded[0]
        pml_lines.append(f"# Align all structures on target chain of {ref}")
        for name in loaded[1:]:
            pml_lines.append(f"align {name} and chain B, {ref} and chain B")
        pml_lines.append("")

    # Initially show only rank01, disable rest
    pml_lines.append("# Initially show only rank 1; toggle others as needed")
    for name in loaded[1:]:
        pml_lines.append(f"disable {name}")
    pml_lines.append("")

    # Legend as pseudoatom labels
    pml_lines.append("# Legend")
    tools_seen = set()
    for _, row in top_df.iterrows():
        tool = row.get("source_tool", "unknown")
        if tool not in tools_seen:
            tools_seen.add(tool)
            display = _TOOL_DISPLAY_PYMOL.get(tool, tool)
            colour = _TOOL_COLOURS_PYMOL.get(tool, "white")
            pml_lines.append(f"# {display} = {colour}")

    pml_lines.append("")
    pml_lines.append("zoom all")
    pml_lines.append("orient")
    pml_lines.append("")

    script_path = structures_dir / "view_top20.pml"
    script_path.write_text("\n".join(pml_lines))


def _attach_native_metrics(df: pd.DataFrame, native_csv: str) -> pd.DataFrame:
    """Left-join BindCraft native metrics (dG, dSASA, etc.) onto df by sequence."""
    from ..extractors.bindcraft import _NATIVE_COL_MAP, _SEQUENCE_COL
    from ..io.read import read_csv_safe

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
    p.add_argument("--boltz2-results", metavar="CSV", help="Output from 'refold-boltz2' (boltz2_results.csv)")
    p.add_argument(
        "--protenix-results",
        metavar="CSV",
        help="Optional: output from 'refold-protenix' (protenix_results.csv). Adds a "
        "second engine to the agreement_count.",
    )
    p.add_argument(
        "--af3-results",
        metavar="CSV",
        help="Optional: output from 'refold-af3' (af3_results.csv; aarch64 / DGX "
        "Spark only). Adds a third engine to the agreement_count.",
    )
    p.add_argument(
        "--sequences", metavar="FASTA", help="FASTA from 'extract' step (for binder_id and source_tool tags)"
    )
    p.add_argument(
        "--native-metrics", metavar="CSV", help="BindCraft final_design_stats.csv to attach dG/dSASA/ShapeComp"
    )
    p.add_argument("--output", "-o", required=True, metavar="DIR", help="Output directory for all report files")
    p.add_argument(
        "--tool-csv",
        metavar="TOOL=CSV",
        action="append",
        help="Tool's original output CSV for native-ranked top-10 section. "
        "Can be specified multiple times. Example: --tool-csv mosaic=runs/mosaic/designs.csv "
        "--tool-csv boltzgen=runs/boltzgen/outputs/final_ranked_designs/final_designs_metrics_700.csv",
    )
    p.add_argument(
        "--tool-pdb-dir",
        metavar="TOOL=DIR",
        action="append",
        help="Directory containing a tool's original design PDBs/CIFs for 3D viewer in the "
        "native top-10 section. Must be used with matching --tool-csv. Can be repeated.",
    )
    p.set_defaults(func=run)
