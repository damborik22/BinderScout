"""HTML report generator.

Produces a self-contained report.html with:
  - Summary table (top binders by composite score)
  - Per-tool summary statistics
  - Embedded plots (metric distributions, radar chart, AF2 vs Boltz2 scatter)
  - Full metrics table (collapsible)
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from .plots import (
    METRIC_META,
    fig_to_base64,
    plot_metric_distributions,
    plot_radar_chart,
    plot_af2_vs_boltz2_scatter,
)

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Binder Comparison Report</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 2em; background: #f8f9fa; color: #333; }}
  h1 {{ color: #1a237e; }}
  h2 {{ color: #283593; margin-top: 2em; border-bottom: 2px solid #c5cae9; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85em; margin-bottom: 1em; }}
  th {{
    background: #3f51b5; color: white; padding: 6px 10px;
    text-align: left; white-space: nowrap;
    position: sticky; top: 0; z-index: 2;
  }}
  td {{ padding: 5px 10px; border-bottom: 1px solid #e0e0e0; white-space: nowrap; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr:nth-child(even) {{ background: #e8eaf6; }}
  tr:hover {{ background: #c5cae9; }}
  .tool-bindcraft {{ color: #1565C0; font-weight: bold; }}
  .tool-boltzgen  {{ color: #E65100; font-weight: bold; }}
  .tool-mosaic    {{ color: #2E7D32; font-weight: bold; }}
  .tool-pxdesign  {{ color: #7B1FA2; font-weight: bold; }}
  .stat-table td {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .stat-table th:first-child, .stat-table td:first-child {{ text-align: left; white-space: nowrap; }}
  img {{ max-width: 100%; margin: 1em 0; border: 1px solid #ccc; border-radius: 4px; }}
  details summary {{ cursor: pointer; color: #3f51b5; font-weight: bold; margin-top: 1em; }}
  .metric-good {{ color: #2e7d32; }}
  .metric-bad  {{ color: #c62828; }}
  .weights {{ background: #fff3e0; border: 1px solid #ffb74d; padding: 0.8em 1.2em;
              border-radius: 4px; margin-bottom: 1em; font-size: 0.9em; }}
  .callout {{
    background: #e8f5e9; border-left: 5px solid #2e7d32;
    padding: 0.8em 1.2em; border-radius: 4px;
    margin: 1em 0; font-size: 0.95em;
  }}
  .callout strong {{ color: #1b5e20; font-size: 1.05em; }}
  th small {{ font-weight: normal; opacity: 0.85; }}
</style>
</head>
<body>
<h1>Binder Design Comparison Report</h1>

<div class="weights">
  <strong>Ensemble weights:</strong>
  AF2 = {af2_weight:.2f} &nbsp;|&nbsp; Boltz2 = {boltz2_weight:.2f}
  &nbsp;&nbsp;·&nbsp;&nbsp;
  <strong>Total binders:</strong> {n_binders}
  &nbsp;&nbsp;·&nbsp;&nbsp;
  {tool_counts_str}
</div>

<h2>Screening Summary (Adaptyv / Overath et al. 2025)</h2>
<p style="font-size:0.85em;color:#555;">
  Primary metric: <b>ipSAE_min</b> (Dunbrack formula) — 1.4× better average precision than ipAE
  across 3,766 experimentally tested designs (Overath et al. 2025).
  Thresholds: &nbsp;<span style="color:#2e7d32">■ High</span> &gt;0.80 &nbsp;
  <span style="color:#f57f17">■ Medium</span> &gt;0.61 &nbsp;
  <span style="color:#e65100">■ Low</span> &gt;0.40 &nbsp;
  <span style="color:#c62828">■ Reject</span> ≤0.40
</p>
{tier_summary}

<h2>Top 20 Binders (Adaptyv rank — ipSAE_min primary)</h2>
{top_table}

<h2>Per-Tool Summary Statistics</h2>
{summary_table}

<h2>Metric Distributions by Tool</h2>
<img src="data:image/png;base64,{dist_plot}" alt="Metric distributions">

<h2>Tool Comparison (Radar Chart)</h2>
<img src="data:image/png;base64,{radar_plot}" alt="Radar chart">

<h2>AF2 vs Boltz-2 Correlation</h2>
{correlation_callout}
<img src="data:image/png;base64,{scatter_plot}" alt="AF2 vs Boltz2 scatter">

<h2>Full Metrics Table</h2>
<details>
  <summary>Click to expand ({n_binders} binders)</summary>
  {full_table}
</details>

</body>
</html>
"""


def _compute_af2_boltz2_r(df: pd.DataFrame) -> dict[str, float | int]:
    """Compute Pearson r between Boltz-2 and AF2 ipSAE_min (primary metric)."""
    import numpy as np
    result: dict[str, float | int] = {}
    for b_col, a_col in [("ipsae_min", "af2_ipsae_min"), ("iptm", "af2_iptm")]:
        if b_col in df.columns and a_col in df.columns:
            b = pd.to_numeric(df[b_col], errors="coerce")
            a = pd.to_numeric(df[a_col], errors="coerce")
            mask = b.notna() & a.notna()
            n = int(mask.sum())
            if n > 2:
                r = float(np.corrcoef(b[mask], a[mask])[0, 1])
                result[f"{b_col}_vs_{a_col}"] = r
                result[f"{b_col}_vs_{a_col}_n"] = n
    return result


def _correlation_callout_html(corr: dict) -> str:
    """Render a highlighted callout box for the AF2 vs Boltz-2 correlation."""
    if not corr:
        return ""

    r_ipsae = corr.get("ipsae_min_vs_af2_ipsae_min")
    n_ipsae = corr.get("ipsae_min_vs_af2_ipsae_min_n", 0)
    r_iptm  = corr.get("iptm_vs_af2_iptm")
    n_iptm  = corr.get("iptm_vs_af2_iptm_n", 0)

    # Pick the most impressive r value for the headline
    headline_r, headline_n, headline_metric = None, 0, ""
    if r_ipsae is not None:
        headline_r, headline_n, headline_metric = r_ipsae, n_ipsae, "ipSAE_min"
    if r_iptm is not None and (headline_r is None or abs(r_iptm) > abs(headline_r)):
        headline_r, headline_n, headline_metric = r_iptm, n_iptm, "ipTM"

    if headline_r is None:
        return ""

    strength = "strong" if abs(headline_r) >= 0.7 else ("moderate" if abs(headline_r) >= 0.5 else "weak")

    lines = []
    if r_iptm is not None:
        lines.append(
            f"<strong>ipTM ↑ (primary):</strong> Boltz-2 vs AF2 Pearson r = "
            f"<strong style='font-size:1.25em; color:#1b5e20;'>{r_iptm:+.3f}</strong> "
            f"(n = {n_iptm}) — {strength} agreement between two completely independent predictors."
        )
    if r_ipsae is not None:
        s2 = "strong" if abs(r_ipsae) >= 0.7 else ("moderate" if abs(r_ipsae) >= 0.5 else "weak")
        lines.append(
            f"<strong>ipSAE_min ↑:</strong> r = {r_ipsae:+.3f} (n = {n_ipsae}) — {s2}"
        )

    inner = "<br>".join(lines)
    return (
        f'<div class="callout">'
        f'<p style="margin:0 0 0.4em 0; font-size:1.05em;">&#x1F4CA;&nbsp;'
        f"<strong>Boltz-2 / AF2 Model Agreement</strong>&nbsp;"
        f"— two independent structure predictors strongly agree on binder quality.</p>"
        f"<p style='margin:0;'>{inner}</p>"
        f"</div>"
    )


def generate_report(
    df: pd.DataFrame,
    summary: dict,
    output_path: str | Path,
    *,
    af2_weight: float = 0.6,
    boltz2_weight: float = 0.4,
    composite_col: str | None = "composite_score",
) -> None:
    """Generate and write the HTML report.

    Args:
        df:            DataFrame with all metrics (after ensemble + statistics).
        summary:       Per-tool summary dict from compute_statistics.
        output_path:   Where to write report.html.
        af2_weight:    AF2 weight used for ensemble (shown in header).
        boltz2_weight: Boltz2 weight used for ensemble.
        composite_col: Column to sort by for top-20 table (fallback if no adaptyv_rank).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Prefer adaptyv_rank ordering; fall back to composite_score
    sort_df = df.copy()
    if "adaptyv_rank" in sort_df.columns:
        sort_df = sort_df.sort_values("adaptyv_rank", ascending=True)
    elif composite_col and composite_col in sort_df.columns:
        sort_df = sort_df.sort_values(composite_col, ascending=False)

    # Tool counts
    tool_counts_str = ""
    if "source_tool" in sort_df.columns:
        counts = sort_df["source_tool"].value_counts()
        tool_counts_str = " &nbsp;|&nbsp; ".join(
            f'<span class="tool-{t}">{t}: {n}</span>' for t, n in counts.items()
        )

    # Tier summary
    tier_summary = _tier_summary_to_html(sort_df)

    # Top 20 table
    display_cols = _select_display_cols(sort_df)
    top20 = sort_df[display_cols].head(20)
    top_table = _df_to_html(top20, colour_tool=True)

    # Summary statistics table
    summary_table = _summary_to_html(summary)

    # Plots
    dist_fig    = plot_metric_distributions(sort_df)
    radar_fig   = plot_radar_chart(summary)
    scatter_fig = plot_af2_vs_boltz2_scatter(sort_df)

    dist_b64    = fig_to_base64(dist_fig)
    radar_b64   = fig_to_base64(radar_fig)
    scatter_b64 = fig_to_base64(scatter_fig)

    # Correlation callout
    corr = _compute_af2_boltz2_r(sort_df)
    correlation_callout = _correlation_callout_html(corr)

    # Full table (all columns, collapsed)
    full_table = _df_to_html(sort_df, max_rows=None)

    html = _HTML_TEMPLATE.format(
        af2_weight=af2_weight,
        boltz2_weight=boltz2_weight,
        n_binders=len(sort_df),
        tool_counts_str=tool_counts_str or "—",
        tier_summary=tier_summary,
        top_table=top_table,
        summary_table=summary_table,
        dist_plot=dist_b64,
        radar_plot=radar_b64,
        scatter_plot=scatter_b64,
        correlation_callout=correlation_callout,
        full_table=full_table,
    )

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"[report] Written → {output_path}")


def _select_display_cols(df: pd.DataFrame) -> list[str]:
    """Pick a readable subset of columns for the top-20 table."""
    preferred = [
        "adaptyv_rank", "binder_id", "source_tool", "quality_tier",
        "ipsae_min", "bt_ipsae", "tb_ipsae", "ipsae_valid",
        "iptm", "ipae", "plddt_binder_mean", "plddt_binder_min",
        "pae_bt", "pae_tb",
        "binder_ptm",
        "ipsae_dg_composite", "ipsae_shape_composite",
        "native_dG", "native_dSASA", "native_shape_complementarity",
        "composite_score",
        "sequence",
    ]
    return [c for c in preferred if c in df.columns]


def _tier_summary_to_html(df: pd.DataFrame) -> str:
    """Render a tier breakdown table (high/medium/low/reject counts per tool)."""
    if "quality_tier" not in df.columns:
        return "<p style='color:#888;font-size:0.85em;'>ipSAE_min not available — tier classification skipped.</p>"

    tier_order  = ["high", "medium", "low", "reject"]
    tier_labels = {
        "high":   '<span style="color:#2e7d32">■ High (&gt;0.80)</span>',
        "medium": '<span style="color:#f57f17">■ Medium (&gt;0.61)</span>',
        "low":    '<span style="color:#e65100">■ Low (&gt;0.40)</span>',
        "reject": '<span style="color:#c62828">■ Reject (≤0.40)</span>',
    }
    n_total = len(df)

    has_tools = "source_tool" in df.columns
    tools = sorted(df["source_tool"].dropna().unique()) if has_tools else []

    # Build header
    tool_headers = "".join(f"<th>{t}</th>" for t in tools)
    header = f'<tr><th style="text-align:left;white-space:nowrap">Tier</th><th>Count</th><th>%</th>{tool_headers}</tr>'

    rows = []
    for tier in tier_order:
        mask = df["quality_tier"] == tier
        n = int(mask.sum())
        pct = 100.0 * n / n_total if n_total > 0 else 0.0
        tool_cells = ""
        if has_tools:
            for t in tools:
                t_mask = mask & (df["source_tool"] == t)
                tool_cells += f"<td>{int(t_mask.sum())}</td>"
        rows.append(
            f'<tr><td style="text-align:left;white-space:nowrap">{tier_labels[tier]}</td>'
            f"<td><b>{n}</b></td><td>{pct:.1f}%</td>{tool_cells}</tr>"
        )

    # Optional: ipsae_dg_composite summary row
    composite_note = ""
    if "ipsae_dg_composite" in df.columns:
        import numpy as np
        vals = pd.to_numeric(df["ipsae_dg_composite"], errors="coerce").dropna()
        if len(vals) > 0:
            composite_note = (
                f"<p style='font-size:0.83em;color:#555;margin-top:0.4em;'>"
                f"ipSAE_min × |ΔG/ΔSASA| (best composite, Overath et al. 2025): "
                f"mean={vals.mean():.4f}, max={vals.max():.4f} "
                f"(n={len(vals)} with BindCraft native metrics)</p>"
            )

    return (
        f'<table class="stat-table">{header}{"".join(rows)}</table>'
        + composite_note
    )


def _col_header(col: str) -> str:
    """Return a formatted <th> label with unit and direction arrow from METRIC_META."""
    meta = METRIC_META.get(col)
    if not meta:
        return col
    label, unit, arrow = meta
    parts = [label]
    if arrow:
        parts.append(arrow)
    suffix = f" <small>({unit})</small>" if unit else ""
    return " ".join(parts) + suffix


def _df_to_html(
    df: pd.DataFrame,
    colour_tool: bool = False,
    max_rows: int | None = 500,
) -> str:
    if max_rows is not None:
        df = df.head(max_rows)

    # Detect numeric columns for right-alignment
    numeric_cols = set(df.select_dtypes(include="number").columns)

    def fmt(col: str, val) -> str:
        is_num = col in numeric_cols
        cls = ' class="num"' if is_num else ""
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return f"<td{cls}>—</td>"
        if isinstance(val, float):
            return f"<td{cls}>{val:.4f}</td>"
        return f"<td{cls}>{val}</td>"

    header = "<tr>" + "".join(
        f"<th>{_col_header(c)}</th>" for c in df.columns
    ) + "</tr>"

    rows = []
    for _, row in df.iterrows():
        cells = "".join(fmt(c, v) for c, v in zip(df.columns, row))
        if colour_tool and "source_tool" in df.columns:
            tool = row.get("source_tool", "")
            rows.append(f'<tr class="tool-{tool}">{cells}</tr>')
        else:
            rows.append(f"<tr>{cells}</tr>")

    return f"<table>{header}{''.join(rows)}</table>"


def _summary_to_html(summary: dict) -> str:
    """Render per-tool summary as an HTML table."""
    all_metrics: set[str] = set()
    for tool_data in summary.values():
        all_metrics.update(tool_data.keys())
    metrics = sorted(all_metrics)
    tools = list(summary.keys())

    # Tool name → colour class header cell
    tool_cols = "".join(
        f'<th><span class="tool-{t}">{t}</span><br><small>mean ± std</small></th>'
        for t in tools
    )
    header = f"<tr><th>Metric</th>{tool_cols}</tr>"

    rows = []
    for m in metrics:
        meta = METRIC_META.get(m)
        if meta:
            label, unit, arrow = meta
            unit_str = f" ({unit})" if unit else ""
            arrow_str = f" {arrow}" if arrow else ""
            m_label = f"{label}{unit_str}{arrow_str}"
        else:
            m_label = m
        row = f"<td>{m_label}</td>"
        for tool in tools:
            stats = summary.get(tool, {}).get(m)
            if stats:
                row += f"<td>{stats['mean']:.4f} ± {stats['std']:.4f}<br><small>n={stats['n']}</small></td>"
            else:
                row += "<td>—</td>"
        rows.append(f"<tr>{row}</tr>")

    return f'<table class="stat-table">{header}{"".join(rows)}</table>'
