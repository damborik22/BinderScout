"""Matplotlib-based plots for the binder comparison report."""

from __future__ import annotations

import base64
import io
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# Colour scheme per source tool
TOOL_COLOURS = {
    "bindcraft": "#2196F3",  # blue
    "boltzgen": "#FF9800",  # orange
    "mosaic": "#4CAF50",  # green
    "pxdesign": "#9C27B0",  # purple
    "unknown": "#9E9E9E",  # grey
}

# Per-metric display metadata: (human_label, unit_str, direction_arrow)
# direction_arrow: "↑" = higher is better, "↓" = lower is better, "" = n/a
METRIC_META: dict[str, tuple[str, str, str]] = {
    "ipsae_min": ("ipSAE_min", "[0–1]", "↑"),
    "bt_ipsae_aux": ("ipSAE B→T (aux)", "[0–1]", "↑"),
    "tb_ipsae_aux": ("ipSAE T→B (aux)", "[0–1]", "↑"),
    "ipsae_min_aux": ("ipSAE_min (aux)", "[0–1]", "↑"),
    "boltz_pae_bt_ipsae": ("Boltz ipSAE B→T", "[0–1]", "↑"),
    "boltz_pae_tb_ipsae": ("Boltz ipSAE T→B", "[0–1]", "↑"),
    "boltz_pae_ipsae_min": ("Boltz ipSAE_min", "[0–1]", "↑"),
    "af2_ipsae_min": ("AF2 ipSAE_min", "[0–1]", "↑"),
    "af2_bt_ipsae": ("AF2 ipSAE (B→T)", "[0–1]", "↑"),
    "af2_tb_ipsae": ("AF2 ipSAE (T→B)", "[0–1]", "↑"),
    "iptm": ("ipTM", "[0–1]", "↑"),
    "af2_iptm": ("AF2 ipTM", "[0–1]", "↑"),
    "binder_ptm": ("Binder pTM", "[0–1]", "↑"),
    "plddt_binder_mean": ("pLDDT binder (mean)", "[0–1]", "↑"),
    "plddt_binder_min": ("pLDDT binder (min)", "[0–1]", "↑"),
    "plddt_target_mean": ("pLDDT target (mean)", "[0–1]", "↑"),
    "ipae": ("ipAE", "Å", "↓"),
    "af2_ipae": ("AF2 ipAE", "Å", "↓"),
    "pae_bt": ("PAE (B→T)", "Å", "↓"),
    "pae_tb": ("PAE (T→B)", "Å", "↓"),
    "pae_bb": ("PAE (intra-B)", "Å", "↓"),
    "composite_score": ("Composite score", "z", "↑"),
    "adaptyv_rank": ("Rank", "", ""),
    "binder_id": ("Binder ID", "", ""),
    "source_tool": ("Tool", "", ""),
    "quality_tier": ("Tier", "", ""),
    "sequence": ("Sequence", "", ""),
    "binder_length": ("Binder length", "aa", ""),
    "ipsae_valid": ("ipSAE valid", "", ""),
}


# ---------------------------------------------------------------------------
# pLDDT curves
# ---------------------------------------------------------------------------


def plot_plddt_curves(
    df: pd.DataFrame,
    plddt_data: dict[str, np.ndarray],  # {sequence: plddt_array [0,1] shape [L]}
    binder_lengths: dict[str, int],  # {sequence: L_b}
    max_binders: int = 30,
    title: str = "pLDDT profiles (Boltz2)",
) -> Figure:
    """Plot per-residue pLDDT for up to *max_binders* binders.

    Args:
        df:             Summary DataFrame with 'sequence' and 'source_tool'.
        plddt_data:     Per-residue pLDDT arrays keyed by sequence.
        binder_lengths: Number of binder residues per sequence.
        max_binders:    Cap to avoid overloaded plots.
        title:          Figure title.
    """
    fig, ax = plt.subplots(figsize=(12, 5))

    subset = df.head(max_binders)
    for _, row in subset.iterrows():
        seq = row.get("sequence", "")
        if seq not in plddt_data:
            continue
        arr = np.array(plddt_data[seq])
        L_b = binder_lengths.get(seq, len(arr))
        tool = row.get("source_tool", "unknown")
        colour = TOOL_COLOURS.get(tool, TOOL_COLOURS["unknown"])
        ax.plot(arr, color=colour, alpha=0.5, linewidth=0.8)

        # Mark binder / target boundary
        if L_b < len(arr):
            ax.axvline(L_b, color="grey", linestyle="--", linewidth=0.5, alpha=0.4)

    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Residue index")
    ax.set_ylabel("pLDDT")
    ax.set_title(title)

    legend_handles = [
        matplotlib.patches.Patch(color=c, label=t)
        for t, c in TOOL_COLOURS.items()
        if t in df.get("source_tool", pd.Series()).values
    ]
    if legend_handles:
        ax.legend(handles=legend_handles, loc="lower right", fontsize=8)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# PAE heatmaps
# ---------------------------------------------------------------------------


def plot_pae_heatmaps(
    sequences: list[str],
    af2_pae_data: dict[str, np.ndarray],
    boltz_pae_data: dict[str, np.ndarray],
    binder_lengths: dict[str, int],
    max_binders: int = 6,
) -> Figure:
    """Side-by-side AF2 / Boltz2 PAE heatmaps for the top binders.

    Shows both models for each binder to make the comparison visual.
    """
    seqs = [s for s in sequences if s in af2_pae_data or s in boltz_pae_data][:max_binders]
    n = len(seqs)
    if n == 0:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No PAE data available", ha="center", va="center")
        return fig

    fig, axes = plt.subplots(n, 2, figsize=(10, 3 * n), squeeze=False)

    for row_i, seq in enumerate(seqs):
        L_b = binder_lengths.get(seq, 0)
        for col_i, (label, pae_dict) in enumerate([("AF2", af2_pae_data), ("Boltz2", boltz_pae_data)]):
            ax = axes[row_i][col_i]
            if seq in pae_dict:
                pae = np.array(pae_dict[seq])
                im = ax.imshow(pae, vmin=0, vmax=30, cmap="bwr", aspect="auto")
                if L_b > 0 and L_b < pae.shape[0]:
                    ax.axhline(L_b - 0.5, color="white", linewidth=1)
                    ax.axvline(L_b - 0.5, color="white", linewidth=1)
                plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="PAE (Å)")
            else:
                ax.text(0.5, 0.5, "N/A", ha="center", va="center", transform=ax.transAxes)

            ax.set_title(f"{label} — seq {row_i + 1}")
            ax.set_xlabel("Residue j")
            ax.set_ylabel("Residue i")

    fig.suptitle("PAE heatmaps (binder | target ordering)", y=1.01)
    fig.tight_layout()
    return fig


def load_pae_data_from_df(
    df: pd.DataFrame,
    max_binders: int = 5,
) -> tuple[list[str], dict[str, np.ndarray], dict[str, np.ndarray], dict[str, int]]:
    """Load PAE .npy files for top-ranked binders from DataFrame file paths.

    Returns (sequences, af2_pae_data, boltz_pae_data, binder_lengths).
    """
    af2_pae_data: dict[str, np.ndarray] = {}
    boltz_pae_data: dict[str, np.ndarray] = {}
    binder_lengths: dict[str, int] = {}
    sequences: list[str] = []

    count = 0
    for _, row in df.iterrows():
        if count >= max_binders:
            break
        seq = row.get("sequence", "")
        if not seq or seq in af2_pae_data or seq in boltz_pae_data:
            continue

        L_b = row.get("binder_length")
        if pd.isna(L_b):
            L_b = len(seq)
        binder_lengths[seq] = int(L_b)

        loaded_any = False

        # Load Boltz-2 PAE (binder|target ordering)
        boltz_path = row.get("boltz_pae_file")
        if boltz_path and not pd.isna(boltz_path):
            try:
                p = Path(str(boltz_path))
                if p.exists():
                    boltz_pae_data[seq] = np.load(str(p))
                    loaded_any = True
            except Exception:
                pass

        # Load AF2 PAE (target|binder ordering → transpose to binder|target)
        af2_path = row.get("af2_pae_file")
        if af2_path and not pd.isna(af2_path):
            try:
                p = Path(str(af2_path))
                if p.exists():
                    pae = np.load(str(p))
                    # Transpose from [target|binder] to [binder|target]
                    L_t = pae.shape[0] - int(L_b)
                    if L_t > 0:
                        pae = np.block(
                            [
                                [pae[L_t:, L_t:], pae[L_t:, :L_t]],
                                [pae[:L_t, L_t:], pae[:L_t, :L_t]],
                            ]
                        )
                    af2_pae_data[seq] = pae
                    loaded_any = True
            except Exception:
                pass

        if loaded_any:
            sequences.append(seq)
            count += 1

    return sequences, af2_pae_data, boltz_pae_data, binder_lengths


# ---------------------------------------------------------------------------
# Radar chart
# ---------------------------------------------------------------------------


def plot_radar_chart(
    summary: dict,
    metrics: list[str] | None = None,
) -> Figure:
    """Radar chart comparing per-tool mean z-scores.

    Args:
        summary: {tool: {metric: {mean, std, ...}}} from compute_statistics.
        metrics: Metrics to include. Defaults to the 8 standardised ensemble metrics.
    """
    if metrics is None:
        metrics = [
            "iptm",
            "ipae",
            "pae_bt",
            "pae_tb",
            "pae_bb",
            "plddt_binder_mean",
            "plddt_binder_min",
            "plddt_target_mean",
        ]

    tools = list(summary.keys())
    n_metrics = len(metrics)
    if n_metrics == 0 or not tools:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No data for radar chart", ha="center", va="center")
        return fig

    angles = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))

    # Collect raw means per tool per metric, then z-score across tools
    raw = {tool: [] for tool in tools}
    for tool in tools:
        tool_data = summary.get(tool, {})
        for m in metrics:
            mean = tool_data.get(m, {}).get("mean", 0.0)
            raw[tool].append(float(mean) if mean is not None else 0.0)

    # z-score each metric across tools
    raw_array = np.array([raw[t] for t in tools])  # shape (n_tools, n_metrics)
    col_mean = raw_array.mean(axis=0)
    col_std = raw_array.std(axis=0)
    col_std[col_std == 0] = 1.0  # avoid division by zero
    z_array = (raw_array - col_mean) / col_std

    for ti, tool in enumerate(tools):
        values = z_array[ti].tolist()
        values += values[:1]
        colour = TOOL_COLOURS.get(tool, TOOL_COLOURS["unknown"])
        ax.plot(angles, values, color=colour, linewidth=2, label=tool)
        ax.fill(angles, values, color=colour, alpha=0.15)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(metrics, size=9)
    ax.set_title("Tool comparison (mean z-scores)", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# AF2 vs Boltz2 scatter
# ---------------------------------------------------------------------------


def plot_af2_vs_boltz2_scatter(
    df: pd.DataFrame,
    metric_pairs: list[tuple[str, str]] | None = None,
) -> Figure:
    """Scatter plots of AF2 vs Boltz2 values for common metrics.

    Args:
        df:           Merged DataFrame with af2_* and boltz_* columns.
        metric_pairs: List of (boltz_col, af2_col) pairs. Defaults to iptm and ipae.
    """
    if metric_pairs is None:
        metric_pairs = [
            ("ipsae_min", "af2_ipsae_min"),  # primary — most diagnostic
            ("iptm", "af2_iptm"),
        ]

    n = len(metric_pairs)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), squeeze=False)

    for i, (b_col, a_col) in enumerate(metric_pairs):
        ax = axes[0][i]
        if b_col not in df.columns or a_col not in df.columns:
            ax.text(0.5, 0.5, f"Missing:\n{b_col}\n{a_col}", ha="center", va="center", transform=ax.transAxes)
            continue

        b_vals = pd.to_numeric(df[b_col], errors="coerce")
        a_vals = pd.to_numeric(df[a_col], errors="coerce")
        mask = b_vals.notna() & a_vals.notna()

        if "source_tool" in df.columns:
            for tool, grp in df[mask].groupby("source_tool"):
                colour = TOOL_COLOURS.get(tool, TOOL_COLOURS["unknown"])
                ax.scatter(b_vals[grp.index], a_vals[grp.index], color=colour, alpha=0.7, s=30, label=tool)
        else:
            ax.scatter(b_vals[mask], a_vals[mask], alpha=0.7, s=30)

        # Identity line
        if mask.sum() == 0:
            ax.text(0.5, 0.5, "No valid data points", ha="center", va="center", transform=ax.transAxes)
            continue

        lo = min(b_vals[mask].min(), a_vals[mask].min()) * 0.95
        hi = max(b_vals[mask].max(), a_vals[mask].max()) * 1.05
        ax.plot([lo, hi], [lo, hi], "k--", linewidth=1, alpha=0.4)

        # Pearson r — prominent boxed annotation
        if mask.sum() > 2:
            r = np.corrcoef(b_vals[mask], a_vals[mask])[0, 1]
            ax.text(
                0.05,
                0.95,
                f"r = {r:.3f}",
                transform=ax.transAxes,
                va="top",
                fontsize=11,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#fff9c4", edgecolor="#f57f17", linewidth=1.5),
            )

        # Axis labels: use METRIC_META if available
        def _axis_label(col: str, role: str) -> str:
            meta = METRIC_META.get(col)
            if meta:
                lbl, unit, arrow = meta
                parts = [lbl]
                if unit:
                    parts.append(f"({unit})")
                if arrow:
                    parts.append(arrow)
                return f"{role}: " + " ".join(parts)
            return f"{role}: {col}"

        ax.set_xlabel(_axis_label(b_col, "Boltz-2"), fontsize=9)
        ax.set_ylabel(_axis_label(a_col, "AF2"), fontsize=9)
        b_meta = METRIC_META.get(b_col)
        title = b_meta[0] if b_meta else b_col.replace("_", " ")
        ax.set_title(f"{title} — Boltz-2 vs AF2", fontsize=10)
        if "source_tool" in df.columns:
            ax.legend(fontsize=7)

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Metric distribution box plots
# ---------------------------------------------------------------------------


def plot_metric_distributions(
    df: pd.DataFrame,
    metrics: list[str] | None = None,
) -> Figure:
    """Box plots of each metric grouped by source tool."""
    if metrics is None:
        metrics = [
            "iptm",
            "ipae",
            "plddt_binder_mean",
            "ipsae_min",
            "boltz_pae_ipsae_min",
            "binder_ptm",
        ]

    present = [m for m in metrics if m in df.columns]
    n = len(present)
    if n == 0:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No data", ha="center", va="center")
        return fig

    tools = sorted(df["source_tool"].dropna().unique()) if "source_tool" in df.columns else ["all"]

    fig, axes = plt.subplots(1, n, figsize=(4 * n, 5), squeeze=False)

    for i, metric in enumerate(present):
        ax = axes[0][i]
        data_per_tool = []
        labels = []
        for tool in tools:
            if "source_tool" in df.columns:
                vals = pd.to_numeric(df.loc[df["source_tool"] == tool, metric], errors="coerce").dropna()
            else:
                vals = pd.to_numeric(df[metric], errors="coerce").dropna()

            if len(vals) == 0:
                continue
            data_per_tool.append(vals.values)
            labels.append(tool)

        if not data_per_tool:
            ax.set_visible(False)
            continue

        bp = ax.boxplot(data_per_tool, patch_artist=True, tick_labels=labels)
        for patch, tool in zip(bp["boxes"], labels):
            patch.set_facecolor(TOOL_COLOURS.get(tool, TOOL_COLOURS["unknown"]))
            patch.set_alpha(0.7)

        # Build y-axis label from METRIC_META
        meta = METRIC_META.get(metric)
        if meta:
            label_str, unit_str, arrow = meta
            ylabel_parts = [label_str]
            if unit_str:
                ylabel_parts.append(f"({unit_str})")
            if arrow:
                ylabel_parts.append(arrow)
            ax.set_ylabel(" ".join(ylabel_parts), fontsize=8)
        else:
            ax.set_ylabel(metric, fontsize=8)

        ax.set_title(metric, fontsize=9)
        ax.tick_params(axis="x", rotation=20, labelsize=8)

    fig.suptitle("Metric distributions by tool", y=1.02)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Utility: figure → base64 PNG string for HTML embedding
# ---------------------------------------------------------------------------


def fig_to_base64(fig: Figure) -> str:
    """Encode a matplotlib figure as a base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def save_figure(fig: Figure, path: str | Path) -> None:
    """Save a figure to a file (PNG or PDF based on extension)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(path), bbox_inches="tight", dpi=150)
    plt.close(fig)
