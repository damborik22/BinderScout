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
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from ..comparison.candidates import build_candidates_table
from ..comparison.ensemble import compute_ensemble_metrics
from ..comparison.merger import merge_refold_results
from ..comparison.scoring import (
    add_boltz_ipsae_from_files,
    add_chain_iptm_interface,
    add_design_groups,
    add_ipsae_from_pae_files,
    add_iptm_from_pae_files,
    annotate_wetlab_recommended,
    apply_screening_thresholds,
    compute_agreement,
    compute_composite_scores,
    compute_consensus_ipsae,
    compute_consensus_iptm,
    rank_by_adaptyv_method,
    rank_by_consensus_iptm,
    rank_by_two_stage,
)
from ..comparison.statistics import compute_statistics
from ..io.write import write_csv, write_json
from ..visualization.report import generate_report
from ..visualization.top30_slim import write_top30_slim


def _parse_tool_meta(specs: list[str] | None) -> dict[str, dict]:
    """Parse repeated --tool-meta TOOL='k:v;k:v' flags into a dict.

    Empty list / None / malformed pieces are skipped silently (we'd rather
    render an under-annotated banner than refuse to render a report).
    """
    overrides: dict[str, dict] = {}
    if not specs:
        return overrides
    for spec in specs:
        if "=" not in spec:
            continue
        tool, payload = spec.split("=", 1)
        tool = tool.strip().lower()
        if not tool:
            continue
        d: dict = {}
        for piece in payload.split(";"):
            if ":" not in piece:
                continue
            k, v = piece.split(":", 1)
            k = k.strip()
            v = v.strip()
            if not k:
                continue
            if k == "pool_pre_filtered":
                d[k] = v.lower() in ("true", "1", "yes", "y")
            else:
                d[k] = v
        if d:
            overrides[tool] = d
    return overrides


def _load_engine_versions(path: str | None) -> dict[str, str]:
    """Load engine version info from a JSON or YAML file. Missing/empty → {}."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        print(f"[report] WARNING: --engine-versions file not found: {p}; skipping.", file=sys.stderr)
        return {}
    try:
        text = p.read_text()
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml

            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text) if text.strip() else {}
        if not isinstance(data, dict):
            print(f"[report] WARNING: --engine-versions file {p} is not a dict; skipping.", file=sys.stderr)
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError, ImportError) as exc:
        print(f"[report] WARNING: could not parse --engine-versions file {p}: {exc}", file=sys.stderr)
        return {}


def _detect_evaluator_version() -> str:
    """Return the binder-comparison version. Falls back to pyproject if uninstalled."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("binder-comparison")
    except (ImportError, PackageNotFoundError):
        pass
    try:
        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        if pyproject.exists():
            for line in pyproject.read_text().splitlines():
                if line.strip().startswith("version") and "=" in line:
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return "unknown"


def _collect_provenance(args: argparse.Namespace) -> dict:
    """Auto-detect git_sha, evaluator_version, timestamp; merge --engine-versions."""
    prov: dict = {
        "run_timestamp_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cli_args": list(sys.argv),
    }
    # git sha (best-effort; works only when run from inside a git checkout).
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if sha.returncode == 0:
            prov["git_sha"] = sha.stdout.strip()
            # also note if the worktree is dirty
            status = subprocess.run(
                ["git", "status", "--porcelain"], capture_output=True, text=True, check=False, timeout=2
            )
            if status.returncode == 0 and status.stdout.strip():
                prov["git_sha"] = f"{prov['git_sha']} (dirty)"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # evaluator version from the installed package metadata (or fall back to pyproject).
    prov["evaluator_version"] = _detect_evaluator_version()
    ev = _load_engine_versions(getattr(args, "engine_versions", None))
    if ev:
        prov["engine_versions"] = ev
    return prov


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
        esmfold2_csv=args.esmfold2_results,
    )

    # Attach native metrics from BindCraft CSV if provided
    if args.native_metrics:
        df = _attach_native_metrics(df, args.native_metrics)

    # Auto-detect the sidecar native_metrics.csv that 'extract' wrote next to
    # the sequences FASTA. Carries per-tool design-time metrics for all tools
    # (BindCraft, BoltzGen, Mosaic, PXDesign, Proteina-Complexa, Protein-Hunter,
    # RFD3) so the final report shows "what the tool said about its own design"
    # next to the cross-validation refold metrics.
    if args.sequences:
        df = _attach_native_metrics_sidecar(df, args.sequences)

    # SoluProt: sequence-only solubility screen output. Left-joined onto df
    # by sequence — adds native_soluprot_score (0–1 probability) and
    # native_soluprot_passes (bool, score >= threshold used at scoring time).
    # Not part of agreement_count; this is a screen, not a re-ranker.
    if args.soluprot_results:
        df = _attach_soluprot_results(df, args.soluprot_results)

    # TmProt: sequence-only melting-temperature (thermostability) screen — sister
    # tool to SoluProt. Left-joined by sequence — adds native_tmprot_tm (°C).
    # A screen, not a re-ranker; not part of agreement_count.
    if args.tmprot_results:
        df = _attach_tmprot_results(df, args.tmprot_results)

    # qc-annotate: BindCraft interface QC panel for a shortlist. Left-joined by
    # binder_id — adds qc_pass + qc_fail_reasons + interface_* columns. ADVISORY
    # (most rows stay NaN; only the annotated shortlist carries values); never
    # used to reorder or drop.
    if getattr(args, "qc_results", None):
        df = _attach_qc_results(df, args.qc_results)

    # epitope: target-side interface residues vs intended hotspot list (Item 2).
    # Joined by binder_id; adds epitope_match_fraction + epitope_status +
    # epitope_off_target_residues. ADVISORY — never reorders or drops.
    if getattr(args, "epitope_results", None):
        df = _attach_epitope_results(df, args.epitope_results)

    # diversity: sequence-similarity clustering into "families" (Item 1).
    # Joined by binder_id; adds family_id / family_size / family_rank. ADVISORY
    # — never reorders or drops; the report surfaces a "Top per family" block.
    if getattr(args, "diversity_results", None):
        df = _attach_diversity_results(df, args.diversity_results)

    # beta-check: binder→target β-sheet intercalation (β-augmentation), from DSSP
    # cross-chain bridges. Joined by binder_id; adds n_xbridge + beta_intercalates.
    # With --exclude-intercalators this DROPS the flagged designs — the one advisory
    # allowed to drop, because a strand threaded into a folded target's sheet is
    # non-physical (a design artifact), not merely weak.
    if getattr(args, "beta_results", None):
        df = _attach_beta_results(df, args.beta_results, exclude=getattr(args, "exclude_intercalators", False))

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

    # ESMFold2 (biohub): same convention as AF3/Protenix — target first in input, so PAE is target_binder.
    esmfold2_base = Path(args.esmfold2_results).resolve().parent if args.esmfold2_results else None
    if "esmfold2_pae_file" in df.columns:
        print("[report] Computing ESMFold2 ipSAE from PAE files (DunbrackLab, cutoff=10 Å)…")
        df = add_ipsae_from_pae_files(
            df,
            pae_file_col="esmfold2_pae_file",
            prefix="esmfold2",
            ordering="target_binder",
            base_dir=esmfold2_base,
        )
        df = add_iptm_from_pae_files(
            df,
            pae_file_col="esmfold2_pae_file",
            ordering="target_binder",
            prefix="esmfold2",
            base_dir=esmfold2_base,
        )

    # Recover the interface chain-pair iPTM (mean of the two directional pair iPTMs).
    # Canonical definition lives in scoring.add_chain_iptm_interface so the report and
    # any downstream gate (e.g. the ESMFold2 autosize loop) share one formula.
    df = add_chain_iptm_interface(df, prefix="esmfold2")

    # Promote the chosen engine's DunbrackLab PAE-based ipsae_min as the primary ranking column.
    # Column naming differs across engines: boltz uses boltz_pae_ipsae_min, others use
    # <engine>_ipsae_min (no _pae_ prefix) — see scoring._ENGINE_IPSAE_COLS for the canonical map.
    from ..comparison.scoring import _ENGINE_IPSAE_COLS as _EICOLS

    primary_engine = getattr(args, "primary_engine", "boltz") or "boltz"
    primary_col = _EICOLS.get(primary_engine, f"{primary_engine}_ipsae_min")
    if primary_col in df.columns and pd.to_numeric(df[primary_col], errors="coerce").notna().any():
        df["ipsae_min"] = df[primary_col]
        print(f"[report] Using {primary_col} as primary ipsae_min for ranking")
    elif "boltz_pae_ipsae_min" in df.columns:
        df["ipsae_min"] = df["boltz_pae_ipsae_min"]
        print(
            f"[report] WARNING: requested primary engine '{primary_engine}' has no PAE-derived ipsae_min "
            f"(missing column {primary_col}); falling back to boltz_pae_ipsae_min"
        )

    # Step 3: Statistics + z-scores
    print("[report] Computing statistics…")
    stats = compute_statistics(df)
    df = stats["df_with_zscores"]
    summary = stats["summary"]

    # Step 3b: Adaptyv scoring pipeline (Overath et al. 2025 methodology)
    # Per-engine thresholds — falls back to defaults (0.61 across active engines, 0.30 AF2 info).
    engine_thresholds: dict[str, float] = {}
    for engine, attr in (
        ("boltz", "threshold_boltz"),
        ("protenix", "threshold_protenix"),
        ("af3", "threshold_af3"),
        ("esmfold2", "threshold_esmfold2"),
        ("af2", "threshold_af2"),
    ):
        val = getattr(args, attr, None)
        if val is not None:
            engine_thresholds[engine] = val
    if engine_thresholds:
        print(f"[report] Per-engine thresholds overridden: {engine_thresholds}")
    print(f"[report] Applying screening thresholds (primary engine: {primary_engine})…")
    df = apply_screening_thresholds(df, primary_engine=primary_engine, engine_thresholds=engine_thresholds)
    df = compute_composite_scores(df)
    df = compute_agreement(df, engine_thresholds=engine_thresholds)

    # Consensus iPTM = max of per-engine PAE-recomputed iptms. Benchmark-validated
    # (ProteinBase 4-target, exhaustive 297-combo search) as the best deployable
    # binder-vs-non-binder score. Always computed; selectable as the ranking metric.
    df = compute_consensus_iptm(df)
    df = compute_consensus_ipsae(df)
    df = rank_by_adaptyv_method(df)
    df = rank_by_consensus_iptm(df)
    screen_metric = getattr(args, "screen_metric", "mean") or "mean"
    df = rank_by_two_stage(df, screen_metric=screen_metric)

    # Item 9: wet-lab-ready badge (SoluProt-passes + agreement_count >= 2 +
    # min binder pLDDT >= 0.50 + no FAILED RUN). Advisory only — the rank is
    # unchanged; the report renders failing rows with CSS strike-through.
    df = annotate_wetlab_recommended(df)

    # All three rankings coexist as columns (adaptyv_rank, consensus_rank,
    # two_stage_rank); --rank-by selects which orders the report. `active_rank`
    # is the chosen ordering (1..N) — used for display + structure-file naming so
    # the HTML shows the selected method's rank. The default is two_stage
    # (max-screen → mean-rank), the benchmark-recommended ordering for wet-lab selection.
    rank_by = getattr(args, "rank_by", "two_stage") or "two_stage"
    if rank_by == "consensus_iptm":
        print("[report] Ranking by consensus_iptm (max engine iptm — benchmark-validated binder filter)")
        df = df.sort_values(["consensus_rank"], ascending=[True]).reset_index(drop=True)
    elif rank_by == "two_stage":
        print(
            f"[report] Ranking by two_stage ({screen_metric}-screen top 50% → mean-rank — "
            "benchmark-validated for selection)"
        )
        df = df.sort_values(["two_stage_rank"], ascending=[True]).reset_index(drop=True)
    else:
        df = df.sort_values(["adaptyv_rank"], ascending=[True]).reset_index(drop=True)
    df["active_rank"] = range(1, len(df) + 1)

    # "Best design, not multiple sequences per design": collapse near-duplicate
    # variants of one trajectory (Protein-Hunter cycles, BindCraft MPNN re-designs)
    # to the single best-ranked representative. metrics.csv keeps ALL rows (with
    # design_group + is_representative); the report/top-N show distinct designs.
    df = add_design_groups(df)
    df["is_representative"] = ~df.duplicated("design_group", keep="first")
    collapse = not getattr(args, "no_collapse_duplicates", False)
    n_groups = int(df["design_group"].nunique())
    if collapse and n_groups < len(df):
        print(
            f"[report] Collapsing {len(df) - n_groups} near-duplicate variant(s) → "
            f"{n_groups} distinct designs (best per trajectory; --no-collapse-duplicates to disable)"
        )
        df_display = df[df["is_representative"]].reset_index(drop=True)
        df_display["active_rank"] = range(1, len(df_display) + 1)
    else:
        df_display = df

    # Step 4: Write outputs — metrics.csv = every row; everything else = distinct designs
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
        "consensus_iptm",
        "consensus_iptm_mean",
        "consensus_iptm_min",
        "consensus_iptm_n",
        "passes_max_screen",
        "ipsae_min",
        "boltz_pae_ipsae_min",
        "protenix_pae_ipsae_min",
        "af3_pae_ipsae_min",
        "esmfold2_ipsae_min",
        "consensus_ipsae_min_mean",
        "esmfold2_chain_iptm_interface",
        "boltz_pae_iptm",
        "boltz_pae_bt_ipsae",
        "boltz_pae_tb_ipsae",
        "esmfold2_pae_iptm",
        "plddt_binder_mean",
        "plddt_binder_min",
        "binder_ptm",
        "pae_bt_mean",
        "pae_tb_mean",
        "agreement_count",
        "passes_boltz_filter",
        "passes_protenix_filter",
        "passes_af3_filter",
        "passes_esmfold2_filter",
        "native_bg_design_ipsae_min",
        "adaptyv_rank",
        "consensus_rank",
        "two_stage_rank",
        "active_rank",
    ]
    _available = [c for c in _top_cols if c in df.columns]
    top30 = df_display.head(30)[_available]
    write_csv(top30, output_dir / "top30_candidates.csv")
    print("  top30_candidates.csv — top 30 distinct designs with sequences")

    # Slim decision-metrics table (companion to report.html): the agreed columns
    # + TmProt Tm + a plain-text Notes column (wet-lab advisory, no icon flags).
    write_top30_slim(df_display, output_dir, pool_size=len(df))
    print("  top30_slim.html     — decision-metrics-only top-30 table (+ .csv)")

    # Parse --tool-csv flags into dict (also consumed by the HTML report below).
    tool_csvs = {}
    if args.tool_csv:
        for spec in args.tool_csv:
            if "=" in spec:
                tool_name, csv_path = spec.split("=", 1)
                tool_csvs[tool_name.strip()] = csv_path.strip()

    # Step 4d: Combined candidates CSV — per-tool native top-20 (refolded designs
    # only, one row per backbone) followed by the refold top-30 ranking. Built
    # from the tools' RAW native CSVs; the in-pool filter + backbone collapse are
    # applied internally (no pre-processing needed).
    candidates = build_candidates_table(df, df_display, tool_csvs or None)
    write_csv(candidates, output_dir / "candidates.csv")
    print("  candidates.csv — per-tool native top-20 + refold top-30 with sequences")

    # Step 4c: Copy top-20 refolded PDB structures for visual inspection.
    # Prefer the *primary engine's* PDB so the viewer shows the structure
    # that was actually used for ranking. Fall back through the engine
    # priority order when a particular engine's file is missing.
    _ENGINE_PDB_PRIORITY: dict[str, list[str]] = {
        "af3": ["af3_pdb", "af3_cif", "boltz_pdb", "pdb"],
        "protenix": ["protenix_pdb", "protenix_cif", "boltz_pdb", "pdb"],
        "esmfold2": ["esmfold2_pdb", "esmfold2_cif", "boltz_pdb", "pdb"],
        "boltz": ["boltz_pdb", "pdb"],
    }
    pdb_cols = [c for c in _ENGINE_PDB_PRIORITY.get(primary_engine, ["boltz_pdb", "pdb"]) if c in df.columns]
    print(f"[report] Top-20 3D viewer source = {primary_engine} (column preference: {pdb_cols})")
    structures_dir = output_dir / "top20_structures"
    structures_dir.mkdir(parents=True, exist_ok=True)
    n_copied = 0
    for _, row in df_display.head(20).iterrows():
        rank = int(row.get("active_rank", row.get("adaptyv_rank", 0)))
        binder_id = row.get("binder_id", f"rank{rank}")
        for col in pdb_cols:
            src = row.get(col)
            if src and isinstance(src, str):
                src_path = Path(src)
                if not src_path.is_absolute() and args.boltz2_results:
                    src_path = Path(args.boltz2_results).resolve().parent / src
                if src_path.exists():
                    import shutil

                    # Preserve the source extension (.cif → .cif, .pdb → .pdb)
                    ext = src_path.suffix or ".pdb"
                    dest = structures_dir / f"rank{rank:02d}_{binder_id}{ext}"
                    shutil.copy2(src_path, dest)
                    n_copied += 1
                    break
    if n_copied:
        print(f"  top20_structures/    — {n_copied} refolded PDB structures for visual inspection")
        _write_pymol_script(df_display.head(20), structures_dir)
        print("  top20_structures/    — view_top20.pml (open in PyMOL)")

    # Step 5: HTML report
    # Parse --tool-pdb-dir flags into dict
    tool_pdb_dirs = {}
    if args.tool_pdb_dir:
        for spec in args.tool_pdb_dir:
            if "=" in spec:
                tool_name, pdb_dir = spec.split("=", 1)
                tool_pdb_dirs[tool_name.strip()] = pdb_dir.strip()

    # Item 3 + 5: fairness banner data. Static defaults live in
    # comparison.tool_classification; per-run overrides come from --tool-meta.
    tool_overrides = _parse_tool_meta(getattr(args, "tool_meta", None))
    # Item 6: provenance footer (git_sha, evaluator_version, CLI flags, ts).
    provenance = _collect_provenance(args)

    generate_report(
        df=df_display,
        full_df=df,
        summary=summary,
        output_path=output_dir / "report.html",
        tool_csvs=tool_csvs or None,
        tool_pdb_dirs=tool_pdb_dirs or None,
        boltz2_results_dir=Path(args.boltz2_results).resolve().parent if args.boltz2_results else None,
        primary_engine=primary_engine,
        top_per_tool=args.top_per_tool,
        rank_method=rank_by,
        tool_overrides=tool_overrides or None,
        provenance=provenance,
        lightweight=bool(getattr(args, "lightweight", False)),
        binding_map=getattr(args, "binding_map", None),
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
    "boltzgen_nano": "orange",
    "boltzgen_protein": "tv_orange",
    "bindcraft": "blue",
    "proteina_complexa": "teal",
    "rfd3": "tv_orange",
    "protein_hunter": "cyan",
}

_TOOL_DISPLAY_PYMOL = {
    "mosaic": "Mosaic",
    "pxdesign": "PXDesign",
    "boltzgen": "BoltzGen",
    "bindcraft": "BindCraft",
    "proteina_complexa": "Proteina-Complexa",
    "rfd3": "RFD3",
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
        rank = int(row.get("active_rank", row.get("adaptyv_rank", 0)))
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


def _attach_native_metrics_sidecar(df: pd.DataFrame, sequences_fasta: str) -> pd.DataFrame:
    """Left-join the per-binder native metrics CSV that 'extract' writes next
    to its FASTA output. Expected at ``<fasta_stem>_native_metrics.csv``.

    Drops fully-empty native_ columns (so e.g. RFD3-only runs don't surface
    empty mosaic_* columns in the final report).
    """
    fasta_path = Path(sequences_fasta)
    sidecar = fasta_path.with_name(fasta_path.stem + "_native_metrics.csv")
    if not sidecar.exists():
        return df

    native_df = pd.read_csv(sidecar)
    if native_df.empty or "sequence" not in native_df.columns:
        return df

    # Drop columns that are entirely empty in this extraction run; saves the
    # downstream report from listing 25 mostly-NaN columns when only 3 tools
    # were used.
    native_cols = [c for c in native_df.columns if c.startswith("native_")]
    keep_cols = ["sequence"] + [c for c in native_cols if native_df[c].notna().any()]
    if len(keep_cols) <= 1:
        return df  # nothing to add

    native_sub = native_df[keep_cols].copy()
    native_sub["sequence"] = native_sub["sequence"].str.strip().str.upper()
    print(f"[report] Attaching {len(keep_cols) - 1} native metric column(s) from {sidecar.name}")
    df = pd.merge(df, native_sub, on="sequence", how="left")
    return df


def _attach_soluprot_results(df: pd.DataFrame, soluprot_csv: str) -> pd.DataFrame:
    """Left-join SoluProt's per-sequence solubility output. The runner writes
    ``sequence, soluprot_score, soluprot_passes, soluprot_threshold`` (plus an
    optional leading ``binder_id``). We rename score and passes to the
    ``native_`` prefix so they live alongside the other design-time metrics in
    the final CSV; the threshold column rides through as ``soluprot_threshold``
    for traceability (which threshold the pass-flag was computed against).
    """
    sp_path = Path(soluprot_csv)
    if not sp_path.exists():
        print(f"[report] [warn] SoluProt CSV not found at {sp_path} — skipping")
        return df
    sp_df = pd.read_csv(sp_path)
    if sp_df.empty or "sequence" not in sp_df.columns:
        return df

    rename = {}
    if "soluprot_score" in sp_df.columns:
        rename["soluprot_score"] = "native_soluprot_score"
    if "soluprot_passes" in sp_df.columns:
        rename["soluprot_passes"] = "native_soluprot_passes"
    keep = ["sequence", *rename.keys()]
    if "soluprot_threshold" in sp_df.columns:
        keep.append("soluprot_threshold")
    sp_sub = sp_df[keep].rename(columns=rename).copy()
    sp_sub["sequence"] = sp_sub["sequence"].str.strip().str.upper()
    print(f"[report] Attaching SoluProt scores from {sp_path.name}")
    return pd.merge(df, sp_sub, on="sequence", how="left")


def _attach_tmprot_results(df: pd.DataFrame, tmprot_csv: str) -> pd.DataFrame:
    """Left-join TmProt's per-sequence melting-temperature output by sequence.

    TmProt (ESM2-LoRA Tm predictor, sister tool to SoluProt) is run externally on
    the same source FASTA; its native CLI writes ``Rank, ID, Predicted Tm [°C],
    Thermostable``. The runner here only requires a ``sequence`` column plus a Tm
    column under any common spelling — renamed to ``native_tmprot_tm`` so it lives
    alongside the other design-time screens in the final CSV.
    """
    tp_path = Path(tmprot_csv)
    if not tp_path.exists():
        print(f"[report] [warn] TmProt CSV not found at {tp_path} — skipping")
        return df
    tp_df = pd.read_csv(tp_path)
    if tp_df.empty or "sequence" not in tp_df.columns:
        return df
    tm_col = next(
        (c for c in tp_df.columns if c.strip().lower() in
         ("native_tmprot_tm", "tmprot_tm", "predicted_tm", "predicted_tm_c", "predicted tm [°c]", "tm", "tm_c")),
        None,
    )
    if tm_col is None:
        print(f"[report] [warn] no Tm column found in {tp_path.name} — skipping")
        return df
    tp_sub = tp_df[["sequence", tm_col]].rename(columns={tm_col: "native_tmprot_tm"}).copy()
    tp_sub["sequence"] = tp_sub["sequence"].str.strip().str.upper()
    tp_sub["native_tmprot_tm"] = pd.to_numeric(tp_sub["native_tmprot_tm"], errors="coerce")
    print(f"[report] Attaching TmProt Tm from {tp_path.name}")
    return pd.merge(df, tp_sub, on="sequence", how="left")


# qc-annotate (interface_qc.py) panel columns to surface in the report.
_DIVERSITY_COLS = ("family_id", "family_size", "family_rank")


def _attach_diversity_results(df: pd.DataFrame, diversity_csv: str) -> pd.DataFrame:
    """Left-join the diversity CSV by binder_id. ADVISORY — no reorder/drop."""
    div_path = Path(diversity_csv)
    if not div_path.exists():
        print(f"[report] WARNING: --diversity-results file not found: {div_path}; skipping.")
        return df
    try:
        div_df = pd.read_csv(div_path)
    except (OSError, pd.errors.ParserError) as exc:
        print(f"[report] WARNING: could not read --diversity-results {div_path}: {exc}")
        return df
    id_col = next((c for c in ("binder_id", "design_id", "id") if c in div_df.columns), None)
    if id_col is None:
        print(f"[report] WARNING: --diversity-results {div_path} has no id column; skipping.")
        return df
    keep = [id_col] + [c for c in _DIVERSITY_COLS if c in div_df.columns]
    sub = div_df[keep].rename(columns={id_col: "binder_id"}).copy()
    sub["binder_id"] = sub["binder_id"].astype(str)
    df = df.copy()
    df["binder_id"] = df["binder_id"].astype(str)
    n_fam = int(sub["family_id"].nunique()) if "family_id" in sub.columns else 0
    print(f"[report] Attaching diversity clusters from {div_path.name} ({n_fam} families)")
    return pd.merge(df, sub, on="binder_id", how="left")


_EPITOPE_COLS = (
    "epitope_match_fraction",
    "epitope_match_n",
    "epitope_n_interface",
    "epitope_off_target_residues",
    "epitope_matched_residues",
    "epitope_status",
)


def _attach_epitope_results(df: pd.DataFrame, epitope_csv: str) -> pd.DataFrame:
    """Left-join the epitope-match CSV by binder_id. ADVISORY — no reorder/drop."""
    epitope_path = Path(epitope_csv)
    if not epitope_path.exists():
        print(f"[report] WARNING: --epitope-results file not found: {epitope_path}; skipping.")
        return df
    try:
        ep_df = pd.read_csv(epitope_path)
    except (OSError, pd.errors.ParserError) as exc:
        print(f"[report] WARNING: could not read --epitope-results {epitope_path}: {exc}")
        return df
    id_col = next((c for c in ("binder_id", "design_id", "id") if c in ep_df.columns), None)
    if id_col is None:
        print(f"[report] WARNING: --epitope-results {epitope_path} has no id column; skipping.")
        return df
    keep = [id_col] + [c for c in _EPITOPE_COLS if c in ep_df.columns]
    ep_sub = ep_df[keep].rename(columns={id_col: "binder_id"}).copy()
    ep_sub["binder_id"] = ep_sub["binder_id"].astype(str)
    df = df.copy()
    df["binder_id"] = df["binder_id"].astype(str)
    n = int(ep_sub["epitope_match_fraction"].notna().sum()) if "epitope_match_fraction" in ep_sub.columns else 0
    print(f"[report] Attaching epitope-match panel from {epitope_path.name} ({n} annotated designs)")
    return pd.merge(df, ep_sub, on="binder_id", how="left")


_BETA_COLS = ("n_xbridge", "n_xbridge2", "beta_intercalates")


def _attach_beta_results(df: pd.DataFrame, beta_csv: str, exclude: bool = False) -> pd.DataFrame:
    """Left-join the beta-check CSV by binder_id. Advisory unless *exclude* — then
    DROP designs flagged ``beta_intercalates=true`` (binder strand threaded into
    the target β-sheet; non-physical)."""
    path = Path(beta_csv)
    if not path.exists():
        print(f"[report] WARNING: --beta-results file not found: {path}; skipping.")
        return df
    try:
        b_df = pd.read_csv(path)
    except (OSError, pd.errors.ParserError) as exc:
        print(f"[report] WARNING: could not read --beta-results {path}: {exc}")
        return df
    id_col = next((c for c in ("binder_id", "design_id", "id") if c in b_df.columns), None)
    if id_col is None:
        print(f"[report] WARNING: --beta-results {path} has no id column; skipping.")
        return df
    keep = [id_col] + [c for c in _BETA_COLS if c in b_df.columns]
    b_sub = b_df[keep].rename(columns={id_col: "binder_id"}).copy()
    b_sub["binder_id"] = b_sub["binder_id"].astype(str)
    df = df.copy()
    df["binder_id"] = df["binder_id"].astype(str)
    df = pd.merge(df, b_sub, on="binder_id", how="left")
    flagged = df["beta_intercalates"].astype(str).str.lower() == "true" if "beta_intercalates" in df.columns else None
    if exclude and flagged is not None:
        before = len(df)
        df = df[~flagged].reset_index(drop=True)
        print(f"[report] beta-check: EXCLUDED {before - len(df)} intercalating designs → {len(df)} remain")
    elif flagged is not None:
        print(f"[report] beta-check: {int(flagged.sum())} intercalating designs flagged (advisory — not dropped)")
    return df


_QC_PANEL_COLS = (
    "qc_pass",
    "qc_fail_reasons",
    "interface_sc",
    "interface_packstat",
    "interface_dG",
    "interface_dSASA",
    "interface_dG_SASA_ratio",
    "interface_nres",
    "interface_interface_hbonds",
    "interface_delta_unsat_hbonds",
    "interface_hydrophobicity",
    "surface_hydrophobicity",
)


def _attach_qc_results(df: pd.DataFrame, qc_csv: str) -> pd.DataFrame:
    """Left-join qc-annotate's BindCraft interface panel (``qc_pass`` +
    ``qc_fail_reasons`` + ``interface_*``) onto the merged frame by ``binder_id``.

    ADVISORY columns — surfaced in the report, never used to reorder or drop. qc-annotate
    annotates only a shortlist, so most rows stay NaN (expected).
    """
    qc_path = Path(qc_csv)
    if not qc_path.exists():
        print(f"[report] [warn] qc-annotate CSV not found at {qc_path} — skipping")
        return df
    qc_df = pd.read_csv(qc_path)
    id_col = next((c for c in ("binder_id", "design_id", "id") if c in qc_df.columns), None)
    if qc_df.empty or id_col is None or "binder_id" not in df.columns:
        print(f"[report] [warn] qc-annotate CSV {qc_path.name} not joinable (need an id column) — skipping")
        return df
    keep = [id_col] + [c for c in _QC_PANEL_COLS if c in qc_df.columns]
    qc_sub = qc_df[keep].rename(columns={id_col: "binder_id"}).copy()
    qc_sub["binder_id"] = qc_sub["binder_id"].astype(str)
    df = df.copy()
    df["binder_id"] = df["binder_id"].astype(str)
    n = int(qc_sub["qc_pass"].notna().sum()) if "qc_pass" in qc_sub.columns else len(qc_sub)
    print(f"[report] Attaching qc-annotate panel from {qc_path.name} ({n} annotated designs)")
    return pd.merge(df, qc_sub, on="binder_id", how="left")


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
        help="Optional: output from 'refold-af3' (af3_results.csv). Adds a third engine to the agreement_count.",
    )
    p.add_argument(
        "--soluprot-results",
        metavar="CSV",
        help="Optional: output from 'filter-soluprot' (soluprot_results.csv). Adds "
        "native_soluprot_score and native_soluprot_passes columns. SoluProt is a "
        "screen, not a re-ranker; the ranking hierarchy is unchanged.",
    )
    p.add_argument(
        "--tmprot-results",
        metavar="CSV",
        help="Optional: TmProt output (sequence + predicted Tm in °C; ESM2-LoRA "
        "thermostability screen, sister tool to SoluProt). Adds native_tmprot_tm. "
        "A screen, not a re-ranker; the ranking hierarchy is unchanged.",
    )
    p.add_argument(
        "--qc-results",
        metavar="CSV",
        help="Optional: output from 'qc-annotate' (BindCraft interface panel for a shortlist). "
        "Adds advisory qc_pass / qc_fail_reasons / interface_* columns joined by binder_id. "
        "Advisory only — never reorders or drops designs.",
    )
    p.add_argument(
        "--epitope-results",
        metavar="CSV",
        help="Optional: output from 'epitope' (per-design overlap with intended hotspots). "
        "Adds advisory epitope_match_fraction + epitope_status columns joined by binder_id. "
        "Critical for serpins / multi-pocket targets where high iPTM doesn't guarantee the "
        "right epitope. Advisory only — never reorders or drops designs.",
    )
    p.add_argument(
        "--diversity-results",
        metavar="CSV",
        help="Optional: output from 'diversity' (sequence-similarity clustering into families). "
        "Adds advisory family_id + family_size + family_rank columns. Surfaces a 'Top per "
        "family' recommendation block in the report — never reorders or drops the main rank.",
    )
    p.add_argument(
        "--beta-results",
        metavar="CSV",
        help="Optional: output from 'beta-check' (binder→target β-sheet intercalation flag via DSSP). "
        "Adds advisory n_xbridge + beta_intercalates columns joined by binder_id.",
    )
    p.add_argument(
        "--exclude-intercalators",
        action="store_true",
        help="With --beta-results: DROP designs flagged as intercalating (binder strand threaded into the "
        "target β-sheet — non-physical β-augmentation). Off by default (advisory).",
    )
    p.add_argument(
        "--esmfold2-results",
        metavar="CSV",
        help="Optional: output from 'refold-esmfold2' (esmfold2_results.csv). "
        "Adds a fourth engine to the agreement_count.",
    )
    p.add_argument(
        "--sequences", metavar="FASTA", help="FASTA from 'extract' step (for binder_id and source_tool tags)"
    )
    p.add_argument(
        "--native-metrics", metavar="CSV", help="BindCraft final_design_stats.csv to attach dG/dSASA/ShapeComp"
    )
    p.add_argument("--output", "-o", required=True, metavar="DIR", help="Output directory for all report files")
    p.add_argument(
        "--primary-engine",
        choices=["boltz", "protenix", "af3", "esmfold2"],
        default="boltz",
        help="Which engine's DunbrackLab PAE-based ipsae_min to use as the primary ranking metric "
        "(default: boltz). Falls back to boltz if the chosen engine's PAE files are missing.",
    )
    p.add_argument(
        "--rank-by",
        choices=["adaptyv", "consensus_iptm", "two_stage"],
        default="two_stage",
        help="Ranking method for the report. 'adaptyv' = quality_tier → agreement_count → "
        "ipsae_min. 'consensus_iptm' = max engine iptm (benchmark-validated binder-vs-non-binder filter). "
        "'two_stage' (default) = screen (top 50%%) then mean-rank survivors (benchmark-validated for wet-lab "
        "selection: precision@top-10%% 0.92 vs 0.79 for max alone; see docs/plans.md Part N). All ranks "
        "are always written as columns (adaptyv_rank, consensus_rank, two_stage_rank).",
    )
    p.add_argument(
        "--screen-metric",
        choices=["max", "mean"],
        default="mean",
        help="Stage-1 screen metric for --rank-by two_stage. 'mean' (default) = consensus_iptm_mean, the "
        "stronger binder screen on the Adaptyv 4-target benchmark with experimental Kd (macro AUC 0.710 vs "
        "0.689; +20 true binders recalled at the 50%% cut). 'max' = consensus_iptm (legacy; best on the "
        "ProteinBase benchmark, ~0.755).",
    )
    p.add_argument(
        "--no-collapse-duplicates",
        action="store_true",
        help="Disable the default 'best design, not multiple sequences per design' collapse. By default "
        "near-duplicate variants of one trajectory (Protein-Hunter cycles, BindCraft MPNN re-designs) are "
        "collapsed to the single best-ranked representative in the report and top-N (metrics.csv keeps all, "
        "tagged with design_group + is_representative).",
    )
    # Per-engine iPSAE thresholds (defaults from scoring.DEFAULT_ENGINE_THRESHOLDS)
    p.add_argument(
        "--threshold-boltz", type=float, default=None, help="Boltz-2 ipsae_min pass threshold (default 0.61)"
    )
    p.add_argument(
        "--threshold-protenix", type=float, default=None, help="Protenix ipsae_min pass threshold (default 0.61)"
    )
    p.add_argument(
        "--threshold-af3",
        type=float,
        default=None,
        help="AF3 ipsae_min pass threshold (default 0.61, DunbrackLab-calibrated)",
    )
    p.add_argument(
        "--threshold-esmfold2",
        type=float,
        default=None,
        help="ESMFold2 ipsae_min pass threshold (default 0.61, using the shared DunbrackLab cutoff)",
    )
    p.add_argument(
        "--threshold-af2",
        type=float,
        default=None,
        help="AF2 informational threshold (default 0.30; AF2 mis-calibrated for short targets — not counted in agreement)",
    )
    p.add_argument(
        "--top-per-tool",
        type=int,
        default=10,
        metavar="N",
        help="How many designs to surface per tool in the per-tool native-ranked sections of the "
        "report (radar plots + per-tool tables + per-tool 3D viewers). Default 10. Increase if "
        "you want to inspect more of each tool's native top picks.",
    )
    p.add_argument(
        "--tool-csv",
        metavar="TOOL=CSV",
        action="append",
        help="Tool's original output CSV for native-ranked top-N section. "
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
    # Item 3: per-tool extractor-metadata overrides for the fairness banner.
    p.add_argument(
        "--tool-meta",
        metavar="TOOL=KEY:VALUE[;KEY:VALUE]",
        action="append",
        help="Override the per-tool fairness banner (e.g. mark a pool as pre-filtered). "
        "Keys: pool_pre_filtered (true|false), source_csv (filename), notes (string). "
        "Example: --tool-meta protein_hunter='pool_pre_filtered:true;source_csv:summary_high_iptm.csv'. "
        "If absent, the static defaults in comparison.tool_classification apply.",
    )
    # Item 6: run provenance (engine versions / checkpoints / seeds for the footer).
    p.add_argument(
        "--engine-versions",
        metavar="FILE",
        help="JSON or YAML file mapping engine name → version/checkpoint string "
        "(e.g. boltz: 2024.08, af3: v3.0.2, esmfold2: full). Rendered in the report footer.",
    )
    # Item 12_orig (Phase 4): coordinate externalisation. Wired here so the
    # CLI surface is stable from Phase 2 onward; the implementation lives in
    # generate_report (Phase 4).
    p.add_argument(
        "--lightweight",
        action="store_true",
        help="Skip the inline 3D viewer (top-20 NGL coords stay in PDB files in top20_structures/, "
        "but no embedded base64). Cuts ~5 MB from the HTML for large pools.",
    )
    p.add_argument(
        "--binding-map",
        default=None,
        metavar="HREF",
        help="Relative path/filename of a binding_map.html (from 'binder-compare epitope-map') to link "
        "from the report as a callout. The file must sit next to report.html in the bundle.",
    )
    p.set_defaults(func=run)
