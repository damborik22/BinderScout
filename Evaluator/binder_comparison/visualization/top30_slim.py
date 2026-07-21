"""Slim top-30 table — the decision metrics only.

A compact, sortable companion to the full ``report.html``. Columns answer the
five questions a wet-lab pick rests on — *does it bind* (Mean ipTM), *is the
signal robust* (Agreement), *is the interface real* (ipSAE_min), *does it bind
the right place* (Epitope), *can we express it* (Solubility) — plus TmProt
thermostability (Tm) and a plain-text Notes column carrying any wet-lab
advisory. No icon flags: the advisory reason is written out in Notes.

Optional columns (Epitope, Solubility, Tm, Notes) render only when their source
column is present in the metrics frame.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

import pandas as pd

# display label -> source column. Optional columns are dropped when absent.
_COLS = [
    ("Rank", "two_stage_rank", "n"),
    ("Binder ID", "binder_id", "s"),
    ("Tool", "source_tool", "s"),
    ("Length", "binder_length", "n"),
    ("Mean ipTM", "consensus_iptm_mean", "n"),
    ("Agreement", "agreement_count", "n"),
    ("ipSAE_min", "ipsae_min", "n"),
    ("Epitope", "epitope_match_fraction", "n"),
    ("Solubility", "native_soluprot_score", "n"),
    ("Tm", "native_tmprot_tm", "n"),
    ("Notes", "wetlab_reason", "s"),
]

_TOOLCOL = {
    "mosaic": "#3b82f6", "pxdesign": "#8b5cf6", "bindcraft": "#ef4444",
    "proteina_complexa": "#10b981", "protein_hunter": "#f59e0b", "rfd3": "#ec4899",
    "boltzgen_protein": "#14b8a6", "boltzgen_nano": "#64748b",
}


def _tier(v: float) -> str:
    if pd.isna(v):
        return "na"
    if v > 0.80:
        return "high"
    if v > 0.61:
        return "med"
    if v > 0.40:
        return "low"
    return "rej"


def write_top30_slim(df: pd.DataFrame, output_dir: Path, n: int = 30, pool_size: int | None = None) -> None:
    """Write ``top30_slim.html`` + ``top30_slim.csv`` (decision metrics only)."""
    output_dir = Path(output_dir)
    sort_col = "two_stage_rank" if "two_stage_rank" in df.columns else "consensus_iptm_mean"
    ascending = sort_col == "two_stage_rank"
    cols = [(lbl, col, kind) for lbl, col, kind in _COLS if col in df.columns]
    t = df.sort_values(sort_col, ascending=ascending).head(n)[[c for _, c, _ in cols]].reset_index(drop=True)
    t.columns = [lbl for lbl, _, _ in cols]
    t.to_csv(output_dir / "top30_slim.csv", index=False)

    body = []
    for _, r in t.iterrows():
        cells = []
        for lbl, _col, _kind in cols:
            v = r[lbl]
            if lbl == "Rank":
                cells.append(f'<td class="rank">{int(v)}</td>')
            elif lbl == "Binder ID":
                cells.append(f'<td class="bid" title="{_html.escape(str(v))}">{_html.escape(str(v))}</td>')
            elif lbl == "Tool":
                c = _TOOLCOL.get(str(v), "#64748b")
                cells.append(f'<td><span class="chip" style="--c:{c}">{_html.escape(str(v))}</span></td>')
            elif lbl == "Length":
                cells.append(f'<td class="num">{"" if pd.isna(v) else int(v)}</td>')
            elif lbl == "Mean ipTM":
                w = int(max(0, min(1, (float(v) - 0.3) / 0.65)) * 100) if pd.notna(v) else 0
                cells.append(f'<td class="iptm"><span class="bar" style="--w:{w}%"></span><b>{"" if pd.isna(v) else f"{v:.3f}"}</b></td>')
            elif lbl == "Agreement":
                ag = int(v) if pd.notna(v) else 0
                cells.append(f'<td class="num"><span class="ag ag{ag}">{ag}/3</span></td>')
            elif lbl == "ipSAE_min":
                cells.append(f'<td class="num"><span class="pill {_tier(v)}">{"—" if pd.isna(v) else f"{v:.2f}"}</span></td>')
            elif lbl == "Epitope":
                cls = "na" if pd.isna(v) else ("high" if v >= 0.5 else "med" if v >= 0.3 else "low")
                cells.append(f'<td class="num"><span class="pill {cls}">{"—" if pd.isna(v) else f"{v * 100:.0f}%"}</span></td>')
            elif lbl == "Solubility":
                cells.append(f'<td class="num">{"—" if pd.isna(v) else f"{float(v):.2f}"}</td>')
            elif lbl == "Tm":
                txt = "—" if pd.isna(v) else f"{float(v):.0f}"
                cls = "" if pd.isna(v) else ("tm-hi" if float(v) >= 60 else "tm-lo")
                cells.append(f'<td class="num"><span class="{cls}">{txt}</span></td>')
            elif lbl == "Notes":
                note = "" if pd.isna(v) or not str(v).strip() else str(v).strip()
                cells.append(f'<td class="note">{_html.escape(note)}</td>')
            else:
                cells.append(f'<td class="num">{"—" if pd.isna(v) else _html.escape(str(v))}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")

    heads = "".join(
        f'<th data-t="{"n" if kind == "n" else "s"}">{_html.escape(lbl)}</th>' for lbl, _, kind in cols
    )
    subtitle = f"Ranked by two-stage cross-engine iPTM · intercalators excluded{f' · n={pool_size} pool' if pool_size else ''}. Click a header to sort."

    page = _TEMPLATE.replace("__HEADS__", heads).replace("__BODY__", "\n".join(body)).replace("__SUB__", _html.escape(subtitle))
    (output_dir / "top30_slim.html").write_text(page)


_TEMPLATE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Top 30 — decision metrics</title>
<style>
:root { color-scheme: light dark; --bg:#fff; --fg:#111827; --mut:#6b7280; --line:#e5e7eb; --head:#f9fafb;
        --high:#16a34a; --med:#d97706; --low:#dc2626; --rej:#991b1b; --barbg:#eef2ff; --bar:#6366f1; }
@media (prefers-color-scheme: dark) { :root { --bg:#0e1116; --fg:#e6e9ef; --mut:#9aa4b2; --line:#272d38; --head:#171b22; --barbg:#1e2230; } }
:root[data-theme=dark]{ --bg:#0e1116;--fg:#e6e9ef;--mut:#9aa4b2;--line:#272d38;--head:#171b22;--barbg:#1e2230; }
:root[data-theme=light]{ --bg:#fff;--fg:#111827;--mut:#6b7280;--line:#e5e7eb;--head:#f9fafb;--barbg:#eef2ff; }
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:22px 18px 60px}
h1{font-size:18px;margin:0 0 4px}
p.sub{color:var(--mut);margin:0 0 16px;font-size:12.5px}
.legend{color:var(--mut);font-size:11.5px;margin:10px 2px 0}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px 11px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
thead th{position:sticky;top:0;background:var(--head);cursor:pointer;user-select:none;font-size:11.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--mut)}
thead th:hover{color:var(--fg)}
thead th::after{content:" \\2195";opacity:.35}
tbody tr:hover{background:color-mix(in srgb, var(--head) 60%, transparent)}
.rank{color:var(--mut);font-variant-numeric:tabular-nums}
.bid{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.num{text-align:right;font-variant-numeric:tabular-nums}
.chip{font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;color:var(--c);background:color-mix(in srgb, var(--c) 15%, transparent);border:1px solid color-mix(in srgb,var(--c) 35%,transparent)}
.iptm{position:relative;text-align:right;min-width:110px}
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
</style></head><body><div class="wrap">
<h1>Top 30 · decision metrics</h1>
<p class="sub">__SUB__</p>
<div class="scroll"><table id="t">
<thead><tr>__HEADS__</tr></thead>
<tbody>
__BODY__
</tbody></table></div>
<p class="legend"><b>Mean ipTM</b> (binds, cross-engine ↑) · <b>Agreement</b> (engines concurring 0–3 ↑) ·
<b>ipSAE_min</b> (interface: <span style="color:var(--high)">High&gt;.80</span>/<span style="color:var(--med)">Med</span>/<span style="color:var(--low)">Low</span> ↑) ·
<b>Epitope</b> (contacts on the target pocket ↑) · <b>Solubility</b> (SoluProt ↑) · <b>Tm</b> (TmProt °C ↑) · <b>Notes</b> (wet-lab advisory).</p>
</div>
<script>
const tb=document.querySelector('#t tbody');
document.querySelectorAll('#t thead th').forEach((th,i)=>{
  let asc=true;
  th.onclick=()=>{
    const num=th.dataset.t==='n';
    [...tb.rows].sort((a,b)=>{
      let x=a.cells[i].innerText.replace('%','').replace('/3','').replace('\\u2014','NaN'),
          y=b.cells[i].innerText.replace('%','').replace('/3','').replace('\\u2014','NaN');
      if(num){x=parseFloat(x);y=parseFloat(y);if(isNaN(x))x=-1;if(isNaN(y))y=-1;return asc?x-y:y-x;}
      return asc?x.localeCompare(y):y.localeCompare(x);
    }).forEach(r=>tb.appendChild(r));
    asc=!asc;
  };
});
</script></body></html>"""
