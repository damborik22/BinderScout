"""Build the wet-lab "Selected Hits" table from ``candidates.csv``.

This reproduces, deterministically, the sheet that was previously assembled by
hand from the candidates file. Two sections, in this order:

**A — per-tool.** Each tool's own top ``per_tool`` designs (default 12), taken
from that tool's native block in the order the tool ranked them, tools in
:data:`CANONICAL_TOOL_ORDER`. A tool may be given extra slots (``extra``) when a
campaign deliberately tests more of it.

**B — refolded.** Walk our cross-engine ranking from rank 1 downwards and list
every design it reaches. A design already present in section A is still written
out — that row is the record that the refold pick was already covered above —
but it does NOT count toward the target. Stop once ``refolded`` *new* designs
have accumulated (default 30), or when the refold block runs out.

Verified against the two hand-built sheets before this existed. CALCA: section A
= 12 x 7 = 84, section B = 41 rows spanning refold ranks 1..43 (43 minus the two
collapse skips at 26 and 32) giving exactly 30 new + 11 already-covered. 2VDY:
section A = 87 (RFDiffusion3 given 3 extra slots by hand), section B = the whole
top-50 giving 31 new + 19 already-covered.

The bookkeeping duplicates are therefore intentional and are preserved. What is
NOT preserved is the manual-entry damage they came with: codes that lost their
separator when a tool name contained a space (``CALCAProtein Hunter-03``) or a
hyphen (prefix ``Proteina``), one sheet using ``Refolded-03`` where the other
used ``CALCA-BinderScout-16``, and trailing spaces in method names that split
one tool into two in any pivot.
"""

from __future__ import annotations

import pandas as pd

from .candidates import CANONICAL_TOOL_ORDER, TOOL_DISPLAY_NAMES, display_tool_name

# Code-safe tool tokens: no spaces, no hyphens, so ``CODE.split("-")`` always
# yields exactly [target, tool, number].
TOOL_CODE_SLUGS = {
    "bindcraft": "BindCraft",
    "boltzgen": "BoltzGen",
    "mosaic": "Mosaic",
    "proteina_complexa": "ProteinaComplexa",
    "pxdesign": "PXDesign",
    "protein_hunter": "ProteinHunter",
    "rfd3": "RFDiffusion3",
}

#: Section-B designs are coded against the pipeline, not a single tool.
REFOLD_CODE_TOKEN = "BinderScout"

HITS_COLUMNS = [
    "No",
    "Code",
    "Method",
    "Section",
    "Ranking native",
    "Ranking refolded",
    "Mean_ipTM",
    "Mean_ipSAE_min",
    "Solubility SoluProt",
    "Length",
    "Primary sequence",
]

_CARRY = [
    "Ranking native",
    "Ranking refolded",
    "Mean_ipTM",
    "Mean_ipSAE_min",
    "Solubility SoluProt",
    "Length",
    "Primary sequence",
]


def _tool_key(method: str) -> str:
    """Map a Method cell back to its pipeline key.

    Accepts a raw key (``rfd3``), a display name (``RFDiffusion3`` — note it does
    NOT contain the key, so a prefix match alone is not enough) or a variant
    (``BoltzGen (protein)`` → ``boltzgen_protein``).
    """
    m = str(method or "").strip()
    if not m:
        return ""
    base, _, rest = m.partition("(")
    variant = rest.rstrip(") ").strip().lower().replace(" ", "_")
    low = base.strip().lower()
    rev = {v.lower(): k for k, v in TOOL_DISPLAY_NAMES.items()}
    key = rev.get(low)
    if key is None:
        norm = low.replace(" ", "_").replace("-", "_")
        key = next((b for b in CANONICAL_TOOL_ORDER if norm == b or norm.startswith(b + "_")), norm)
    return f"{key}_{variant}" if variant else key


def code_slug(method: str) -> str:
    """Code-safe token for a tool: no spaces, no hyphens.

    So ``CODE.split("-")`` always yields exactly ``[target, tool, number]`` —
    unlike the hand-built sheets, where a tool name containing a space produced
    ``CALCAProtein Hunter-03`` and one containing a hyphen produced a bare
    ``Proteina`` prefix.
    """
    key = _tool_key(method)
    if key in TOOL_CODE_SLUGS:
        return TOOL_CODE_SLUGS[key]
    for base, slug in TOOL_CODE_SLUGS.items():
        if key.startswith(base + "_"):
            return slug + key[len(base) + 1 :].replace("_", " ").title().replace(" ", "")
    return str(method or "").replace(" ", "").replace("-", "") or "Unknown"


def select_hits(
    candidates: pd.DataFrame,
    target: str,
    per_tool: int = 12,
    refolded: int = 30,
    extra: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Select section A + section B from one target's ``candidates.csv``.

    Args:
        candidates: a ``candidates.csv`` frame (native blocks + refold block).
        target: code prefix, e.g. ``CALCA`` or ``2VDY``.
        per_tool: section-A designs per tool.
        refolded: how many NEW designs section B must accumulate.
        extra: per-tool additional section-A slots, keyed on the tool key
            (``{"rfd3": 3}`` reproduces 2VDY's hand-added RFDiffusion3 designs).
    """
    extra = {_tool_key(k): v for k, v in (extra or {}).items()}
    is_refold = candidates["Set"].astype(str).str.contains("Refold", na=False)
    native, refold = candidates[~is_refold], candidates[is_refold]

    rows: list[dict] = []

    # --- section A: each tool's own top-N, in the tool's own order ---
    by_key = {}
    for method, g in native.groupby("Method", sort=False):
        by_key.setdefault(_tool_key(method), []).append(g)
    for key in CANONICAL_TOOL_ORDER + [k for k in by_key if k not in CANONICAL_TOOL_ORDER]:
        if key not in by_key:
            continue
        g = pd.concat(by_key[key]).sort_values("Ranking native", kind="mergesort")
        n = per_tool + int(extra.get(key, 0))
        for i, (_, r) in enumerate(g.head(n).iterrows(), start=1):
            rows.append(
                {
                    "Code": f"{target}-{code_slug(r['Method'])}-{i:02d}",
                    "Method": display_tool_name(_tool_key(r["Method"])),
                    "Section": "per-tool",
                    **{c: r.get(c, "") for c in _CARRY},
                }
            )

    # --- section B: walk our ranking, recording already-covered picks ---
    seen = {str(r["Primary sequence"]).strip() for r in rows}
    n_new = 0
    b = refold.copy()
    b["_rr"] = pd.to_numeric(b["Ranking refolded"], errors="coerce")
    for i, (_, r) in enumerate(b.sort_values("_rr", kind="mergesort").iterrows(), start=1):
        if n_new >= refolded:
            break
        seq = str(r["Primary sequence"]).strip()
        already = seq in seen
        if not already:
            n_new += 1
            seen.add(seq)
        rows.append(
            {
                "Code": f"{target}-{REFOLD_CODE_TOKEN}-{i:02d}",
                "Method": display_tool_name(_tool_key(r["Method"])),
                "Section": "already covered above" if already else "refolded",
                **{c: r.get(c, "") for c in _CARRY},
            }
        )

    out = pd.DataFrame(rows)
    out.insert(0, "No", range(1, len(out) + 1))
    return out[HITS_COLUMNS]


def hits_summary(hits: pd.DataFrame) -> dict:
    """Counts a reader (and the sheet header) needs."""
    sec = hits["Section"]
    distinct = hits.loc[sec != "already covered above", "Primary sequence"].nunique()
    return {
        "rows": len(hits),
        "per_tool": int((sec == "per-tool").sum()),
        "refolded_new": int((sec == "refolded").sum()),
        "already_covered": int((sec == "already covered above").sum()),
        "distinct_designs_to_test": int(distinct),
    }
