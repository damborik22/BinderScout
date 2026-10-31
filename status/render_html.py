"""Static HTML renderer, for a page a box can serve without an agent in the loop.

The artifact page can only be written by an agent session, so keeping it fresh
means a session firing on a timer -- which is a notification every few minutes
for data that usually has not changed. This renderer is the other half: a plain
file any box can regenerate from a timer and serve over HTTP, with no account,
no token and nothing to push.

Grouping, evidence and deadlines are imported from the terminal renderer rather
than reimplemented. A second copy of that logic would drift, and the first thing
to drift would be the dedup rule that keeps two RFD3 rounds visible as two arms.
"""

import html

from status.render_term import _deadline_for, _rows
from status.schema import DEAD, DONE, QUEUED, RUNNING

#: How long the browser waits before re-reading the file. Shorter than the
#: generator's own period would only re-render identical bytes.
REFRESH_S = 60

_LABEL = {DONE: "done", RUNNING: "running", DEAD: "dead", QUEUED: "queued"}

# Freshness bands, in seconds. These describe the DOCUMENT, not an arm: a page
# whose generator died looks exactly like a quiet fleet until the stamp is read.
_FRESH_S = 5 * 60
_AGING_S = 20 * 60

_CSS = """\
:root {
  color-scheme: light;
  --bg: #f7f6f3; --panel: #ffffff; --line: #e3e0d8;
  --fg: #1c1b19; --fg-dim: #5c5850; --fg-faint: #8c877c;
  --ok: #2f7a4f; --live: #1f6f8b; --warn: #b07503; --bad: #a6341f;
  --track: #e8e5dd;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #15161a; --panel: #1d1f24; --line: #2e3238;
    --fg: #e8e6e1; --fg-dim: #a7a49d; --fg-faint: #76736c;
    --ok: #68c48c; --live: #5fb6d4; --warn: #e0a83c; --bad: #e2705a;
    --track: #282c32;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #15161a; --panel: #1d1f24; --line: #2e3238;
  --fg: #e8e6e1; --fg-dim: #a7a49d; --fg-faint: #76736c;
  --ok: #68c48c; --live: #5fb6d4; --warn: #e0a83c; --bad: #e2705a;
  --track: #282c32;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background: var(--bg); color: var(--fg);
  font: 15px/1.5 "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  padding-block: 0 2.5rem;
  padding-left: 16px; padding-right: 16px;
}
.wrap { max-width: 56rem; margin: 0 auto; }
header {
  position: sticky; top: env(safe-area-inset-top, 0px); z-index: 2;
  background: var(--bg); padding-block: 1.1rem .7rem;
  border-bottom: 1px solid var(--line);
  display: flex; flex-wrap: wrap; gap: .5rem 1rem; align-items: baseline;
}
h1 { font-size: 1.05rem; font-weight: 600; margin: 0; letter-spacing: -.01em; }
.stamp { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .8rem; color: var(--fg-dim); }
.age { margin-left: auto; font-size: .78rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
.age[data-age="fresh"] { color: var(--ok); }
.age[data-age="aging"] { color: var(--warn); }
.age[data-age="stale"] { color: var(--bad); }
section { margin-top: 2rem; }
.camp { display: flex; flex-wrap: wrap; gap: .3rem .75rem; align-items: baseline; margin-bottom: .7rem; }
.camp h2 { font-size: .95rem; font-weight: 600; margin: 0; }
.due { font-size: .78rem; color: var(--fg-dim); font-variant-numeric: tabular-nums; }
.arms { display: flex; flex-direction: column; gap: .5rem; }
.arm {
  background: var(--panel); border: 1px solid var(--line); border-radius: 7px;
  padding: .7rem .85rem; display: grid; gap: .45rem;
  grid-template-columns: minmax(0, 1fr) auto; align-items: baseline;
}
.arm[data-state="dead"] { border-color: color-mix(in srgb, var(--bad) 45%, var(--line)); }
.name { font-weight: 600; min-width: 0; }
.name .host { font-weight: 400; color: var(--fg-faint); font-size: .85em; margin-left: .45rem; }
.count {
  font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .85rem;
  font-variant-numeric: tabular-nums; color: var(--fg-dim); text-align: right;
}
.count b { color: var(--fg); font-weight: 600; }
.track { grid-column: 1 / -1; height: 5px; background: var(--track); border-radius: 3px; overflow: hidden; }
.fill { height: 100%; border-radius: 3px; }
.fill[data-state="done"] { background: var(--ok); }
.fill[data-state="running"] { background: var(--live); }
.fill[data-state="dead"] { background: var(--bad); }
.fill[data-state="queued"] { background: var(--fg-faint); }
.sweep {
  grid-column: 1 / -1; height: 5px; border-radius: 3px;
  background: repeating-linear-gradient(115deg, var(--live) 0 10px, var(--track) 10px 22px);
}
.sig {
  grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: .25rem 1.1rem;
  font-size: .8rem; color: var(--fg-dim);
}
.sig span { font-variant-numeric: tabular-nums; }
.sig .k { color: var(--fg-faint); }
.state { font-weight: 600; }
.state[data-state="done"] { color: var(--ok); }
.state[data-state="running"] { color: var(--live); }
.state[data-state="dead"] { color: var(--bad); }
.state[data-state="queued"] { color: var(--fg-faint); }
.warn { grid-column: 1 / -1; font-size: .8rem; color: var(--bad); }
.tot {
  margin-top: .6rem; font-size: .82rem; color: var(--fg-dim);
  font-variant-numeric: tabular-nums;
}
.down { margin-top: 1.6rem; font-size: .82rem; color: var(--bad); }
.empty { margin-top: 2rem; color: var(--fg-dim); }
footer { margin-top: 2.5rem; font-size: .76rem; color: var(--fg-faint); }
"""


def _duration(seconds) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds / 3600:.1f}h"


def _band(age_s) -> str:
    if age_s is None:
        return "stale"
    if age_s < _FRESH_S:
        return "fresh"
    if age_s < _AGING_S:
        return "aging"
    return "stale"


def _e(value) -> str:
    return html.escape(str(value), quote=True)


def _bar(done, total, state) -> str:
    """A filled bar, or an indeterminate sweep when the denominator is unknown.

    A bar drawn against a guessed total is a worse lie than no bar: it reads as
    progress toward a number nobody set.
    """
    if not total:
        return '<div class="sweep"></div>' if state == RUNNING else '<div class="track"></div>'
    pct = max(0.0, min(100.0, 100.0 * (done or 0) / total))
    return f'<div class="track"><div class="fill" data-state="{_e(state)}" style="width:{pct:.1f}%"></div></div>'


def _arm(tool, host, arm) -> str:
    state = arm.get("state", QUEUED)
    done, total = arm.get("done", 0) or 0, arm.get("total")
    count = f"<b>{done}</b>/{total}" if total else f"<b>{done}</b>/?"

    sig = [f'<span class="state" data-state="{_e(state)}">{_LABEL.get(state, _e(state))}</span>']
    if arm.get("phase"):
        sig.append(f'<span><span class="k">phase</span> {_e(arm["phase"])}</span>')
    proc = arm.get("proc") or {}
    if state == RUNNING and proc.get("gpu_mem_mib"):
        sig.append(f'<span><span class="k">gpu</span> {proc["gpu_mem_mib"] / 1024:.1f} GiB</span>')
    if arm.get("output_age_s") is not None:
        sig.append(f'<span><span class="k">last write</span> {_duration(arm["output_age_s"])}</span>')
    if arm.get("eta_s"):
        sig.append(f'<span><span class="k">eta</span> {_duration(arm["eta_s"])}</span>')

    warnings = "".join(f'<div class="warn">{_e(w)}</div>' for w in arm.get("warnings") or [])
    where = f'<span class="host">{_e(host)}</span>' if host and host != "-" else ""
    return (
        f'<div class="arm" data-state="{_e(state)}">'
        f'<div class="name">{_e(tool)}{where}</div>'
        f'<div class="count">{count}</div>'
        f"{_bar(done, total, state)}"
        f'<div class="sig">{"".join(sig)}</div>'
        f"{warnings}"
        "</div>"
    )


def render(doc: dict, age_s=None) -> str:
    """A complete HTML document for `doc`, ready to write to a served file."""
    by_group, members = _rows(doc)
    stamp = doc.get("generated_at", "")

    out = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
        f'<meta http-equiv="refresh" content="{REFRESH_S}">',
        "<title>BinderScout Campaign Arms</title>",
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
        '?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;600&display=swap">',
        f'<style>{_CSS}</style></head><body><div class="wrap">',
        "<header><h1>Campaign arms</h1>"
        f'<span class="stamp">{_e(stamp)}</span>'
        f'<span class="age" data-age="{_band(age_s)}">{_band(age_s)}</span></header>',
    ]

    for group in sorted(by_group):
        arms = sorted(by_group[group], key=lambda r: (r[1], r[0]))
        iso = _deadline_for(doc, group, members.get(group, []))
        due = f'<span class="due">due {_e(iso[:10])}</span>' if iso else ""
        banked = sum((a.get("done") or 0) for _, _, a in arms)
        live = sum(1 for _, _, a in arms if a.get("state") == RUNNING)
        fin = sum(1 for _, _, a in arms if a.get("state") == DONE)
        gone = sum(1 for _, _, a in arms if a.get("state") == DEAD)

        tot = f"{banked} designs banked &middot; {live} running &middot; {fin} done"
        if gone:
            tot += f" &middot; {gone} dead"
        tot += f" &middot; {len(arms)} arms"

        out.append(
            f'<section><div class="camp"><h2>{_e(group)}</h2>{due}</div>'
            f'<div class="arms">{"".join(_arm(t, h, a) for h, t, a in arms)}</div>'
            f'<div class="tot">{tot}</div></section>'
        )

    down = [(h, r.get("error", "")) for h, r in (doc.get("hosts") or {}).items() if not r.get("reachable")]
    for host, err in sorted(down):
        out.append(f'<div class="down">{_e(host)} unreachable &mdash; {_e(err)}</div>')

    if not by_group and not down:
        out.append('<p class="empty">No run directories found on any reachable box.</p>')

    out.append(
        f"<footer>Regenerated on this box; the browser re-reads every {REFRESH_S}s. "
        "A stale stamp means the generator stopped, not that the fleet went quiet.</footer>"
    )
    # The freshness band is recomputed in the browser, from the stamp. Baking it
    # in at render time would read "fresh" forever once the generator died --
    # the one failure this page exists to make visible.
    out.append(
        "<script>(function(){"
        'var el=document.querySelector(".age"),t=document.querySelector(".stamp");'
        "if(!el||!t)return;"
        "var at=Date.parse(t.textContent.trim());"
        "function tick(){"
        "if(isNaN(at)){el.dataset.age='stale';el.textContent='unknown';return;}"
        "var s=Math.max(0,(Date.now()-at)/1000);"
        f"el.dataset.age=s<{_FRESH_S}?'fresh':(s<{_AGING_S}?'aging':'stale');"
        "el.textContent=s<90?Math.round(s)+'s ago':(s<5400?Math.round(s/60)+'m ago'"
        ":(s/3600).toFixed(1)+'h ago');}"
        "tick();setInterval(tick,15000);})();</script>"
    )
    out.append("</div></body></html>")
    return "\n".join(out) + "\n"
