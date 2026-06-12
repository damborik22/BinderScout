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
    "boltzgen_nano": "#FF9800",  # orange (nano sub-variant)
    "boltzgen_protein": "#EF6C00",  # deep orange (protein sub-variant)
    "mosaic": "#4CAF50",  # green
    "pxdesign": "#9C27B0",  # purple
    "proteina_complexa": "#795548",  # brown
    "rfd3": "#D84315",  # deep-orange
    "protein_hunter": "#00838F",  # teal-cyan
    "unknown": "#9E9E9E",  # grey
}

# Display names for tools
_TOOL_DISPLAY = {
    "mosaic": "Mosaic",
    "pxdesign": "PXDesign",
    "boltzgen": "BoltzGen",
    "boltzgen_nano": "BoltzGen (nano)",
    "boltzgen_protein": "BoltzGen (protein)",
    "bindcraft": "BindCraft",
    "proteina_complexa": "Proteina-Complexa",
    "rfd3": "RFD3",
    "protein_hunter": "Protein-Hunter",
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


_ENGINE_RADAR_METRICS: dict[str, list[tuple[str, str, str]]] = {
    # engine_key -> list of (df_col, label, direction)  direction: "↑" or "↓"
    # Column naming: boltz uses `boltz_pae_*`; protenix/af3 use `<engine>_*` (no _pae_).
    "boltz": [
        ("boltz_pae_ipsae_min", "ipSAE_min", "↑"),
        ("boltz_pae_iptm", "ipTM", "↑"),
        ("plddt_binder_mean", "pLDDT binder", "↑"),
        ("binder_ptm", "binder pTM", "↑"),
        ("boltz_pae_bt_mean", "PAE b→t", "↓"),
        ("boltz_pae_tb_mean", "PAE t→b", "↓"),
    ],
    "protenix": [
        ("protenix_ipsae_min", "ipSAE_min", "↑"),
        ("protenix_iptm", "ipTM", "↑"),
        ("protenix_plddt_binder_mean", "pLDDT binder", "↑"),
        ("protenix_pae_bt", "PAE b→t", "↓"),
        ("protenix_pae_tb", "PAE t→b", "↓"),
    ],
    "af3": [
        ("af3_ipsae_min", "ipSAE_min", "↑"),
        ("af3_iptm", "ipTM", "↑"),
        ("af3_plddt_binder_mean", "pLDDT binder", "↑"),
        ("af3_pae_bt", "PAE b→t", "↓"),
        ("af3_pae_tb", "PAE t→b", "↓"),
    ],
}

# Canonical per-engine ipsae column for the radar's tool-top-N ranking.
# Mirrors scoring._ENGINE_IPSAE_COLS but kept inline so plots.py has no
# cross-package import.
_ENGINE_RANK_COLS: dict[str, str] = {
    "boltz": "boltz_pae_ipsae_min",
    "protenix": "protenix_ipsae_min",
    "af3": "af3_ipsae_min",
}

_ENGINE_DISPLAY = {"boltz": "Boltz-2", "protenix": "Protenix", "af3": "AF3"}


def plot_radar_per_engine(df: pd.DataFrame, top_n: int = 10) -> Figure:
    """One radar per available refold engine, each showing per-tool **top-N** mean
    (so the chart reflects "tool at its best", not full-pool average).

    Per-engine ranking column = `<engine>_pae_ipsae_min`. Engines whose ipSAE
    column isn't present in *df* are skipped entirely. Tools with fewer than 3
    designs in their engine-specific top-N (after dropna) are excluded from
    that engine's panel.
    """
    if "source_tool" not in df.columns:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No source_tool column — radar skipped", ha="center", va="center")
        return fig

    # Which engines actually have data?
    active_engines = []
    for e, metrics in _ENGINE_RADAR_METRICS.items():
        rank_col = _ENGINE_RANK_COLS.get(e)
        if (
            rank_col
            and rank_col in df.columns
            and pd.to_numeric(df[rank_col], errors="coerce").notna().any()
            and any(m[0] in df.columns for m in metrics)
        ):
            active_engines.append(e)
    if not active_engines:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No per-engine ipSAE columns — radar skipped", ha="center", va="center")
        return fig

    n_panels = len(active_engines)
    fig, axes = plt.subplots(
        1,
        n_panels,
        figsize=(7 * n_panels, 7),
        subplot_kw=dict(polar=True),
    )
    if n_panels == 1:
        axes = [axes]

    all_legend_handles: dict[str, object] = {}
    for ax, engine in zip(axes, active_engines):
        rank_col = _ENGINE_RANK_COLS[engine]
        # per-tool top-N by this engine's ipsae_min
        per_tool_top: dict[str, pd.DataFrame] = {}
        for tool, gdf in df.groupby("source_tool"):
            vals = pd.to_numeric(gdf[rank_col], errors="coerce")
            top = gdf.assign(_rk=vals).dropna(subset=["_rk"]).nlargest(top_n, "_rk").drop(columns=["_rk"])
            if len(top) >= 3:
                per_tool_top[str(tool)] = top
        tools = sorted(per_tool_top.keys())
        if not tools:
            ax.text(0.5, 0.5, f"No data for {_ENGINE_DISPLAY[engine]}", ha="center", va="center")
            ax.set_title(_ENGINE_DISPLAY[engine])
            continue

        # Collect per-engine metrics, restrict to columns actually present
        metric_specs = [m for m in _ENGINE_RADAR_METRICS[engine] if m[0] in df.columns]
        n_metrics = len(metric_specs)
        angles = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist() + [0.0]

        # tool x metric mean array
        raw_array = np.array(
            [[pd.to_numeric(per_tool_top[t][col], errors="coerce").mean() for col, _, _ in metric_specs] for t in tools]
        )
        # z-score across tools per metric (column-wise)
        col_mean = np.nanmean(raw_array, axis=0)
        col_std = np.nanstd(raw_array, axis=0)
        col_std[col_std == 0] = 1.0
        z_array = (raw_array - col_mean) / col_std
        # Flip "lower is better" so outward = better for all
        for mi, (_, _, direction) in enumerate(metric_specs):
            if direction == "↓":
                z_array[:, mi] *= -1
        z_array = np.nan_to_num(z_array, nan=0.0)

        for ti, tool in enumerate(tools):
            values = z_array[ti].tolist() + [z_array[ti, 0]]
            colour = TOOL_COLOURS.get(tool, TOOL_COLOURS["unknown"])
            (line,) = ax.plot(angles, values, color=colour, linewidth=2, label=_tool_display(tool))
            ax.fill(angles, values, color=colour, alpha=0.12)
            all_legend_handles.setdefault(tool, line)

        labels = [lbl if d == "↑" else f"{lbl} (inv)" for _, lbl, d in metric_specs]
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, size=8)
        ax.set_title(f"{_ENGINE_DISPLAY[engine]} — top-{top_n} per tool", pad=14)

    # Single shared legend below
    if all_legend_handles:
        fig.legend(
            handles=list(all_legend_handles.values()),
            labels=list(all_legend_handles.keys()),
            loc="lower center",
            ncol=min(len(all_legend_handles), 8),
            bbox_to_anchor=(0.5, -0.02),
            frameon=False,
        )
    fig.suptitle("Per-tool radar (outward = better; z-scored within engine)", y=1.02)
    fig.tight_layout()
    return fig


def plot_radar_per_engine_uniform_selection(
    df: pd.DataFrame,
    primary_engine: str = "af3",
    top_n: int = 10,
) -> Figure:
    """Per-engine radar where every panel shows the SAME per-tool top-N selection,
    chosen by the evaluator's **primary refold rank** (``<primary_engine>_pae_ipsae_min``
    or fallback to ``adaptyv_rank``). Useful to see engine *agreement* on the same
    designs the evaluator promoted, rather than each engine's own "favorites".
    """
    if "source_tool" not in df.columns:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No source_tool column — radar skipped", ha="center", va="center")
        return fig

    # Pick the per-tool top-N ONCE, using the primary engine's column
    pri_col = _ENGINE_RANK_COLS.get(primary_engine, "boltz_pae_ipsae_min")
    fallback_col = "adaptyv_rank"
    per_tool_top: dict[str, pd.DataFrame] = {}
    for tool, gdf in df.groupby("source_tool"):
        if pri_col in gdf.columns and pd.to_numeric(gdf[pri_col], errors="coerce").notna().any():
            ranked = (
                gdf.assign(_rk=pd.to_numeric(gdf[pri_col], errors="coerce"))
                .dropna(subset=["_rk"])
                .nlargest(top_n, "_rk")
                .drop(columns=["_rk"])
            )
        elif fallback_col in gdf.columns:
            ranked = (
                gdf.assign(_rk=pd.to_numeric(gdf[fallback_col], errors="coerce"))
                .dropna(subset=["_rk"])
                .nsmallest(top_n, "_rk")
                .drop(columns=["_rk"])
            )
        else:
            ranked = gdf.head(top_n)
        if len(ranked) >= 3:
            per_tool_top[str(tool)] = ranked

    if not per_tool_top:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "Not enough data per tool — radar skipped", ha="center", va="center")
        return fig

    active_engines = [e for e in _ENGINE_RADAR_METRICS if any(m[0] in df.columns for m in _ENGINE_RADAR_METRICS[e])]
    if not active_engines:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No engine metric columns present", ha="center", va="center")
        return fig

    n_panels = len(active_engines)
    fig, axes = plt.subplots(1, n_panels, figsize=(7 * n_panels, 7), subplot_kw=dict(polar=True))
    if n_panels == 1:
        axes = [axes]

    pri_label = _ENGINE_DISPLAY.get(primary_engine, primary_engine.upper())
    tools = sorted(per_tool_top.keys())
    all_legend: dict[str, object] = {}
    for ax, engine in zip(axes, active_engines):
        metric_specs = [m for m in _ENGINE_RADAR_METRICS[engine] if m[0] in df.columns]
        n_metrics = len(metric_specs)
        angles = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist() + [0.0]
        raw_array = np.array(
            [[pd.to_numeric(per_tool_top[t][col], errors="coerce").mean() for col, _, _ in metric_specs] for t in tools]
        )
        col_mean = np.nanmean(raw_array, axis=0)
        col_std = np.nanstd(raw_array, axis=0)
        col_std[col_std == 0] = 1.0
        z_array = (raw_array - col_mean) / col_std
        for mi, (_, _, direction) in enumerate(metric_specs):
            if direction == "↓":
                z_array[:, mi] *= -1
        z_array = np.nan_to_num(z_array, nan=0.0)
        for ti, tool in enumerate(tools):
            values = z_array[ti].tolist() + [z_array[ti, 0]]
            colour = TOOL_COLOURS.get(tool, TOOL_COLOURS["unknown"])
            (line,) = ax.plot(angles, values, color=colour, linewidth=2, label=_tool_display(tool))
            ax.fill(angles, values, color=colour, alpha=0.12)
            all_legend.setdefault(tool, line)
        labels = [lbl if d == "↑" else f"{lbl} (inv)" for _, lbl, d in metric_specs]
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(labels, size=8)
        ax.set_title(f"{_ENGINE_DISPLAY[engine]} metrics on {pri_label}-top-{top_n}", pad=14)

    if all_legend:
        fig.legend(
            handles=list(all_legend.values()),
            labels=list(all_legend.keys()),
            loc="lower center",
            ncol=min(len(all_legend), 8),
            bbox_to_anchor=(0.5, -0.02),
            frameon=False,
        )
    fig.suptitle(
        f"Per-tool radar — fixed selection: top-{top_n} per tool by {pri_label} refold rank (z-scored within each engine)",
        y=1.02,
    )
    fig.tight_layout()
    return fig


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


# Engine iPTM columns for the two-stage radar/scatter (uses whichever are present,
# in this priority order). Mirrors scoring._ENGINE_IPTM_COLS.
_IPTM_RADAR_SPOKES: list[tuple[str, str]] = [
    ("boltz_pae_iptm", "Boltz-2 iPTM"),
    ("af3_pae_iptm", "AF3 iPTM"),
    ("esmfold2_pae_iptm", "ESMFold2 iPTM"),
    ("protenix_pae_iptm", "Protenix iPTM"),
]


def plot_radar_iptm(df: pd.DataFrame, top_n: int = 10) -> Figure:
    """Per-tool radar over the engine iPTMs — the two-stage view.

    Spokes = each available engine's iPTM (raw 0–1, NOT z-scored). One polygon
    per tool = mean iPTM over that tool's top-N designs (by ``consensus_iptm``).
    A large, balanced polygon = engines agree (high mean → ranks high in the
    two-stage mean step); a spiky/lopsided polygon = one engine confident and
    the others not (passes the max screen but low mean).
    """
    if "source_tool" not in df.columns:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No source_tool — radar skipped", ha="center", va="center")
        return fig
    spokes = [
        (c, lbl)
        for c, lbl in _IPTM_RADAR_SPOKES
        if c in df.columns and pd.to_numeric(df[c], errors="coerce").notna().any()
    ]
    if len(spokes) < 2:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "<2 engine iPTM columns — radar skipped", ha="center", va="center")
        return fig

    cols = [c for c, _ in spokes]
    rank_col = "consensus_iptm" if "consensus_iptm" in df.columns else None
    angles = np.linspace(0, 2 * np.pi, len(spokes), endpoint=False).tolist() + [0.0]
    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))

    handles: dict[str, object] = {}
    for tool, gdf in df.groupby("source_tool"):
        sub = gdf
        if rank_col:
            sub = (
                gdf.assign(_r=pd.to_numeric(gdf[rank_col], errors="coerce")).dropna(subset=["_r"]).nlargest(top_n, "_r")
            )
        if len(sub) == 0:
            continue
        means = [pd.to_numeric(sub[c], errors="coerce").mean() for c in cols]
        if not np.isfinite(np.nanmean(means)):
            continue
        vals = means + [means[0]]
        colour = TOOL_COLOURS.get(str(tool), TOOL_COLOURS["unknown"])
        (line,) = ax.plot(angles, vals, color=colour, linewidth=2, label=_tool_display(str(tool)))
        ax.fill(angles, vals, color=colour, alpha=0.12)
        handles.setdefault(str(tool), line)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([lbl for _, lbl in spokes], size=9)
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.2", "0.4", "0.6", "0.8", "1.0"], size=7)
    ax.set_title(f"Per-tool engine-iPTM radar — top-{top_n} per tool (raw iPTM; outward = higher)", pad=16)
    if handles:
        fig.legend(
            handles=list(handles.values()),
            labels=list(handles.keys()),
            loc="lower center",
            ncol=min(len(handles), 8),
            bbox_to_anchor=(0.5, -0.04),
            frameon=False,
        )
    fig.tight_layout()
    return fig


def plot_max_vs_mean_iptm(df: pd.DataFrame, label_n: int = 20) -> Figure:
    """Two-stage signature scatter: max engine iPTM (screen) vs mean engine iPTM (rank).

    x = ``consensus_iptm`` (max, the Stage-1 screen), y = ``consensus_iptm_mean``
    (the Stage-2 re-rank). The dashed y=x line is the upper bound (max ≥ mean) —
    vertical distance below it = engine disagreement. The dotted vertical line is
    the max-screen threshold (top 50%). Colour by tool; top designs are labelled
    with their rank. Top-right = strong, agreed-upon binders.
    """
    fig, ax = plt.subplots(figsize=(8, 7))
    if "consensus_iptm" not in df.columns or "consensus_iptm_mean" not in df.columns:
        ax.text(0.5, 0.5, "consensus iptm columns missing — scatter skipped", ha="center", va="center")
        return fig
    x = pd.to_numeric(df["consensus_iptm"], errors="coerce")
    y = pd.to_numeric(df["consensus_iptm_mean"], errors="coerce")
    m = x.notna() & y.notna()
    d = df[m].copy()
    d["_x"], d["_y"] = x[m], y[m]
    tools = sorted(d["source_tool"].dropna().unique()) if "source_tool" in d.columns else ["all"]

    ax.plot([0, 1], [0, 1], ls="--", color="#888", lw=1, zorder=0)
    for tool in tools:
        sel = (d["source_tool"] == tool) if "source_tool" in d.columns else slice(None)
        ax.scatter(
            d.loc[sel, "_x"],
            d.loc[sel, "_y"],
            s=28,
            alpha=0.72,
            color=TOOL_COLOURS.get(str(tool), TOOL_COLOURS["unknown"]),
            label=_tool_display(str(tool)),
            edgecolors="none",
        )
    if "passes_max_screen" in d.columns and d["passes_max_screen"].any():
        thr = pd.to_numeric(d.loc[d["passes_max_screen"], "consensus_iptm"], errors="coerce").min()
        ax.axvline(thr, ls=":", color="#c62828", lw=1.5)
        ax.text(thr, 0.02, f" max-screen ≥ {thr:.3f} (top 50%)", color="#c62828", fontsize=8, rotation=90, va="bottom")

    if "active_rank" in d.columns:
        topd = d.dropna(subset=["active_rank"]).nsmallest(label_n, "active_rank")
    else:
        topd = d.nlargest(label_n, "_x")
    for _, r in topd.iterrows():
        lab = str(int(r["active_rank"])) if "active_rank" in r and pd.notna(r.get("active_rank")) else ""
        ax.annotate(lab, (r["_x"], r["_y"]), fontsize=7, xytext=(3, 3), textcoords="offset points")

    ax.set_xlabel("max engine iPTM = consensus_iptm   (Stage-1 screen →)")
    ax.set_ylabel("mean engine iPTM = consensus_iptm_mean   (Stage-2 rank ↑)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Two-stage selection: max-screen (x) → mean-rank (y); top-right = best", fontsize=10)
    ax.legend(fontsize=7, loc="upper left", frameon=False, ncol=2)
    fig.tight_layout()
    return fig


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
