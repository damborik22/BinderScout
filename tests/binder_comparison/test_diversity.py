"""Tests for Phase 3 Item 1 — cross-design diversity clustering."""

import pytest

pytest.importorskip("pandas")
import pandas as pd
from binder_comparison.comparison.diversity import (
    cluster_sequences,
    cluster_sequences_df,
    top_per_family,
)

# Three nearly-identical 30-mers and one outlier — should form 2 families.
SIMILAR_SET = [
    "MAEVKLILEELEEAVRRALAQGLSQEEIIK",
    "MAEVKLILEELEEAVRRALAQGLSQEELIK",  # 1 char diff vs #1
    "MAEVKLILEELEEAVRRALAQGLSQEELIR",  # 1 char diff vs #2
    "GHTKYNCVPQSDLMWTRNAGFEPCLAVRMK",  # completely different
]


def test_cluster_sequences_merges_near_duplicates():
    fams = cluster_sequences(SIMILAR_SET, threshold=0.7, k=4)
    # First three sequences share most k-mers and should fall in one family;
    # the outlier sits in its own.
    assert len(set(fams)) == 2
    # The first three should share the same family id (they're > 70% Jaccard).
    assert fams[0] == fams[1] == fams[2]
    assert fams[3] != fams[0]


def test_cluster_sequences_threshold_one_makes_singletons():
    """A threshold of 1.0 only merges exact duplicates (when seqs differ)."""
    fams = cluster_sequences(SIMILAR_SET, threshold=1.0, k=4)
    assert len(set(fams)) == 4


def test_cluster_sequences_handles_empty_sequence():
    fams = cluster_sequences(["", "MAEV", ""], threshold=0.7, k=4)
    # The empty strings become singleton clusters; "MAEV" is too short for k=4
    # so it also becomes a singleton (empty k-mer set).
    assert len(set(fams)) == 3


def test_cluster_sequences_empty_input():
    assert cluster_sequences([]) == []


def test_cluster_sequences_df_adds_columns():
    df = pd.DataFrame({"binder_id": ["a", "b", "c", "d"], "sequence": SIMILAR_SET})
    out = cluster_sequences_df(df, sequence_col="sequence", threshold=0.7, k=4)
    assert "family_id" in out.columns
    assert "family_size" in out.columns
    assert "family_rank" in out.columns
    # 4 designs → 2 families.
    assert out["family_id"].nunique() == 2


def test_cluster_sequences_df_family_size_correct():
    df = pd.DataFrame({"binder_id": ["a", "b", "c", "d"], "sequence": SIMILAR_SET})
    out = cluster_sequences_df(df, sequence_col="sequence", threshold=0.7, k=4)
    counts = out.groupby("family_id")["family_size"].first().sort_values(ascending=False).tolist()
    assert counts == [3, 1]


def test_cluster_sequences_df_no_sequence_column_returns_empty_families():
    df = pd.DataFrame({"binder_id": ["a", "b"]})
    out = cluster_sequences_df(df)
    assert (out["family_id"] == "").all()
    assert (out["family_size"] == 0).all()


def test_top_per_family_picks_best_rank():
    df = pd.DataFrame(
        {
            "binder_id": ["a", "b", "c", "d"],
            "family_id": ["F1", "F1", "F2", "F1"],
            "two_stage_rank": [3, 1, 5, 7],
        }
    )
    picks = top_per_family(df, n_per_family=1, sort_col="two_stage_rank", ascending=True)
    # F1 best by rank is 'b' (rank 1); F2 best is 'c' (rank 5).
    ids = sorted(picks["binder_id"].tolist())
    assert ids == ["b", "c"]


def test_top_per_family_n_per_family_argument():
    df = pd.DataFrame(
        {
            "binder_id": ["a", "b", "c", "d"],
            "family_id": ["F1", "F1", "F2", "F1"],
            "two_stage_rank": [3, 1, 5, 7],
        }
    )
    picks = top_per_family(df, n_per_family=2, sort_col="two_stage_rank", ascending=True)
    assert len(picks) == 3  # F1 contributes 2 (b, a); F2 contributes 1 (c)


def test_top_per_family_no_family_id_returns_input():
    df = pd.DataFrame({"binder_id": ["a", "b"], "two_stage_rank": [1, 2]})
    out = top_per_family(df, n_per_family=1, sort_col="two_stage_rank")
    pd.testing.assert_frame_equal(out, df)
