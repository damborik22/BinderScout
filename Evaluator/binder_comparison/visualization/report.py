"""HTML report generator.

Produces a self-contained report.html with:
  - Summary table (top binders by composite score)
  - Per-tool summary statistics
  - Embedded plots (metric distributions, radar chart)
  - Full metrics table (collapsible)
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import pandas as pd

from ..comparison.candidates import _NATIVE_SEQ_COLS, collapse_native_df, order_tools
from .plots import (
    METRIC_META,
    fig_to_base64,
    plot_max_vs_mean_iptm,
    plot_metric_correlation_heatmap,
    plot_metric_distributions,
    plot_pareto_front,
    plot_radar_chart,
    plot_radar_iptm,
    plot_radar_per_engine,
    plot_radar_per_engine_uniform_selection,
)

# Display names for tools (source_tool values are lowercase internally)
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

# Primary reference link per tool. Points at the canonical repository used by
# the BindMaster installer (so the link matches the code the user actually
# ran). Swap to a paper URL once each method is published.
_TOOL_LINKS = {
    # BindCraft — Pacesa et al. (Nature 2025), repo at martinpacesa/BindCraft
    "bindcraft": "https://github.com/martinpacesa/BindCraft",
    # BoltzGen — diffusion-based binder generator (installer pin)
    "boltzgen": "https://github.com/HannesStark/boltzgen",
    # Mosaic — escalante-bio JAX/Boltz-2 hallucinator
    "mosaic": "https://github.com/escalante-bio/mosaic",
    # PXDesign — ByteDance Protenix-based binder design
    "pxdesign": "https://github.com/bytedance/PXDesign",
    # Proteina-Complexa — NVIDIA flow-matching binder design
    "proteina_complexa": "https://github.com/NVIDIA-Digital-Bio/proteina-complexa",
    # RFD3 — RFdiffusion3 / foundry
    "rfd3": "https://github.com/RosettaCommons/RFdiffusion",
    # Protein-Hunter — Cho et al. 2025, bioRxiv preprint
    "protein_hunter": "https://doi.org/10.1101/2025.10.10.681530",
}


def _tool_display(name: str, *, link: bool = False) -> str:
    """Return the display label for a tool.

    Emits a plain string by default. Pass ``link=True`` to wrap the label
    in an ``<a>`` tag pointing at the tool's primary reference (paper or
    repository) — used only by the top counts banner so links don't repeat
    on every tool mention in tables/section headings.
    """
    label = _TOOL_DISPLAY.get(name, name)
    if not link:
        return label
    url = _TOOL_LINKS.get(name)
    if not url:
        return label
    # target=_blank + rel=noopener for safe new-tab navigation; inherit colour
    # so the existing ``.tool-<name>`` class still tints the link.
    return f'<a href="{url}" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline dotted;">{label}</a>'


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
  /* Selected-design button in any 3D Structure Viewer (top-20 + per-tool top-10) */
  [class*="design-btn"].active,
  [class^="design-btn"].active {{
    box-shadow: 0 0 0 3px #000, 0 0 6px rgba(0,0,0,0.35);
    transform: scale(1.08);
    filter: brightness(0.85);
  }}
  .tool-bindcraft          {{ color: #1565C0; font-weight: bold; }}
  .tool-boltzgen           {{ color: #E65100; font-weight: bold; }}
  .tool-boltzgen_nano      {{ color: #E65100; font-weight: bold; }}
  .tool-boltzgen_protein   {{ color: #EF6C00; font-weight: bold; }}
  .tool-mosaic             {{ color: #2E7D32; font-weight: bold; }}
  .tool-pxdesign           {{ color: #7B1FA2; font-weight: bold; }}
  .tool-proteina_complexa  {{ color: #6D4C41; font-weight: bold; }}
  .tool-rfd3               {{ color: #D84315; font-weight: bold; }}
  .tool-protein_hunter     {{ color: #00838F; font-weight: bold; }}
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
  All designed binder sequences are independently re-folded as target–binder complexes by the
  refolding engines used in this report — {engines_present_html}. The cross-engine 3D structures
  shown are from the <b>primary structure source</b> (<code>--primary-engine</code>, default
  <code>boltz</code>); ranking aggregates across all available engines (the primary engine
  controls only which PDB/CIF the 3D viewer shows, not which numbers drive the rank).
  {methodology_ranking_html}
</p>

{benchmark_provenance_block}
{qc_rules_block}
{tool_classification_banner}

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
      &nbsp;&nbsp;·&nbsp;&nbsp; cutoff = 10 Å (uniform across all engines)
    </div>
  </div>
</details>

<h2>Screening Summary</h2>
{screening_summary_intro}
{engine_threshold_legend}
{agreement_summary}
{tier_summary}

<h2>Top 30 Binders</h2>
{top_table}

{top_table_legend}

{top_per_family_block}

<details style="margin:1em 0;">
  <summary style="cursor:pointer;font-size:1.5em;color:#1a5276;font-weight:bold;
           border-bottom:2px solid #CFE6F6;padding-bottom:4px;margin-bottom:0.5em;">
    Per-Tool Summary Statistics <span style="font-size:0.65em;color:#888;font-weight:normal;">(click to expand)</span>
  </summary>
  {summary_table}
</details>

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
<p style="font-size:0.85em;color:#555;margin:0.2em 0 0.6em 0;">
  Each panel: per-tool top-10 ranked by <b>that engine's own ipSAE_min</b>.
</p>
<img src="data:image/png;base64,{radar_plot}" alt="Per-engine radar (each panel ranks per-tool top-10 independently)">

{scatter_block}

{radar_fixed_block}

{correlation_heatmap_block}

{pareto_block}

{per_tool_top10}

<h2>3D Structure Viewer — Top 20
  <span style="background:#0277bd;color:white;padding:2px 10px;border-radius:4px;
        font-size:0.7em;font-weight:bold;vertical-align:middle;margin-left:0.4em;">
    REFOLDED · {primary_engine_label}
  </span>
</h2>
<p style="font-size:0.85em;color:#555;line-height:1.6;">
  Structures shown here are <b>{primary_engine_label} re-folds</b> of each
  design's sequence — the structures used for ranking (primary engine).
  Independent of the design tool. Click any rank button below to load. Binder
  (chain A) is coloured by tool, target (chain B) is grey. Drag to rotate,
  scroll to zoom, right-drag to pan.
</p>
{ngl_viewer_block}

<details style="margin:1em 0;">
  <summary style="cursor:pointer;font-size:0.85em;color:#1565C0;font-weight:bold;">
    Alternative: open in PyMOL
  </summary>
  <p style="font-size:0.85em;color:#555;line-height:1.6;">
    Top 20 refolded structures are available in <code>top20_structures/</code>.
    Open the PyMOL session script to visualise all binders aligned on the target:
  </p>
  <pre style="background:#f5f5f5;padding:0.6em 1em;border-radius:4px;font-size:0.85em;display:inline-block;">
cd report/top20_structures/
pymol view_top20.pml</pre>
</details>

<h2>Full Metrics Table</h2>
<details>
  <summary>Click to expand ({n_binders} binders)</summary>
  {full_table}
</details>

{provenance_footer}

</body>
</html>
"""


_TOOL_COLOURS_NGL = {
    "mosaic": "#4CAF50",
    "pxdesign": "#9C27B0",
    "boltzgen": "#FF9800",
    "boltzgen_nano": "#FF9800",
    "boltzgen_protein": "#EF6C00",
    "bindcraft": "#2196F3",
    "proteina_complexa": "#00897B",
    "rfd3": "#D84315",
    "protein_hunter": "#00838F",
    "unknown": "#9E9E9E",
}


def _build_ngl_viewer(top_df: pd.DataFrame, structures_dir: Path, target_seq: str | None = None) -> str:
    """Build an NGL-based 3D viewer section for the top 20 designs.

    Embeds PDB/CIF content inline so the report stays self-contained.
    Uses NGL Viewer loaded from CDN. Accepts whichever extension the
    primary-engine PDB copier produced (.pdb or .cif).
    """
    # Collect PDBs/CIFs and metadata for each top design
    entries = []
    for _, row in top_df.head(20).iterrows():
        rank = int(row.get("active_rank", row.get("adaptyv_rank", 0)))
        binder_id = row.get("binder_id", f"rank{rank}")
        tool = row.get("source_tool", "unknown")
        ipsae = row.get("ipsae_min", "")
        iptm = row.get("iptm", "")
        length = row.get("binder_length", "")

        # Search for the structure file with whichever extension was copied.
        pdb_path = None
        for ext in (".pdb", ".cif"):
            candidate = structures_dir / f"rank{rank:02d}_{binder_id}{ext}"
            if candidate.exists():
                pdb_path = candidate
                break
        if pdb_path is None:
            continue
        raw_text = pdb_path.read_text()
        raw_ext = pdb_path.suffix[1:]  # 'pdb' or 'cif'
        # Normalize to PDB with letter chain IDs (handles BG/PXD numeric chains)
        pdb_text, struct_ext, _ = _normalize_struct_to_pdb(raw_text, raw_ext)
        binder_chain, target_chain = _pick_binder_target_chains(pdb_text, struct_ext, target_seq)
        # Escape backticks and backslashes for JS template literal
        pdb_js = pdb_text.replace("\\", "\\\\").replace("`", "\\`")
        entries.append(
            {
                "rank": rank,
                "binder_id": binder_id,
                "tool": tool,
                "ext": struct_ext,
                "binder_chain": binder_chain,
                "target_chain": target_chain,
                "tool_colour": _TOOL_COLOURS_NGL.get(tool, _TOOL_COLOURS_NGL["unknown"]),
                "ipsae": f"{float(ipsae):.3f}" if ipsae not in ("", None) else "n/a",
                "iptm": f"{float(iptm):.3f}" if iptm not in ("", None) else "n/a",
                "length": str(length).rstrip(".0") if length else "?",
                "pdb": pdb_js,
            }
        )

    if not entries:
        return "<p style='color:#888;'><em>No refolded structures available.</em></p>"

    # Build the HTML/JS block
    # Button row — one button per rank, coloured by tool
    buttons_html = []
    for e in entries:
        buttons_html.append(
            f'<button id="design-btn-{e["rank"]}" class="design-btn" onclick="loadDesign({e["rank"]})" '
            f'style="background:{e["tool_colour"]};color:white;border:none;padding:0.4em 0.7em;'
            f"margin:0.15em;border-radius:4px;cursor:pointer;font-size:0.85em;font-weight:bold;"
            f'transition:transform 0.1s,filter 0.1s,box-shadow 0.1s;" '
            f'title="{_TOOL_DISPLAY.get(e["tool"], e["tool"])} — ipSAE={e["ipsae"]}, ipTM={e["iptm"]}, {e["length"]}aa">'
            f"#{e['rank']}</button>"
        )
    buttons = "\n".join(buttons_html)

    # Embed PDB data as JS object
    pdb_data_js = ",\n        ".join(
        f'{e["rank"]}: {{"pdb": `{e["pdb"]}`, "ext": "{e["ext"]}", '
        f'"tool": "{e["tool"]}", "colour": "{e["tool_colour"]}", '
        f'"binder_chain": "{e["binder_chain"]}", "target_chain": "{e["target_chain"]}", '
        f'"binder_id": "{e["binder_id"]}", '
        f'"ipsae": "{e["ipsae"]}", "iptm": "{e["iptm"]}", "length": "{e["length"]}"}}'
        for e in entries
    )

    default_rank = entries[0]["rank"]

    html = f"""
<div style="margin:1em 0;">
  <div style="margin-bottom:0.5em;">
    <b>Design:</b> {buttons}
  </div>
  <div id="ngl-info" style="font-size:0.9em;color:#333;margin-bottom:0.4em;padding:0.4em 0.8em;background:#f5f5f5;border-radius:4px;">
    Loading...
  </div>
  <div id="ngl-viewer" style="width:100%;height:500px;border:1px solid #ccc;border-radius:4px;background:#000;"></div>
  <div style="margin-top:0.4em;font-size:0.8em;color:#666;">
    Controls: drag = rotate | scroll = zoom | right-drag = pan | double-click atom = centre
  </div>
</div>

<script src="https://unpkg.com/ngl@2.3.1/dist/ngl.js"></script>
<script>
(function() {{
  const designs = {{
    {pdb_data_js}
  }};

  // Wait for NGL to load
  function initWhenReady() {{
    if (typeof NGL === 'undefined') {{
      setTimeout(initWhenReady, 100);
      return;
    }}
    const stage = new NGL.Stage("ngl-viewer", {{backgroundColor: "white"}});
    window.addEventListener("resize", function() {{ stage.handleResize(); }}, false);

    window.loadDesign = function(rank) {{
      const design = designs[rank];
      if (!design) return;

      stage.removeAllComponents();
      const blob = new Blob([design.pdb], {{type: "text/plain"}});

      stage.loadFile(blob, {{ext: design.ext || "pdb"}}).then(function(comp) {{
        // Binder chain (detected by sequence): coloured by tool
        comp.addRepresentation("cartoon", {{
          sele: ":" + design.binder_chain,
          color: design.colour,
          smoothSheet: true,
        }});
        // Target chain (detected by sequence): grey
        comp.addRepresentation("cartoon", {{
          sele: ":" + design.target_chain,
          color: "#9E9E9E",
          smoothSheet: true,
        }});
        comp.autoView();
      }});

      document.getElementById("ngl-info").innerHTML =
        "<b>Rank #" + rank + "</b> &nbsp;·&nbsp; " + design.binder_id +
        " &nbsp;·&nbsp; " + design.tool +
        " &nbsp;·&nbsp; length=" + design.length + "aa" +
        " &nbsp;·&nbsp; ipSAE=" + design.ipsae +
        " &nbsp;·&nbsp; ipTM=" + design.iptm;

      // Mark the clicked button as the active selection
      document.querySelectorAll(".design-btn.active").forEach(function(b) {{
        b.classList.remove("active");
      }});
      const btn = document.getElementById("design-btn-" + rank);
      if (btn) btn.classList.add("active");
    }};

    // Load default (rank 1)
    window.loadDesign({default_rank});
  }}
  initWhenReady();
}})();
</script>
"""
    return html


def _native_pdb_sort_key(tool: str, p: Path) -> tuple[int, int]:
    """Rank a candidate PDB/CIF so the tool's own complex prediction wins.

    For PXDesign: ptx_pred (Protenix refold, has pLDDT) > converted_pdbs (raw
    diffusion, no confidence) > af2_pred (cross-validation). For other tools:
    prefer non-AF2 paths. Within a tier, .pdb beats .cif.
    """
    parts_lower = [s.lower() for s in p.parts]

    if tool == "pxdesign":
        if "ptx_pred" in parts_lower:
            tier = 0
        elif "converted_pdbs" in parts_lower:
            tier = 1
        elif "af2_pred" in parts_lower:
            tier = 2
        else:
            tier = 3
    else:
        tier = 1 if any("af2" in s for s in parts_lower) else 0

    return (tier, 0 if p.suffix == ".pdb" else 1)


def _build_per_tool_refold_viewer(
    tool: str,
    tool_df: pd.DataFrame,
    boltz2_results_dir: Path | None,
    n: int = 10,
    primary_engine: str = "boltz",
    target_seq: str | None = None,
) -> str:
    """3D viewer for a tool's top-N picks using the **refolded** PDBs of the primary engine.

    Used by the "Top Designs per Tool" fallback path (no --tool-csv supplied).
    Picks the primary-engine PDB column when available (af3_pdb/cif for AF3,
    boltz_pdb otherwise). Binder vs target chain is detected per-design by
    matching the target sequence.
    """
    colour = _TOOL_COLOURS_NGL.get(tool, _TOOL_COLOURS_NGL["unknown"])
    # Engine-specific PDB column preference (mirrors cli/report.py _ENGINE_PDB_PRIORITY)
    _PRI: dict[str, list[str]] = {
        "af3": ["af3_pdb", "af3_cif", "boltz_pdb", "pdb"],
        "protenix": ["protenix_pdb", "protenix_cif", "boltz_pdb", "pdb"],
        "boltz": ["boltz_pdb", "pdb"],
    }
    pdb_cols = [c for c in _PRI.get(primary_engine, ["boltz_pdb", "pdb"]) if c in tool_df.columns]
    if not pdb_cols:
        return ""
    entries = []
    for i, (_, row) in enumerate(tool_df.head(n).iterrows()):
        src = None
        for col in pdb_cols:
            v = row.get(col)
            if isinstance(v, str) and v:
                src = v
                break
        if not src:
            continue
        src_path = Path(src)
        if not src_path.is_absolute() and boltz2_results_dir is not None:
            src_path = boltz2_results_dir / src
        if not src_path.exists():
            continue
        try:
            raw_text = src_path.read_text()
        except Exception:
            continue
        raw_ext = src_path.suffix.lstrip(".") or "pdb"
        pdb_text, ext, _ = _normalize_struct_to_pdb(raw_text, raw_ext)
        binder_chain, target_chain = _pick_binder_target_chains(pdb_text, ext, target_seq)
        pdb_js = pdb_text.replace("\\", "\\\\").replace("`", "\\`")
        binder_id = str(row.get("binder_id", ""))
        length = row.get("binder_length", "")
        ipsae = row.get("ipsae_min", "")
        iptm = row.get("iptm", "")
        entries.append(
            {
                "rank": i + 1,
                "binder_id": binder_id,
                "name": binder_id or f"rank{i + 1}",
                "length": int(length) if pd.notna(length) and length != "" else 0,
                "ipsae": f"{float(ipsae):.3f}" if ipsae not in ("", None) and pd.notna(ipsae) else "n/a",
                "iptm": f"{float(iptm):.3f}" if iptm not in ("", None) and pd.notna(iptm) else "n/a",
                "ext": ext,
                "binder_chain": binder_chain,
                "target_chain": target_chain,
                "pdb": pdb_js,
            }
        )
    if not entries:
        return ""
    viewer_id = f"ngl-refold-viewer-{tool}"
    info_id = f"ngl-refold-info-{tool}"
    tool_id = tool.replace("-", "_") + "_refold"
    btn_class = f"design-btn-refold-{tool}"
    buttons_html = []
    for e in entries:
        title = f"{e['name']} — {e['length']}aa — ipSAE={e['ipsae']}, ipTM={e['iptm']}"
        buttons_html.append(
            f'<button id="design-btn-refold-{tool}-{e["rank"]}" class="{btn_class}" '
            f'onclick="loadDesign_{tool_id}({e["rank"]})" '
            f'style="background:{colour};color:white;border:none;padding:0.3em 0.6em;'
            f"margin:0.1em;border-radius:3px;cursor:pointer;font-size:0.8em;"
            f'transition:transform 0.1s,filter 0.1s,box-shadow 0.1s;" '
            f'title="{title}">#{e["rank"]}</button>'
        )
    pdb_data_js = ",\n        ".join(
        f'{e["rank"]}: {{"pdb": `{e["pdb"]}`, "ext": "{e["ext"]}", '
        f'"binder_chain": "{e["binder_chain"]}", "target_chain": "{e["target_chain"]}", '
        f'"name": "{e["name"]}", "binder_id": "{e["binder_id"]}", '
        f'"ipsae": "{e["ipsae"]}", "iptm": "{e["iptm"]}", "length": {e["length"]}}}'
        for e in entries
    )
    default_rank = entries[0]["rank"]
    _engine_label = {"af3": "AlphaFold 3", "protenix": "Protenix", "boltz": "Boltz-2"}.get(
        primary_engine, primary_engine.upper()
    )
    html = f"""
<div style="margin:0.6em 0;padding:0.6em;border:1px solid #ddd;border-radius:4px;background:#fafafa;">
  <div style="font-size:0.78em;margin-bottom:0.3em;">
    <span style="background:#0277bd;color:white;padding:1px 8px;border-radius:3px;
                 font-weight:bold;">REFOLDED · {_engine_label}</span>
    <span style="color:#555;margin-left:0.4em;">
      structure shown is the {_engine_label} re-fold; binder/target chain detected per design
    </span>
  </div>
  <div style="margin-bottom:0.4em;">{"".join(buttons_html)}</div>
  <div id="{info_id}" style="font-size:0.85em;color:#333;margin-bottom:0.3em;padding:0.3em 0.6em;background:#fff;border-radius:3px;">Click a rank button to load 3D structure</div>
  <div id="{viewer_id}" style="width:100%;height:380px;border:1px solid #ccc;border-radius:4px;background:#000;"></div>
</div>

<script>
(function() {{
  const designs_{tool_id} = {{
    {pdb_data_js}
  }};
  let stage_{tool_id} = null;
  let loaded_{tool_id} = false;

  function init_{tool_id}() {{
    if (typeof NGL === 'undefined') {{ setTimeout(init_{tool_id}, 100); return; }}
    if (stage_{tool_id}) return;
    stage_{tool_id} = new NGL.Stage("{viewer_id}", {{backgroundColor: "white"}});
    window.addEventListener("resize", function() {{ if (stage_{tool_id}) stage_{tool_id}.handleResize(); }}, false);

    window.loadDesign_{tool_id} = function(rank) {{
      const d = designs_{tool_id}[rank];
      if (!d || !stage_{tool_id}) return;
      stage_{tool_id}.removeAllComponents();
      const blob = new Blob([d.pdb], {{type: "text/plain"}});
      stage_{tool_id}.loadFile(blob, {{ext: d.ext}}).then(function(comp) {{
        comp.addRepresentation("cartoon", {{sele: ":" + d.binder_chain, color: "{colour}", smoothSheet: true}});
        comp.addRepresentation("cartoon", {{sele: ":" + d.target_chain, color: "#9E9E9E", smoothSheet: true}});
        comp.autoView();
        stage_{tool_id}.handleResize();
      }});
      document.getElementById("{info_id}").innerHTML =
        "<b>" + d.name + "</b> &nbsp;·&nbsp; length=" + d.length + "aa" +
        " &nbsp;·&nbsp; ipSAE=" + d.ipsae + " &nbsp;·&nbsp; ipTM=" + d.iptm;
      document.querySelectorAll(".{btn_class}.active").forEach(function(b) {{ b.classList.remove("active"); }});
      const btn = document.getElementById("design-btn-refold-{tool}-" + rank);
      if (btn) btn.classList.add("active");
      loaded_{tool_id} = true;
    }};
  }}

  document.addEventListener("DOMContentLoaded", function() {{
    const viewer = document.getElementById("{viewer_id}");
    if (!viewer) return;
    const details = viewer.closest("details");
    if (details) {{
      details.addEventListener("toggle", function() {{
        if (details.open) {{
          init_{tool_id}();
          if (!loaded_{tool_id}) {{
            setTimeout(function() {{ window.loadDesign_{tool_id}({default_rank}); }}, 200);
          }} else if (stage_{tool_id}) {{
            setTimeout(function() {{ stage_{tool_id}.handleResize(); }}, 100);
          }}
        }}
      }});
    }} else {{
      init_{tool_id}();
      setTimeout(function() {{ window.loadDesign_{tool_id}({default_rank}); }}, 200);
    }}
  }});
}})();
</script>
"""
    return html


_AA3 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLU": "E",
    "GLN": "Q",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}


def _pdb_chains(path: Path) -> dict[str, str]:
    """Read ATOM records from a PDB and return {chain_id: single-letter-sequence}."""
    chains: dict[str, list[tuple[int, str]]] = {}
    try:
        with path.open() as f:
            for line in f:
                if not line.startswith("ATOM"):
                    continue
                if line[12:16].strip() != "CA":
                    continue
                resname = line[17:20].strip()
                aa = _AA3.get(resname)
                if not aa:
                    continue
                chain_id = line[21]
                resseq = int(line[22:26])
                chains.setdefault(chain_id, []).append((resseq, aa))
    except (OSError, ValueError):
        return {}
    # Deduplicate by resseq, sort, join.
    out = {}
    for c, residues in chains.items():
        seen: dict[int, str] = {}
        for rs, aa in residues:
            seen.setdefault(rs, aa)
        out[c] = "".join(aa for _, aa in sorted(seen.items()))
    return out


def _struct_chains(text: str, ext: str) -> dict[str, str]:
    """Parse a PDB- or CIF-formatted string and return {chain_id: 1-letter sequence}.

    Used to figure out which chain is the target vs binder when the assignment
    is not the Boltz-2 default (binder=A, target=B). Robust against unknown
    residues by skipping them.
    """
    if ext == "cif":
        # Minimal CIF parse: walk the atom_site loop for label_atom_id=CA rows.
        chains: dict[str, list[tuple[int, str]]] = {}
        in_loop = False
        cols: list[str] = []
        loop_lines: list[str] = []
        for raw in text.splitlines():
            line = raw.rstrip()
            if line.startswith("loop_"):
                in_loop = True
                cols = []
                loop_lines = []
                continue
            if in_loop and line.startswith("_atom_site."):
                cols.append(line.split(".", 1)[1])
                continue
            if (
                in_loop
                and cols
                and (
                    not line
                    or line.startswith("#")
                    or line.startswith("loop_")
                    or line.startswith("_")
                    or line.startswith("data_")
                )
            ):
                in_loop = False
                cols = []
                continue
            if in_loop and cols and line and not line.startswith("#"):
                loop_lines.append(line)
        if not (cols and loop_lines):
            return {}
        try:
            i_atom = cols.index("label_atom_id")
            i_comp = cols.index("label_comp_id")
            i_chain = cols.index("label_asym_id") if "label_asym_id" in cols else cols.index("auth_asym_id")
            i_seq = cols.index("label_seq_id") if "label_seq_id" in cols else cols.index("auth_seq_id")
        except ValueError:
            return {}
        for line in loop_lines:
            toks = line.split()
            if len(toks) <= max(i_atom, i_comp, i_chain, i_seq):
                continue
            if toks[i_atom].strip('"') != "CA":
                continue
            aa = _AA3.get(toks[i_comp].strip('"'))
            if not aa:
                continue
            ch = toks[i_chain].strip('"')
            try:
                rs = int(toks[i_seq])
            except ValueError:
                continue
            chains.setdefault(ch, []).append((rs, aa))
        out: dict[str, str] = {}
        for c, residues in chains.items():
            seen: dict[int, str] = {}
            for rs, aa in residues:
                seen.setdefault(rs, aa)
            out[c] = "".join(aa for _, aa in sorted(seen.items()))
        return out
    # PDB fallback: reuse _pdb_chains' inner logic on text
    chains2: dict[str, list[tuple[int, str]]] = {}
    for line in text.splitlines():
        if not line.startswith("ATOM"):
            continue
        if line[12:16].strip() != "CA":
            continue
        aa = _AA3.get(line[17:20].strip())
        if not aa:
            continue
        try:
            rs = int(line[22:26])
        except ValueError:
            continue
        chains2.setdefault(line[21], []).append((rs, aa))
    out2: dict[str, str] = {}
    for c, residues in chains2.items():
        seen2: dict[int, str] = {}
        for rs, aa in residues:
            seen2.setdefault(rs, aa)
        out2[c] = "".join(aa for _, aa in sorted(seen2.items()))
    return out2


def _normalize_struct_to_pdb(text: str, ext: str) -> tuple[str, str, dict[str, str]]:
    """Convert any structure (PDB or CIF) to PDB text with letter chain IDs.

    Returns (pdb_text, "pdb", chain_map) where chain_map is original→letter.
    Falls back to original (text, ext, identity-map) if gemmi is unavailable
    or parsing fails. BoltzGen CIFs use numeric chain IDs (`1`, `2`) that
    NGL Viewer's selection language can't address; PDB output renames them
    to A, B so the binder/target selectors work.
    """
    try:
        import gemmi  # local import — keeps module importable without gemmi
    except ImportError:
        return text, ext, {}
    try:
        if ext == "cif":
            block = gemmi.cif.read_string(text).sole_block()
            structure = gemmi.make_structure_from_block(block)
        else:
            structure = gemmi.read_pdb_string(text)
    except Exception:
        return text, ext, {}
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    chain_map: dict[str, str] = {}
    for model in structure:
        idx = 0
        for chain in model:
            old = chain.name
            if old in chain_map:
                chain.name = chain_map[old]
                continue
            if idx >= len(letters):
                break
            new = letters[idx]
            chain_map[old] = new
            chain.name = new
            idx += 1
        break  # first model only
    try:
        pdb_text = structure.make_pdb_string()
    except AttributeError:
        # older gemmi
        import io

        buf = io.StringIO()
        structure.write_pdb(buf)
        pdb_text = buf.getvalue()
    return pdb_text, "pdb", chain_map


def _pick_binder_target_chains(
    text: str,
    ext: str,
    target_seq: str | None,
) -> tuple[str, str]:
    """Return (binder_chain, target_chain). Detects target chain by sequence match.

    Falls back to (A, B) — the Boltz-2 default — when the structure has only
    one chain or can't be parsed.
    """
    if not target_seq:
        return "A", "B"
    chains = _struct_chains(text, ext)
    if not chains:
        return "A", "B"
    target_up = target_seq.upper().strip()
    matches = [c for c, s in chains.items() if s == target_up]
    if len(matches) == 1:
        target_chain = matches[0]
        others = [c for c in chains if c != target_chain]
        if len(others) == 1:
            return others[0], target_chain
    # No exact match — try by length (target len is short, usually 32 here)
    target_len = len(target_up)
    by_len = [(c, abs(len(s) - target_len)) for c, s in chains.items()]
    by_len.sort(key=lambda x: x[1])
    if by_len and by_len[0][1] <= 5 and len(chains) >= 2:
        target_chain = by_len[0][0]
        others = [c for c in chains if c != target_chain]
        if others:
            return others[0], target_chain
    return "A", "B"


_PC_SEQ_INDEX_CACHE: dict[str, dict[str, Path]] = {}


def _pc_seq_to_pdb_index(pdb_dir: Path, target_sequence: str | None = None) -> dict[str, Path]:
    """Build a {binder_sequence -> AF2-refold complex PDB} index for Proteina-Complexa.

    Prefers ``AF2/*_self_seq_0_model1.pdb`` (post-MPNN AF2 refold, full sidechains)
    over ``*_updated.pdb`` (CA-only flow-matching backbone) so the 3D viewer
    shows actual side chains. Falls back to ``*_updated.pdb`` only when the
    AF2 file is missing for a given design.
    """
    key = str(pdb_dir.resolve())
    if key in _PC_SEQ_INDEX_CACHE:
        return _PC_SEQ_INDEX_CACHE[key]
    target_up = (target_sequence or "").upper().strip()
    index: dict[str, Path] = {}

    def _add(path: Path) -> None:
        chains = _pdb_chains(path)
        if not chains:
            return
        for _cid, seq in chains.items():
            if target_up and seq == target_up:
                continue
            # First-seen-wins; full-atom AF2 file always preferred because we
            # iterate AF2 PDBs before any *_updated.pdb fallback.
            index.setdefault(seq, path)

    for pdb in pdb_dir.rglob("AF2/*_self_seq_0_model1.pdb"):
        _add(pdb)
    # Fallback: any CA-only *_updated.pdb whose sequence we haven't seen yet.
    for pdb in pdb_dir.rglob("*_updated.pdb"):
        _add(pdb)
    _PC_SEQ_INDEX_CACHE[key] = index
    return index


_GENERAL_SEQ_INDEX_CACHE: dict[str, dict[str, Path]] = {}


def _seq_to_pdb_index_general(pdb_dir: Path, target_seq: str | None = None, max_files: int = 6000) -> dict[str, Path]:
    """Build a {binder_sequence -> structure path} index for ANY tool's design dir.

    Parses every .pdb/.cif under *pdb_dir*, takes the chain whose sequence is NOT
    the target as the binder, and indexes it by sequence (first-seen wins). This
    lets the per-tool viewer match a design to its ORIGINAL structure by sequence,
    independent of the tool's filename convention. Cached per directory.
    """
    key = str(pdb_dir.resolve())
    if key in _GENERAL_SEQ_INDEX_CACHE:
        return _GENERAL_SEQ_INDEX_CACHE[key]
    target_up = (target_seq or "").upper().strip()
    index: dict[str, Path] = {}
    files = (list(pdb_dir.rglob("*.pdb")) + list(pdb_dir.rglob("*.cif")))[:max_files]
    for p in files:
        if "MONOMER_ONLY" in p.name:
            continue
        try:
            chains = _struct_chains(p.read_text(), p.suffix[1:] or "pdb")
        except Exception:
            continue
        if not chains:
            continue
        for seq in chains.values():
            if target_up and seq == target_up:
                continue
            index.setdefault(seq, p)
    _GENERAL_SEQ_INDEX_CACHE[key] = index
    return index


def _build_per_tool_pdb_viewer(
    tool: str,
    tool_csv_path: Path,
    tool_pdb_dir: Path,
    pdb_pattern: str,
    seq_to_ids: dict,
    n: int = 10,
    target_seq: str | None = None,
) -> str:
    """Build an NGL viewer for top-N designs from a tool's own native ranking.

    Args:
        tool: Tool name
        tool_csv_path: CSV sorted by the tool's native ranking
        tool_pdb_dir: Directory containing original design PDBs/CIFs
        pdb_pattern: Pattern to find PDB for each design (with {name} placeholder)
        seq_to_ids: sequence → {binder_id, adaptyv_rank} mapping
        n: Number of top designs to show
        target_seq: target sequence for per-design binder/target chain detection
    """
    entries = []
    colour = _TOOL_COLOURS_NGL.get(tool, _TOOL_COLOURS_NGL["unknown"])
    with open(tool_csv_path) as f:
        for i, row in enumerate(csv.DictReader(f)):
            if i >= n:
                break
            # Extract sequence and name
            seq = ""
            name = ""
            for key in ("sequence", "Sequence", "designed_chain_sequence", "designed_sequence", "self_sequence"):
                if row.get(key):
                    seq = row[key].strip().upper()
                    break
            for key in ("name", "id", "Design", "design_id", "binder_id"):
                if row.get(key):
                    name = row[key].strip()
                    break
            if not seq:
                continue

            eval_info = seq_to_ids.get(seq, {})

            # Tool-specific direct-path resolution: PXDesign rows carry
            # __source_file + chosen_struct_path columns that point exactly at
            # the design's CIF — no glob needed.
            direct_pdb = None
            sf = row.get("__source_file")
            cs = row.get("chosen_struct_path")
            if sf and cs:
                from pathlib import Path as _Path

                p = _Path(sf).parent / cs
                if p.exists():
                    direct_pdb = p
            if direct_pdb is not None:
                raw_ext = direct_pdb.suffix[1:] or "pdb"
                raw_text = direct_pdb.read_text()
                pdb_text, ext, _ = _normalize_struct_to_pdb(raw_text, raw_ext)
                bch, tch = _pick_binder_target_chains(pdb_text, ext, target_seq or row.get("target_sequence"))
                pdb_js = pdb_text.replace("\\", "\\\\").replace("`", "\\`")
                entries.append(
                    {
                        "rank": i + 1,
                        "name": name or direct_pdb.stem,
                        "binder_id": eval_info.get("binder_id", ""),
                        "eval_rank": eval_info.get("adaptyv_rank", ""),
                        "length": len(seq),
                        "ext": ext,
                        "binder_chain": bch,
                        "target_chain": tch,
                        "pdb": pdb_js,
                    }
                )
                continue  # next CSV row

            # Tool-specific sequence-based resolution: Proteina-Complexa PDBs
            # live under raw_evaluation_results/.../job_<X>/job_<X>_updated.pdb
            # with names that don't match the top-700 CSV's pc_top_N aliases.
            # Build a sequence → PDB index on first hit (cached per dir).
            if tool == "proteina_complexa":
                # target sequence: try to read from row.get("target_sequence") or skip
                target_seq_guess = row.get("target_sequence") or ""
                idx = _pc_seq_to_pdb_index(tool_pdb_dir, target_seq_guess)
                hit = idx.get(seq)
                if hit is not None and hit.exists():
                    raw_text = hit.read_text()
                    pdb_text, _ext, _ = _normalize_struct_to_pdb(raw_text, hit.suffix[1:] or "pdb")
                    bch, tch = _pick_binder_target_chains(pdb_text, "pdb", target_seq or target_seq_guess)
                    pdb_js = pdb_text.replace("\\", "\\\\").replace("`", "\\`")
                    entries.append(
                        {
                            "rank": i + 1,
                            "name": name or hit.stem,
                            "binder_id": eval_info.get("binder_id", ""),
                            "eval_rank": eval_info.get("adaptyv_rank", ""),
                            "length": len(seq),
                            "ext": "pdb",
                            "binder_chain": bch,
                            "target_chain": tch,
                            "pdb": pdb_js,
                        }
                    )
                    continue

            # General sequence-based resolution for ANY tool: match the design's
            # binder sequence to a structure in the tool's own design dir. Robust
            # to per-tool filename conventions.
            gidx = _seq_to_pdb_index_general(tool_pdb_dir, target_seq or row.get("target_sequence"))
            ghit = gidx.get(seq)
            if ghit is not None and ghit.exists():
                raw_text = ghit.read_text()
                pdb_text, gext, _ = _normalize_struct_to_pdb(raw_text, ghit.suffix[1:] or "pdb")
                bch, tch = _pick_binder_target_chains(pdb_text, gext, target_seq or row.get("target_sequence"))
                pdb_js = pdb_text.replace("\\", "\\\\").replace("`", "\\`")
                entries.append(
                    {
                        "rank": i + 1,
                        "name": name or ghit.stem,
                        "binder_id": eval_info.get("binder_id", ""),
                        "eval_rank": eval_info.get("adaptyv_rank", ""),
                        "length": len(seq),
                        "ext": gext,
                        "binder_chain": bch,
                        "target_chain": tch,
                        "pdb": pdb_js,
                    }
                )
                continue

            # Find matching PDB/CIF file.
            # Try exact name first, then strip common prefixes (e.g. "pc_0001_")
            pdb_file = None
            name_variants = [name] if name else []
            if name:
                # Strip leading "tool_NNNN_" prefix if present
                import re as _re

                m = _re.match(r"^([a-z]+_\d+_)(.+)$", name)
                if m:
                    name_variants.append(m.group(2))
                # Try the last underscore-separated suffix
                if "_" in name:
                    name_variants.append(name.split("_", 1)[-1])

            for variant in name_variants:
                candidates = list(tool_pdb_dir.rglob(pdb_pattern.format(name=variant)))
                # Drop binder-alone files — interface view needs target present.
                candidates = [p for p in candidates if "MONOMER_ONLY" not in p.name]
                candidates = sorted(candidates, key=lambda p: _native_pdb_sort_key(tool, p))
                if candidates:
                    pdb_file = candidates[0]
                    break

            if not pdb_file:
                # Try by rank — sanitize to avoid '**NNNN**' (invalid glob).
                # Use the pattern's extension only and wrap with single '*'.
                ext_for_rank = pdb_pattern.rsplit(".", 1)[-1] if "." in pdb_pattern else "pdb"
                rank_pattern = f"*{i + 1:04d}*.{ext_for_rank}"
                candidates = list(tool_pdb_dir.rglob(rank_pattern))
                if candidates:
                    pdb_file = candidates[0]

            if not pdb_file or not pdb_file.exists():
                continue

            raw_text = pdb_file.read_text()
            raw_ext = pdb_file.suffix[1:]
            # Normalize CIF -> PDB with letter chain IDs (BG/PXD use numeric chain ids)
            pdb_text, ext, _ = _normalize_struct_to_pdb(raw_text, raw_ext)
            bch, tch = _pick_binder_target_chains(pdb_text, ext, target_seq or row.get("target_sequence"))
            pdb_js = pdb_text.replace("\\", "\\\\").replace("`", "\\`")

            entries.append(
                {
                    "rank": i + 1,
                    "name": name or pdb_file.stem,
                    "binder_id": eval_info.get("binder_id", ""),
                    "eval_rank": eval_info.get("adaptyv_rank", ""),
                    "length": len(seq),
                    "ext": ext,
                    "binder_chain": bch,
                    "target_chain": tch,
                    "pdb": pdb_js,
                }
            )

    if not entries:
        return ""

    viewer_id = f"ngl-viewer-{tool}"
    info_id = f"ngl-info-{tool}"

    buttons_html = []
    for e in entries:
        title_parts = [f"{e['name']}", f"{e['length']}aa"]
        if e["binder_id"]:
            title_parts.append(f"eval_id={e['binder_id']}")
        if e["eval_rank"]:
            title_parts.append(f"eval_rank={e['eval_rank']}")
        title = " — ".join(title_parts)
        buttons_html.append(
            f'<button id="design-btn-{tool}-{e["rank"]}" class="design-btn-{tool}" '
            f'onclick="loadDesign_{tool.replace("-", "_")}({e["rank"]})" '
            f'style="background:{colour};color:white;border:none;padding:0.3em 0.6em;'
            f"margin:0.1em;border-radius:3px;cursor:pointer;font-size:0.8em;"
            f'transition:transform 0.1s,filter 0.1s,box-shadow 0.1s;" '
            f'title="{title}">#{e["rank"]}</button>'
        )

    pdb_data_js = ",\n        ".join(
        f'{e["rank"]}: {{"pdb": `{e["pdb"]}`, "ext": "{e["ext"]}", '
        f'"binder_chain": "{e.get("binder_chain", "A")}", "target_chain": "{e.get("target_chain", "B")}", '
        f'"name": "{e["name"]}", "binder_id": "{e["binder_id"]}", '
        f'"eval_rank": "{e["eval_rank"]}", "length": {e["length"]}}}'
        for e in entries
    )
    default_rank = entries[0]["rank"]

    tool_id = tool.replace("-", "_")
    html = f"""
<div style="margin:0.8em 0;padding:0.6em;border:1px solid #ddd;border-radius:4px;background:#fafafa;">
  <div style="font-size:0.78em;margin-bottom:0.3em;">
    <span style="background:#2e7d32;color:white;padding:1px 8px;border-radius:3px;
                 font-weight:bold;">NATIVE DESIGN PDB</span>
    <span style="color:#555;margin-left:0.4em;">
      original structure as produced by the design tool (not refolded)
    </span>
  </div>
  <div style="margin-bottom:0.4em;">
    {"".join(buttons_html)}
  </div>
  <div id="{info_id}" style="font-size:0.85em;color:#333;margin-bottom:0.3em;padding:0.3em 0.6em;background:#fff;border-radius:3px;">Click a rank button to load 3D structure</div>
  <div id="{viewer_id}" style="width:100%;height:400px;border:1px solid #ccc;border-radius:4px;background:#000;"></div>
</div>

<script>
(function() {{
  const designs_{tool_id} = {{
    {pdb_data_js}
  }};
  let stage_{tool_id} = null;
  let loaded_{tool_id} = false;

  function init_{tool_id}() {{
    if (typeof NGL === 'undefined') {{
      setTimeout(init_{tool_id}, 100);
      return;
    }}
    if (stage_{tool_id}) return;  // already initialized
    stage_{tool_id} = new NGL.Stage("{viewer_id}", {{backgroundColor: "white"}});
    window.addEventListener("resize", function() {{
      if (stage_{tool_id}) stage_{tool_id}.handleResize();
    }}, false);

    window.loadDesign_{tool_id} = function(rank) {{
      const d = designs_{tool_id}[rank];
      if (!d || !stage_{tool_id}) return;
      stage_{tool_id}.removeAllComponents();
      const blob = new Blob([d.pdb], {{type: "text/plain"}});
      stage_{tool_id}.loadFile(blob, {{ext: d.ext}}).then(function(comp) {{
        comp.addRepresentation("cartoon", {{sele: ":" + d.binder_chain, color: "{colour}", smoothSheet: true}});
        comp.addRepresentation("cartoon", {{sele: ":" + d.target_chain, color: "#9E9E9E", smoothSheet: true}});
        comp.autoView();
        stage_{tool_id}.handleResize();  // ensure visible after data load
      }});
      document.getElementById("{info_id}").innerHTML =
        "<b>" + d.name + "</b> &nbsp;·&nbsp; length=" + d.length + "aa" +
        (d.binder_id ? " &nbsp;·&nbsp; eval_id=" + d.binder_id : "") +
        (d.eval_rank ? " &nbsp;·&nbsp; eval_rank=" + d.eval_rank : "");
      // Mark the clicked button as the active selection (scoped to this tool's buttons)
      document.querySelectorAll(".design-btn-{tool}.active").forEach(function(b) {{
        b.classList.remove("active");
      }});
      const btn = document.getElementById("design-btn-{tool}-" + rank);
      if (btn) btn.classList.add("active");
      loaded_{tool_id} = true;
    }};
  }}

  // Init when parent details opens (NGL needs visible container)
  // Using MutationObserver to detect when details opens
  document.addEventListener("DOMContentLoaded", function() {{
    const viewer = document.getElementById("{viewer_id}");
    if (!viewer) return;
    const details = viewer.closest("details");
    if (details) {{
      details.addEventListener("toggle", function() {{
        if (details.open) {{
          init_{tool_id}();
          // Auto-load first design if not loaded yet
          if (!loaded_{tool_id}) {{
            setTimeout(function() {{ window.loadDesign_{tool_id}({default_rank}); }}, 200);
          }} else if (stage_{tool_id}) {{
            setTimeout(function() {{ stage_{tool_id}.handleResize(); }}, 100);
          }}
        }}
      }});
    }} else {{
      // Not in details — init immediately
      init_{tool_id}();
      setTimeout(function() {{ window.loadDesign_{tool_id}({default_rank}); }}, 200);
    }}
  }});
}})();
</script>
"""
    return html


# Per-tool native sort column for the "Top Designs per Tool" fallback path
# (used when --tool-csv isn't provided so we can't read the original CSV).
# Each column listed must be present in the merged metrics.csv we hand to the report.
_TOOL_NATIVE_SORT: dict[str, str] = {
    "mosaic": "ipsae_min_aux",  # Mosaic Boltz-2 internal loss signal
    "boltzgen": "native_bg_design_ipsae_min",  # BoltzGen's own design_ipsae_min (per INVESTIGATION §5)
}
_TOOL_NATIVE_SORT_DIR: dict[str, str] = {
    "mosaic": "desc",
    "boltzgen": "desc",
}


# Mapping: tool → (pdb_pattern, subdir_hints) for finding native PDBs
# Value is (glob_pattern, relative_subdirs_to_try)
_TOOL_PDB_HINTS = {
    # BoltzGen final designs have names like 'config_XXXX'
    "boltzgen": ("*{name}*.cif", []),
    # BindCraft accepted PDBs named by Design column
    "bindcraft": ("{name}*.pdb", []),
    # PXDesign structures are in output dirs
    "pxdesign": ("{name}*.pdb", []),
    # Proteina-Complexa structures
    "proteina_complexa": ("*{name}*.pdb", []),
    # Mosaic (no PDBs when TOP_K=0)
    "mosaic": ("*{name}*.pdb", []),
}


def generate_report(
    df: pd.DataFrame,
    summary: dict,
    output_path: str | Path,
    tool_csvs: dict[str, str | Path] | None = None,
    tool_pdb_dirs: dict[str, str | Path] | None = None,
    boltz2_results_dir: str | Path | None = None,
    primary_engine: str = "boltz",
    top_per_tool: int = 10,
    rank_method: str = "adaptyv",
    full_df: pd.DataFrame | None = None,
    tool_overrides: dict[str, dict] | None = None,
    provenance: dict | None = None,
    lightweight: bool = False,
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
    boltz2_results_dir = Path(boltz2_results_dir) if boltz2_results_dir else None

    # Extract the target sequence (constant across all rows in a single campaign)
    # so the 3D viewers can detect binder vs target chain per design instead of
    # relying on the brittle "chain A = binder" assumption.
    target_seq: str | None = None
    if "target_sequence" in df.columns:
        vals = df["target_sequence"].dropna().astype(str).str.upper().str.strip()
        if len(vals) and vals.iloc[0]:
            target_seq = vals.iloc[0]

    sort_df = df.copy()
    # active_rank reflects the --rank-by choice (== adaptyv_rank for the default),
    # so the HTML table/structures follow the selected ranking method.
    _order_col = "active_rank" if "active_rank" in sort_df.columns else "adaptyv_rank"
    if _order_col in sort_df.columns:
        sort_df = sort_df.sort_values(_order_col, ascending=True)

    # Tool counts
    tool_counts_str = ""
    if "source_tool" in sort_df.columns:
        counts = sort_df["source_tool"].value_counts()
        tool_counts_str = " &nbsp;|&nbsp; ".join(
            f'<span class="tool-{t}">{_tool_display(t, link=True)}: {n}</span>' for t, n in counts.items()
        )

    # Tier summary
    tier_summary = _tier_summary_to_html(sort_df)
    # Engine threshold legend + cross-engine agreement summary
    engine_threshold_legend = _engine_threshold_legend_html(sort_df)
    agreement_summary = _agreement_summary_html(sort_df)

    # Top 30 table (primary + collapsible secondary). flag_disagreement adds a
    # ⚠ warning icon next to the rank when agreement_count < 2 or per-engine
    # iPTM spread > 0.3 — surfaces "single-engine spike" / "one engine rejects"
    # cases that the rank alone hides.
    primary_cols, secondary_cols = _select_display_cols(sort_df, rank_method=rank_method)
    top30_primary = sort_df[primary_cols].head(30)
    _rank_col_for_flag = next(
        (c for c in ("active_rank", "two_stage_rank", "consensus_rank", "adaptyv_rank") if c in primary_cols),
        None,
    )
    top_table = _df_to_html(
        top30_primary,
        colour_tool=True,
        flag_disagreement=True,
        rank_col=_rank_col_for_flag,
        strike_when_false_col="wetlab_recommended" if "wetlab_recommended" in top30_primary.columns else None,
    ).replace("<table>", '<table style="width:100%">', 1)
    if secondary_cols:
        top30_secondary = sort_df[primary_cols[:2] + secondary_cols].head(30)
        top_table += (
            '\n<details style="margin:0.5em 0;">'
            '<summary style="cursor:pointer;font-size:0.85em;color:#1565C0;font-weight:bold;">'
            "Show additional metrics for Top 30</summary>\n"
            + _df_to_html(top30_secondary, colour_tool=True)
            + "\n</details>"
        )
    top_table += _advisory_legend_html(sort_df)

    # Summary statistics table
    summary_table = _summary_to_html(summary)

    # Plots
    dist_fig = plot_metric_distributions(sort_df)
    scatter_fig = None
    if rank_method == "two_stage":
        # Two-stage view: radar over the engine iPTMs (balance = consensus =
        # high mean-rank; spike = passes max-screen only) + the max-vs-mean
        # signature scatter. Replaces the ipsae-centric per-engine radars.
        try:
            radar_fig = plot_radar_iptm(sort_df, top_n=top_per_tool)
        except Exception:  # pragma: no cover - defensive
            radar_fig = plot_radar_chart(summary)
        try:
            scatter_fig = plot_max_vs_mean_iptm(sort_df, label_n=20)
        except Exception:  # pragma: no cover - defensive
            scatter_fig = None
        radar_fixed_fig = None
    else:
        # Per-engine radar (top-N per tool by that engine's ipSAE), one polar
        # subplot per available engine. Falls back to legacy radar if df lacks
        # the per-engine PAE-ipsae columns.
        try:
            radar_fig = plot_radar_per_engine(sort_df, top_n=top_per_tool)
        except Exception:  # pragma: no cover - defensive
            radar_fig = plot_radar_chart(summary)
        # Second radar: fixed per-tool selection by *our refold rank* (primary engine),
        # then measure each engine on the same designs.
        try:
            radar_fixed_fig = plot_radar_per_engine_uniform_selection(
                sort_df, primary_engine=primary_engine, top_n=top_per_tool
            )
        except Exception:  # pragma: no cover - defensive
            radar_fixed_fig = None

    dist_b64 = fig_to_base64(dist_fig)
    radar_b64 = fig_to_base64(radar_fig)
    scatter_b64 = fig_to_base64(scatter_fig) if scatter_fig is not None else ""
    radar_fixed_b64 = fig_to_base64(radar_fixed_fig) if radar_fixed_fig is not None else ""

    # Per-tool top 10 tables (collapsible, one per tool present in data)
    # When tool_csvs is provided, read top 10 from the tool's own CSV (native ranking)
    # and join with our binder_id via sequence matching.
    per_tool_top10 = ""
    if "source_tool" in sort_df.columns:
        tools_present = order_tools(sort_df["source_tool"].dropna().unique())
        if tools_present:
            per_tool_top10 = (
                "<h2>Top Designs per Tool "
                '<span style="background:#1565C0;color:white;padding:2px 10px;'
                "border-radius:4px;font-size:0.7em;font-weight:bold;vertical-align:middle;"
                'margin-left:0.4em;">NATIVE TOOL RANKING</span></h2>\n'
                '<p style="font-size:0.85em;color:#555;">'
                "Each tool's top designs ranked by <b>that tool's own internal scoring</b> "
                "(not the evaluator's cross-engine ranking). Shows <b>refolded designs only</b>, "
                "one row per backbone (MPNN/cycle siblings collapsed; never-refolded designs omitted)."
                "</p>\n"
            )

            # Build sequence → binder_id + rank lookup. Use the FULL (pre-collapse)
            # frame when available: df/sort_df here is representatives-only, so
            # multi-sequence-per-backbone tools (BindCraft MPNN siblings,
            # Protein-Hunter cycles) would otherwise leave their sibling rows'
            # eval_rank blank. active_rank is the primary (two-stage) ranking.
            def _r3(v):
                try:
                    return round(float(v), 3)
                except (TypeError, ValueError):
                    return v

            # eval_rank = the collapsed two-stage refold rank (dense, the same
            # ranking the Top-30 table and candidates.csv use), keyed by backbone
            # so sibling rows resolve to their representative's rank.
            grp_to_dense = {}
            if "design_group" in sort_df.columns and "active_rank" in sort_df.columns:
                grp_to_dense = dict(zip(sort_df["design_group"], sort_df["active_rank"], strict=False))

            seq_to_ids = {}
            lookup_df = full_df if full_df is not None else sort_df
            if "sequence" in lookup_df.columns:
                for _, row in lookup_df.iterrows():
                    seq = str(row.get("sequence", "")).strip().upper()
                    if seq and seq not in seq_to_ids:
                        seq_to_ids[seq] = {
                            "binder_id": row.get("binder_id", ""),
                            "adaptyv_rank": row.get("adaptyv_rank", ""),
                            "active_rank": grp_to_dense.get(row.get("design_group", ""), row.get("active_rank", "")),
                            "consensus_iptm_mean": _r3(row.get("consensus_iptm_mean", "")),
                            "consensus_ipsae_min_mean": _r3(row.get("consensus_ipsae_min_mean", "")),
                            "native_soluprot_score": _r3(row.get("native_soluprot_score", "")),
                            "binder_length": row.get("binder_length", ""),
                            "sequence": row.get("sequence", ""),
                            "design_group": row.get("design_group", ""),
                        }

            # Sequence → backbone (design_group) for the refold pool, so the
            # native section can drop never-refolded designs and collapse MPNN/
            # cycle siblings to one row per backbone.
            seq_to_group = {s: d["design_group"] for s, d in seq_to_ids.items() if d.get("design_group")}

            for tool in tools_present:
                display_name = _tool_display(tool)

                # Try reading from tool's original CSV
                if tool_csvs and tool in tool_csvs:
                    csv_path = Path(tool_csvs[tool])
                    if csv_path.exists():
                        try:
                            # Refolded designs only, one row per backbone (best
                            # native rank), in the tool's native order. Drops
                            # never-refolded designs and MPNN/cycle siblings so
                            # the native top-N is distinct backbones with no
                            # blank-metric rows.
                            native_df = collapse_native_df(csv_path, seq_to_group, top_n=top_per_tool)
                            native_df = native_df.drop(columns=["_seq_key", "_design_group"], errors="ignore")
                            if native_df.empty:
                                raise ValueError("no refolded native designs for this tool")
                            # Add our binder_id by matching sequence (full-chain
                            # column first — same preference collapse_native_df used).
                            seq_col = None
                            for candidate in _NATIVE_SEQ_COLS:
                                if candidate in native_df.columns:
                                    seq_col = candidate
                                    break
                            if seq_col:
                                native_df.insert(0, "native_rank", range(1, len(native_df) + 1))
                                _keyseq = native_df[seq_col].str.strip().str.upper()
                                # Evaluator columns alongside the tool's native ranking, matched by
                                # sequence: refold rank, cross-engine means, solubility, length, sequence.
                                _eval_cols = [
                                    ("eval_rank", "active_rank"),
                                    ("binder_id", "binder_id"),
                                    ("consensus_iptm_mean", "consensus_iptm_mean"),
                                    ("consensus_ipsae_min_mean", "consensus_ipsae_min_mean"),
                                    ("native_soluprot_score", "native_soluprot_score"),
                                    ("binder_length", "binder_length"),
                                    ("sequence", "sequence"),
                                ]
                                _pos = 1
                                for _col, _key in _eval_cols:
                                    if _col in native_df.columns:
                                        continue
                                    native_df.insert(
                                        _pos,
                                        _col,
                                        _keyseq.map(lambda s, k=_key: seq_to_ids.get(s, {}).get(k, "")),
                                    )
                                    _pos += 1
                            n = len(native_df)
                            tool_table = _df_to_html(native_df, colour_tool=False)

                            # Add 3D viewer if tool_pdb_dirs provided
                            viewer_block = ""
                            if tool_pdb_dirs and tool in tool_pdb_dirs:
                                pdb_dir = Path(tool_pdb_dirs[tool])
                                if pdb_dir.exists():
                                    pattern = _TOOL_PDB_HINTS.get(tool, ("*{name}*.pdb", []))[0]
                                    try:
                                        viewer_block = _build_per_tool_pdb_viewer(
                                            tool,
                                            csv_path,
                                            pdb_dir,
                                            pattern,
                                            seq_to_ids,
                                            n=top_per_tool,
                                            target_seq=target_seq,
                                        )
                                    except Exception as e:
                                        viewer_block = f"<p style='color:#888;'><em>3D viewer error: {e}</em></p>"

                            # Fallback: if no native PDB viewer was produced (no tool_pdb_dir,
                            # PDBs not found by pattern, or empty result), show refolded
                            # Boltz-2 structures for the same designs that are in the table.
                            if not viewer_block:
                                try:
                                    if "binder_id" in native_df.columns:
                                        ids_in_top = [str(b) for b in native_df["binder_id"].fillna("").tolist() if b]
                                    else:
                                        ids_in_top = []
                                    if ids_in_top and "binder_id" in sort_df.columns:
                                        # preserve native ranking order
                                        refold_df = (
                                            sort_df[sort_df["binder_id"].isin(ids_in_top)]
                                            .set_index("binder_id")
                                            .reindex(ids_in_top)
                                            .reset_index()
                                            .dropna(subset=["sequence"])
                                            .head(top_per_tool)
                                        )
                                    else:
                                        refold_df = sort_df[sort_df["source_tool"] == tool].head(top_per_tool)
                                    if not refold_df.empty:
                                        viewer_block = _build_per_tool_refold_viewer(
                                            tool,
                                            refold_df,
                                            boltz2_results_dir,
                                            n=top_per_tool,
                                            primary_engine=primary_engine,
                                            target_seq=target_seq,
                                        )
                                        if viewer_block:
                                            _eng = {
                                                "af3": "AlphaFold 3",
                                                "protenix": "Protenix",
                                                "boltz": "Boltz-2",
                                            }.get(primary_engine, primary_engine.upper())
                                            viewer_block = (
                                                "<p style='font-size:0.8em;color:#888;margin:0.2em 0;'>"
                                                "<em>Original design PDBs not found for this tool — "
                                                f"showing refolded {_eng} structures instead.</em></p>" + viewer_block
                                            )
                                except Exception as e:
                                    viewer_block = f"<p style='color:#888;'><em>3D viewer error: {e}</em></p>"

                            per_tool_top10 += (
                                f'<details style="margin:0.3em 0;">'
                                f'<summary style="cursor:pointer;font-weight:bold;">'
                                f"{display_name} — top {n} (native ranking)</summary>\n"
                                f"{tool_table}\n{viewer_block}\n</details>\n"
                            )
                            continue
                        except Exception:
                            pass  # Fall through to evaluator-based ranking

                # Fallback: use a per-tool native column when available;
                # else fall back to the evaluator's ranking within this tool.
                tool_only = sort_df[sort_df["source_tool"] == tool].copy()
                native_sort_col = _TOOL_NATIVE_SORT.get(tool)
                native_sort_dir = _TOOL_NATIVE_SORT_DIR.get(tool, "desc")
                used_native = False
                if native_sort_col and native_sort_col in tool_only.columns:
                    vals = pd.to_numeric(tool_only[native_sort_col], errors="coerce")
                    if vals.notna().any():
                        ascending = native_sort_dir == "asc"
                        tool_only = (
                            tool_only.assign(_sort=vals)
                            .sort_values("_sort", ascending=ascending, na_position="last")
                            .drop(columns=["_sort"])
                        )
                        used_native = True
                tool_df = tool_only.head(top_per_tool)
                n = len(tool_df)
                # If native sort applied, surface its column so it's visible in the table
                cols_for_table = list(primary_cols)
                if used_native and native_sort_col not in cols_for_table:
                    cols_for_table = cols_for_table + [native_sort_col]
                cols_for_table = [c for c in cols_for_table if c in tool_df.columns]
                tool_table = _df_to_html(tool_df[cols_for_table], colour_tool=True)
                # 3D viewer using refolded Boltz-2 PDBs (works for Mosaic etc.
                # without needing --tool-csv/--tool-pdb-dir flags)
                refold_viewer = ""
                try:
                    refold_viewer = _build_per_tool_refold_viewer(
                        tool,
                        tool_df,
                        boltz2_results_dir,
                        n=top_per_tool,
                        primary_engine=primary_engine,
                        target_seq=target_seq,
                    )
                except Exception as e:  # pragma: no cover - defensive
                    refold_viewer = f"<p style='color:#888;'><em>3D viewer error: {e}</em></p>"
                if used_native:
                    badge = (
                        f'<span style="background:#1565C0;color:white;padding:1px 6px;'
                        f'border-radius:3px;font-size:0.75em;margin-left:0.4em;">NATIVE RANK</span>'
                        f'<span style="font-size:0.8em;color:#555;margin-left:0.4em;">'
                        f"sorted by <code>{native_sort_col}</code> ({native_sort_dir})</span>"
                    )
                    label = f"{display_name} — top {n}{badge}"
                else:
                    label = (
                        f"{display_name} — top {n} "
                        f'<span style="font-size:0.8em;color:#888;">(evaluator ranking; '
                        f"no native column available)</span>"
                    )
                per_tool_top10 += (
                    f'<details style="margin:0.3em 0;">'
                    f'<summary style="cursor:pointer;font-weight:bold;">'
                    f"{label}</summary>\n"
                    f"{tool_table}\n{refold_viewer}\n</details>\n"
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
        "consensus_ipsae_min_mean",
        "iptm",
        "boltz_pae_iptm",
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
        "native_soluprot_score",
        "native_soluprot_passes",
        "qc_pass",
        "sequence",
        "target_sequence",
    ]
    full_cols_available = [c for c in _full_cols if c in sort_df.columns]
    full_table = _df_to_html(sort_df[full_cols_available], max_rows=None)

    # 3D viewer for top-20 refolded structures. When --lightweight is set,
    # the inline NGL viewer (which embeds ~140 KB of PDB text per design) is
    # skipped; instead we point at the on-disk top20_structures/ directory +
    # PyMOL session script. Cuts the HTML from ~5 MB to ~150 KB on big pools.
    structures_dir = output_path.parent / "top20_structures"
    if lightweight:
        if structures_dir.exists():
            ngl_viewer_block = (
                "<div class='callout' style='background:#fff3e0;border-left-color:#f57f17;'>"
                "<b>Lightweight mode</b> — inline 3D viewer was skipped to keep the HTML small "
                "(<code>--lightweight</code>). The top-20 refolded structures are still on disk: "
                f"<code>{structures_dir.relative_to(output_path.parent)}/</code>. Open the bundled "
                "PyMOL session (<code>view_top20.pml</code>) or any other viewer of choice."
                "</div>"
            )
        else:
            ngl_viewer_block = (
                "<p style='color:#888;'><em>Lightweight mode — no refolded structures available.</em></p>"
            )
    elif structures_dir.exists():
        ngl_viewer_block = _build_ngl_viewer(sort_df, structures_dir, target_seq=target_seq)
    else:
        ngl_viewer_block = "<p style='color:#888;'><em>No refolded structures available.</em></p>"

    engine_label_map = {"af3": "AlphaFold 3", "protenix": "Protenix", "boltz": "Boltz-2"}
    primary_engine_label = engine_label_map.get(primary_engine, primary_engine.upper())

    _pri_engine_label = engine_label_map.get(primary_engine, primary_engine.upper())
    if radar_fixed_b64:
        radar_fixed_block = (
            f"<h2>Tool Comparison — Same designs across engines</h2>\n"
            f'<p style="font-size:0.85em;color:#555;margin:0.2em 0 0.6em 0;">'
            f"Per-tool top-10 selected <b>once</b> by the {_pri_engine_label} refold rank "
            f"(our primary), then each panel shows how the same 10 designs per tool score "
            f"on the other engines. Useful for spotting engine disagreement on our actual ranked picks."
            f"</p>\n"
            f'<img src="data:image/png;base64,{radar_fixed_b64}" alt="Per-engine radar with fixed selection">'
        )
    else:
        radar_fixed_block = ""

    if scatter_b64:
        scatter_block = (
            f"<h2>Two-stage selection — max-screen vs mean-rank</h2>\n"
            f'<p style="font-size:0.85em;color:#555;margin:0.2em 0 0.6em 0;">'
            f"Each point is a design: x = <b>max</b> engine iPTM (Stage-1 screen), "
            f"y = <b>mean</b> engine iPTM (Stage-2 rank). The dotted red line is the "
            f"top-50% max-screen cut; the dashed diagonal is the upper bound (max ≥ mean) — "
            f"vertical distance below it = engine disagreement. Points near the diagonal in the "
            f"top-right are strong, agreed-upon binders; points that clear the screen but sit low "
            f"are single-engine spikes. Top-20 are labelled with their rank."
            f"</p>\n"
            f'<img src="data:image/png;base64,{scatter_b64}" alt="max vs mean engine iPTM scatter">'
        )
    else:
        scatter_block = ""

    # Item 10 plots (correlation heatmap + Pareto front). Both are optional —
    # render only when they have enough data.
    correlation_heatmap_block = ""
    try:
        heat_fig = plot_metric_correlation_heatmap(sort_df)
    except Exception as exc:
        print(f"[report] WARNING: correlation heatmap failed: {exc}")
        heat_fig = None
    if heat_fig is not None:
        heat_b64 = fig_to_base64(heat_fig)
        correlation_heatmap_block = (
            "<details style='margin:0.8em 0;'>"
            "<summary style='cursor:pointer;font-size:1.2em;color:#1a5276;font-weight:bold;'>"
            "Metric correlation heatmap "
            "<small style='color:#888;font-weight:normal;'>(redundancy check — Spearman ρ)</small></summary>"
            "<p style='font-size:0.85em;color:#555;margin:0.4em 0;'>"
            "Highly correlated pairs (|ρ| &gt; 0.9) are largely redundant signals — picking by one is "
            "almost equivalent to picking by the other. Use to identify metrics that don't add information."
            "</p>"
            f'<img src="data:image/png;base64,{heat_b64}" alt="Spearman correlation heatmap">'
            "</details>"
        )

    pareto_block = ""
    pareto_z_candidate = next((c for c in ("interface_dG_SASA_ratio", "interface_dG") if c in sort_df.columns), None)
    pareto_y_candidate = (
        "native_soluprot_score" if "native_soluprot_score" in sort_df.columns else "consensus_ipsae_min_mean"
    )
    try:
        pareto_fig = plot_pareto_front(
            sort_df,
            x="consensus_iptm_mean" if "consensus_iptm_mean" in sort_df.columns else "ipsae_min",
            y=pareto_y_candidate if pareto_y_candidate in sort_df.columns else "ipsae_min",
            z=pareto_z_candidate,
        )
    except Exception as exc:
        print(f"[report] WARNING: Pareto front failed: {exc}")
        pareto_fig = None
    if pareto_fig is not None:
        pareto_b64 = fig_to_base64(pareto_fig)
        pareto_block = (
            "<details style='margin:0.8em 0;'>"
            "<summary style='cursor:pointer;font-size:1.2em;color:#1a5276;font-weight:bold;'>"
            "Pareto front "
            "<small style='color:#888;font-weight:normal;'>(jointly-optimal designs across multiple objectives)</small></summary>"
            "<p style='font-size:0.85em;color:#555;margin:0.4em 0;'>"
            "Points on the dashed Pareto line aren't dominated on either axis — there is no design "
            "with strictly better confidence AND solubility (the two visible axes). Use to spot the "
            "design where a small drop in one objective buys you a big gain on another."
            "</p>"
            f'<img src="data:image/png;base64,{pareto_b64}" alt="Pareto front">'
            "</details>"
        )

    _ipsae_link = (
        "interface Predicted Structural Alignment Error, computed using the "
        '<a href="https://github.com/DunbrackLab/IPSAE" target="_blank">DunbrackLab d0<sub>res</sub> formula</a> '
        "(per-residue d0, uniform 10 Å PAE cutoff for all engines)"
    )
    _rank_desc = {
        "adaptyv": (
            f"The primary ranking metric is <b>ipSAE_min</b> — the minimum of binder→target and "
            f"target→binder {_ipsae_link}. This metric showed 1.4× better average precision than ipAE "
            f'across 3,766 experimentally tested designs in the <a href="https://doi.org/10.1101/2025.08.14.670059" '
            f'target="_blank">Adaptyv/Overath et al. 2025</a> benchmark. Quality tiers and the 0.61 pass '
            f"threshold follow their screening methodology. <b>agreement_count</b> reports how many refolding "
            f"engines score ipSAE_min above 0.61. Ranking sorts by quality tier, then agreement count, then ipSAE_min."
        ),
        "consensus_iptm": (
            f"Ranking is by <b>consensus_iptm</b> = max(boltz2, af3, esmfold2 iPTM) — the benchmark-validated "
            f"binder-vs-non-binder screen (the most predictive engine flips per target, so trusting the most "
            f"confident engine wins; macro-AUC ≈ 0.76). <b>ipSAE_min</b> ({_ipsae_link}) and "
            f"<b>agreement_count</b> are still computed and shown per design as secondary cross-validation."
        ),
        "two_stage": (
            f"Ranking is <b>two-stage mean iPTM</b>, validated on two <em>internal</em> 4-target benchmarks "
            f"(Adaptyv: 8 hand-curated targets, Kd-screened, n &gt; 3,700; ProteinBase: Nipah / EGFR / "
            f"IL7R / PD-L1, n = 175). <b>Stage 1 — screen:</b> <code>consensus_iptm_mean</code> = "
            f"mean(boltz2, af3, esmfold2 iPTM); the top 50% (<code>passes_max_screen</code>) form the "
            f"binder-likely pool. Mean was selected as default over max because it is more robust to "
            f"per-target engine blind spots (Adaptyv macro AUC <b>0.710 vs 0.689</b> for max; ~20 more "
            f"true binders recalled at the 50% cut). The legacy max-screen (<code>--screen-metric max</code>) "
            f"is the precision-leaning alternative (ProteinBase macro AUC <b>~0.755</b>). "
            f"<b>Stage 2 — rank:</b> survivors are ordered by <code>consensus_iptm_mean</code> (the same "
            f"metric — so Stage 1 + Stage 2 collapse to a single mean-iPTM gate-then-rank). Demanding "
            f"multi-engine consensus at the sharp end lifts <b>precision@top-10% to 0.92 vs 0.79</b> for "
            f"max alone. All designs are ranked — the screen is a flag, nothing is dropped. "
            f"<b>ipSAE_min</b> ({_ipsae_link}) and <b>agreement_count</b> are computed and shown per "
            f"design as cross-validation — and are surfaced in the Top-30 as the <span style='color:#c62828;"
            f"font-weight:bold;'>⚠</span> engine-disagreement flag — but are <em>not</em> the ranking key. "
            f"<b>Caveat:</b> both benchmarks comprise compact globular targets; transferability to serpins "
            f"(e.g. 2VDY), small peptide receptors (CALCA), or flexible/membrane targets is currently "
            f"<em>unvalidated</em>. Treat the rank as a strong shortlist signal, not a guarantee."
        ),
    }
    methodology_ranking_html = _rank_desc.get(rank_method, _rank_desc["adaptyv"])

    # Engine list reflects the engines actually present (populated) in this run.
    _engine_check = [
        ("<b>Boltz-2</b>", ("boltz_pae_iptm", "boltz_iptm")),
        ("<b>AlphaFold 3</b>", ("af3_iptm",)),
        ("<b>ESMFold2</b>", ("esmfold2_iptm",)),
        ("<b>Protenix</b>", ("protenix_iptm",)),
    ]
    _engines = [
        lbl
        for lbl, cols in _engine_check
        if any(c in sort_df.columns and pd.to_numeric(sort_df[c], errors="coerce").notna().any() for c in cols)
    ]
    if len(_engines) > 1:
        engines_present_html = ", ".join(_engines[:-1]) + " and " + _engines[-1]
    elif _engines:
        engines_present_html = _engines[0]
    else:
        engines_present_html = "one or more refolding engines"

    # Item 7 + 15: provenance + QC rules blocks live under the methodology
    # paragraph. Item 12: legend + screening intro adapt to rank_method.
    # Items 3 + 5: per-tool framing banner (pre-filter / modality / convergence).
    # Item 6: run provenance footer (CLI args / git_sha / engine versions).
    benchmark_provenance_block = _benchmark_provenance_html() if rank_method == "two_stage" else ""
    qc_rules_block = _qc_rules_html() if "qc_pass" in sort_df.columns else ""
    screening_summary_intro = _screening_summary_intro_html(rank_method)
    top_table_legend = _top_table_legend_html(rank_method, top30_primary)
    tool_classification_banner = _tool_classification_banner_html(sort_df, tool_overrides=tool_overrides)
    provenance_footer = _provenance_footer_html(provenance)
    top_per_family_block = _top_per_family_html(sort_df)

    html = _HTML_TEMPLATE.format(
        n_binders=len(sort_df),
        methodology_ranking_html=methodology_ranking_html,
        benchmark_provenance_block=benchmark_provenance_block,
        qc_rules_block=qc_rules_block,
        tool_classification_banner=tool_classification_banner,
        screening_summary_intro=screening_summary_intro,
        top_table_legend=top_table_legend,
        top_per_family_block=top_per_family_block,
        engines_present_html=engines_present_html,
        tool_counts_str=tool_counts_str or "—",
        engine_threshold_legend=engine_threshold_legend,
        agreement_summary=agreement_summary,
        tier_summary=tier_summary,
        top_table=top_table,
        summary_table=summary_table,
        dist_plot=dist_b64,
        radar_plot=radar_b64,
        scatter_block=scatter_block,
        radar_fixed_block=radar_fixed_block,
        correlation_heatmap_block=correlation_heatmap_block,
        pareto_block=pareto_block,
        per_tool_top10=per_tool_top10,
        ngl_viewer_block=ngl_viewer_block,
        full_table=full_table,
        primary_engine_label=primary_engine_label,
        provenance_footer=provenance_footer,
    )

    with output_path.open("w", encoding="utf-8") as fh:
        fh.write(html)

    print(f"[report] Written → {output_path}")


# ────────────────────────────────────────────────────────────────────────────
# Rank-method-aware helpers (Item 12: report-presentation sync).
#
# The ranking core moved from "ipSAE_min as primary" to "two-stage mean iPTM"
# but the report surface used to lag (stale "primary metric: ipSAE_min" labels,
# stale legend rows). These helpers regenerate the user-visible labels each
# render so methodology and tables tell the same story.
# ────────────────────────────────────────────────────────────────────────────


def _top_table_legend_html(rank_method: str, df: pd.DataFrame) -> str:
    """Per-column description table that sits under the Top-30 table.

    Rendered text matches the column set produced by :func:`_select_display_cols`
    for the active rank_method, so a reader can never get a description that
    references a column that isn't in the table above.
    """
    if rank_method == "two_stage":
        rows = [
            ("two_stage_rank", "Overall rank — Stage-1 screen survival, then mean engine iPTM (primary ranking key)."),
            (
                "passes_max_screen",
                "True ⇒ in the top 50% by the screen metric (mean iPTM by default — change with "
                "<code>--screen-metric max</code>).",
            ),
            ("binder_length", "Designed binder length in amino acids."),
            (
                "consensus_iptm_mean ↑",
                "<b>Primary ranking metric</b> — mean of per-engine PAE-iPTM. Higher = stronger multi-engine consensus.",
            ),
            ("consensus_iptm ↑", "Max engine iPTM (Stage-1 alternative screen via <code>--screen-metric max</code>)."),
            ("consensus_iptm_min ↑", "Min engine iPTM — conservative lower bound."),
            (
                "consensus_iptm_spread ↓",
                "Max − min engine iPTM. Large spread ⇒ engine disagreement; a row with spread &gt; 0.3 "
                "earns the <span style='color:#c62828;font-weight:bold;'>⚠</span> warning next to its rank.",
            ),
            (
                "agreement_count ↑",
                "Number of engines whose ipSAE_min &gt; 0.61 (Boltz-2 / AF3 / ESMFold2 / Protenix). "
                "agreement_count &lt; 2 earns the <span style='color:#c62828;font-weight:bold;'>⚠</span> warning.",
            ),
            (
                "boltz_pae_iptm / af3_iptm / esmfold2_iptm ↑",
                "Per-engine PAE-recomputed iPTM (the values entering the mean).",
            ),
            (
                "ipsae_min ↑",
                "Cross-validation — Boltz-2 ipSAE_min. Tier-banded (High &gt; 0.80, Medium &gt; 0.61). Not used for ranking.",
            ),
            ("consensus_ipsae_min_mean ↑", "Mean of per-engine ipSAE_min — diagnostic cross-validation column."),
            ("plddt_binder_mean ↑", "Mean binder pLDDT from Boltz-2 (also see plddt_binder_min in secondary)."),
        ]
    elif rank_method == "consensus_iptm":
        rows = [
            ("consensus_rank", "Overall rank — max(boltz, af3, esmfold2) iPTM, then ipSAE_min for tiebreak."),
            ("binder_length", "Designed binder length in amino acids."),
            ("consensus_iptm ↑", "<b>Primary ranking metric</b> — max engine iPTM (binder-vs-non-binder screen)."),
            ("consensus_iptm_mean ↑", "Mean engine iPTM — precision-leaning consensus metric."),
            ("consensus_iptm_min ↑", "Min engine iPTM — conservative lower bound."),
            ("consensus_iptm_spread ↓", "Engine disagreement (max − min). &gt; 0.3 flagged on the rank."),
            (
                "agreement_count ↑",
                "Engines with ipSAE_min &gt; 0.61. &lt; 2 flagged with <span style='color:#c62828;"
                "font-weight:bold;'>⚠</span> on the rank.",
            ),
            ("boltz_pae_iptm / af3_iptm / esmfold2_iptm ↑", "Per-engine PAE-recomputed iPTM."),
            ("ipsae_min ↑", "Cross-validation — Boltz-2 ipSAE_min. Tier-banded. Not the ranking key."),
            ("plddt_binder_mean ↑", "Mean binder pLDDT from Boltz-2."),
        ]
    else:  # adaptyv
        rows = [
            ("adaptyv_rank", "Overall rank — quality tier → agreement_count → ipSAE_min → ipTM → pLDDT."),
            ("binder_length", "Designed binder length in amino acids."),
            ("quality_tier", "High (&gt;0.80), Medium (&gt;0.61), Low (&gt;0.40), Reject (≤0.40) based on ipSAE_min."),
            ("agreement_count ↑", "Engines with ipSAE_min &gt; 0.61."),
            (
                "ipsae_min ↑",
                "<b>Primary ranking metric</b> — min(binder→target, target→binder) iPSAE from Boltz-2 PAE.",
            ),
            ("iptm ↑", "Interface predicted TM-score from Boltz-2 (cross-validation column under adaptyv)."),
            ("plddt_binder_mean ↑", "Mean binder pLDDT from Boltz-2."),
        ]
    # Show only rows whose column is actually present (or whose label aggregates
    # multiple per-engine columns).
    visible = [(c, d) for c, d in rows if _col_in_df_legend(c, df)]
    lines = [
        "<table style='font-size:0.8em;border-collapse:collapse;margin:0.5em 0 1.5em 0;color:#555;'>",
    ]
    for col, desc in visible:
        lines.append(
            f"<tr><td style='padding:2px 12px 2px 0;vertical-align:top;white-space:nowrap;'><b>{col}</b></td>"
            f"<td>{desc}</td></tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _col_in_df_legend(label: str, df: pd.DataFrame) -> bool:
    """True if the legend row's column (or any of its per-engine variants) is in df.

    Handles aggregated labels like "boltz_pae_iptm / af3_iptm / esmfold2_iptm".
    """
    cols = [c.strip() for c in label.split("↑")[0].split("↓")[0].strip().split("/")]
    return any(c.strip() in df.columns for c in cols if c.strip())


def _tool_classification_banner_html(
    df: pd.DataFrame,
    tool_overrides: dict[str, dict] | None = None,
) -> str:
    """Per-tool fairness banner (Items 3 + 5).

    Reports each tool's pool size, modality, pre-filter caveat, native-metric
    interpretation, and convergence verdict. Renders nothing if neither
    source_tool nor tool data are available.

    ``tool_overrides`` is keyed by tool name (lowercase) and may carry extractor
    runtime metadata (``pool_pre_filtered``, ``source_csv``, ``notes``); the CLI
    can populate it from extractor sidecar JSON or per-tool flags. When absent,
    we fall back to the static defaults in TOOL_CLASSIFICATION.
    """
    if "source_tool" not in df.columns:
        return ""
    from ..comparison.tool_classification import (
        convergence_status,
        get_classification,
    )

    counts = df["source_tool"].fillna("unknown").astype(str).str.lower().value_counts()
    if counts.empty:
        return ""

    overrides = {(k or "").lower(): v for k, v in (tool_overrides or {}).items()}

    # Aggregate ipSAE_min consensus per tool so convergence checks can fire.
    mean_per_tool: dict[str, float] = {}
    if "consensus_ipsae_min_mean" in df.columns:
        try:
            mean_per_tool = (
                df.assign(_t=df["source_tool"].fillna("unknown").astype(str).str.lower())
                .groupby("_t")["consensus_ipsae_min_mean"]
                .mean()
                .dropna()
                .to_dict()
            )
        except (TypeError, ValueError):
            mean_per_tool = {}

    rows = []
    any_flag = False
    any_failed = False
    for tool_name, count in counts.items():
        cls = get_classification(tool_name)
        ov = overrides.get(tool_name, {})
        display = cls.display_name if cls else tool_name
        modality = cls.modality if cls else "—"
        pre_filtered = bool(ov.get("pool_pre_filtered", cls.pool_pre_filtered_default if cls else False))
        source_csv = ov.get("source_csv", cls.source_csv_default if cls else None)
        notes = ov.get("notes")
        native_note = cls.native_metric_interpretation if cls else ""
        failed, reason = convergence_status(tool_name, mean_per_tool.get(tool_name))
        if pre_filtered or modality not in ("de-novo", "—") or failed:
            any_flag = True
        if failed:
            any_failed = True
        # Status badge
        if failed:
            status = (
                f"<span style='background:#c62828;color:white;padding:2px 8px;border-radius:3px;"
                f"font-size:0.75em;font-weight:bold;'>FAILED RUN</span><br>"
                f"<small style='color:#555;'>{reason}</small>"
            )
        elif pre_filtered:
            status = (
                "<span style='background:#f57f17;color:white;padding:2px 8px;border-radius:3px;"
                "font-size:0.75em;font-weight:bold;'>PRE-FILTERED POOL</span>"
            )
        elif cls and cls.modality not in ("de-novo", "—"):
            status = (
                f"<span style='background:#1565C0;color:white;padding:2px 8px;border-radius:3px;"
                f"font-size:0.75em;font-weight:bold;'>{cls.modality.upper()}</span>"
            )
        else:
            status = "<span style='color:#888;'>—</span>"

        notes_html = ""
        if notes:
            notes_html = f"<br><small style='color:#777;'><em>{notes}</em></small>"
        rows.append(
            "<tr>"
            f'<td><span class="tool-{tool_name}">{display}</span></td>'
            f"<td style='text-align:right;'><b>{int(count)}</b></td>"
            f"<td>{modality}</td>"
            f"<td>{source_csv or '—'}{notes_html}</td>"
            f"<td><small>{native_note}</small></td>"
            f"<td>{status}</td>"
            "</tr>"
        )

    summary_caveat = ""
    if any_failed:
        summary_caveat += (
            "<p style='color:#c62828;font-size:0.85em;margin:0.4em 0;'>"
            "<b>⚠ At least one tool's run did not converge</b> — its rows still appear in the "
            "Top-30 and the merged metrics CSV, but the per-tool mean is dominated by noise. "
            "Exclude FAILED-RUN tools from head-to-head comparisons.</p>"
        )
    if any_flag:
        return (
            "<details open style='margin:0.8em 0;'>"
            "<summary style='cursor:pointer;font-size:0.95em;color:#1565C0;font-weight:bold;'>"
            "Per-tool framing &nbsp;<small style='color:#888;font-weight:normal;'>"
            "(pre-filter / modality / convergence — fairness caveats)</small></summary>"
            f"<div style='padding:0.4em 0;'>{summary_caveat}"
            "<table style='font-size:0.85em;border-collapse:collapse;'>"
            "<tr><th style='text-align:left;'>Tool</th><th>Count</th><th style='text-align:left;'>Modality</th>"
            "<th style='text-align:left;'>Source CSV</th>"
            "<th style='text-align:left;'>Native metric (what it measures)</th>"
            "<th style='text-align:left;'>Status</th></tr>" + "".join(rows) + "</table>"
            "<p style='font-size:0.8em;color:#777;margin:0.4em 0 0 0;'>"
            "<b>PRE-FILTERED POOL</b> = the extractor read a curated subset (e.g. Protein-Hunter's "
            "<code>summary_high_iptm.csv</code> applies the tool's own iPTM + %X filter). Pool means "
            "are inflated relative to unfiltered tools — compare per-design rank, not per-tool mean. "
            "<b>VHH-CDR-REDESIGN</b> = sequences inside a fixed antibody framework; not de-novo. "
            "<b>FAILED RUN</b> = mean cross-engine ipSAE_min &lt; 0.20 — output is essentially noise. "
            "Status badges are advisory; ranking is unchanged.</p>"
            "</div></details>"
        )
    # Even when nothing is flagged we still show the count table (transparency
    # baseline). Use the same wrapper so the layout is consistent.
    return (
        "<details style='margin:0.8em 0;'>"
        "<summary style='cursor:pointer;font-size:0.95em;color:#1565C0;font-weight:bold;'>"
        "Per-tool framing</summary>"
        "<div style='padding:0.4em 0;'>"
        "<table style='font-size:0.85em;border-collapse:collapse;'>"
        "<tr><th style='text-align:left;'>Tool</th><th>Count</th><th style='text-align:left;'>Modality</th>"
        "<th style='text-align:left;'>Source CSV</th>"
        "<th style='text-align:left;'>Native metric (what it measures)</th>"
        "<th style='text-align:left;'>Status</th></tr>" + "".join(rows) + "</table></div></details>"
    )


def _provenance_footer_html(provenance: dict | None) -> str:
    """Item 6: footer with run reproducibility metadata.

    Renders only when ``provenance`` is non-empty. CLI auto-populates git_sha,
    evaluator_version, cli_args, run_timestamp_utc; ``engine_versions`` flows
    in from ``--engine-versions FILE`` (JSON/YAML).
    """
    if not provenance:
        return ""
    lines = [
        "<hr style='margin:2em 0 0.5em 0;border:0;border-top:1px solid #ddd;'>",
        "<details style='margin:0.5em 0;font-size:0.82em;color:#555;'>",
        "<summary style='cursor:pointer;font-weight:bold;color:#1565C0;'>"
        "Run provenance &nbsp;<small style='color:#888;font-weight:normal;'>"
        "(versions / git / CLI flags — for reproducibility)</small></summary>",
        "<table style='border-collapse:collapse;margin:0.4em 0;font-size:0.95em;'>",
    ]

    def _row(label, value):
        if value in (None, "", {}, []):
            return ""
        return (
            f"<tr><td style='padding:2px 12px 2px 0;vertical-align:top;white-space:nowrap;'>"
            f"<b>{label}</b></td><td>{value}</td></tr>"
        )

    lines.append(_row("git_sha", provenance.get("git_sha", "unknown")))
    lines.append(_row("evaluator_version", provenance.get("evaluator_version", "unknown")))
    lines.append(_row("run_timestamp_utc", provenance.get("run_timestamp_utc", "unknown")))
    cli_args = provenance.get("cli_args")
    if cli_args:
        if isinstance(cli_args, list):
            cli_str = "<code>" + " ".join(str(a) for a in cli_args) + "</code>"
        else:
            cli_str = f"<code>{cli_args}</code>"
        lines.append(_row("cli_args", cli_str))
    engine_versions = provenance.get("engine_versions") or {}
    if engine_versions:
        rows = "".join(
            f"<tr><td style='padding:2px 8px;'><code>{k}</code></td><td>{v}</td></tr>"
            for k, v in engine_versions.items()
        )
        ev_html = (
            f"<table style='border-collapse:collapse;font-size:0.95em;'>"
            f"<tr><th style='text-align:left;'>engine</th><th style='text-align:left;'>version</th></tr>"
            f"{rows}</table>"
        )
        lines.append(_row("engine_versions", ev_html))
    extra = provenance.get("extra") or {}
    for key, value in extra.items():
        lines.append(_row(key, value))
    lines.append("</table>")
    lines.append(
        "<p style='font-size:0.85em;color:#888;margin:0.3em 0;'>"
        "Pass <code>--engine-versions FILE</code> to <code>binder-compare report</code> to record "
        "engine checkpoints and random seeds. The other fields auto-populate from the running CLI.</p>"
    )
    lines.append("</details>")
    return "\n".join(lines)


def _screening_summary_intro_html(rank_method: str) -> str:
    """Single combined tier legend block above the screening tables.

    iPTM is the active ranking metric (under two_stage / consensus_iptm);
    ipSAE_min drives the ``quality_tier`` column and the tier-count table.
    Previously rendered as two near-identical paragraphs — readers had to
    cross-reference which threshold belonged to which metric. Now folded
    into one side-by-side table with a shared tier label.
    """
    if rank_method in ("two_stage", "consensus_iptm"):
        active = "consensus_iptm_mean" if rank_method == "two_stage" else "consensus_iptm"
        rows = [
            ("#2e7d32", "■ Strong / High", "≥ 0.80", "&gt; 0.80"),
            ("#f57f17", "■ Plausible / Medium", "≥ 0.60", "&gt; 0.61"),
            ("#e65100", "■ Weak / Low", "≥ 0.40", "&gt; 0.40"),
            ("#c62828", "■ Reject", "&lt; 0.40", "≤ 0.40"),
        ]
        body = "".join(
            f"<tr><td style='color:{c};white-space:nowrap;padding-right:1em;'><b>{label}</b></td>"
            f"<td style='padding-right:2em;'>{iptm}</td><td>{ipsae}</td></tr>"
            for c, label, iptm, ipsae in rows
        )
        return (
            "<p style='font-size:0.85em;color:#555;margin:0.3em 0;'>"
            "<b>Threshold bands.</b> Active ranking metric: <code>" + active + "</code>. "
            "The <code>quality_tier</code> column + tier-count table below use ipSAE_min."
            "</p>"
            "<table style='font-size:0.85em;border-collapse:collapse;margin:0.3em 0 0.6em 0;'>"
            "<tr><th style='text-align:left;padding-right:1em;'>Tier</th>"
            "<th style='text-align:left;padding-right:2em;'>iPTM band <small>(ranking)</small></th>"
            "<th style='text-align:left;'>ipSAE_min band <small>(quality_tier)</small></th></tr>" + body + "</table>"
        )
    # adaptyv: ipSAE_min IS the ranking metric, single band.
    return (
        "<p style='font-size:0.85em;color:#555;margin:0.3em 0;'>"
        "<b>ipSAE_min tiers</b> (the ranking metric under <code>adaptyv</code> — "
        "and the basis for <code>quality_tier</code>):"
        " &nbsp;<span style='color:#2e7d32'>■ High</span> &gt;0.80 &nbsp;"
        "<span style='color:#f57f17'>■ Medium</span> &gt;0.61 &nbsp;"
        "<span style='color:#e65100'>■ Low</span> &gt;0.40 &nbsp;"
        "<span style='color:#c62828'>■ Reject</span> ≤0.40"
        "</p>"
    )


def _qc_rules_html() -> str:
    """Surface BindCraft interface QC thresholds (Item 15) — `qc_pass` semantics."""
    # Lazy import: cli.qc_annotate is imported via cli.__init__ which transitively
    # imports cli.report which imports this module — would cycle at module load.
    from ..cli.qc_annotate import DEFAULT_QC

    return (
        "<details style='margin:0.8em 0;'>"
        "<summary style='cursor:pointer;font-size:0.85em;color:#1565C0;font-weight:bold;'>"
        "Show <code>qc_pass</code> rules (BindCraft interface panel)</summary>"
        "<div style='font-size:0.85em;color:#555;padding:0.4em 0 0.4em 1em;'>"
        "<p style='margin:0.3em 0;'>"
        "<code>qc_pass = True</code> requires <em>all five</em> BindCraft interface defaults to clear "
        "(BindCraft <code>settings_filters/default_filters.json</code>):"
        "</p>"
        "<table style='font-size:0.95em;border-collapse:collapse;margin:0.3em 0 0.6em 0;'>"
        f"<tr><td style='padding:2px 12px 2px 0;'><code>interface_dG</code> ≤ {DEFAULT_QC['dg_max']}</td>"
        "<td>Rosetta interface ΔG (REU). Negative = favourable.</td></tr>"
        f"<tr><td style='padding:2px 12px 2px 0;'><code>interface_sc</code> ≥ {DEFAULT_QC['sc_min']}</td>"
        "<td>Shape complementarity (0–1).</td></tr>"
        f"<tr><td style='padding:2px 12px 2px 0;'><code>interface_interface_hbonds</code> ≥ {DEFAULT_QC['hbonds_min']}</td>"
        "<td>Hydrogen bonds across the interface.</td></tr>"
        f"<tr><td style='padding:2px 12px 2px 0;'><code>interface_delta_unsat_hbonds</code> ≤ {DEFAULT_QC['unsat_max']}</td>"
        "<td>Buried unsatisfied H-bond donors/acceptors (lower = better).</td></tr>"
        f"<tr><td style='padding:2px 12px 2px 0;'><code>interface_nres</code> ≥ {DEFAULT_QC['nres_min']}</td>"
        "<td>Number of interface residues.</td></tr>"
        "</table>"
        "<p style='margin:0.3em 0;'><b>Advisory only.</b> The interface panel is a ~0.52-AUC binder "
        "classifier on PREDICTED structures — hard-gating with these thresholds removed ~2/3 of true "
        "binders from the Adaptyv 4-target shortlist. Designs flagged here are surfaced for review, "
        "never auto-dropped. Run <code>binder-compare qc-annotate --drop-failures</code> to opt into "
        "hard-filtering.</p>"
        "</div></details>"
    )


def _benchmark_provenance_html() -> str:
    """Item 7 follow-on: collapsible block citing the benchmarks the ranking is validated on."""
    return (
        "<details style='margin:0.8em 0;'>"
        "<summary style='cursor:pointer;font-size:0.85em;color:#1565C0;font-weight:bold;'>"
        "Show ranking benchmark provenance</summary>"
        "<div style='font-size:0.85em;color:#555;padding:0.4em 0 0.4em 1em;line-height:1.55;'>"
        "<p style='margin:0.3em 0;'><b>Two internal 4-target benchmarks underpin the default ranking.</b> "
        "Numbers below are macro-averaged AUC (binder vs non-binder discrimination) and "
        "precision-at-top-k. Reported per-target ranges hide the per-engine-per-target variability "
        "the consensus metrics paper over.</p>"
        "<table style='font-size:0.85em;border-collapse:collapse;margin:0.3em 0;'>"
        "<tr><th style='text-align:left;padding:2px 12px 2px 0;'>Benchmark</th>"
        "<th style='text-align:left;padding:2px 12px 2px 0;'>n</th>"
        "<th style='text-align:left;padding:2px 12px 2px 0;'>Targets</th>"
        "<th style='text-align:left;padding:2px 12px 2px 0;'>Mean-screen AUC</th>"
        "<th style='text-align:left;padding:2px 12px 2px 0;'>Max-screen AUC</th></tr>"
        "<tr><td style='padding:2px 12px 2px 0;'><b>Adaptyv</b> "
        "(<a href='https://doi.org/10.1101/2025.08.14.670059' target='_blank'>Overath et al. 2025</a>)</td>"
        "<td>&gt; 3,700</td>"
        "<td>4 (Kd-screened)</td>"
        "<td><b>0.710</b> ✓ default</td>"
        "<td>0.689</td></tr>"
        "<tr><td style='padding:2px 12px 2px 0;'><b>ProteinBase</b></td>"
        "<td>175</td>"
        "<td>Nipah, EGFR, IL7R, PD-L1</td>"
        "<td>~0.74</td>"
        "<td><b>~0.755</b> (precision-leaning)</td></tr>"
        "</table>"
        "<p style='margin:0.3em 0;'><b>Mean-screen vs max-screen.</b> Mean recalls ~20 more true binders "
        "at the 50% cut on Adaptyv (more robust to one engine's per-target blind spots); max is sharper "
        "on the ProteinBase ranking benchmark. Both Stage 1 and Stage 2 share the mean metric by default, "
        "so the headline ranking collapses to a single mean-iPTM gate-then-rank. Pass "
        "<code>--screen-metric max</code> to revert to max-first.</p>"
        "<p style='margin:0.3em 0;'><b>Precision@top-10%.</b> Two-stage (max-screen then mean-rank) lifts "
        "precision@top-10% to <b>0.92</b> vs <b>0.79</b> for max-screen alone, measured on ProteinBase. "
        "This is the headline number that motivated the move from single-stage to two-stage.</p>"
        "<p style='margin:0.3em 0;'><b>Transferability caveat.</b> All 8 validation targets across both "
        "benchmarks are compact globular proteins. The ranking is <em>unvalidated</em> on serpins "
        "(2VDY/CBG has a reactive-center loop and a deep steroid pocket), small peptide receptors "
        "(CALCA/CTR), antibody framework grafts, membrane proteins, and intrinsically disordered "
        "targets. Treat the rank as a strong shortlist signal, not a guarantee.</p>"
        "<p style='margin:0.3em 0;'><b>Engine bias.</b> <code>consensus_iptm</code> validates "
        "<em>binder vs non-binder</em> only — it does NOT rank affinity among confirmed binders. "
        "Use the interface-energy composite (<code>binder-compare affinity</code>, Part N) for that.</p>"
        "</div></details>"
    )


# Advisory annotation columns: SoluProt solubility score (--soluprot-results, renamed
# native_soluprot_*) + qc-annotate BindCraft interface panel (--qc-results) + epitope-
# match fraction (--epitope-results). Surfaced in the report only when present.
# ADVISORY — displayed for human review, never used to reorder or drop designs.
_ADVISORY_PRIMARY = [
    "wetlab_recommended",
    "native_soluprot_score",
    "qc_pass",
    "epitope_match_fraction",
    "family_id",
]
_ADVISORY_SECONDARY = [
    "wetlab_reason",
    "native_soluprot_passes",
    "qc_fail_reasons",
    # Interface energy decomposition (Item 13) — surfaces existing
    # interface_qc.py columns. Already in `_attach_qc_results`, just now
    # visible in the report.
    "interface_sc",
    "interface_dG",
    "interface_dG_SASA_ratio",
    "interface_delta_unsat_hbonds",
    "interface_interface_hbonds",
    "interface_hydrophobicity",
    "interface_nres",
    "epitope_status",
    "epitope_match_n",
    "epitope_n_interface",
    "epitope_off_target_residues",
    "epitope_matched_residues",
    "family_size",
    "family_rank",
]


def _top_per_family_html(df: pd.DataFrame, n_per_family: int = 1, top_n: int = 15) -> str:
    """Render the diversity 'Top per family' recommendations block (Item 1).

    Collapses the ranked frame to one representative per family (best
    active_rank wins), then surfaces the top ``top_n`` families. Renders
    nothing if no ``family_id`` column is present.
    """
    if "family_id" not in df.columns or df.empty:
        return ""
    from ..comparison.diversity import top_per_family

    rank_col = next(
        (c for c in ("active_rank", "two_stage_rank", "consensus_rank", "adaptyv_rank") if c in df.columns),
        None,
    )
    if rank_col is None:
        return ""
    representatives = top_per_family(df, n_per_family=n_per_family, sort_col=rank_col, ascending=True)
    representatives = representatives.head(top_n)
    cols = [
        rank_col,
        "binder_id",
        "source_tool",
        "binder_length",
        "family_id",
        "family_size",
    ]
    if "consensus_iptm_mean" in representatives.columns:
        cols.append("consensus_iptm_mean")
    if "epitope_match_fraction" in representatives.columns:
        cols.append("epitope_match_fraction")
    if "native_soluprot_score" in representatives.columns:
        cols.append("native_soluprot_score")
    cols = [c for c in cols if c in representatives.columns]
    table_html = _df_to_html(representatives[cols], colour_tool=True)
    return (
        "<h2>Top per family — diversity-aware shortlist</h2>"
        "<p style='font-size:0.85em;color:#555;line-height:1.55;'>"
        "Designs are clustered into <b>families</b> by sequence similarity (default ≥ 0.70 Jaccard on "
        "4-mers — see <code>binder-compare diversity</code>). This block shows the best-ranked design "
        "from each of the top families, so the wet-lab portfolio doesn't accidentally test 5 copies of "
        "one motif. <b>Advisory</b> — the main Top-30 ranking is unchanged."
        "</p>" + table_html
    )


def _advisory_legend_html(df: pd.DataFrame) -> str:
    """Legend for the advisory SoluProt + qc-annotate + epitope columns, shown only when present."""
    bits = []
    if "native_soluprot_score" in df.columns:
        bits.append("<b>soluprot_score</b> = SoluProt solubility (0–1, higher = more soluble; sequence-only screen)")
    if "qc_pass" in df.columns:
        bits.append(
            "<b>qc_pass</b> = BindCraft interface QC panel (shape-comp / ΔG / buried-unsat H-bonds / #interface res)"
        )
    if "epitope_match_fraction" in df.columns:
        bits.append(
            "<b>epitope_match_fraction</b> = fraction of intended hotspots within Cα-Cα cutoff of the binder "
            "in the refolded complex (target-side recall; &lt; 0.30 flagged as OFF_TARGET)"
        )
    if "family_id" in df.columns:
        bits.append(
            "<b>family_id / family_size</b> = sequence-similarity cluster (greedy Jaccard k-mer, default "
            "70% similarity threshold). Use the 'Top per family' block to pick non-redundant wet-lab candidates."
        )
    if "wetlab_recommended" in df.columns:
        bits.append(
            "<b>wetlab_recommended</b> = SoluProt pass + agreement_count ≥ 2 + min binder pLDDT ≥ 0.50 "
            "+ no FAILED RUN. Failing rows are rendered with a strike-through in the Top-30 (rank unchanged)."
        )
    if "interface_dG" in df.columns:
        # Item 13: surface the interface-energy decomposition columns (computed
        # by qc-annotate, already in the secondary table). The legend explains
        # what they decompose into.
        bits.append(
            "<b>interface_*</b> (Rosetta decomposition; from qc-annotate): "
            "<code>dG</code> Rosetta interface energy · "
            "<code>sc</code> shape complementarity · "
            "<code>interface_hbonds</code> H-bonds across interface · "
            "<code>delta_unsat_hbonds</code> buried unsatisfied polar atoms · "
            "<code>nres</code> # interface residues."
        )
    if not bits:
        return ""
    return (
        "<p style='font-size:0.85em;color:#555;'><b>Advisory annotations</b> "
        "(shown, never used to reorder or drop): &nbsp;" + " &nbsp;·&nbsp; ".join(bits) + "</p>"
    )


def _select_display_cols(df: pd.DataFrame, rank_method: str = "adaptyv") -> tuple[list[str], list[str]]:
    """Pick columns for the top-20 table: (primary, secondary).

    Primary columns are always visible; secondary are in a collapsible section.
    For the iptm-based rankings (two_stage / consensus_iptm) the iptm/consensus
    columns lead and ipSAE is demoted to secondary (still shown). adaptyv keeps
    the ipSAE-led layout.
    """
    if rank_method in ("two_stage", "consensus_iptm"):
        rank_col = "two_stage_rank" if rank_method == "two_stage" else "consensus_rank"
        # Lead with the iPTM ranking columns; surface agreement_count + spread
        # right at the top so engine-disagreement is visible in the Top-30 table
        # (per maintainer feedback: rank-3 with agreement=1 must not hide).
        primary = [rank_col, "binder_id", "source_tool", "binder_length"]
        if rank_method == "two_stage":
            primary.append("passes_max_screen")
        primary += [
            "consensus_iptm_mean",
            "consensus_iptm",
            "consensus_iptm_min",
            "consensus_iptm_spread",
            "agreement_count",
            "boltz_pae_iptm",
            "af3_iptm",
            "esmfold2_iptm",
            "ipsae_min",
            "consensus_ipsae_min_mean",
            "plddt_binder_mean",
        ]
        secondary = [
            "quality_tier",
            "boltz_pae_ipsae_min",
            "af3_ipsae_min",
            "esmfold2_ipsae_min",
            "consensus_ipsae_min_spread",
            "binder_ptm",
            "plddt_binder_min",
            "pae_bt",
            "pae_tb",
            "native_bg_design_ipsae_min",
            "native_dG",
            "native_dSASA",
            "native_shape_complementarity",
            "sequence",
        ]
        return (
            [c for c in primary + _ADVISORY_PRIMARY if c in df.columns],
            [c for c in _ADVISORY_SECONDARY + secondary if c in df.columns],
        )
    primary = [
        "adaptyv_rank",
        "binder_id",
        "source_tool",
        "binder_length",
        "quality_tier",
        "agreement_count",
        "ipsae_min",
        "boltz_pae_ipsae_min",
        "protenix_pae_ipsae_min",
        "af3_pae_ipsae_min",
        "iptm",
        "plddt_binder_mean",
    ]
    secondary = [
        "boltz_pae_iptm",
        "binder_ptm",
        "plddt_binder_min",
        "ipae",
        "pae_bt",
        "pae_tb",
        "ipsae_dg_composite",
        "ipsae_shape_composite",
        "native_bg_design_ipsae_min",  # BoltzGen's own ipSAE (per-tool native rank)
        "native_dG",
        "native_dSASA",
        "native_shape_complementarity",
        "sequence",
    ]
    return (
        [c for c in primary + _ADVISORY_PRIMARY if c in df.columns],
        [c for c in _ADVISORY_SECONDARY + secondary if c in df.columns],
    )


def _engine_threshold_legend_html(df: pd.DataFrame) -> str:
    """One-line legend showing per-engine thresholds in effect for this report."""
    rows = []
    for _engine, col, label in (
        ("boltz", "boltz_pae_ipsae_min", "Boltz-2 ≥ 0.61"),
        ("protenix", "protenix_pae_ipsae_min", "Protenix ≥ 0.61"),
        ("af3", "af3_pae_ipsae_min", "AF3 ≥ 0.61"),
        ("af2", "af2_pae_ipsae_min", "AF2 ≥ 0.30 <i>(informational; mis-calibrated on short targets)</i>"),
    ):
        if col in df.columns:
            rows.append(label)
    if not rows:
        return ""
    return (
        "<p style='font-size:0.85em;color:#555;'>"
        "<b>Per-engine cutoffs:</b> &nbsp;" + "&nbsp; · &nbsp;".join(rows) + "</p>"
    )


def _agreement_summary_html(df: pd.DataFrame) -> str:
    """Cross-engine agreement breakdown."""
    if "agreement_count" not in df.columns:
        return ""
    parts = [
        "<details open style='margin:0.5em 0;'>",
        "<summary style='cursor:pointer;font-weight:bold;'>Cross-engine agreement</summary>",
        "<table class='stat-table' style='margin-top:0.5em;'>",
        "<tr><th>engines passing</th><th>designs</th></tr>",
    ]
    ac = pd.to_numeric(df["agreement_count"], errors="coerce").fillna(0).astype(int)
    for k in sorted(ac.unique(), reverse=True):
        parts.append(f"<tr><td><b>{k}</b></td><td>{int((ac == k).sum())}</td></tr>")
    parts.append("</table></details>")
    return "\n".join(parts)


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
    flag_disagreement: bool = False,
    rank_col: str | None = None,
    strike_when_false_col: str | None = None,
) -> str:
    """Render a DataFrame as an HTML table.

    flag_disagreement: when True, annotate the rank cell with a warning icon
    when the row shows weak cross-engine agreement (agreement_count < 2 OR
    consensus_iptm_spread > 0.3). The flag is purely advisory — the rank itself
    is unchanged. rank_col is the column to attach the warning to (defaults
    to the first numeric *rank* column found).
    """
    if max_rows is not None:
        df = df.head(max_rows)

    # Detect numeric columns for right-alignment
    numeric_cols = set(df.select_dtypes(include="number").columns)

    # Engine-disagreement flag setup (advisory; never reorders / drops).
    # Triggers when agreement_count < 2 OR per-engine ipTM max-min spread > 0.3.
    # Both thresholds documented in the methodology block of the report.
    DISAGREEMENT_AGREEMENT_MAX = 1  # warn when agreement_count <= this
    DISAGREEMENT_SPREAD_MIN = 0.3  # warn when consensus_iptm_spread >= this
    disagreement_lookup: dict[int, str] = {}
    rank_warn_col: str | None = None
    if flag_disagreement:
        # Pick the rank column to attach the flag to (caller-supplied wins).
        rank_warn_col = rank_col
        if rank_warn_col is None:
            for candidate in ("active_rank", "two_stage_rank", "consensus_rank", "adaptyv_rank"):
                if candidate in df.columns:
                    rank_warn_col = candidate
                    break
        agreement = pd.to_numeric(df["agreement_count"], errors="coerce") if "agreement_count" in df.columns else None
        spread = (
            pd.to_numeric(df["consensus_iptm_spread"], errors="coerce")
            if "consensus_iptm_spread" in df.columns
            else None
        )
        for idx in df.index:
            reasons = []
            if (
                agreement is not None
                and pd.notna(agreement.get(idx))
                and agreement.get(idx) <= DISAGREEMENT_AGREEMENT_MAX
            ):
                reasons.append(f"only {int(agreement.get(idx))}/3 engines pass ipSAE 0.61")
            if spread is not None and pd.notna(spread.get(idx)) and spread.get(idx) >= DISAGREEMENT_SPREAD_MIN:
                reasons.append(f"per-engine iPTM spread {spread.get(idx):.2f}")
            if reasons:
                disagreement_lookup[idx] = "; ".join(reasons)

    def fmt(col: str, val, row_idx=None) -> str:
        is_num = col in numeric_cols
        cls = ' class="num"' if is_num else ""
        # Inject engine-disagreement warning icon next to the rank value.
        warning_html = ""
        if rank_warn_col and col == rank_warn_col and row_idx in disagreement_lookup:
            warning_html = (
                f' <span title="Engine disagreement — {disagreement_lookup[row_idx]}. '
                f'Verify Top-30 carefully before wet-lab handoff." '
                f'style="color:#c62828;font-weight:bold;cursor:help;">⚠</span>'
            )
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return f"<td{cls}>—{warning_html}</td>"
        if isinstance(val, float):
            if col == "binder_length":
                return f"<td{cls}>{int(val)}{warning_html}</td>"
            return f"<td{cls}>{val:.4f}{warning_html}</td>"
        # Truncate long strings like sequences
        if isinstance(val, str) and len(val) > 20 and col in ("sequence", "target_sequence"):
            return f'<td title="{val}">{val[:17]}…{warning_html}</td>'
        return f"<td{cls}>{val}{warning_html}</td>"

    header = (
        "<tr>"
        + "".join(
            f'<th style="text-align:right">{_col_header(c)}</th>' if c in numeric_cols else f"<th>{_col_header(c)}</th>"
            for c in df.columns
        )
        + "</tr>"
    )

    rows = []
    for idx, row in df.iterrows():
        cells = "".join(
            fmt(c, _tool_display(v) if c == "source_tool" and isinstance(v, str) else v, row_idx=idx)
            for c, v in zip(df.columns, row)
        )
        # Item 9: strike-through any row whose recommendation column is False.
        # The row stays present (the rank doesn't move); the visual cue tells
        # the reader to skip it when picking wet-lab candidates.
        strike_style = ""
        if strike_when_false_col and strike_when_false_col in df.columns:
            val = row.get(strike_when_false_col)
            is_falsey_str = val is not None and val is not True and str(val).lower() in ("false", "0", "no")
            if val is False or is_falsey_str:
                strike_style = "text-decoration:line-through;opacity:0.6;"
        attrs: list[str] = []
        if colour_tool and "source_tool" in df.columns:
            tool = row.get("source_tool", "")
            attrs.append(f'class="tool-{tool}"')
        if strike_style:
            attrs.append(f'style="{strike_style}"')
        rows.append(f"<tr {' '.join(attrs)}>{cells}</tr>")

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
    "iptm": (
        "Interface predicted TM-score from Boltz-2 — measures overall interface quality. "
        "Higher = more confident complex prediction. Want >0.8."
    ),
    "boltz_pae_iptm": (
        "ipTM recomputed from Boltz-2 PAE matrix (rather than model-reported value). "
        "More consistent across runs. Higher = better."
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
        "Number of independent prediction engines that score ipSAE_min above the 0.61 pass threshold. "
        "Currently Boltz-2 only (0 or 1); Protenix (x86) and AlphaFold 3 (aarch64 / DGX Spark) "
        "will be added as the refactor progresses. Higher = more engines agree = stronger candidate."
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
