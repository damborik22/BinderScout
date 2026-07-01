"""CLI subcommand: binder-compare epitope-map.

Render a single interactive target structure that shows *where* the pool binds:

- the target cartoon + surface coloured by **per-residue contact frequency**
  (the aggregate "where do binders land" heatmap), and
- per-**binding-mode** toggles — designs clustered by footprint — each lighting
  up that mode's consensus patch in a distinct colour, plus an optional outline
  of the intended hotspot pocket.

Usage:
    binder-compare epitope-map \\
        --epitope-results epitope.csv \\
        --target-structure refold/af3_out/af3_0001.pdb --target-chain A \\
        --hotspots "18,19,22,232,240,242,260,263,264,267,366,368,371" \\
        -o binding_map.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..comparison.epitope import parse_hotspots
from ..comparison.epitope_map import (
    cluster_binding_modes,
    design_footprints,
    mode_consensus,
    residue_frequency,
)
from ..io.read import read_csv_safe

# Distinct, colour-blind-friendlyish palette for binding modes.
_MODE_COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22"]

# Vendored NGL (relative to the Evaluator package root) — inlined by default so the
# map is self-contained (no unpkg CDN dependency; works offline / behind Brave Shields).
_VENDORED_NGL = "tools/ngl/ngl-2.3.1.min.js"


def _recolor_target_pdb(pdb_path: Path, chain: str, freq_pct: dict[int, float]) -> str:
    """Return the target chain's ATOM records with the B-factor column overwritten
    by each residue's contact-frequency percentage (so NGL's bfactor colour scheme
    paints the aggregate heatmap). Non-target chains are dropped."""
    lines_out: list[str] = []
    for line in pdb_path.read_text().splitlines():
        if line.startswith(("ATOM", "HETATM")):
            if line[21] != chain:
                continue
            try:
                resnum = int(line[22:26])
            except ValueError:
                continue
            pct = freq_pct.get(resnum, 0.0)
            line = line[:60] + f"{pct:6.2f}" + line[66:]
        if line.startswith(("ATOM", "HETATM", "TER", "END")):
            lines_out.append(line)
    return "\n".join(lines_out)


def _sele(residues: list[int], chain: str) -> str:
    if not residues:
        return "none"
    return "(" + " or ".join(str(r) for r in residues) + ") and :" + chain


def run(args: argparse.Namespace) -> None:
    epi_path = Path(args.epitope_results)
    if not epi_path.exists():
        print(f"Error: --epitope-results not found: {epi_path}", file=sys.stderr)
        sys.exit(1)
    df = read_csv_safe(epi_path)
    footprints = design_footprints(df.to_dict("records"))
    if not footprints:
        print("Error: no usable footprints in epitope CSV (need matched/off-target residue columns).", file=sys.stderr)
        sys.exit(1)
    n_designs = len(footprints)

    chain = args.target_chain.upper()
    tgt = Path(args.target_structure)
    if not tgt.exists():
        print(f"Error: --target-structure not found: {tgt}", file=sys.stderr)
        sys.exit(1)

    freq = residue_frequency(footprints)
    freq_pct = {r: 100.0 * c / n_designs for r, c in freq.items()}
    max_pct = max(freq_pct.values()) if freq_pct else 100.0
    pdb_text = _recolor_target_pdb(tgt, chain, freq_pct)

    # Binding modes (footprint clustering), keep the substantive ones.
    modes_all = cluster_binding_modes(footprints, threshold=args.mode_threshold)
    modes = [m for m in modes_all if len(m["members"]) >= args.min_mode_size][: args.max_modes]
    mode_data = []
    for i, m in enumerate(modes):
        cons = mode_consensus(footprints, m["members"], frac=args.consensus_frac)
        mode_data.append(
            {
                "label": f"Mode {i + 1}",
                "n": len(m["members"]),
                "color": _MODE_COLORS[i % len(_MODE_COLORS)],
                "sele": _sele(cons, chain),
                "residues": cons,
            }
        )

    hotspots = parse_hotspots(args.hotspots) if args.hotspots else []
    pocket_res = sorted({h.resnum for h in hotspots})
    pocket_sele = _sele(pocket_res, chain)

    # Resolve the NGL library: inline it (self-contained, immune to CDN blocks /
    # Brave Shields / offline) by default from the vendored copy; --ngl-js overrides
    # the path; --ngl-cdn falls back to the unpkg <script src>.
    ngl_inline = None
    if not args.ngl_cdn:
        ngl_path = Path(args.ngl_js) if args.ngl_js else (Path(__file__).resolve().parents[2] / _VENDORED_NGL)
        if ngl_path.is_file():
            ngl_inline = ngl_path.read_text()
        else:
            print(f"[epitope-map] note: vendored NGL not found at {ngl_path}; using CDN.", file=sys.stderr)

    top_freq = sorted(freq.items(), key=lambda kv: -kv[1])[:15]
    html = _render_html(
        pdb_text=pdb_text,
        chain=chain,
        n_designs=n_designs,
        max_pct=max_pct,
        modes=mode_data,
        pocket_sele=pocket_sele,
        pocket_res=pocket_res,
        top_freq=[(r, c, round(100.0 * c / n_designs)) for r, c in top_freq],
        title=args.title or tgt.stem,
        ngl_inline=ngl_inline,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(
        f"[epitope-map] {out}: {n_designs} designs, {len(mode_data)} binding modes "
        f"(of {len(modes_all)} raw), {len(freq)} target residues contacted. "
        f"Most-contacted: {', '.join(f'{r}({round(100 * c / n_designs)}%)' for r, c in top_freq[:5])}.",
        file=sys.stderr,
    )


def _render_html(
    *, pdb_text, chain, n_designs, max_pct, modes, pocket_sele, pocket_res, top_freq, title, ngl_inline=None
) -> str:
    ngl_script = (
        "<script>" + ngl_inline + "</script>"
        if ngl_inline
        else '<script src="https://unpkg.com/ngl@2.3.1/dist/ngl.js"></script>'
    )
    pdb_js = json.dumps(pdb_text)
    modes_js = json.dumps(modes)
    mode_buttons = "".join(
        f"<button onclick='toggleMode({i})' id='mbtn{i}' style='margin:2px;border:2px solid {m['color']};"
        f"background:#fff;border-radius:4px;cursor:pointer;padding:3px 8px;font-size:0.85em;'>"
        f"<span style='color:{m['color']};font-weight:bold;'>&#9632;</span> {m['label']} "
        f"(n={m['n']}, {len(m['residues'])} res)</button>"
        for i, m in enumerate(modes)
    )
    pocket_btn = (
        "<button onclick='togglePocket()' id='pbtn' style='margin:2px;border:2px solid #2e7d32;background:#fff;"
        "border-radius:4px;cursor:pointer;padding:3px 8px;font-size:0.85em;'>"
        "<span style='color:#2e7d32;font-weight:bold;'>&#9632;</span> Intended pocket "
        f"({len(pocket_res)} res)</button>"
        if pocket_res
        else ""
    )
    top_rows = "".join(
        f"<tr><td style='padding:1px 8px;'>{chain}{r}</td><td style='padding:1px 8px;'>{c}/{n_designs}</td>"
        f"<td style='padding:1px 8px;'>{pct}%</td></tr>"
        for r, c, pct in top_freq
    )
    pocket_set = set(pocket_res)
    mode_rows = "".join(
        f"<tr><td style='padding:1px 8px;color:{m['color']};white-space:nowrap;'>&#9632; {m['label']}</td>"
        f"<td style='padding:1px 8px;'>{m['n']}</td>"
        f"<td style='padding:1px 8px;'>{sum(1 for r in m['residues'] if r in pocket_set)}/{len(m['residues'])}</td>"
        f"<td style='padding:1px 8px;font-family:monospace;'>"
        f"{', '.join(str(r) for r in m['residues'][:18])}{'…' if len(m['residues']) > 18 else ''}</td></tr>"
        for m in modes
    )
    mode_table = (
        "<div style='margin-top:0.8em;'><b style='font-size:0.9em;'>Binding modes (footprint clusters)</b>"
        "<table><tr><th>Mode</th><th>Designs</th><th>In pocket</th><th>Consensus residues</th></tr>"
        + mode_rows
        + "</table></div>"
        if mode_rows
        else ""
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Target binding map — {title}</title>
{ngl_script}
<style>body{{font-family:system-ui,Arial,sans-serif;margin:1em;color:#222;}}
#viewer{{width:100%;height:560px;border:1px solid #ccc;border-radius:4px;background:#fff;}}
table{{border-collapse:collapse;font-size:0.85em;}} th{{text-align:left;padding:1px 8px;}}</style>
</head><body>
<h2>Target binding map — {title}</h2>
<p style="font-size:0.9em;color:#555;max-width:60em;">
The target cartoon + surface is coloured by <b>contact frequency</b> — how many of the {n_designs}
designs touch each residue (white = none, deep red = most, max {max_pct:.0f}%). Toggle a
<b>binding mode</b> (designs clustered by which residues they contact) to light up that mode's
consensus patch; toggle the intended pocket to compare. This shows <em>where</em> the families land.</p>
<div style="margin:0.5em 0;"><b>Modes &amp; overlays:</b><br>{pocket_btn}{mode_buttons}
<button onclick="clearAll()" style="margin:2px;padding:3px 8px;border-radius:4px;cursor:pointer;font-size:0.85em;">Clear overlays</button></div>
<div id="viewer"></div>
<div style="display:flex;gap:2em;flex-wrap:wrap;margin-top:0.6em;">
<div><b style="font-size:0.9em;">Most-contacted target residues</b>
<table><tr><th>Residue</th><th>Designs</th><th>%</th></tr>{top_rows}</table></div>
<div style="font-size:0.85em;color:#555;max-width:24em;">
<b>Heatmap scale</b>: white (0%) &rarr; <span style="color:#d73027;font-weight:bold;">red</span> ({max_pct:.0f}%).
The B-factor column of the embedded structure carries each residue's contact %.</div>
</div>
{mode_table}
<script>
var PDB = {pdb_js};
var MODES = {modes_js};
var POCKET_SELE = {json.dumps(pocket_sele)};
var MAXPCT = {max_pct:.2f};
var stage = null, comp = null, reps = {{}};
function webglOK() {{
  try {{ var c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl") || c.getContext("experimental-webgl"))); }}
  catch (e) {{ return false; }}
}}
function showMsg(h) {{ document.getElementById("viewer").innerHTML =
  "<div style='padding:1.4em;font-size:0.95em;color:#333;line-height:1.6;'>" + h + "</div>"; }}
if (typeof NGL === "undefined") {{
  showMsg("<b>The 3D library (NGL) did not load.</b> The binding data is fully available in the "
    + "tables below. If this map is served from the internet and NGL is blocked, disable "
    + "<b>Brave Shields</b> for this page and reload (this build normally inlines NGL, so you should "
    + "not see this).");
}} else if (!webglOK()) {{
  showMsg("<b>The 3D viewer needs WebGL, which is disabled in this browser.</b> The binding data is "
    + "fully available in the tables below (aggregate footprint + per-mode consensus residues).<br><br>"
    + "<b>To enable the interactive 3D:</b><br>"
    + "&bull; <b>Brave / Chrome on Linux</b> (the GPU is often blocklisted): open <code>brave://flags</code> "
    + "(or <code>chrome://flags</code>) &rarr; set <b>&ldquo;Override software rendering list&rdquo;</b> = "
    + "<b>Enabled</b> &rarr; <b>Relaunch</b>. This turns on software WebGL (SwiftShader).<br>"
    + "&bull; And/or Settings &rarr; System &rarr; <b>Use graphics acceleration when available</b> = on; "
    + "drop <b>Brave Shields</b> for this page.<br>"
    + "&bull; Check <code>brave://gpu</code> &mdash; the WebGL rows should not say &lsquo;Disabled&rsquo;.");
}} else {{
  try {{
    stage = new NGL.Stage("viewer", {{backgroundColor: "white"}});
    window.addEventListener("resize", function(){{ stage.handleResize(); }});
    var blob = new Blob([PDB], {{type: "text/plain"}});
    stage.loadFile(blob, {{ext: "pdb"}}).then(function(c) {{
      comp = c;
      comp.addRepresentation("cartoon", {{colorScheme:"bfactor", colorScale:"OrRd", colorDomain:[0, MAXPCT]}});
      comp.addRepresentation("surface", {{colorScheme:"bfactor", colorScale:"OrRd", colorDomain:[0, MAXPCT],
        opacity:0.35, surfaceType:"av", probeRadius:1.4}});
      comp.autoView();
    }}).catch(function(err) {{ showMsg("<b>Structure failed to load:</b> " + err); }});
  }} catch (e) {{
    showMsg("<b>3D init failed:</b> " + e.message + "<br>The binding data is available in the tables below.");
  }}
}}
function toggleMode(i) {{
  if (!comp) return;
  var key = "mode"+i, btn = document.getElementById("mbtn"+i);
  if (reps[key]) {{ reps[key].forEach(function(r){{comp.removeRepresentation(r);}}); reps[key]=null; btn.style.background="#fff"; return; }}
  var m = MODES[i];
  reps[key] = [
    comp.addRepresentation("ball+stick", {{sele:m.sele, color:m.color}}),
    comp.addRepresentation("surface", {{sele:m.sele, color:m.color, opacity:0.5, surfaceType:"av"}})
  ];
  btn.style.background = m.color + "22";
}}
function togglePocket() {{
  if (!comp) return;
  var btn = document.getElementById("pbtn");
  if (reps["pocket"]) {{ reps["pocket"].forEach(function(r){{comp.removeRepresentation(r);}}); reps["pocket"]=null; btn.style.background="#fff"; return; }}
  reps["pocket"] = [ comp.addRepresentation("licorice", {{sele:POCKET_SELE, color:"#2e7d32"}}) ];
  btn.style.background = "#2e7d3222";
}}
function clearAll() {{
  if (!comp) return;
  Object.keys(reps).forEach(function(k){{ if(reps[k]){{ reps[k].forEach(function(r){{comp.removeRepresentation(r);}}); reps[k]=null; }} }});
  document.querySelectorAll("button[id^=mbtn],#pbtn").forEach(function(b){{b.style.background="#fff";}});
}}
</script></body></html>"""


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(
        "epitope-map",
        help="Interactive target structure coloured by binding-frequency + per-binding-mode toggles.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    p.add_argument("--epitope-results", required=True, metavar="CSV", help="Output of 'binder-compare epitope'.")
    p.add_argument("--target-structure", required=True, metavar="PDB", help="A complex/target PDB to paint.")
    p.add_argument("--target-chain", default="A", metavar="CH", help="Target chain ID in the structure (default A).")
    p.add_argument("--hotspots", default=None, metavar="LIST", help="Optional intended-pocket residues to outline.")
    p.add_argument("--mode-threshold", type=float, default=0.5, help="Footprint Jaccard to merge into a mode (0.5).")
    p.add_argument("--min-mode-size", type=int, default=3, help="Drop binding modes smaller than this (default 3).")
    p.add_argument("--max-modes", type=int, default=8, help="Cap the number of modes shown (default 8).")
    p.add_argument("--consensus-frac", type=float, default=0.5, help="Residue in a mode if ≥ this frac contact it.")
    p.add_argument("--title", default=None, help="Heading for the page (default: structure stem).")
    p.add_argument(
        "--ngl-js",
        default=None,
        metavar="JS",
        help="Path to an ngl.js to inline (default: the vendored Evaluator/tools/ngl copy). "
        "Inlining makes the map self-contained — no unpkg CDN, works offline / behind Brave Shields.",
    )
    p.add_argument(
        "--ngl-cdn",
        action="store_true",
        help="Load NGL from the unpkg CDN via <script src> instead of inlining it (smaller file, needs network).",
    )
    p.add_argument("--output", "-o", required=True, metavar="HTML", help="Output HTML file.")
    p.set_defaults(func=run)
