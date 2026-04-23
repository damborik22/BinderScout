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
    "proteina_complexa": "#795548",  # brown
    "rfaa": "#C62828",  # red
    "unknown": "#9E9E9E",  # grey
}

# Display names for tools
_TOOL_DISPLAY = {
    "mosaic": "Mosaic",
    "pxdesign": "PXDesign",
    "boltzgen": "BoltzGen",
    "bindcraft": "BindCraft",
    "proteina_complexa": "Proteina-Complexa",
    "rfaa": "RFAA",
}


def _tool_display(name: str) -> str:
    """Return the display name for a tool, defaulting to the original."""
    return _TOOL_DISPLAY.get(name, name)


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
    "iptm": ("ipTM", "[0–1]", "↑"),
    "boltz_pae_iptm": ("Boltz ipTM (PAE)", "[0–1]", "↑"),
    "binder_ptm": ("Binder pTM", "[0–1]", "↑"),
    "plddt_binder_mean": ("pLDDT binder (mean)", "[0–1]", "↑"),
    "plddt_binder_min": ("pLDDT binder (min)", "[0–1]", "↑"),
    "plddt_target_mean": ("pLDDT target (mean)", "[0–1]", "↑"),
    "ipae": ("ipAE", "Å", "↓"),
    "pae_bt": ("PAE (B→T)", "Å", "↓"),
    "pae_tb": ("PAE (T→B)", "Å", "↓"),
    "pae_bb": ("PAE (intra-B)", "Å", "↓"),
    "agreement_count": ("Agreement", "", "↑"),
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
        matplotlib.patches.Patch(color=c, label=_tool_display(t))
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
    boltz_pae_data: dict[str, np.ndarray],
    binder_lengths: dict[str, int],
    max_binders: int = 6,
) -> Figure:
    """Boltz-2 PAE heatmaps for the top binders.

    Additional engines (Protenix on x86, AF3 on aarch64) will be added as
    extra columns in later refactor parts.
    """
    seqs = [s for s in sequences if s in boltz_pae_data][:max_binders]
    n = len(seqs)
    if n == 0:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No PAE data available", ha="center", va="center")
        return fig

    fig, axes = plt.subplots(n, 1, figsize=(6, 3 * n), squeeze=False)

    for row_i, seq in enumerate(seqs):
        L_b = binder_lengths.get(seq, 0)
        ax = axes[row_i][0]
        pae = np.array(boltz_pae_data[seq])
        im = ax.imshow(pae, vmin=0, vmax=30, cmap="bwr", aspect="auto")
        if L_b > 0 and L_b < pae.shape[0]:
            ax.axhline(L_b - 0.5, color="white", linewidth=1)
            ax.axvline(L_b - 0.5, color="white", linewidth=1)
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="PAE (Å)")

        ax.set_title(f"Boltz-2 — seq {row_i + 1}")
        ax.set_xlabel("Residue j")
        ax.set_ylabel("Residue i")

    fig.suptitle("PAE heatmaps (binder | target ordering)", y=1.01)
    fig.tight_layout()
    return fig


def load_pae_data_from_df(
    df: pd.DataFrame,
    max_binders: int = 5,
) -> tuple[list[str], dict[str, np.ndarray], dict[str, int]]:
    """Load Boltz-2 PAE .npy files for top-ranked binders from DataFrame file paths.

    Returns (sequences, boltz_pae_data, binder_lengths).
    """
    boltz_pae_data: dict[str, np.ndarray] = {}
    binder_lengths: dict[str, int] = {}
    sequences: list[str] = []

    count = 0
    for _, row in df.iterrows():
        if count >= max_binders:
            break
        seq = row.get("sequence", "")
        if not seq or seq in boltz_pae_data:
            continue

        L_b = row.get("binder_length")
        if pd.isna(L_b):
            L_b = len(seq)
        binder_lengths[seq] = int(L_b)

        # Load Boltz-2 PAE (binder|target ordering)
        boltz_path = row.get("boltz_pae_file")
        if boltz_path and not pd.isna(boltz_path):
            try:
                p = Path(str(boltz_path))
                if p.exists():
                    boltz_pae_data[seq] = np.load(str(p))
                    sequences.append(seq)
                    count += 1
            except Exception:
                pass

    return sequences, boltz_pae_data, binder_lengths


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

    # z-score each metric across tools, then flip "lower is better" metrics
    # so that outward from center always means better
    raw_array = np.array([raw[t] for t in tools])  # shape (n_tools, n_metrics)
    col_mean = raw_array.mean(axis=0)
    col_std = raw_array.std(axis=0)
    col_std[col_std == 0] = 1.0  # avoid division by zero
    z_array = (raw_array - col_mean) / col_std

    # Negate "lower is better" metrics (↓) so outward = better for all
    for mi, m in enumerate(metrics):
        meta = METRIC_META.get(m)
        if meta and meta[2] == "↓":
            z_array[:, mi] *= -1

    for ti, tool in enumerate(tools):
        values = z_array[ti].tolist()
        values += values[:1]
        colour = TOOL_COLOURS.get(tool, TOOL_COLOURS["unknown"])
        ax.plot(angles, values, color=colour, linewidth=2, label=_tool_display(tool))
        ax.fill(angles, values, color=colour, alpha=0.15)

    # Use human-readable labels, mark inverted metrics
    tick_labels = []
    for m in metrics:
        meta = METRIC_META.get(m)
        if meta:
            label = meta[0]
            if meta[2] == "↓":
                label += " (inv)"
        else:
            label = m
        tick_labels.append(label)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(tick_labels, size=9)
    ax.set_title("Tool comparison (outward = better)", pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
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
            labels.append(_tool_display(tool))

        if not data_per_tool:
            ax.set_visible(False)
            continue

        bp = ax.boxplot(data_per_tool, patch_artist=True, tick_labels=labels)
        for patch, tool in zip(bp["boxes"], tools[: len(data_per_tool)]):
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
