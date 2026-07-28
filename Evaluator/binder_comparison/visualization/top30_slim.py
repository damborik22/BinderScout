"""Slim decision-metrics tables — a compact companion to the full ``report.html``.

Emits ``top30_slim.html`` (+ ``top30_slim.csv``) with, top to bottom:

* an overall **Top-30** table of the metrics a wet-lab pick rests on — *does it
  bind* (Mean ipTM), *is the signal robust* (Agreement), *is the interface real*
  (ipSAE_min), *does it bind the right place* (Epitope), *can we express it*
  (Solubility), plus TmProt thermostability (Tm) and a plain-text **Notes** column
  carrying any wet-lab advisory (no icon flags);
* the same slim view **per tool** (top-N each);
* at the bottom, every one of those tables again with **all metrics**, each in a
  collapsed ``<details>`` roll-up.

Optional slim columns (Epitope, Solubility, Tm, Notes) render only when their
source column is present in the metrics frame.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

import pandas as pd

from ..comparison.scoring import (
    _ENGINE_IPSAE_COLS,
    IPSAE_HIGH_THRESHOLD,
    IPSAE_MIN_THRESHOLD,
    IPSAE_PASS_THRESHOLD,
)

# display label -> (source column, sort kind). Optional columns drop when absent.
_SLIM = [
    ("Rank", "rank", "n"),
    ("Binder ID", "binder_id", "s"),
    ("Tool", "source_tool", "s"),
    ("Length", "binder_length", "n"),
    ("Mean ipTM", "consensus_iptm_mean", "n"),
    ("Agreement", "agreement_count", "n"),
    ("ipSAE_min", "ipsae_min", "n"),
    ("Epitope", "epitope_match_fraction", "n"),
    ("Mode", "binding_mode", "n"),
    ("Solubility", "native_soluprot_score", "n"),
    ("Tm", "native_tmprot_tm", "n"),
    ("Notes", "wetlab_reason", "s"),
]

_TOOLCOL = {
    "mosaic": "#3b82f6",
    "pxdesign": "#8b5cf6",
    "bindcraft": "#ef4444",
    "proteina_complexa": "#10b981",
    "protein_hunter": "#f59e0b",
    "rfd3": "#ec4899",
    "boltzgen_protein": "#14b8a6",
    "boltzgen_nano": "#64748b",
}

# columns excluded from the "all metrics" roll-ups (paths / blobs, not metrics).
_DROP_SUFFIX = ("_pdb", "_cif", "_file", "_path", "_idx")
_DROP_EXACT = {"sequence", "pdb", "cif"}
_FULL_LEAD = [
    "rank",
    "binder_id",
    "source_tool",
    "binder_length",
    "consensus_iptm_mean",
    "agreement_count",
    "ipsae_min",
]


def _tier(v) -> str:
    """Tier band for the slim table's ipSAE_min colouring.

    Reads the same constants `scoring.apply_screening_thresholds` bands
    `quality_tier` with — retyped literals here meant the slim table could
    colour a row differently from the tier the full report assigned it.
    """
    if pd.isna(v):
        return "na"
    if v > IPSAE_HIGH_THRESHOLD:
        return "high"
    if v > IPSAE_PASS_THRESHOLD:
        return "med"
    return "low" if v > IPSAE_MIN_THRESHOLD else "rej"


def _n_engines(df: pd.DataFrame) -> int:
    """How many refolding engines contributed — the real ceiling of agreement_count."""
    return sum(1 for col in _ENGINE_IPSAE_COLS.values() if col in df.columns) or 3


def _slim_cols(df: pd.DataFrame):
    return [(lbl, col, kind) for lbl, col, kind in _SLIM if col in df.columns]


def _slim_table(df: pd.DataFrame, cols, table_id: str) -> str:
    heads = "".join(f'<th data-t="{kind}">{_html.escape(lbl)}</th>' for lbl, _, kind in cols)
    rows = []
    for _, r in df[[c for _, c, _ in cols]].iterrows():
        d = dict(zip([lbl for lbl, _, _ in cols], r))
        cells = []
        for lbl, _col, _kind in cols:
            v = d[lbl]
            if lbl == "Rank":
                cells.append(f'<td class="rank">{"" if pd.isna(v) else int(v)}</td>')
            elif lbl == "Binder ID":
                cells.append(f'<td class="bid" title="{_html.escape(str(v))}">{_html.escape(str(v))}</td>')
            elif lbl == "Tool":
                c = _TOOLCOL.get(str(v), "#64748b")
                cells.append(f'<td><span class="chip" style="--c:{c}">{_html.escape(str(v))}</span></td>')
            elif lbl == "Length":
                cells.append(f'<td class="num">{"" if pd.isna(v) else int(v)}</td>')
            elif lbl == "Mean ipTM":
                w = int(max(0, min(1, (float(v) - 0.3) / 0.65)) * 100) if pd.notna(v) else 0
                cells.append(
                    f'<td class="iptm"><span class="bar" style="--w:{w}%"></span><b>{"" if pd.isna(v) else f"{v:.3f}"}</b></td>'
                )
            elif lbl == "Agreement":
                ag = int(v) if pd.notna(v) else 0
                cells.append(f'<td class="num"><span class="ag ag{ag}">{ag}/3</span></td>')
            elif lbl == "ipSAE_min":
                cells.append(
                    f'<td class="num"><span class="pill {_tier(v)}">{"—" if pd.isna(v) else f"{v:.2f}"}</span></td>'
                )
            elif lbl == "Epitope":
                cls = "na" if pd.isna(v) else ("high" if v >= 0.5 else "med" if v >= 0.3 else "low")
                cells.append(
                    f'<td class="num"><span class="pill {cls}">{"—" if pd.isna(v) else f"{v * 100:.0f}%"}</span></td>'
                )
            elif lbl == "Mode":
                cells.append(f'<td class="num">{"—" if pd.isna(v) else f"#{int(v)}"}</td>')
            elif lbl == "Solubility":
                cells.append(f'<td class="num">{"—" if pd.isna(v) else f"{float(v):.2f}"}</td>')
            elif lbl == "Tm":
                cls = "" if pd.isna(v) else ("tm-hi" if float(v) >= 60 else "tm-lo")
                cells.append(
                    f'<td class="num"><span class="{cls}">{"—" if pd.isna(v) else f"{float(v):.0f}"}</span></td>'
                )
            elif lbl == "Notes":
                note = "" if pd.isna(v) or not str(v).strip() else str(v).strip()
                cells.append(f'<td class="note">{_html.escape(note)}</td>')
            else:
                cells.append(f'<td class="num">{"—" if pd.isna(v) else _html.escape(str(v))}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="sortable" id="{table_id}"><thead><tr>{heads}</tr></thead><tbody>\n{chr(10).join(rows)}\n</tbody></table>'


def _full_table(df: pd.DataFrame, table_id: str) -> str:
    cols = [c for c in df.columns if not c.endswith(_DROP_SUFFIX) and c not in _DROP_EXACT]
    cols = [c for c in _FULL_LEAD if c in cols] + [c for c in cols if c not in _FULL_LEAD]
    heads = "".join(
        f'<th data-t="{"n" if pd.api.types.is_numeric_dtype(df[c]) else "s"}">{_html.escape(c)}</th>' for c in cols
    )
    rows = []
    for _, r in df[cols].iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if pd.isna(v):
                cells.append('<td class="num">—</td>')
            elif isinstance(v, float):
                cells.append(f'<td class="num">{v:.3f}</td>')
            else:
                cells.append(f"<td>{_html.escape(str(v))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="sortable full" id="{table_id}"><thead><tr>{heads}</tr></thead><tbody>\n{chr(10).join(rows)}\n</tbody></table>'


def slim_table_html(df: pd.DataFrame, top_n: int = 30, table_id: str = "t") -> str:
    """Return just the slim ``<table>`` HTML for the top-``top_n`` rows (for embedding)."""
    sort_col = "rank" if "rank" in df.columns else "consensus_iptm_mean"
    d = df.sort_values(sort_col, ascending=(sort_col == "rank")).head(top_n)
    return _slim_table(d, _slim_cols(d), table_id)


# Slim-table CSS scoped under a ``.slimreport`` wrapper, for embedding in the main
# report.html (whose own table CSS would otherwise clash). Light-theme values.
SLIM_REPORT_CSS = """
.slimreport{--high:#16a34a;--med:#d97706;--low:#dc2626;--rej:#991b1b;--bar:#6366f1;--barbg:#eef2ff;--line:#e5e7eb;--head:#eef2f7;--mut:#6b7280;overflow-x:auto}
.slimreport table{border-collapse:collapse;width:100%;font-size:0.85em;margin:0}
.slimreport th,.slimreport td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap;min-width:0}
.slimreport thead th{background:var(--head);color:var(--mut);position:sticky;top:0;cursor:pointer;font-size:0.82em;text-transform:uppercase;letter-spacing:.4px}
.slimreport tbody tr:hover{background:#f6f8fb}
.slimreport .rank{color:var(--mut);font-variant-numeric:tabular-nums}
.slimreport .bid{font-family:ui-monospace,Menlo,monospace;font-size:0.9em;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.slimreport .num{text-align:right;font-variant-numeric:tabular-nums}
.slimreport .chip{font-size:0.85em;font-weight:600;padding:2px 8px;border-radius:20px;color:var(--c);background:color-mix(in srgb,var(--c) 15%,transparent);border:1px solid color-mix(in srgb,var(--c) 35%,transparent)}
.slimreport .iptm{position:relative;text-align:right;min-width:104px}
.slimreport .iptm .bar{position:absolute;left:8px;right:8px;bottom:3px;height:3px;border-radius:2px;background:var(--barbg)}
.slimreport .iptm .bar::after{content:"";position:absolute;left:0;top:0;bottom:0;width:var(--w);background:var(--bar);border-radius:2px}
.slimreport .pill{padding:2px 8px;border-radius:6px;font-weight:600;color:#fff}
.slimreport .pill.high{background:var(--high)}.slimreport .pill.med{background:var(--med)}
.slimreport .pill.low{background:var(--low)}.slimreport .pill.rej{background:var(--rej)}.slimreport .pill.na{background:transparent;color:var(--mut)}
.slimreport .ag{padding:2px 7px;border-radius:6px;font-weight:600}
.slimreport .ag3{background:var(--high);color:#fff}
.slimreport .ag2{background:color-mix(in srgb,var(--high) 22%,transparent);color:var(--high)}
.slimreport .ag1{background:color-mix(in srgb,var(--med) 22%,transparent);color:var(--med)}
.slimreport .ag0{background:color-mix(in srgb,var(--low) 18%,transparent);color:var(--low)}
.slimreport .tm-hi{color:var(--high);font-weight:600}.slimreport .tm-lo{color:var(--mut)}
.slimreport .note{white-space:normal;max-width:280px;font-size:0.9em;color:var(--mut)}
"""


def write_top30_slim(df: pd.DataFrame, output_dir: Path, top_per_tool: int = 10, pool_size: int | None = None) -> None:
    """Write ``top30_slim.html`` + ``top30_slim.csv`` (decision metrics + per-tool + all-metric roll-ups)."""
    output_dir = Path(output_dir)
    sort_col = "rank" if "rank" in df.columns else "consensus_iptm_mean"
    asc = sort_col == "rank"
    d = df.sort_values(sort_col, ascending=asc).reset_index(drop=True)
    cols = _slim_cols(d)

    # overall slim CSV (unchanged contract)
    top30 = d.head(30)[[c for _, c, _ in cols]].copy()
    top30.columns = [lbl for lbl, _, _ in cols]
    top30.to_csv(output_dir / "top30_slim.csv", index=False)

    tools = list(d["source_tool"].value_counts().index) if "source_tool" in d.columns else []

    sections = [f"<h2>Overall — Top 30</h2>{_slim_table(d.head(30), cols, 't_overall')}"]
    for i, tool in enumerate(tools):
        sub = d[d["source_tool"] == tool].head(top_per_tool)
        c = _TOOLCOL.get(tool, "#64748b")
        sections.append(
            f'<h2><span class="dot" style="background:{c}"></span>{_html.escape(tool)} — Top {min(top_per_tool, len(sub))}</h2>{_slim_table(sub, cols, f"t_tool{i}")}'
        )

    rolls = [
        f'<details><summary>Overall Top-30 — all metrics</summary><div class="scroll">{_full_table(d.head(30), "f_overall")}</div></details>'
    ]
    for i, tool in enumerate(tools):
        sub = d[d["source_tool"] == tool].head(top_per_tool)
        rolls.append(
            f'<details><summary>{_html.escape(tool)} Top-{min(top_per_tool, len(sub))} — all metrics</summary><div class="scroll">{_full_table(sub, f"f_tool{i}")}</div></details>'
        )

    subtitle = f"Ranked by two-stage cross-engine iPTM · intercalators excluded{f' · n={pool_size} pool' if pool_size else ''}. Click any header to sort."
    page = (
        _TEMPLATE.replace("__SUB__", _html.escape(subtitle))
        .replace(
            "__SECTIONS__",
            "\n".join(f'<div class="scroll">{s}</div>' if s.startswith("<table") else s for s in sections),
        )
        .replace("__ROLLS__", "\n".join(rolls))
        # Rendered from the scoring constants and from the engines that actually
        # ran, so the legend cannot claim a band or an engine count the tables
        # below were not built with. (CSS braces rule out an f-string template.)
        .replace("__TIER_HIGH__", f"{IPSAE_HIGH_THRESHOLD:.2f}".lstrip("0"))
        .replace("__N_ENGINES__", str(_n_engines(d)))
    )
    (output_dir / "top30_slim.html").write_text(page)


_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Decision tables — Top 30 + per tool</title>
<style>
:root { color-scheme: light dark; --bg:#fff; --fg:#111827; --mut:#6b7280; --line:#e5e7eb; --head:#f9fafb;
        --high:#16a34a; --med:#d97706; --low:#dc2626; --rej:#991b1b; --barbg:#eef2ff; --bar:#6366f1; }
@media (prefers-color-scheme: dark) { :root { --bg:#0e1116; --fg:#e6e9ef; --mut:#9aa4b2; --line:#272d38; --head:#171b22; --barbg:#1e2230; } }
:root[data-theme=dark]{ --bg:#0e1116;--fg:#e6e9ef;--mut:#9aa4b2;--line:#272d38;--head:#171b22;--barbg:#1e2230; }
:root[data-theme=light]{ --bg:#fff;--fg:#111827;--mut:#6b7280;--line:#e5e7eb;--head:#f9fafb;--barbg:#eef2ff; }
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:22px 18px 80px}
h1{font-size:19px;margin:0 0 4px}
h2{font-size:14px;margin:26px 2px 8px;display:flex;align-items:center;gap:8px}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block}
p.sub{color:var(--mut);margin:0 0 8px;font-size:12.5px}
.legend{color:var(--mut);font-size:11.5px;margin:6px 2px 4px}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px;margin-top:6px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:7px 11px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
thead th{position:sticky;top:0;background:var(--head);cursor:pointer;user-select:none;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--mut)}
thead th:hover{color:var(--fg)}
thead th::after{content:" \\2195";opacity:.35}
tbody tr:hover{background:color-mix(in srgb, var(--head) 60%, transparent)}
.rank{color:var(--mut);font-variant-numeric:tabular-nums}
.bid{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.num{text-align:right;font-variant-numeric:tabular-nums}
.chip{font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;color:var(--c);background:color-mix(in srgb, var(--c) 15%, transparent);border:1px solid color-mix(in srgb,var(--c) 35%,transparent)}
.iptm{position:relative;text-align:right;min-width:104px}
.iptm .bar{position:absolute;left:8px;right:8px;bottom:3px;height:3px;border-radius:2px;background:var(--barbg)}
.iptm .bar::after{content:"";position:absolute;left:0;top:0;bottom:0;width:var(--w);background:var(--bar);border-radius:2px}
.pill{padding:2px 8px;border-radius:6px;font-weight:600;font-size:12px}
.pill.high{color:#fff;background:var(--high)}.pill.med{color:#fff;background:var(--med)}
.pill.low{color:#fff;background:var(--low)}.pill.rej{color:#fff;background:var(--rej)}.pill.na{color:var(--mut)}
.ag{padding:2px 7px;border-radius:6px;font-weight:600;font-size:12px}
.ag3{background:var(--high);color:#fff}
.ag2{background:color-mix(in srgb,var(--high) 22%,transparent);color:var(--high)}
.ag1{background:color-mix(in srgb,var(--med) 22%,transparent);color:var(--med)}
.ag0{background:color-mix(in srgb,var(--low) 18%,transparent);color:var(--low)}
.tm-hi{color:var(--high);font-weight:600}.tm-lo{color:var(--mut)}
.note{white-space:normal;max-width:280px;font-size:11.5px;color:var(--mut)}
details{margin:8px 0;border:1px solid var(--line);border-radius:10px;background:var(--head)}
summary{cursor:pointer;padding:10px 14px;font-weight:600;font-size:13px}
details .scroll{margin:0 0 0 0;border:none;border-top:1px solid var(--line);border-radius:0 0 10px 10px}
details .full th,details .full td{font-size:11px;padding:5px 8px}
.rollhdr{margin:34px 2px 4px;font-size:13px;color:var(--mut);border-top:1px solid var(--line);padding-top:16px}
</style></head><body><div class="wrap">
<h1>Decision tables · Top 30 + per tool</h1>
<p class="sub">__SUB__</p>
<p class="legend"><b>Mean ipTM</b> (binds, cross-engine ↑) · <b>Agreement</b> (engines concurring 0–__N_ENGINES__ ↑) ·
<b>ipSAE_min</b> (interface: <span style="color:var(--high)">High&gt;__TIER_HIGH__</span>/<span style="color:var(--med)">Med</span>/<span style="color:var(--low)">Low</span> ↑) ·
<b>Epitope</b> (contacts on the pocket ↑) · <b>Solubility</b> (SoluProt ↑) · <b>Tm</b> (TmProt °C ↑) · <b>Notes</b> (wet-lab advisory).</p>
__SECTIONS__
<div class="rollhdr">All metrics — roll-ups (click to expand)</div>
__ROLLS__
<script>
document.querySelectorAll('table.sortable').forEach(tbl=>{
  const tb=tbl.querySelector('tbody');
  tbl.querySelectorAll('thead th').forEach((th,i)=>{
    let asc=true;
    th.onclick=()=>{
      const num=th.dataset.t==='n';
      [...tb.rows].sort((a,b)=>{
        let x=(a.cells[i].innerText||'').replace('%','').replace('/3','').replace('\\u2014','NaN'),
            y=(b.cells[i].innerText||'').replace('%','').replace('/3','').replace('\\u2014','NaN');
        if(num){x=parseFloat(x);y=parseFloat(y);if(isNaN(x))x=-1e9;if(isNaN(y))y=-1e9;return asc?x-y:y-x;}
        return asc?x.localeCompare(y):y.localeCompare(x);
      }).forEach(r=>tb.appendChild(r));
      asc=!asc;
    };
  });
});
</script></body></html>"""
