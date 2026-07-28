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
  2. Backbone collapse — a tool's native CSV may list many sequences for one
     backbone (BindCraft MPNN siblings, Protein-Hunter cycles); we keep the
     best-native-ranked sequence per ``design_group`` so every row is a
     distinct design. Native rank is dense over the surviving distinct
     backbones.

Both "Ranking refolded" columns use the SAME ranking — the collapsed two-stage
order (``df_display`` dense ``rank``), looked up by ``design_group`` — so
a native design and the refold-block appearance of its backbone carry the same
refold rank. Likewise the refold block's "Ranking native" is looked up by
``design_group`` (not exact sequence) so a refold representative that is a
*different* MPNN sibling than the native-best one still resolves to its
backbone's native rank.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import pandas as pd

# Section sizes — fixed by request: per-method 20 native designs + 30 refolded.
N_NATIVE_PER_TOOL = 20
N_REFOLD = 30

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
    # backbone → collapsed two-stage refold rank (the single, dense ranking used
    # by both the refold block and the native block's "Ranking refolded").
    grp_to_refold_rank = dict(zip(df_display.get("design_group", []), df_display.get("rank", []), strict=False))

    rows: list[dict] = []

    # --- per-tool native blocks (canonical order), refolded designs only ---
    grp_native_rank: dict[str, dict[str, int]] = {}
    tool_csvs = tool_csvs or {}
    for tool in order_tools(tool_csvs.keys()):
        survivors = collapse_native_df(tool_csvs[tool], seq_to_group, top_n=None)
        if survivors.empty:
            continue
        # Dense native rank over ALL surviving backbones, so the refold block can
        # resolve a backbone's native rank even when it sits below the top-N.
        grp_native_rank[tool] = {dg: i for i, dg in enumerate(survivors["_design_group"].tolist(), start=1)}
        set_label = f"Native top-{n_native}"
        for native_rank, key in enumerate(survivors["_seq_key"].head(n_native).tolist(), start=1):
            m = meta.get(key, {})
            rows.append(
                {
                    "Set": set_label,
                    "Method": tool,
                    "Ranking native": native_rank,
                    "Ranking refolded": grp_to_refold_rank.get(m.get("design_group", ""), ""),
                    "Mean_ipTM": m.get("Mean_ipTM", ""),
                    "Mean_ipSAE_min": m.get("Mean_ipSAE_min", ""),
                    "Solubility SoluProt": m.get("Solubility SoluProt", ""),
                    "Length": m.get("Length", ""),
                    "Primary sequence": m.get("Primary sequence", ""),
                }
            )

    # --- refold block (cross-engine two-stage ranking), LAST ---
    set_label = f"Refold top-{n_refold}"
    for refold_rank, row in enumerate(df_display.head(n_refold).to_dict("records"), start=1):
        tool = row.get("source_tool", "")
        native_rank = grp_native_rank.get(tool, {}).get(row.get("design_group", ""), "")
        rows.append(
            {
                "Set": set_label,
                "Method": tool,
                "Ranking native": native_rank,
                "Ranking refolded": refold_rank,
                "Mean_ipTM": _num3(row.get("consensus_iptm_mean", "")),
                "Mean_ipSAE_min": _num3(row.get("consensus_ipsae_min_mean", "")),
                "Solubility SoluProt": _num3(row.get("native_soluprot_score", "")),
                "Length": _intlen(row.get("binder_length", "")),
                "Primary sequence": row.get("sequence", ""),
            }
        )

    return pd.DataFrame(rows, columns=CANDIDATES_COLUMNS)
