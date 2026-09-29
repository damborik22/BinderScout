"""Design families on two axes: sequence redundancy, and shared fold.

Two separate questions, deliberately not merged into one number:

* **`seq_family_id`** — did the design pipeline emit near-identical *sequences*? This is a
  per-tool diagnostic. Measured 2026-09-29 on two real campaigns, every near-duplicate
  pair came from a single tool: on one target all 36 pairs above k-mer Jaccard 0.10 were
  RFDiffusion3, reaching **0.938**; on the other they were BindCraft, 0.17–0.30. That is
  MPNN producing near-identical sequences across different backbones, and it is worth
  surfacing per tool.

* **`struct_family_id`** — do two designs share a *fold*? This is the only axis on which
  de novo designs are comparable at all. Over 114 unique designs the maximum pairwise
  k-mer Jaccard was **0.298**, below `cluster_sequences_df`'s shipped threshold of 0.70,
  so sequence clustering can never group two distinct designs; even alignment identity
  tops out near 0.24. Structure found same-fold pairs those methods cannot see.

Both are **diagnostics**. Neither ranks, filters or gates — the same rule as
`agreement_count` after Part U and the composition gate.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.design_families import (  # noqa: E402
    SEQ_FAMILY_THRESHOLD,
    annotate_sequence_families,
)


def _pool(seqs, tools=None):
    n = len(seqs)
    return pd.DataFrame(
        {
            "binder_id": [f"d{i}" for i in range(n)],
            "sequence": seqs,
            "source_tool": tools or ["toolA"] * n,
        }
    )


def test_distinct_designs_are_each_their_own_family():
    """De novo designs are genuinely unrelated; the common case must not over-group."""
    d = _pool(["MKTAYIAKQRQISFVKSHFSRQLEERLG", "PVLSKDEEILRRWNEFAKQHGYTVQWAE", "GSHMDWLKAFYDKVAEKLKEAF"])
    out = annotate_sequence_families(d)
    assert out["seq_family_id"].nunique() == 3
    assert list(out["seq_family_size"]) == [1, 1, 1]


def test_identical_sequences_share_a_family():
    s = "MKTAYIAKQRQISFVKSHFSRQLEERLG"
    out = annotate_sequence_families(_pool([s, s, "PVLSKDEEILRRWNEFAKQHGYTVQWAE"]))
    assert out.loc[0, "seq_family_id"] == out.loc[1, "seq_family_id"]
    assert out.loc[0, "seq_family_id"] != out.loc[2, "seq_family_id"]
    assert list(out["seq_family_size"]) == [2, 2, 1]


def test_a_near_duplicate_is_grouped():
    """The RFD3 case: same tool, one substitution block apart, ~0.8 Jaccard."""
    base = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHSLAKWKR"
    near = base[:60] + "WWWW" + base[64:]
    out = annotate_sequence_families(_pool([base, near, "PVLSKDEEILRRWNEFAKQHGYTVQWAEDGKA"]))
    assert out.loc[0, "seq_family_id"] == out.loc[1, "seq_family_id"], (
        "a near-identical sequence must land in the same family — this is the MPNN signal"
    )


def test_the_threshold_sits_above_the_observed_noise_floor():
    """0.20 is chosen, not inherited. Measured p99 of unrelated design pairs was 0.053,
    and the shipped 0.70 was above the maximum observed similarity (0.298), so it could
    never group anything."""
    assert 0.10 < SEQ_FAMILY_THRESHOLD < 0.50, (
        f"threshold {SEQ_FAMILY_THRESHOLD} is outside the justified band: above the ~0.05 "
        "noise floor of unrelated designs, below the 0.70 that provably groups nothing"
    )


def test_redundancy_is_reported_per_tool():
    """Every near-duplicate pair we measured came from ONE tool, so the column has to say
    which — 'this tool repeated itself' is the actionable form."""
    s = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSG"
    d = _pool([s, s, "PVLSKDEEILRRWNEFAKQHGYTVQWAEDGKA"], tools=["rfd3", "rfd3", "mosaic"])
    out = annotate_sequence_families(d)
    assert "seq_family_tools" in out.columns
    assert out.loc[0, "seq_family_tools"] == "rfd3"
    assert bool(out.loc[0, "seq_family_is_redundant"]) is True
    assert bool(out.loc[2, "seq_family_is_redundant"]) is False


def test_it_never_drops_or_reorders_rows():
    """A diagnostic annotates; it does not filter. Row count and order are preserved."""
    d = _pool(["AAAACCCCGGGG", "AAAACCCCGGGG", "PVLSKDEEILRRWNEF"])
    out = annotate_sequence_families(d)
    assert len(out) == len(d)
    assert list(out["binder_id"]) == list(d["binder_id"])


def test_an_empty_or_missing_column_is_survivable():
    assert annotate_sequence_families(pd.DataFrame()).empty
    d = pd.DataFrame({"binder_id": ["a"]})
    assert "seq_family_id" not in annotate_sequence_families(d).columns
