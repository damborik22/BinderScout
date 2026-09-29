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
