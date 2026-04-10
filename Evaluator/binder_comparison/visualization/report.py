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
)

# Display names for tools (source_tool values are lowercase internally)
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


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Binder Comparison Report</title>
<style>
  body {{ font-family: 'Segoe UI', sans-serif; margin: 2em; background: #f8f9fa; color: #333; }}
  h1 {{ color: #1a5276; }}
  h2 {{ color: #1a5276; margin-top: 2em; border-bottom: 2px solid #CFE6F6; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: auto; font-size: 0.85em; margin-bottom: 1em; }}
  th {{
    background: #1a5276; color: white; padding: 6px 8px;
    text-align: left; white-space: normal; min-width: 3em;
    position: sticky; top: 0; z-index: 2;
  }}
  td {{ padding: 5px 8px; border-bottom: 1px solid #e0e0e0; white-space: nowrap; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr:nth-child(even) {{ background: #EBF5FB; }}
  tr:hover {{ background: #CFE6F6; }}
  .tool-bindcraft          {{ color: #1565C0; font-weight: bold; }}
  .tool-boltzgen           {{ color: #E65100; font-weight: bold; }}
  .tool-mosaic             {{ color: #2E7D32; font-weight: bold; }}
  .tool-pxdesign           {{ color: #7B1FA2; font-weight: bold; }}
  .tool-proteina_complexa  {{ color: #6D4C41; font-weight: bold; }}
  .tool-rfaa               {{ color: #C62828; font-weight: bold; }}
  .stat-table td {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .stat-table th:first-child, .stat-table td:first-child {{ text-align: left; white-space: nowrap; }}
  img {{ max-width: 100%; margin: 1em 0; border: 1px solid #ccc; border-radius: 4px; }}
  details summary {{ cursor: pointer; color: #1a5276; font-weight: bold; margin-top: 1em; }}
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
  <strong>Total binders:</strong> {n_binders}
  &nbsp;&nbsp;·&nbsp;&nbsp;
  {tool_counts_str}
</div>

<p style="font-size:0.85em;color:#555;line-height:1.6;">
  <b>Methodology.</b>
  All designed binder sequences are independently refolded with <b>Boltz-2</b> (primary predictor)
  and <b>AlphaFold2</b> (cross-validation) as target–binder complexes.
  The primary ranking metric is <b>ipSAE_min</b> — the minimum of binder→target and target→binder
  interface Predicted Structural Alignment Error, computed using the
  <a href="https://github.com/DunbrackLab/IPSAE" target="_blank">DunbrackLab d0<sub>res</sub> formula</a>
  (per-residue d0, uniform 10 Å PAE cutoff for both engines).
  This metric showed 1.4× better average precision than ipAE across 3,766 experimentally tested
  designs in the <a href="https://doi.org/10.1101/2025.08.14.670059" target="_blank">Adaptyv/Overath et al. 2025</a>
  benchmark. Quality tiers and the 0.61 pass threshold follow their screening methodology.
  <b>agreement_count</b> reports how many engines (0–2) score ipSAE_min above 0.61.
  Ranking sorts by quality tier first, then agreement count, then ipSAE_min.
</p>

<details style="margin:0.8em 0;">
  <summary style="cursor:pointer;font-size:0.85em;color:#1565C0;font-weight:bold;">
    Show ipSAE formula
  </summary>
  <div style="background:#f5f5f5;border:1px solid #ddd;border-radius:6px;padding:1em 1.5em;
              margin:0.5em 0;font-size:0.9em;line-height:1.8;font-family:'Courier New',monospace;">
    <div style="margin-bottom:0.6em;">
      <b>ipSAE</b><sub>A→B</sub> = max<sub>i∈A</sub> [ pSAE<sub>i</sub> ]
    </div>
    <div style="margin-bottom:0.6em;">
      pSAE<sub>i</sub> = mean<sub>j∈B, PAE<sub>ij</sub>&lt;cutoff</sub>
      &nbsp;[ 1 / (1 + (PAE<sub>ij</sub> / d0<sub>i</sub>)²) ]
    </div>
    <div style="margin-bottom:0.6em;">
      d0<sub>i</sub> = max(1.0, &nbsp;1.24 · (N<sub>cutoff,i</sub> − 15)<sup>1/3</sup> − 1.8)
    </div>
    <div style="margin-bottom:0.6em;">
      N<sub>cutoff,i</sub> = |{{ j ∈ B : PAE<sub>ij</sub> &lt; cutoff }}|
    </div>
    <div style="border-top:1px solid #ccc;padding-top:0.5em;margin-top:0.5em;
                font-family:'Segoe UI',sans-serif;font-size:0.9em;color:#555;">
      <b>ipSAE_min</b> = min(ipSAE<sub>binder→target</sub>, ipSAE<sub>target→binder</sub>)
      &nbsp;&nbsp;·&nbsp;&nbsp; cutoff = 10 Å (uniform for Boltz-2 and AF2)
    </div>
  </div>
</details>

<h2>Screening Summary</h2>
<p style="font-size:0.85em;color:#555;">
  Thresholds: &nbsp;<span style="color:#2e7d32">■ High</span> &gt;0.80 &nbsp;
  <span style="color:#f57f17">■ Medium</span> &gt;0.61 &nbsp;
  <span style="color:#e65100">■ Low</span> &gt;0.40 &nbsp;
  <span style="color:#c62828">■ Reject</span> ≤0.40
</p>
{tier_summary}

<h2>Top 20 Binders</h2>
{top_table}

<table style="font-size:0.8em;border-collapse:collapse;margin:0.5em 0 1.5em 0;color:#555;">
  <tr><td style="padding:2px 12px 2px 0;"><b>rank</b></td>
      <td>Overall rank (quality tier → agreement → ipSAE_min → ipTM → pLDDT)</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><b>binder_length</b></td>
      <td>Designed binder length in amino acids</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><b>quality_tier</b></td>
      <td>High (&gt;0.80), Medium (&gt;0.61), Low (&gt;0.40), Reject (≤0.40) based on ipSAE_min</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><b>agreement</b></td>
      <td>Number of engines (0–2) with ipSAE_min &gt; 0.61</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><b>ipSAE_min ↑</b></td>
      <td>Primary metric — min(binder→target, target→binder) iPSAE from Boltz-2 PAE [0–1]</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><b>AF2 ipSAE_min ↑</b></td>
      <td>Same metric from AlphaFold2 cross-validation [0–1]</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><b>ipTM ↑</b></td>
      <td>Interface predicted TM-score from Boltz-2 [0–1]</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><b>pLDDT binder ↑</b></td>
      <td>Mean per-residue confidence of binder from Boltz-2 [0–1]</td></tr>
</table>

<h2>Per-Tool Summary Statistics</h2>
{summary_table}

<h2>Metric Distributions by Tool</h2>
<img src="data:image/png;base64,{dist_plot}" alt="Metric distributions">
<p style="font-size:0.8em;color:#555;line-height:1.5;margin-top:0.3em;">
  <b>Box plot guide:</b>
  The horizontal line inside each box is the <b>median</b>.
  The box spans the <b>interquartile range</b> (IQR, 25th–75th percentile — the middle 50% of values).
  Whiskers extend to the most extreme data points within 1.5× IQR from the box edges.
  Points beyond the whiskers are <b>outliers</b>.
  A taller box indicates greater variability across designs from that tool.
</p>

<h2>Tool Comparison (Radar Chart)</h2>
<img src="data:image/png;base64,{radar_plot}" alt="Radar chart">

{per_tool_top10}

<h2>Visual Inspection</h2>
<p style="font-size:0.85em;color:#555;line-height:1.6;">
  Top 20 refolded structures are available in <code>top20_structures/</code>.
  Open the PyMOL session script to visualise all binders aligned on the target:
</p>
<pre style="background:#f5f5f5;padding:0.6em 1em;border-radius:4px;font-size:0.85em;display:inline-block;">
cd report/top20_structures/
pymol view_top20.pml</pre>
<p style="font-size:0.85em;color:#555;">
  Binder (chain A) is coloured by tool. Target (chain B) is grey.
  Only rank 1 is shown initially — enable other structures in PyMOL's object panel.
</p>

<h2>Full Metrics Table</h2>
<details>
  <summary>Click to expand ({n_binders} binders)</summary>
  {full_table}
</details>

</body>
</html>
"""


def _compute_af2_boltz2_r(df: pd.DataFrame) -> dict[str, float | int]:
    """Compute Pearson r and systematic bias between Boltz-2 and AF2 metrics."""
    import numpy as np

    result: dict[str, float | int] = {}
    for b_col, a_col in [("ipsae_min", "af2_ipsae_min"), ("iptm", "af2_iptm")]:
        if b_col in df.columns and a_col in df.columns:
            b = pd.to_numeric(df[b_col], errors="coerce")
            a = pd.to_numeric(df[a_col], errors="coerce")
            mask = b.notna() & a.notna()
            n = int(mask.sum())
            if n > 2:
                bv, av = b[mask], a[mask]
                r = float(np.corrcoef(bv, av)[0, 1])
                result[f"{b_col}_vs_{a_col}"] = r
                result[f"{b_col}_vs_{a_col}_n"] = n
                # Systematic bias: mean difference and mean absolute error
                result[f"{b_col}_mean"] = float(bv.mean())
                result[f"{a_col}_mean"] = float(av.mean())
                result[f"{b_col}_vs_{a_col}_mae"] = float((bv - av).abs().mean())
    return result


def _correlation_callout_html(corr: dict) -> str:
    """Render a highlighted callout box for the AF2 vs Boltz-2 correlation."""
    if not corr:
        return ""

    r_ipsae = corr.get("ipsae_min_vs_af2_ipsae_min")
    n_ipsae = corr.get("ipsae_min_vs_af2_ipsae_min_n", 0)
    r_iptm = corr.get("iptm_vs_af2_iptm")
    n_iptm = corr.get("iptm_vs_af2_iptm_n", 0)

    # Pick the most representative r value for the headline
    headline_r = None
    if r_ipsae is not None:
        headline_r = r_ipsae
    if r_iptm is not None and (headline_r is None or abs(r_iptm) > abs(headline_r)):
        headline_r = r_iptm

    if headline_r is None:
        return ""

    strength = "strong" if abs(headline_r) >= 0.7 else ("moderate" if abs(headline_r) >= 0.5 else "weak")

    # Headline reflects the actual data
    if strength == "strong":
        headline_desc = "good rank-order agreement between the two predictors."
    elif strength == "moderate":
        headline_desc = "moderate rank-order correlation; absolute values may differ substantially."
    else:
        headline_desc = "weak correlation; the two predictors disagree on binder ranking."

    # Detect systematic bias
    bias_notes = []
    for b_col, a_col, label in [
        ("iptm", "af2_iptm", "ipTM"),
        ("ipsae_min", "af2_ipsae_min", "ipSAE_min"),
    ]:
        b_mean = corr.get(f"{b_col}_mean")
        a_mean = corr.get(f"{a_col}_mean")
        mae = corr.get(f"{b_col}_vs_{a_col}_mae")
        if b_mean is not None and a_mean is not None:
            diff = b_mean - a_mean
            if abs(diff) > 0.15:
                higher = "Boltz-2" if diff > 0 else "AF2"
                bias_notes.append(
                    f"{label}: {higher} scores systematically higher "
                    f"(Boltz-2 mean={b_mean:.3f}, AF2 mean={a_mean:.3f}, MAE={mae:.3f})"
                )

    # Correlation color: green for strong, amber for moderate, red for weak
    r_colors = {"strong": "#1b5e20", "moderate": "#e65100", "weak": "#c62828"}
    r_color = r_colors[strength]

    lines = []
    if r_iptm is not None:
        s1 = "strong" if abs(r_iptm) >= 0.7 else ("moderate" if abs(r_iptm) >= 0.5 else "weak")
        lines.append(
            f"<strong>ipTM:</strong> Boltz-2 vs AF2 Pearson r = "
            f"<strong style='font-size:1.25em; color:{r_color};'>{r_iptm:+.3f}</strong> "
            f"(n = {n_iptm}) — {s1} rank-order correlation."
        )
    if r_ipsae is not None:
        s2 = "strong" if abs(r_ipsae) >= 0.7 else ("moderate" if abs(r_ipsae) >= 0.5 else "weak")
        lines.append(f"<strong>ipSAE_min:</strong> r = {r_ipsae:+.3f} (n = {n_ipsae}) — {s2}")

    if bias_notes:
        lines.append(
            "<br><em style='color:#c62828;'>Systematic bias detected:</em> "
            + "; ".join(bias_notes)
            + ".<br><small>Note: AF2 (ColabDesign, single model, 3 recycles) is typically stricter "
            "than Boltz-2 for de novo designs. Large absolute differences are common and do not "
            "necessarily indicate errors.</small>"
        )

    # Callout style: green for strong, amber for moderate, muted for weak
    if strength == "strong":
        bg, border = "#e8f5e9", "#2e7d32"
    elif strength == "moderate":
        bg, border = "#fff8e1", "#f57f17"
    else:
        bg, border = "#fbe9e7", "#c62828"

    inner = "<br>".join(lines)
    return (
        f'<div style="background:{bg}; border-left:5px solid {border}; '
        f'padding:0.8em 1.2em; border-radius:4px; margin:1em 0; font-size:0.95em;">'
        f'<p style="margin:0 0 0.4em 0; font-size:1.05em;">&#x1F4CA;&nbsp;'
        f"<strong>Boltz-2 / AF2 Cross-Validation</strong>&nbsp;"
        f"— {headline_desc}</p>"
        f"<p style='margin:0;'>{inner}</p>"
        f"</div>"
    )


def generate_report(
    df: pd.DataFrame,
    summary: dict,
    output_path: str | Path,
    tool_csvs: dict[str, str | Path] | None = None,
) -> None:
    """Generate and write the HTML report.

    Args:
        df:            DataFrame with all metrics (after Boltz-2 promotion + statistics).
        summary:       Per-tool summary dict from compute_statistics.
        output_path:   Where to write report.html.
        tool_csvs:     Optional mapping of tool name → path to the tool's original
                       output CSV. When provided, the "Top Designs per Tool" section
                       shows the first 10 rows from the tool's own ranking instead of
                       the evaluator's ranking.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sort_df = df.copy()
    if "adaptyv_rank" in sort_df.columns:
        sort_df = sort_df.sort_values("adaptyv_rank", ascending=True)

    # Tool counts
    tool_counts_str = ""
    if "source_tool" in sort_df.columns:
        counts = sort_df["source_tool"].value_counts()
        tool_counts_str = " &nbsp;|&nbsp; ".join(
            f'<span class="tool-{t}">{_tool_display(t)}: {n}</span>' for t, n in counts.items()
        )

    # Tier summary
    tier_summary = _tier_summary_to_html(sort_df)

    # Top 20 table (primary + collapsible secondary)
    primary_cols, secondary_cols = _select_display_cols(sort_df)
    top20_primary = sort_df[primary_cols].head(20)
    top_table = _df_to_html(top20_primary, colour_tool=True).replace("<table>", '<table style="width:100%">', 1)
    if secondary_cols:
        top20_secondary = sort_df[primary_cols[:2] + secondary_cols].head(20)
        top_table += (
            '\n<details style="margin:0.5em 0;">'
            '<summary style="cursor:pointer;font-size:0.85em;color:#1565C0;font-weight:bold;">'
            "Show additional metrics for Top 20</summary>\n"
            + _df_to_html(top20_secondary, colour_tool=True)
            + "\n</details>"
        )

    # Summary statistics table
    summary_table = _summary_to_html(summary)

    # Plots
    dist_fig = plot_metric_distributions(sort_df)
    radar_fig = plot_radar_chart(summary)

    dist_b64 = fig_to_base64(dist_fig)
    radar_b64 = fig_to_base64(radar_fig)

    # Per-tool top 10 tables (collapsible, one per tool present in data)
    # When tool_csvs is provided, read top 10 from the tool's own CSV (native ranking)
    # and join with our binder_id via sequence matching.
    per_tool_top10 = ""
    if "source_tool" in sort_df.columns:
        tools_present = sorted(sort_df["source_tool"].dropna().unique())
        if tools_present:
            per_tool_top10 = (
                "<h2>Top Designs per Tool</h2>\n"
                '<p style="font-size:0.85em;color:#555;">'
                "Ranked by each tool's own internal scoring (not the evaluator's ranking)."
                "</p>\n"
            )

            # Build sequence → binder_id + adaptyv_rank lookup
            seq_to_ids = {}
            if "sequence" in sort_df.columns:
                for _, row in sort_df.iterrows():
                    seq = str(row.get("sequence", "")).strip().upper()
                    if seq and seq not in seq_to_ids:
                        seq_to_ids[seq] = {
                            "binder_id": row.get("binder_id", ""),
                            "adaptyv_rank": row.get("adaptyv_rank", ""),
                        }

            for tool in tools_present:
                display_name = _tool_display(tool)

                # Try reading from tool's original CSV
                if tool_csvs and tool in tool_csvs:
                    csv_path = Path(tool_csvs[tool])
                    if csv_path.exists():
                        try:
                            native_df = pd.read_csv(csv_path, nrows=10)
                            # Add our binder_id by matching sequence
                            seq_col = None
                            for candidate in ("sequence", "Sequence", "designed_chain_sequence", "designed_sequence"):
                                if candidate in native_df.columns:
                                    seq_col = candidate
                                    break
                            if seq_col:
                                native_df.insert(
                                    0,
                                    "binder_id",
                                    native_df[seq_col]
                                    .str.strip()
                                    .str.upper()
                                    .map(lambda s: seq_to_ids.get(s, {}).get("binder_id", "")),
                                )
                                native_df.insert(
                                    1,
                                    "eval_rank",
                                    native_df[seq_col]
                                    .str.strip()
                                    .str.upper()
                                    .map(lambda s: seq_to_ids.get(s, {}).get("adaptyv_rank", "")),
                                )
                            n = len(native_df)
                            tool_table = _df_to_html(native_df, colour_tool=False)
                            per_tool_top10 += (
                                f'<details style="margin:0.3em 0;">'
                                f'<summary style="cursor:pointer;font-weight:bold;">'
                                f"{display_name} — top {n} (native ranking)</summary>\n"
                                f"{tool_table}\n</details>\n"
                            )
                            continue
                        except Exception:
                            pass  # Fall through to evaluator-based ranking

                # Fallback: use evaluator ranking within this tool
                tool_df = sort_df[sort_df["source_tool"] == tool].head(10)
                n = len(tool_df)
                tool_table = _df_to_html(tool_df[primary_cols], colour_tool=True)
                per_tool_top10 += (
                    f'<details style="margin:0.3em 0;">'
                    f'<summary style="cursor:pointer;font-weight:bold;">'
                    f"{display_name} — top {n} (evaluator ranking)</summary>\n"
                    f"{tool_table}\n</details>\n"
                )

    # Full table — curated columns in ranking order
    _full_cols = [
        "adaptyv_rank",
        "binder_id",
        "source_tool",
        "binder_length",
        "quality_tier",
        "agreement_count",
        "ipsae_min",
        "af2_ipsae_min",
        "iptm",
        "af2_iptm",
        "boltz_pae_iptm",
        "af2_pae_iptm",
        "plddt_binder_mean",
        "plddt_binder_min",
        "binder_ptm",
        "ipae",
        "pae_bt",
        "pae_tb",
        "pae_bb",
        "plddt_target_mean",
        "intra_contact",
        "target_contact",
        "ipsae_dg_composite",
        "ipsae_shape_composite",
        "native_dG",
        "native_dSASA",
        "native_shape_complementarity",
        "sequence",
        "target_sequence",
    ]
    full_cols_available = [c for c in _full_cols if c in sort_df.columns]
    full_table = _df_to_html(sort_df[full_cols_available], max_rows=None)

    html = _HTML_TEMPLATE.format(
        n_binders=len(sort_df),
        tool_counts_str=tool_counts_str or "—",
        tier_summary=tier_summary,
        top_table=top_table,
        summary_table=summary_table,
        dist_plot=dist_b64,
        radar_plot=radar_b64,
        per_tool_top10=per_tool_top10,
        full_table=full_table,
    )

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"[report] Written → {output_path}")


def _select_display_cols(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Pick columns for the top-20 table: (primary, secondary).

    Primary columns are always visible; secondary are in a collapsible section.
    """
    primary = [
        "adaptyv_rank",
        "binder_id",
        "source_tool",
        "binder_length",
        "quality_tier",
        "agreement_count",
        "ipsae_min",
        "af2_ipsae_min",
        "iptm",
        "plddt_binder_mean",
    ]
    secondary = [
        "af2_iptm",
        "boltz_pae_iptm",
        "af2_pae_iptm",
        "binder_ptm",
        "plddt_binder_min",
        "ipae",
        "pae_bt",
        "pae_tb",
        "ipsae_dg_composite",
        "ipsae_shape_composite",
        "native_dG",
        "native_dSASA",
        "native_shape_complementarity",
        "sequence",
    ]
    return (
        [c for c in primary if c in df.columns],
        [c for c in secondary if c in df.columns],
    )


def _tier_summary_to_html(df: pd.DataFrame) -> str:
    """Render a tier breakdown table (high/medium/low/reject counts per tool)."""
    if "quality_tier" not in df.columns:
        return "<p style='color:#888;font-size:0.85em;'>ipSAE_min not available — tier classification skipped.</p>"

    tier_order = ["high", "medium", "low", "reject"]
    tier_labels = {
        "high": '<span style="color:#2e7d32">■ High (&gt;0.80)</span>',
        "medium": '<span style="color:#f57f17">■ Medium (&gt;0.61)</span>',
        "low": '<span style="color:#e65100">■ Low (&gt;0.40)</span>',
        "reject": '<span style="color:#c62828">■ Reject (≤0.40)</span>',
    }
    n_total = len(df)

    has_tools = "source_tool" in df.columns
    tools = sorted(df["source_tool"].dropna().unique()) if has_tools else []

    # Build header
    tool_headers = "".join(f"<th>{_tool_display(t)}</th>" for t in tools)
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

    # Total row
    total_tool_cells = ""
    if has_tools:
        for t in tools:
            total_tool_cells += f"<td><b>{int((df['source_tool'] == t).sum())}</b></td>"
    rows.append(
        f'<tr style="border-top:2px solid #333"><td style="text-align:left"><b>Total</b></td>'
        f"<td><b>{n_total}</b></td><td>100%</td>{total_tool_cells}</tr>"
    )

    # Optional: ipsae_dg_composite summary row
    composite_note = ""
    if "ipsae_dg_composite" in df.columns:
        vals = pd.to_numeric(df["ipsae_dg_composite"], errors="coerce").dropna()
        if len(vals) > 0:
            composite_note = (
                f"<p style='font-size:0.83em;color:#555;margin-top:0.4em;'>"
                f"ipSAE_min × |ΔG/ΔSASA| (best composite, Overath et al. 2025): "
                f"mean={vals.mean():.4f}, max={vals.max():.4f} "
                f"(n={len(vals)} with BindCraft native metrics)</p>"
            )

    return f'<table class="stat-table">{header}{"".join(rows)}</table>' + composite_note


def _col_header(col: str) -> str:
    """Return a formatted <th> label with unit and direction arrow from METRIC_META."""
    meta = METRIC_META.get(col)
    if not meta:
        return col
    label, unit, arrow = meta
    parts = [label]
    if arrow:
        parts.append(arrow)
    suffix = f" <small>{unit}</small>" if unit else ""
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
            if col == "binder_length":
                return f"<td{cls}>{int(val)}</td>"
            return f"<td{cls}>{val:.4f}</td>"
        # Truncate long strings like sequences
        if isinstance(val, str) and len(val) > 20 and col in ("sequence", "target_sequence"):
            return f'<td title="{val}">{val[:17]}…</td>'
        return f"<td{cls}>{val}</td>"

    header = (
        "<tr>"
        + "".join(
            f'<th style="text-align:right">{_col_header(c)}</th>' if c in numeric_cols else f"<th>{_col_header(c)}</th>"
            for c in df.columns
        )
        + "</tr>"
    )

    rows = []
    for _, row in df.iterrows():
        cells = "".join(
            fmt(c, _tool_display(v) if c == "source_tool" and isinstance(v, str) else v)
            for c, v in zip(df.columns, row)
        )
        if colour_tool and "source_tool" in df.columns:
            tool = row.get("source_tool", "")
            rows.append(f'<tr class="tool-{tool}">{cells}</tr>')
        else:
            rows.append(f"<tr>{cells}</tr>")

    return f"<table>{header}{''.join(rows)}</table>"


# Short plain-language descriptions for the summary table
_METRIC_DESCRIPTION = {
    "ipsae_min": (
        "Interface Predicted Structural Alignment Error — TM-score-like metric computed from PAE matrix. "
        "Measures how confidently the model predicts the binder–target interface. "
        "This is the primary ranking metric. Higher = more likely to bind. Want >0.61 (medium), >0.80 (high)."
    ),
    "bt_ipsae_aux": (
        "ipSAE in the binder→target direction, reported by the design tool during generation (not independent). "
        "Higher = better predicted interface from binder side."
    ),
    "tb_ipsae_aux": (
        "ipSAE in the target→binder direction, reported by the design tool during generation (not independent). "
        "Higher = better predicted interface from target side."
    ),
    "ipsae_min_aux": (
        "Minimum of binder→target and target→binder ipSAE from the design tool (not independent refolding). "
        "Useful for comparison, but biased — the tool optimized for this. Higher = better."
    ),
    "boltz_pae_bt_ipsae": (
        "ipSAE in the binder→target direction from independent Boltz-2 refolding. "
        "Measures how well Boltz-2 predicts the binder contacts the target. Higher = better."
    ),
    "boltz_pae_tb_ipsae": (
        "ipSAE in the target→binder direction from independent Boltz-2 refolding. "
        "Measures how well Boltz-2 predicts the target contacts the binder. Higher = better."
    ),
    "boltz_pae_ipsae_min": (
        "Primary ranking metric — ipSAE_min from independent Boltz-2 refolding (DunbrackLab formula, 10 Å cutoff). "
        "The sequence is refolded from scratch, so this is an unbiased assessment. Want >0.61."
    ),
    "af2_ipsae_min": (
        "ipSAE_min from independent AlphaFold2 refolding — cross-validation with a second prediction engine. "
        "If both Boltz-2 and AF2 score >0.61, the design has dual-engine agreement (agreement_count = 2). "
        "AF2 tends to score lower for computationally designed binders."
    ),
    "af2_bt_ipsae": (
        "ipSAE binder→target from independent AF2 refolding. "
        "Cross-validation metric — higher means AF2 also predicts binder contacts the target."
    ),
    "af2_tb_ipsae": (
        "ipSAE target→binder from independent AF2 refolding. "
        "Cross-validation metric — higher means AF2 also predicts target contacts the binder."
    ),
    "iptm": (
        "Interface predicted TM-score from Boltz-2 — measures overall interface quality. "
        "Higher = more confident complex prediction. Want >0.8. Note: can be inflated for AF2-designed sequences."
    ),
    "af2_iptm": (
        "Interface predicted TM-score from AF2 refolding. "
        "Low values are common for computationally designed binders — AF2 often struggles with de novo sequences."
    ),
    "boltz_pae_iptm": (
        "ipTM recomputed from Boltz-2 PAE matrix (rather than model-reported value). "
        "More consistent across runs. Higher = better."
    ),
    "af2_pae_iptm": (
        "ipTM recomputed from AF2 PAE matrix. More consistent than model-reported AF2 ipTM. Higher = better."
    ),
    "binder_ptm": (
        "Predicted TM-score of the binder chain alone — does the binder fold into a stable structure by itself? "
        "Want >0.9. Low values suggest the binder may be disordered or misfolded."
    ),
    "plddt_binder_mean": (
        "Average per-residue confidence (pLDDT) of the binder from Boltz-2. "
        "Indicates how confidently each residue position is predicted. Want >0.7."
    ),
    "plddt_binder_min": (
        "Lowest per-residue pLDDT in the binder — identifies the least confident residue. "
        "Very low values (<0.4) suggest a disordered loop or poorly predicted region."
    ),
    "plddt_target_mean": (
        "Average pLDDT of the target chain in the complex prediction. "
        "Should be reasonably stable (>0.5). Very low suggests the target is not well modeled."
    ),
    "ipae": (
        "Interface Predicted Aligned Error — mean PAE across the binder–target interface in Angstroms. "
        "Lower = more confident interface. Superseded by ipSAE as a ranking metric."
    ),
    "af2_ipae": "Same as ipAE but from AF2 refolding. Lower = better.",
    "pae_bt": (
        "Mean Predicted Aligned Error from binder residues to target residues in Angstroms. "
        "Lower = Boltz-2 is more confident about binder→target spatial arrangement."
    ),
    "pae_tb": (
        "Mean PAE from target residues to binder residues. "
        "Lower = Boltz-2 is more confident about target→binder spatial arrangement."
    ),
    "pae_bb": (
        "Mean PAE within the binder chain (binder-to-binder). "
        "Reflects internal fold confidence. Lower = well-folded binder."
    ),
    "agreement_count": (
        "Number of independent prediction engines (0–2) that score ipSAE_min above the 0.61 pass threshold. "
        "0 = neither agrees, 1 = Boltz-2 only, 2 = both Boltz-2 and AF2 agree. Want 2."
    ),
    "intra_contact": (
        "Binder internal contact score — measures how tightly the binder folds. "
        "More negative = more internal contacts = tighter, more stable fold."
    ),
    "target_contact": (
        "Target contact score in complex — measures binder–target interaction extent. "
        "More negative = more contacts at the interface = larger binding surface."
    ),
    "pTMEnergy": (
        "TM-score-based energy term combining fold quality and interface prediction. "
        "More negative = better overall prediction quality."
    ),
}


def _summary_to_html(summary: dict) -> str:
    """Render per-tool summary as an HTML table."""
    all_metrics: set[str] = set()
    for tool_data in summary.values():
        all_metrics.update(tool_data.keys())
    metrics = sorted(all_metrics)
    tools = list(summary.keys())

    # Tool name → colour class header cell
    tool_cols = "".join(
        f'<th><span class="tool-{t}">{_tool_display(t)}</span><br><small>mean ± std</small></th>' for t in tools
    )
    header = f'<tr><th>Metric</th>{tool_cols}<th style="text-align:left">Description</th></tr>'

    rows = []
    for m in metrics:
        meta = METRIC_META.get(m)
        if meta:
            label, unit, arrow = meta
            unit_str = f" {unit}" if unit else ""
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
        desc = _METRIC_DESCRIPTION.get(m, "")
        row += f'<td style="font-size:0.85em;color:#666;text-align:left">{desc}</td>'
        rows.append(f"<tr>{row}</tr>")

    return f'<table class="stat-table">{header}{"".join(rows)}</table>'
