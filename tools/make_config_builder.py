#!/usr/bin/env python3
"""Generate the static config-builder page from the configurator itself.

`binderscout configure --config run.json` already replays a campaign headlessly,
so a form that emits that JSON is a second door into the pipeline for anyone who
would rather not answer eighty prompts. The risk is the one this repo keeps
paying for: a second surface listing tools and flags drifts from the first.

So the page is GENERATED — from `REQUIRED_CFG_KEYS` and the shipped example
config — and a test fails when the committed HTML stops matching this output.
Drift becomes a red CI run instead of a config that silently enables nothing.

Usage:
    python tools/make_config_builder.py                  # write docs/config-builder.html
    python tools/make_config_builder.py --stdout         # print it
    python tools/make_config_builder.py --emit-default-config
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "configurator"))

EXAMPLE = REPO / "examples" / "CALCA" / "smoke.json"
OUTPUT = REPO / "docs" / "config-builder.html"

# Human labels + help for the cfg keys. Anything absent here still renders, so a
# new key added to the example cannot vanish from the form.
FIELD_HELP: dict[str, str] = {
    "name": "Run name. Becomes the run directory's name.",
    "run_dir": "Where the run lives. RELATIVE to the repo root — an absolute path from another machine will not resolve.",
    "target_pdb_src": "Target structure (.pdb / .mmcif), relative to the repo root.",
    "target_sequence": "Target sequence. Must match the chain named below, or RFD3 refuses the contig.",
    "chains": "Target chain id(s) in the structure, e.g. A.",
    "hotspots": "Optional. Epitope residues to aim at, e.g. A15,A18,A22. Leave blank for none.",
    "min_length": "Shortest binder to design (aa).",
    "max_length": "Longest binder to design (aa).",
    "n_designs": "Designs per tool, unless a per-tool override below says otherwise.",
    "filter_preset": "BindCraft filter set. no_filters keeps everything — right for a smoke run, wrong for a campaign.",
    "advanced_preset": "BindCraft advanced settings preset.",
    "boltzgen_intermediate": "BoltzGen generates this many candidates before its own ranked selection.",
    "pxdesign_binder_length": "PXDesign designs one fixed binder length.",
    "rfd3_diffusion_steps": "RFD3 denoising steps. 200 for a campaign; 20 only for a smoke test.",
    "use_boltz": "Refold with Boltz-2.",
    "use_af3": "Refold with AlphaFold 3. Cheapest engine here (~5 GB), despite its reputation.",
    "use_esmfold2": "Refold with ESMFold2. Needs ~14 GB even for small complexes — it cannot run on a 12 GB card.",
    "primary_engine": "Which engine's structures the report shows. Ranking is always cross-engine.",
    "use_soluprot": "Run the sequence-only solubility screen before any GPU work.",
    "soluprot_filter": "Drop sub-threshold designs from the FASTA before refolding. Off = score only.",
}

TOOL_LABELS = {
    "bindcraft": "BindCraft (AF2 hallucination + MPNN + PyRosetta)",
    "bindcraft2": "BindCraft 2 (AF2 hallucination + MPNN, JAX only)",
    "boltzgen": "BoltzGen (Boltz-1 diffusion)",
    "mosaic": "Mosaic (Boltz-2 gradient hallucination)",
    "pxdesign_local": "PXDesign (Protenix + MPNN + AF2 eval)",
    "proteina_complexa": "Proteina-Complexa (flow matching + MCTS)",
    "protein_hunter": "Protein-Hunter (Boltz-2 / Chai-1 hallucination)",
    "rfd3": "RFD3 (RosettaCommons diffusion + ProteinMPNN)",
    "evaluator": "Evaluator (cross-engine refold + ranking)",
}


def _schema():
    """(tools, cfg_defaults, required_by_tool) read from the live configurator."""
    import configurator as conf

    example = json.loads(EXAMPLE.read_text())
    tools = list(example["tools_enabled"])
    for tool in conf.REQUIRED_CFG_KEYS:
        if tool not in tools:
            tools.append(tool)
    required = {t: list(conf.REQUIRED_CFG_KEYS.get(t, ())) for t in tools}
    return tools, dict(example["cfg"]), required


def _field_html(key: str, value) -> str:
    helptext = html.escape(FIELD_HELP.get(key, ""))
    kid = html.escape(key)
    if isinstance(value, bool):
        checked = " checked" if value else ""
        control = f'<input type="checkbox" id="f_{kid}" data-key="{kid}" data-type="bool"{checked}>'
    elif isinstance(value, int):
        control = f'<input type="number" id="f_{kid}" data-key="{kid}" data-type="int" value="{value}">'
    else:
        shown = "" if value is None else html.escape(str(value))
        control = f'<input type="text" id="f_{kid}" data-key="{kid}" data-type="str" value="{shown}">'
    return (
        f'<div class="field"><label for="f_{kid}"><code>{kid}</code></label>'
        f"{control}<p class='help'>{helptext}</p></div>"
    )


def build_page() -> str:
    tools, defaults, required = _schema()

    tool_rows = "\n".join(
        f'<label class="tool"><input type="checkbox" data-tool="{html.escape(t)}" checked> '
        f"<span>{html.escape(TOOL_LABELS.get(t, t))}</span> "
        f'<code>"{html.escape(t)}"</code></label>'
        for t in tools
    )
    fields = "\n".join(_field_html(k, v) for k, v in defaults.items())
    required_json = json.dumps(required, indent=2)
    defaults_json = json.dumps(defaults, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BinderScout config builder</title>
<style>
:root {{ --bg:#fff; --fg:#111; --mut:#666; --line:#ddd; --accent:#0b5; --warn:#a40; --code:#f5f5f5; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#14161a; --fg:#e8e8e8; --mut:#9aa; --line:#333; --accent:#3d8; --warn:#f96; --code:#1d2026; }} }}
:root[data-theme="dark"] {{ --bg:#14161a; --fg:#e8e8e8; --mut:#9aa; --line:#333; --accent:#3d8; --warn:#f96; --code:#1d2026; }}
* {{ box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--fg); margin:0; padding:16px;
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
.wrap {{ max-width:900px; margin:0 auto; }}
h1 {{ font-size:1.5rem; margin:0 0 .25rem; }}
p.sub {{ color:var(--mut); margin:0 0 1.5rem; }}
h2 {{ font-size:1.05rem; margin:1.75rem 0 .5rem; padding-bottom:.3rem; border-bottom:1px solid var(--line); }}
code {{ background:var(--code); padding:.1em .35em; border-radius:3px; font-size:.9em; }}
.tool {{ display:flex; align-items:center; gap:.5rem; padding:.35rem 0; }}
.tool span {{ flex:1; }}
.field {{ margin:.9rem 0; }}
.field label {{ display:block; margin-bottom:.2rem; }}
.field input[type=text], .field input[type=number] {{
  width:100%; padding:.45rem .6rem; border:1px solid var(--line); border-radius:4px;
  background:var(--bg); color:var(--fg); font:inherit; }}
.help {{ color:var(--mut); font-size:.85em; margin:.25rem 0 0; }}
pre {{ background:var(--code); padding:1rem; border-radius:6px; overflow:auto; max-height:420px; }}
button {{ font:inherit; padding:.5rem .9rem; border:1px solid var(--line); border-radius:5px;
  background:var(--accent); color:#04120a; cursor:pointer; margin-right:.5rem; }}
.note {{ border-left:3px solid var(--warn); padding:.6rem .9rem; margin:1rem 0; color:var(--mut); }}
.err {{ color:var(--warn); font-weight:600; }}
</style></head><body><div class="wrap">

<h1>BinderScout config builder</h1>
<p class="sub">Fills in a <code>config.json</code> for
<code>binderscout configure --config &lt;file&gt;</code>. Nothing is uploaded; the page
runs entirely in your browser.</p>

<div class="note"><strong>This page is generated</strong> from
<code>configurator.py</code> by <code>tools/make_config_builder.py</code>. Do not edit it
by hand — a test fails when the two disagree, which is how a second list of tools and
flags is kept from drifting out of step with the real one.</div>

<h2>Tools</h2>
{tool_rows}

<h2>Settings</h2>
{fields}

<h2>config.json</h2>
<p id="status"></p>
<button id="dl">Download config.json</button>
<button id="copy">Copy</button>
<pre id="out"></pre>

<div class="note">Then: <code>binderscout configure --config config.json</code>, and
<code>bash runs/&lt;name&gt;/run_all.sh</code>. Add <code>--run</code> to start immediately.</div>

<script>
const REQUIRED = {required_json};
const DEFAULTS = {defaults_json};

function collect() {{
  const tools = {{}};
  document.querySelectorAll('[data-tool]').forEach(el => {{ tools[el.dataset.tool] = el.checked; }});
  const cfg = {{}};
  document.querySelectorAll('[data-key]').forEach(el => {{
    const k = el.dataset.key, t = el.dataset.type;
    if (t === 'bool') cfg[k] = el.checked;
    else if (t === 'int') cfg[k] = el.value === '' ? null : parseInt(el.value, 10);
    else cfg[k] = el.value === '' ? null : el.value;
  }});
  return {{ config_version: 1, tools_enabled: tools, cfg: cfg }};
}}

function problems(doc) {{
  const out = [];
  for (const [tool, keys] of Object.entries(REQUIRED)) {{
    if (!doc.tools_enabled[tool]) continue;
    for (const k of keys) {{
      if (k === 'target_pdb' && doc.cfg.target_pdb_src) continue;
      const v = doc.cfg[k];
      if (v === undefined || v === null || v === '') out.push(tool + ' needs ' + k);
    }}
  }}
  if (doc.cfg.run_dir && /^([/]|[A-Za-z]:)/.test(doc.cfg.run_dir))
    out.push('run_dir should be relative, not absolute');
  return out;
}}

function render() {{
  const doc = collect();
  document.getElementById('out').textContent = JSON.stringify(doc, null, 2);
  const errs = problems(doc);
  const s = document.getElementById('status');
  s.className = errs.length ? 'err' : '';
  s.textContent = errs.length ? errs.join(' · ') : 'Looks complete.';
}}

document.addEventListener('input', render);
document.addEventListener('change', render);
document.getElementById('dl').addEventListener('click', () => {{
  const blob = new Blob([JSON.stringify(collect(), null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'config.json';
  a.click();
  URL.revokeObjectURL(a.href);
}});
document.getElementById('copy').addEventListener('click', async () => {{
  try {{ await navigator.clipboard.writeText(JSON.stringify(collect(), null, 2)); }} catch (e) {{}}
}});
render();
</script>
</div></body></html>
"""


def default_config() -> dict:
    tools, defaults, _required = _schema()
    return {"config_version": 1, "tools_enabled": dict.fromkeys(tools, True), "cfg": defaults}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stdout", action="store_true", help="print the page instead of writing it")
    ap.add_argument("--emit-default-config", action="store_true", help="print the page's default config.json")
    args = ap.parse_args(argv)

    if args.emit_default_config:
        print(json.dumps(default_config(), indent=2))
        return

    page = build_page()
    if args.stdout:
        sys.stdout.write(page)
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page)
    print(f"wrote {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
