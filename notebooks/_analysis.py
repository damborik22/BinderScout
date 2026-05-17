"""Investigation script for ranking discrepancy.

Loads metrics.csv, rejoins per-tool native metrics where possible, and
emits the data needed for the markdown report. Re-run safely.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path("/home/bindmaster5/dev/BindMaster")
RUN_DIR = ROOT / "runs/CALCA_helix_BM4"
EVAL_DIR = RUN_DIR / "evaluate/run1_free"
METRICS_CSV = EVAL_DIR / "report/metrics.csv"
NB_DIR = ROOT / "notebooks"
OUT_DIR = NB_DIR / "_artifacts"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_metrics():
    df = pd.read_csv(METRICS_CSV)
    return df


# --- Per-tool native joins -----------------------------------------------


def join_bindcraft(df):
    bc = df[df["source_tool"] == "bindcraft"].copy()
    native_dfs = []
    for d in ["bindcraft", "bindcraft_default", "bindcraft_variant_a"]:
        p = RUN_DIR / d / "outputs/final_design_stats.csv"
        if p.exists():
            t = pd.read_csv(p)
            if not t.empty:
                t["_source_dir"] = d
                native_dfs.append(t)
    if not native_dfs:
        return bc, pd.DataFrame()
    native = pd.concat(native_dfs, ignore_index=True)

    def strip_prefix(bid):
        if bid.startswith("bindcraft_default_"):
            return bid[len("bindcraft_default_") :]
        if bid.startswith("bindcraft_"):
            return bid[len("bindcraft_") :]
        return bid

    bc["_join_key"] = bc["binder_id"].apply(strip_prefix)
    # Native primary metrics for ranking: 'Average_i_pTM' desc, 'Rank' asc
    native_keep = native[
        [
            "Design",
            "Rank",
            "Average_pLDDT",
            "Average_pTM",
            "Average_i_pTM",
            "Average_pAE",
            "Average_i_pAE",
            "Average_dG",
            "Average_dSASA",
            "Average_ShapeComplementarity",
            "Average_PackStat",
            "Average_n_InterfaceHbonds",
            "Average_InterfaceHbondsPercentage",
            "MPNN_seq_recovery",
        ]
    ].copy()
    native_keep = native_keep.rename(
        columns={
            "Design": "_join_key",
            "Rank": "native_rank",
            "Average_pLDDT": "native_plddt",
            "Average_pTM": "native_pTM",
            "Average_i_pTM": "native_i_pTM",
            "Average_pAE": "native_pAE",
            "Average_i_pAE": "native_i_pAE",
            "Average_dG": "native_dG",
            "Average_dSASA": "native_dSASA",
            "Average_ShapeComplementarity": "native_shape_comp",
            "Average_PackStat": "native_packstat",
            "Average_n_InterfaceHbonds": "native_hbonds",
            "Average_InterfaceHbondsPercentage": "native_hbond_pct",
            "MPNN_seq_recovery": "native_mpnn_recovery",
        }
    )
    # In case duplicates: take the row with min Rank
    native_keep = native_keep.sort_values("native_rank").drop_duplicates("_join_key", keep="first")
    merged = bc.merge(native_keep, on="_join_key", how="left")
    return merged, native_keep


def join_boltzgen(df):
    bg = df[df["source_tool"] == "boltzgen"].copy()
    p = RUN_DIR / "boltzgen/outputs/final_ranked_designs/final_designs_metrics_700.csv"
    native = pd.read_csv(p)

    # binder_id format: boltzgen_config_NNNN_rRANK  -> strip 'boltzgen_' and trailing '_r\d+'
    def keyfn(bid):
        s = bid[len("boltzgen_") :] if bid.startswith("boltzgen_") else bid
        if "_r" in s and s.rsplit("_r", 1)[1].isdigit():
            return s.rsplit("_r", 1)[0]
        return s

    bg["_join_key"] = bg["binder_id"].apply(keyfn)
    keep_cols = [
        "id",
        "final_rank",
        "design_to_target_iptm",
        "min_design_to_target_pae",
        "design_ptm",
        "filter_rmsd",
        "design_ipsae_min",  # BoltzGen's own ipSAE_min (designfolding output)
        "design_to_target_ipsae",
        "target_to_design_ipsae",
        "iptm",  # BG self-folding iptm
    ]
    keep_cols = [c for c in keep_cols if c in native.columns]
    native_keep = native[keep_cols].rename(
        columns={
            "id": "_join_key",
            "final_rank": "native_rank",
            "design_to_target_iptm": "native_d2t_iptm",
            "min_design_to_target_pae": "native_min_d2t_pae",
            "design_ptm": "native_design_ptm",
            "filter_rmsd": "native_filter_rmsd",
            "design_ipsae_min": "native_bg_ipsae_min",
            "design_to_target_ipsae": "native_bg_d2t_ipsae",
            "target_to_design_ipsae": "native_bg_t2d_ipsae",
            "iptm": "native_bg_iptm",
        }
    )
    merged = bg.merge(native_keep, on="_join_key", how="left")
    return merged, native_keep


def join_pxdesign(df):
    px = df[df["source_tool"] == "pxdesign"].copy()
    p = RUN_DIR / "pxdesign/summary.csv"
    if not p.exists():
        return px, pd.DataFrame()
    native = pd.read_csv(p)
    keep = native[["design_id", "sequence", "af2_iptm", "af2_plddt", "length"]].rename(
        columns={"design_id": "binder_id", "af2_iptm": "native_af2_iptm", "af2_plddt": "native_af2_plddt"}
    )
    # Merge on binder_id where possible (only ~half overlap because on-disk summary differs from when run1_free was made)
    merged = px.merge(keep[["binder_id", "native_af2_iptm", "native_af2_plddt"]], on="binder_id", how="left")
    return merged, keep


def join_proteina_complexa(df):
    pc = df[df["source_tool"] == "proteina_complexa"].copy()
    # On-disk sequences.csv uses different IDs (complexa_CALCA_helix_b1_XXX, pc_top_N)
    # and zero sequence overlap with metrics. We cannot reconstruct native ranking metrics
    # for run1_free PC designs. Return empty native frame.
    return pc, pd.DataFrame()


def join_mosaic(df):
    mo = df[df["source_tool"] == "mosaic"].copy()
    # Use ipsae_min_aux as a proxy native ranking (Mosaic's own optimization-time aux score)
    # Real ranking_loss is not recoverable from current on-disk designs.csv (different vintage).
    # Also reconstruct from checkpoints: same problem (different workers).
    # Use Mosaic-internal aux ipSAE as the closest proxy for "what Mosaic considered top".
    return mo, pd.DataFrame()


# --- Correlation helpers -------------------------------------------------


def spearman(a, b):
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    mask = a.notna() & b.notna()
    if mask.sum() < 5:
        return np.nan, mask.sum()
    rho, _ = stats.spearmanr(a[mask], b[mask])
    return rho, mask.sum()


def top_n_agreement(df, native_col, refold_col, n, ascending_native=True, ascending_refold=False):
    """Pct of top-n designs by native rank that also appear in top-n by refold metric.
    ascending_native=True means lower is better (e.g. native_rank=1 is top).
    ascending_refold=False means higher is better (e.g. ipsae_min higher is better).
    """
    a = df.dropna(subset=[native_col, refold_col])
    if len(a) < n:
        return np.nan, len(a)
    top_native = a.nsmallest(n, native_col) if ascending_native else a.nlargest(n, native_col)
    top_refold = a.nlargest(n, refold_col) if not ascending_refold else a.nsmallest(n, refold_col)
    nset = set(top_native["binder_id"])
    rset = set(top_refold["binder_id"])
    return len(nset & rset) / n, len(a)


# --- Main correlation analysis -------------------------------------------


def build_correlation_table(df):
    rows = []
    # Per tool
    tool_data = {}

    # BindCraft
    bc_merged, _ = join_bindcraft(df)
    tool_data["bindcraft"] = bc_merged
    bc_metrics_for_corr = [
        ("ipsae_min_aux", "ipsae_min_aux"),
        ("boltz_pae_ipsae_min", "boltz_pae_ipsae_min"),
        ("af2_ipsae_min", "af2_ipsae_min"),
        ("iptm", "iptm"),
        ("plddt_binder_mean", "plddt_binder_mean"),
        ("binder_length", "binder_length"),
    ]
    rows.append(_one_tool(bc_merged, "bindcraft", "native_i_pTM", asc_native=False, refold_metrics=bc_metrics_for_corr))
    # Also BindCraft by native_rank (since rank is fundamental)
    rows.append(
        _one_tool(
            bc_merged, "bindcraft (by native_rank)", "native_rank", asc_native=True, refold_metrics=bc_metrics_for_corr
        )
    )

    # BoltzGen
    bg_merged, _ = join_boltzgen(df)
    tool_data["boltzgen"] = bg_merged
    bg_metrics_for_corr = [
        ("ipsae_min_aux", "ipsae_min_aux"),
        ("boltz_pae_ipsae_min", "boltz_pae_ipsae_min"),
        ("af2_ipsae_min", "af2_ipsae_min"),
        ("iptm", "iptm"),
        ("plddt_binder_mean", "plddt_binder_mean"),
        ("binder_length", "binder_length"),
        ("native_bg_ipsae_min", "native_bg_ipsae_min"),  # BoltzGen's internal ipSAE
    ]
    rows.append(_one_tool(bg_merged, "boltzgen", "native_rank", asc_native=True, refold_metrics=bg_metrics_for_corr))
    # Cross-check vs BoltzGen's own native ipSAE
    rows.append(
        _one_tool(
            bg_merged, "boltzgen (by d2t_iptm)", "native_d2t_iptm", asc_native=False, refold_metrics=bg_metrics_for_corr
        )
    )

    # PXDesign
    px_merged, _ = join_pxdesign(df)
    tool_data["pxdesign"] = px_merged
    px_metrics_for_corr = [
        ("ipsae_min_aux", "ipsae_min_aux"),
        ("boltz_pae_ipsae_min", "boltz_pae_ipsae_min"),
        ("af2_ipsae_min", "af2_ipsae_min"),
        ("iptm", "iptm"),
        ("plddt_binder_mean", "plddt_binder_mean"),
        ("binder_length", "binder_length"),
    ]
    rows.append(
        _one_tool(px_merged, "pxdesign", "native_af2_iptm", asc_native=False, refold_metrics=px_metrics_for_corr)
    )

    # Mosaic (no recoverable native)
    mo_merged, _ = join_mosaic(df)
    tool_data["mosaic"] = mo_merged
    # Use ipsae_min_aux (Mosaic-native optimization-time aux) as proxy for "Mosaic confidence"
    mo_metrics_for_corr = [
        ("boltz_pae_ipsae_min", "boltz_pae_ipsae_min"),
        ("af2_ipsae_min", "af2_ipsae_min"),
        ("iptm", "iptm"),
        ("plddt_binder_mean", "plddt_binder_mean"),
        ("binder_length", "binder_length"),
    ]
    rows.append(
        _one_tool(
            mo_merged,
            "mosaic (by ipsae_min_aux proxy)",
            "ipsae_min_aux",
            asc_native=False,
            refold_metrics=mo_metrics_for_corr,
        )
    )

    # Proteina-Complexa: no recoverable native; use iptm as proxy
    pc_merged, _ = join_proteina_complexa(df)
    tool_data["proteina_complexa"] = pc_merged
    pc_metrics_for_corr = [
        ("ipsae_min_aux", "ipsae_min_aux"),
        ("boltz_pae_ipsae_min", "boltz_pae_ipsae_min"),
        ("af2_ipsae_min", "af2_ipsae_min"),
        ("plddt_binder_mean", "plddt_binder_mean"),
        ("binder_length", "binder_length"),
    ]
    rows.append(
        _one_tool(
            pc_merged, "proteina_complexa (by iptm proxy)", "iptm", asc_native=False, refold_metrics=pc_metrics_for_corr
        )
    )

    return pd.DataFrame(rows), tool_data


def _one_tool(df_tool, label, native_col, *, asc_native, refold_metrics):
    """Compute spearman ρ vs native_col for each refold metric, plus top-n agreements."""
    out = {"tool": label, "n_designs": len(df_tool), "native_metric": native_col}
    if native_col not in df_tool.columns:
        return out
    for refold_name, refold_col in refold_metrics:
        if refold_col not in df_tool.columns:
            out[f"rho_{refold_name}"] = np.nan
            out[f"n_{refold_name}"] = 0
            continue
        rho, n = spearman(df_tool[native_col], df_tool[refold_col])
        out[f"rho_{refold_name}"] = round(rho, 3) if pd.notna(rho) else np.nan
        out[f"n_{refold_name}"] = n
    # Top-N agreement: native rank "best" vs refold metric best
    # use boltz_pae_ipsae_min as the canonical refold metric
    for n in (5, 10, 20):
        agree, _valid_n = top_n_agreement(
            df_tool,
            native_col,
            "boltz_pae_ipsae_min",
            n,
            ascending_native=asc_native,
            ascending_refold=False,
        )
        out[f"top{n}_overlap_pct"] = round(agree * 100, 1) if pd.notna(agree) else np.nan
    return out


# --- Top-20 ipSAE outliers (high refold ipsae, below-median native) ------


def find_top20_outliers(df, tool_data):
    """For top-20 by boltz_pae_ipsae_min, characterize each design.

    Below-median native rank within tool is included as a flag rather than a filter,
    because for Mosaic/PC/some PX we have no recoverable native rank.
    """
    top20 = df.nlargest(20, "boltz_pae_ipsae_min").copy().reset_index(drop=True)

    def get_native_pct(row):
        # Look up the merged tool df for this binder_id and return native_rank percentile
        td = tool_data.get(row["source_tool"])
        if td is None or "native_rank" not in td.columns:
            return np.nan
        m = td[td["binder_id"] == row["binder_id"]]
        if m.empty or pd.isna(m["native_rank"].iloc[0]):
            return np.nan
        nat_rank = m["native_rank"].iloc[0]
        # Compute its native percentile
        ranks = td["native_rank"].dropna()
        return float((ranks <= nat_rank).sum()) / len(ranks)

    def low_complexity_frac(seq):
        if not seq or len(seq) < 5:
            return np.nan
        c = pd.Series(list(seq)).value_counts()
        return float(c.iloc[0] / len(seq))  # fraction of most-common aa

    def hydrophobic_frac(seq):
        H = set("AILMFVWY")
        return float(sum(1 for a in seq if a in H)) / max(1, len(seq))

    def net_charge(seq):
        pos = sum(1 for a in seq if a in "KR")
        neg = sum(1 for a in seq if a in "DE")
        return pos - neg

    top20["native_pct"] = top20.apply(get_native_pct, axis=1)
    top20["low_complexity_frac"] = top20["sequence"].apply(low_complexity_frac)
    top20["hydrophobic_frac"] = top20["sequence"].apply(hydrophobic_frac)
    top20["net_charge"] = top20["sequence"].apply(net_charge)
    top20["ipsae_max_min_asym"] = top20["boltz_pae_ipsae_max"] - top20["boltz_pae_ipsae_min"]
    top20["below_median_native"] = top20["native_pct"] > 0.5

    def verdict(r):
        b = r["boltz_pae_ipsae_min"]
        a = r["af2_ipsae_min"]
        asym = r["ipsae_max_min_asym"]
        bl = r["binder_length"]
        lc = r["low_complexity_frac"]
        # multi-engine agreement
        agree = (pd.notna(b) and b > 0.61) and (pd.notna(a) and a > 0.61)
        # warning signs
        very_short = bl <= 30
        low_complex = lc > 0.30
        big_asym = asym > 0.3
        single_only = (pd.notna(b) and b > 0.61) and not (pd.notna(a) and a > 0.61)
        if agree and not (very_short and low_complex):
            return "likely_real"
        if single_only and (very_short or low_complex or big_asym):
            return "likely_artifact"
        return "inconclusive"

    top20["verdict"] = top20.apply(verdict, axis=1)
    return top20


# --- BoltzGen deep dive ---------------------------------------------------


def boltzgen_deep_dive(df, bg_merged):
    out = {}
    # BG #1 by native final_rank
    if "native_rank" in bg_merged.columns:
        sorted_bg = bg_merged.dropna(subset=["native_rank"]).sort_values("native_rank")
        bg_top1 = sorted_bg.iloc[0]
        out["bg_top1_binder_id"] = bg_top1["binder_id"]
        out["bg_top1_final_rank"] = bg_top1["native_rank"]
        out["bg_top1_boltz_ipsae_min"] = bg_top1.get("boltz_pae_ipsae_min")
        out["bg_top1_af2_ipsae_min"] = bg_top1.get("af2_ipsae_min")
        out["bg_top1_native_bg_ipsae_min"] = bg_top1.get("native_bg_ipsae_min")
        out["bg_top1_sequence"] = bg_top1["sequence"]
        out["bg_top1_binder_length"] = bg_top1["binder_length"]
    # Top-5 by BG internal ipsae_min
    if "native_bg_ipsae_min" in bg_merged.columns:
        top5_native = bg_merged.dropna(subset=["native_bg_ipsae_min"]).nlargest(5, "native_bg_ipsae_min")
        cols_top = [
            c
            for c in ["binder_id", "native_bg_ipsae_min", "boltz_pae_ipsae_min", "af2_ipsae_min"]
            if c in top5_native.columns
        ]
        out["top5_by_native_bg_ipsae"] = top5_native[cols_top].to_dict(orient="records")
    # Bottom-5 by Boltz refold ipsae_min (within BG)
    bot5 = bg_merged.dropna(subset=["boltz_pae_ipsae_min"]).nsmallest(5, "boltz_pae_ipsae_min")
    cols_bot = [
        c
        for c in ["binder_id", "native_bg_ipsae_min", "boltz_pae_ipsae_min", "af2_ipsae_min", "native_rank"]
        if c in bot5.columns
    ]
    out["bot5_by_boltz_ipsae"] = bot5[cols_bot].to_dict(orient="records")
    # Overall stats
    out["n_bg_designs"] = len(bg_merged)
    # Spearman between BoltzGen internal ipSAE and Boltz refold ipSAE
    if "native_bg_ipsae_min" in bg_merged.columns:
        rho, n = spearman(bg_merged["native_bg_ipsae_min"], bg_merged["boltz_pae_ipsae_min"])
        out["rho_bg_native_vs_boltz_refold"] = rho
        out["n_for_rho"] = n
    return out


# --- Outputs --------------------------------------------------------------


def main():
    df = load_metrics()
    print(f"Loaded metrics.csv: {df.shape}")

    corr_df, tool_data = build_correlation_table(df)
    corr_path = OUT_DIR / "per_tool_correlations.csv"
    corr_df.to_csv(corr_path, index=False)
    print(f"\nPer-tool correlations:\n{corr_df.to_string()}\n -> {corr_path}")

    # Save merged frames for the notebook
    for tool, d in tool_data.items():
        d.to_csv(OUT_DIR / f"{tool}_merged.csv", index=False)

    # Top-20 outliers
    top20 = find_top20_outliers(df, tool_data)
    top20_path = OUT_DIR / "top20_outliers.csv"
    keep = [
        "binder_id",
        "source_tool",
        "binder_length",
        "sequence",
        "boltz_pae_ipsae_min",
        "af2_ipsae_min",
        "ipsae_min_aux",
        "ipsae_max_min_asym",
        "low_complexity_frac",
        "hydrophobic_frac",
        "net_charge",
        "native_pct",
        "below_median_native",
        "verdict",
    ]
    top20[keep].to_csv(top20_path, index=False)
    print("\nTop-20 outliers verdict counts:")
    print(top20["verdict"].value_counts().to_string())
    print(f" -> {top20_path}")

    # BoltzGen deep dive
    bg_dive = boltzgen_deep_dive(df, tool_data["boltzgen"])
    bg_dive_path = OUT_DIR / "boltzgen_deep_dive.json"

    # Convert numpy types for JSON
    def cv(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return o

    serial = json.loads(json.dumps(bg_dive, default=cv))
    with open(bg_dive_path, "w") as fh:
        json.dump(serial, fh, indent=2, default=cv)
    print(f"\nBoltzGen deep dive saved -> {bg_dive_path}")
    print(json.dumps(serial, indent=2, default=cv)[:2000])

    return df, corr_df, tool_data, top20, bg_dive


if __name__ == "__main__":
    main()
