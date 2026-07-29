"""Combined per-tool native + cross-engine refold candidates table.

Produces ``candidates.csv`` — a single shortlist that puts each design tool's
own top picks next to the evaluator's cross-engine refold ranking, so a
reviewer can see, per method, which native designs survived refolding and where
the refold winners sit in each tool's own ranking.

Layout (rows, in this order):
  - one "Native top-N" block per tool, tools in :data:`CANONICAL_TOOL_ORDER`
  - one "Refold top-M" block (the cross-engine two-stage ranking), LAST

Two correctness rules are baked in here so the file is right straight out of
``binder-compare report`` with the tools' RAW native CSVs (no pre-processing):

  1. In-pool filter — native designs that were never refolded carry no
     cross-engine metrics, so they are dropped. This is the general,
     target-agnostic form of the campaign-specific "drop PXDesign 150/160aa"
     step: a design absent from the refold pool has no Mean_ipTM to show. Every
     native-block row is therefore a refolded design (no blank-metric rows,
     barring a design whose engines all failed to score).
  2. Backbone collapse — **REFOLD block only.** A tool's native CSV may list many
     sequences for one backbone (BindCraft MPNN siblings, Protein-Hunter cycles).
     Our shortlist keeps one row per ``design_group`` so it does not spend slots
     on several sequences of one design. It must NOT touch the tool's own top-N:
     collapsing there renumbered BindCraft's native list as 1,2,3,4,7,8,11,…,
     which is not its ranking.

  3. One row = one real design, and **the native block is the TOOL's view** — our
     refold never picks which sibling it shows, nor reorders it. Every cell in a
     row describes the sequence named in that row.

     Getting this wrong has shipped three times. Printing the native sibling's
     ipTM beside the representative's rank made rows describing no actual design
     (10 of 140 on the CALCA top-50 pool). Rendering the row *from* the
     representative instead fixed the arithmetic but let our ranking overwrite
     the tool's own #1 (BindCraft ranks ``…_l186_s671234_mpnn5`` first; the table
     said ``_mpnn2``). Taking "Ranking native" from ``design_group`` printed the
     best-native sibling's number on our rank-22 row, which holds a different
     sequence (``_mpnn4``, native 10) — it read 4, ``_mpnn3``'s.

Both rankings count **sequences**, and every cell quotes the rank of the sequence
in its own row — looked up by sequence, never by ``design_group``. "Ranking
native" is that sequence's place in its tool's ranking; "Ranking refolded" is its
place in ours (``rank``, which ``cli/report.py`` does not renumber).

Consequence: the NATIVE blocks read 1..N with no holes, because they reproduce
the tool's list untouched. The REFOLD block skips a number wherever a sibling was
collapsed out of our shortlist — that skip is the whole point of the collapse and
the skipped design is still in its tool's native block and in ``metrics.csv``.
The two can disagree about which sibling is better and that is real signal:
BindCraft rates ``l127_s975277_mpnn3`` 4th (our rank 26) while our engines prefer
its sibling ``_mpnn4`` (our rank 22, native 10).
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import pandas as pd

# Section sizes — fixed by request: per-method 20 native designs + 50 refolded.
N_NATIVE_PER_TOOL = 20
N_REFOLD = 50

# How each tool is written for a human. The keys the pipeline joins on
# (`source_tool`, `--tool-csv` names) stay lowercase everywhere — this is display
# only, applied at render time, so nothing downstream has to know about it.
TOOL_DISPLAY_NAMES = {
    "bindcraft": "BindCraft",
    "boltzgen": "BoltzGen",
    "mosaic": "Mosaic",
    "proteina_complexa": "Proteina-Complexa",
    "pxdesign": "PXDesign",
    "protein_hunter": "Protein Hunter",
    "rfd3": "RFDiffusion3",
}


def display_tool_name(tool: str) -> str:
    """Human-facing name for a tool key; unknown tools pass through unchanged.

    A variant keeps its qualifier so the two BoltzGen modes stay distinguishable:
    ``boltzgen_protein`` → ``BoltzGen (protein)``, ``boltzgen_nano`` →
    ``BoltzGen (nano)``.
    """
    t = str(tool or "").strip()
    if t in TOOL_DISPLAY_NAMES:
        return TOOL_DISPLAY_NAMES[t]
    for base, name in TOOL_DISPLAY_NAMES.items():
        if t.startswith(base + "_"):
            return f"{name} ({t[len(base) + 1 :].replace('_', ' ')})"
    return t


# Native blocks are emitted in this order; the refold block always comes last.
CANONICAL_TOOL_ORDER = [
    "bindcraft",
    "boltzgen",
    "mosaic",
    "proteina_complexa",
    "pxdesign",
    "protein_hunter",
    "rfd3",
]

CANDIDATES_COLUMNS = [
    "Set",
    "Method",
    "Ranking native",
    "Ranking refolded",
    "Mean_ipTM",
    "Mean_ipSAE_min",
    "Solubility SoluProt",
    "Length",
    "Primary sequence",
]

# Sequence column preference for a tool's native CSV. Full chain first — matches
# the extractors (e.g. BoltzGen nanobody CSVs store the truncated CDR in
# `sequence` and the full VHH in `designed_chain_sequence`; the refold pool is
# keyed on the full chain, so we must join on it too).
_NATIVE_SEQ_COLS = ("designed_chain_sequence", "sequence", "Sequence", "designed_sequence")


def order_tools(tools) -> list[str]:
    """Canonical order first (variants like ``boltzgen_nano`` slot under their
    base tool), then any unknown tools alphabetically."""

    def key(t: str):
        pos = len(CANONICAL_TOOL_ORDER)
        for i, name in enumerate(CANONICAL_TOOL_ORDER):
            if t == name or t.startswith(name + "_"):
                pos = i
                break
        return (pos, t)

    return sorted(tools, key=key)


def _native_seq_col(native: pd.DataFrame) -> str | None:
    for c in _NATIVE_SEQ_COLS:
        if c in native.columns:
            return c
    return None


def collapse_native_df(
    csv_path: str | Path,
    seq_to_group: dict[str, str],
    top_n: int | None = None,
    collapse: bool = True,
) -> pd.DataFrame:
    """Read a tool's native CSV → keep refolded designs only, one row per backbone.

    Rows are filtered to the refold pool (``seq_to_group`` keys), collapsed to
    the first (best native-ranked) row per ``design_group``, and left in native
    file order. Returns the surviving rows with their original columns plus two
    helper columns: ``_seq_key`` (UPPER/stripped sequence) and
    ``_design_group``. Returns an empty frame if the CSV is unreadable or has no
    recognised sequence column.
    """
    try:
        native = pd.read_csv(csv_path)
    except Exception as exc:
        warnings.warn(f"[candidates] {csv_path}: unreadable ({exc}) — this tool's native block is dropped.")
        return pd.DataFrame()
    col = _native_seq_col(native)
    if col is None or native.empty:
        why = "no rows" if native.empty else f"no sequence column (tried {list(_NATIVE_SEQ_COLS)})"
        warnings.warn(f"[candidates] {csv_path}: {why} — this tool's native block is dropped.")
        return native.iloc[0:0].copy()
    key = native[col].astype(str).str.strip().str.upper()
    grp = key.map(seq_to_group)
    native = native.assign(_seq_key=key.to_numpy(), _design_group=grp.to_numpy())
    n_read = len(native)
    native = native[native["_design_group"].notna()]  # in-pool filter
    if native.empty:
        warnings.warn(
            f"[candidates] {csv_path}: none of its {n_read} native designs are in the refold pool — "
            "this tool's native block is dropped. Stale native CSV (tool re-run since it was written)?"
        )
    if collapse:
        native = native[~native["_design_group"].duplicated(keep="first")]  # backbone collapse
    native = native.reset_index(drop=True)
    if top_n is not None:
        native = native.head(top_n)
    return native


def _num3(v):
    """Round to 3 dp; blank for missing / NaN / non-numeric."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return "" if math.isnan(f) else round(f, 3)


def _intlen(v):
    """Binder length as a plain int (avoid the '127.0' float wart); blank if NaN."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v if v is not None else ""
    return "" if math.isnan(f) else int(f)


def _seq_meta(full_df: pd.DataFrame) -> dict[str, dict]:
    """First-seen per-sequence metrics from the refold pool, keyed UPPER(seq)."""
    meta: dict[str, dict] = {}
    for row in full_df.to_dict("records"):
        k = str(row.get("sequence", "")).strip().upper()
        if not k or k in meta:
            continue
        meta[k] = {
            "Mean_ipTM": _num3(row.get("consensus_iptm_mean", "")),
            "Mean_ipSAE_min": _num3(row.get("consensus_ipsae_min_mean", "")),
            "Solubility SoluProt": _num3(row.get("native_soluprot_score", "")),
            "Length": _intlen(row.get("binder_length", "")),
            "Primary sequence": row.get("sequence", ""),
            "design_group": row.get("design_group", ""),
        }
    return meta


def build_candidates_table(
    full_df: pd.DataFrame,
    df_display: pd.DataFrame,
    tool_csvs: dict[str, str | Path] | None,
    n_native: int = N_NATIVE_PER_TOOL,
    n_refold: int = N_REFOLD,
) -> pd.DataFrame:
    """Build the combined candidates table (see the module docstring).

    Args:
        full_df:    Every refolded design (the ``metrics.csv`` frame) carrying
                    ``design_group`` and the consensus columns.
        df_display: The collapsed, two-stage-ranked representatives (the
                    ``top30_candidates.csv`` frame, dense ``rank``) used
                    for the refold block and for every design's refold rank.
        tool_csvs:  Mapping tool name → that tool's RAW native CSV.
    """
    meta = _seq_meta(full_df)
    seq_to_group = {k: v["design_group"] for k, v in meta.items() if v.get("design_group") not in (None, "")}
    # UPPER(sequence) → the refold rank of the DESIGN that sequence belongs to.
    # `rank` is dense over distinct designs and shared by a backbone's siblings
    # (see cli/report.py), so a native row can always quote a rank — including
    # for a sibling the shortlist collapsed — and it is the same number the
    # shortlist prints for that design.
    seq_to_rank = {
        str(r.get("sequence", "")).strip().upper(): r.get("rank", "")
        for r in full_df.to_dict("records")
        if str(r.get("sequence", "")).strip()
    }

    rows: list[dict] = []

    # --- per-tool native blocks (canonical order), refolded designs only ---
    seq_native_rank: dict[str, dict[str, int]] = {}
    tool_csvs = tool_csvs or {}
    for tool in order_tools(tool_csvs.keys()):
        # Native rank is per SEQUENCE, over every in-pool design the tool ranked —
        # NOT per backbone. The tool and the refold can prefer different siblings
        # of one backbone (BindCraft rates l127_s975277_mpnn3 4th, we rate its
        # sibling _mpnn4 higher), so a backbone-level native rank would print the
        # best-native sibling's number on a row holding a different sequence.
        full_native = collapse_native_df(tool_csvs[tool], seq_to_group, top_n=None, collapse=False)
        if full_native.empty:
            continue
        # first occurrence wins: a sequence listed twice in a native CSV keeps its
        # BEST rank, not whichever copy happens to come last.
        _ranks: dict[str, int] = {}
        for _i, _k in enumerate(full_native["_seq_key"].tolist(), start=1):
            _ranks.setdefault(_k, _i)
        seq_native_rank[tool] = _ranks
        # The native block is the TOOL's list, reproduced as the tool ordered it:
        # NOT collapsed. Backbone collapse exists so *our* shortlist does not
        # spend slots on several MPNN sequences of one design — it has no
        # business rewriting the tool's own top-N. Collapsing here renumbered
        # BindCraft's top-20 as 1,2,3,4,7,8,11,… , which is not its ranking.
        survivors = full_native
        set_label = f"Native top-{n_native}"
        for key in survivors["_seq_key"].head(n_native).tolist():
            m = meta.get(key, {})
            rows.append(
                {
                    "Set": set_label,
                    "Method": display_tool_name(tool),
                    # THIS sequence's own native rank — never a sibling's.
                    "Ranking native": seq_native_rank[tool].get(key, ""),
                    # THIS design's own refold rank — never a sibling's.
                    "Ranking refolded": seq_to_rank.get(key, ""),
                    "Mean_ipTM": m.get("Mean_ipTM", ""),
                    "Mean_ipSAE_min": m.get("Mean_ipSAE_min", ""),
                    "Solubility SoluProt": m.get("Solubility SoluProt", ""),
                    "Length": m.get("Length", ""),
                    "Primary sequence": m.get("Primary sequence", ""),
                }
            )

    # --- refold block (cross-engine ranking), LAST ---
    set_label = f"Refold top-{n_refold}"
    unresolved: dict[str, int] = {}
    for refold_rank, row in enumerate(df_display.head(n_refold).to_dict("records"), start=1):
        tool = row.get("source_tool", "")
        # THIS sequence's own native rank. Looking it up by design_group instead
        # printed the best-native sibling's number here: our rank-22 row is
        # l127_s975277_mpnn4 (native 10), and it read 4 — mpnn3's.
        native_rank = seq_native_rank.get(tool, {}).get(str(row.get("sequence", "")).strip().upper(), "")
        if native_rank == "" and tool in seq_native_rank:
            unresolved[tool] = unresolved.get(tool, 0) + 1
        rows.append(
            {
                "Set": set_label,
                "Method": display_tool_name(tool),
                "Ranking native": native_rank,
                # the frame's own rank, not the row position, so both blocks
                # quote the same number for the same design
                "Ranking refolded": row.get("rank", refold_rank),
                "Mean_ipTM": _num3(row.get("consensus_iptm_mean", "")),
                "Mean_ipSAE_min": _num3(row.get("consensus_ipsae_min_mean", "")),
                "Solubility SoluProt": _num3(row.get("native_soluprot_score", "")),
                "Length": _intlen(row.get("binder_length", "")),
                "Primary sequence": row.get("sequence", ""),
            }
        )

    if unresolved:
        detail = ", ".join(f"{t}: {n}" for t, n in sorted(unresolved.items()))
        warnings.warn(
            f"[candidates] no native rank for {sum(unresolved.values())} of the top-{n_refold} "
            f"refold designs ({detail}) — those designs are in the refold pool but absent from "
            "their tool's native CSV, so the cell is left blank. The snapshot predates the pool "
            "(tool re-run, or the pool was assembled from a different selection)."
        )
    return pd.DataFrame(rows, columns=CANDIDATES_COLUMNS)
