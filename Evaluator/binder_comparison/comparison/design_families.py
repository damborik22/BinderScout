"""Design families on two independent axes — sequence redundancy, and shared fold.

Both are **diagnostics**. Neither ranks, filters nor gates, which is the same rule
``agreement_count`` follows after Part U and the composition gate follows in
``sequence_panel``.

Why two axes, and why they are not merged into one number
---------------------------------------------------------

They answer different questions, and one of them is answerable only by structure.

**Sequence — "did the pipeline repeat itself?"** Measured 2026-09-29 across two real
campaigns, every near-duplicate pair came from a *single tool*: on one target all 36
pairs above k-mer Jaccard 0.10 were RFDiffusion3, reaching **0.938**, 0.819, 0.774; on
the other they were BindCraft at 0.17–0.30. That is MPNN emitting near-identical
sequences across different backbones. It says something about the *run*, not about the
binder, and it is worth surfacing per tool.

**Structure — "are these the same fold?"** This is the only axis on which de novo
designs are comparable at all. Over 114 unique designs from one campaign the maximum
pairwise k-mer Jaccard was **0.298** — below the 0.70 threshold
``diversity.cluster_sequences_df`` ships with, so that function can never group two
*distinct* designs, at any threshold in a sensible range. Even proper alignment identity
between our designs tops out near 0.24. Designs that share a fold are therefore
invisible to every sequence method, and were found only by structural comparison.

The threshold
-------------

``SEQ_FAMILY_THRESHOLD`` is 0.20, chosen rather than inherited:

* unrelated designs sit at a median k-mer Jaccard of ~0.010 with a p99 of ~0.053, so
  0.20 is roughly 4x the noise floor;
* the shipped 0.70 is above the maximum similarity ever observed between distinct
  designs (0.298), so it groups nothing but exact duplicates;
* 0.20 catches the observed same-tool redundancy on both campaigns.

It is a diagnostic threshold. Nothing downstream depends on its exact value, which is
the point: if it is wrong, a column is noisy, not a design is lost.
"""

from __future__ import annotations

import pandas as pd

from .diversity import _jaccard, _kmer_set

#: k-mer Jaccard at or above which two designs are called the same sequence family.
#: See the module docstring for why this is 0.20 and not diversity.py's 0.70.
SEQ_FAMILY_THRESHOLD = 0.20

#: k-mer size, matching ``diversity.cluster_sequences_df`` so the two are comparable.
SEQ_FAMILY_K = 4


def annotate_sequence_families(
    df: pd.DataFrame,
    *,
    sequence_col: str = "sequence",
    tool_col: str = "source_tool",
    threshold: float = SEQ_FAMILY_THRESHOLD,
    k: int = SEQ_FAMILY_K,
) -> pd.DataFrame:
    """Group designs by sequence similarity and report the redundancy per tool.

    Adds, and never removes or reorders a row:

    ``seq_family_id``
        Single-linkage group over k-mer Jaccard >= *threshold*.
    ``seq_family_size``
        How many designs share it. 1 means "nothing else looks like this".
    ``seq_family_is_redundant``
        ``seq_family_size > 1`` — the actionable bit.
    ``seq_family_tools``
        Comma-separated tools contributing to the family. A single name here is the
        MPNN-repeated-itself signal; several names means two tools converged, which is
        a different and more interesting event.

    Returns *df* unchanged when it is empty or has no sequence column — a diagnostic
    that cannot be computed is absent, not fatal.
    """
    if df.empty or sequence_col not in df.columns:
        return df

    out = df.copy()
    seqs = [str(s) if pd.notna(s) else "" for s in out[sequence_col]]
    kmers = [_kmer_set(s, k=k) for s in seqs]

    # Single linkage via union-find. n is a design pool (hundreds), so the O(n^2)
    # comparison is a few million set intersections at worst -- far cheaper than any
    # refold, and it keeps the grouping transitive, which a greedy pass would not.
    parent = list(range(len(out)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(len(out)):
        if not kmers[i]:
            continue
        for j in range(i + 1, len(out)):
            if kmers[j] and _jaccard(kmers[i], kmers[j]) >= threshold:
                union(i, j)

    roots = [find(i) for i in range(len(out))]
    # Name families by first appearance so the ids are stable and readable.
    order: dict[int, str] = {}
    for r in roots:
        if r not in order:
            order[r] = f"seqfam{len(order):04d}"
    out["seq_family_id"] = [order[r] for r in roots]

    sizes = out["seq_family_id"].value_counts().to_dict()
    out["seq_family_size"] = out["seq_family_id"].map(sizes).astype(int)
    out["seq_family_is_redundant"] = out["seq_family_size"] > 1

    if tool_col in out.columns:
        tools = (
            out.groupby("seq_family_id")[tool_col]
            .apply(lambda s: ", ".join(sorted({str(v) for v in s if pd.notna(v)})))
            .to_dict()
        )
        out["seq_family_tools"] = out["seq_family_id"].map(tools)
    else:
        out["seq_family_tools"] = ""

    return out


# ─── axis 2: structural families ─────────────────────────────────────────────
#
# The only axis on which de novo designs are comparable. See the module docstring:
# sequence methods provably cannot group two distinct designs here, so a shared fold is
# invisible to them.
#
# TM-score, not RMSD. TM is length-normalised and alignment-based; the Ca-RMSD helper in
# `diversity.refine_families_by_structure` compares residue i to residue i after
# truncating to the shorter chain, which assumes N-terminal correspondence -- true for
# two poses of one design, false for two independent designs of different length, which
# is the only case that matters here.
#
# Compare the BINDER CHAIN ALONE. Clustering whole complexes against a shared target is
# meaningless: the shared chain guarantees similarity. Getting this wrong on 2026-09-28
# produced the exact opposite of the right answer.

#: TM-score at or above which two designs are called the same fold. The conventional
#: boundary; 0.6 would have found none of the pairs observed on the golden pool.
STRUCT_FAMILY_TM = 0.5


def annotate_structural_families(
    df: pd.DataFrame,
    *,
    tm_lookup=None,
    id_col: str = "binder_id",
    threshold: float = STRUCT_FAMILY_TM,
) -> pd.DataFrame:
    """Group designs that share a fold.

    Args:
        tm_lookup: ``f(id_a, id_b) -> float | None`` returning the TM-score between two
            designs' binder chains. ``None`` (the default) means structural comparison is
            unavailable -- no foldseek, or no structures collected -- and every
            ``struct_family_id`` comes back ``NA``.

    Adds ``struct_family_id``, ``struct_family_size`` and
    ``struct_family_is_redundant``. Never drops or reorders a row: a diagnostic that
    cannot be computed is absent, not fatal, because foldseek exists only on x86 and
    structures are only present when ``extract --collect-structures`` ran.

    .. note:: **Single linkage chains, and that is visible in real output.**

       Grouping is transitive: A-B and B-C at/above the threshold put A, B and C in one
       family even when A-C is below it. On the golden pool that produced a 3-member
       family from pairs at TM 0.573 and 0.581 whose outer pair is only 0.34.

       That is the right default for "same fold" -- folds form continua and complete
       linkage would split obvious relatives -- but on a large pool it can over-merge,
       and a family is therefore a hint to look, not a proof of identity. If chaining
       becomes a problem the fix is to report the minimum within-family TM alongside the
       id rather than to switch linkage blindly.
    """
    if df.empty or id_col not in df.columns:
        return df

    out = df.copy()
    if tm_lookup is None:
        out["struct_family_id"] = pd.Series([pd.NA] * len(out), dtype="object")
        out["struct_family_size"] = pd.Series([pd.NA] * len(out), dtype="object")
        out["struct_family_is_redundant"] = pd.Series([pd.NA] * len(out), dtype="object")
        return out

    ids = [str(v) for v in out[id_col]]
    parent = list(range(len(ids)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            tm = tm_lookup(ids[i], ids[j])
            if tm is not None and tm >= threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)

    roots = [find(i) for i in range(len(ids))]
    order: dict[int, str] = {}
    for r in roots:
        if r not in order:
            order[r] = f"fold{len(order):04d}"
    out["struct_family_id"] = [order[r] for r in roots]
    sizes = out["struct_family_id"].value_counts().to_dict()
    out["struct_family_size"] = out["struct_family_id"].map(sizes).astype(int)
    out["struct_family_is_redundant"] = out["struct_family_size"] > 1
    return out


def suggest_swaps(
    df: pd.DataFrame,
    *,
    top_n: int = 12,
    id_col: str = "binder_id",
    rank_col: str = "rank",
    family_col: str = "struct_family_id",
) -> list[dict]:
    """Propose replacing a fold-duplicate in the top *top_n* with the next new fold.

    The actionable form of the structural axis. Picking N designs for synthesis, the
    question is not "are these the N best scores" but "how many distinct folds am I
    buying" -- two slots on one fold is a wasted slot.

    Returns one dict per suggestion: ``{"drop", "add", "duplicate_fold", "new_fold"}``.
    The **lower-ranked** member of a duplicated fold is the one dropped, and the
    replacement is the highest-ranked design outside the selection whose fold is not
    already represented.

    A suggestion, never an action: nothing here re-ranks or rewrites the selection, and
    designs whose fold is unknown (``NA``) are never called duplicates -- "not measured"
    is not "same as something else".
    """
    if df.empty or family_col not in df.columns or id_col not in df.columns:
        return []
    work = df.copy()
    if rank_col in work.columns:
        work = work.sort_values(rank_col)
    selected = work.head(top_n)

    seen: set[str] = set()
    redundant: list[tuple[str, str]] = []
    for _, row in selected.iterrows():
        fam = row[family_col]
        if pd.isna(fam):
            continue  # unknown fold is never a duplicate -- "not measured" != "same as"
        # Compare and store the SAME key. Checking the raw value while storing str(...)
        # happens to agree for string ids and silently disagrees for anything else.
        key = str(fam)
        if key in seen:
            redundant.append((str(row[id_col]), key))
        else:
            seen.add(key)

    if not redundant:
        return []

    # Candidates: outside the selection, fold known, fold not already represented.
    pool = work.iloc[top_n:]
    suggestions: list[dict] = []
    for drop_id, dup_fam in redundant:
        replacement = None
        for _, cand in pool.iterrows():
            fam = cand[family_col]
            if pd.isna(fam) or str(fam) in seen:
                continue
            replacement = cand
            seen.add(str(fam))
            break
        if replacement is None:
            continue
        suggestions.append(
            {
                "drop": drop_id,
                "add": str(replacement[id_col]),
                "duplicate_fold": dup_fam,
                "new_fold": str(replacement[family_col]),
            }
        )
    return suggestions
