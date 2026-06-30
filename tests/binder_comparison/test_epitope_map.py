"""Tests for the target binding-map analysis (comparison/epitope_map.py)."""

from binder_comparison.comparison.epitope_map import (
    cluster_binding_modes,
    design_footprints,
    mode_consensus,
    parse_residue_tokens,
    residue_frequency,
)


def test_parse_residue_tokens_bare_and_chain_prefixed():
    assert parse_residue_tokens("18,19,22") == {18, 19, 22}
    assert parse_residue_tokens("A18,A232,B5") == {18, 232, 5}  # chain letters stripped
    assert parse_residue_tokens("18, A19 , garbage, 22") == {18, 19, 22}
    assert parse_residue_tokens("") == set()
    assert parse_residue_tokens(None) == set()
    assert parse_residue_tokens(float("nan")) == set()


def test_design_footprints_union_and_skip_empty():
    rows = [
        {"binder_id": "d1", "epitope_matched_residues": "18,19", "epitope_off_target_residues": "A50"},
        {"binder_id": "d2", "epitope_matched_residues": "", "epitope_off_target_residues": ""},  # skipped
    ]
    fp = design_footprints(rows)
    assert fp == {"d1": {18, 19, 50}}  # matched ∪ off-target; d2 dropped (empty)


def test_residue_frequency_counts_across_designs():
    fp = {"a": {18, 19}, "b": {18, 50}, "c": {18}}
    freq = residue_frequency(fp)
    assert freq[18] == 3
    assert freq[19] == 1
    assert freq[50] == 1


def test_cluster_binding_modes_merges_overlapping_separates_disjoint():
    fp = {
        "a": {1, 2, 3, 4},
        "b": {1, 2, 3, 5},  # high Jaccard with a -> same mode
        "z": {90, 91, 92, 93},  # disjoint -> own mode
    }
    modes = cluster_binding_modes(fp, threshold=0.5)
    assert len(modes) == 2
    biggest = modes[0]
    assert set(biggest["members"]) == {"a", "b"}  # a and b cluster together


def test_cluster_binding_modes_threshold_one_makes_singletons():
    fp = {"a": {1, 2, 3}, "b": {1, 2, 4}}  # Jaccard 0.5 < 1.0
    modes = cluster_binding_modes(fp, threshold=1.0)
    assert len(modes) == 2


def test_mode_consensus_by_fraction():
    fp = {"a": {1, 2, 3}, "b": {1, 2, 9}, "c": {1, 7, 8}}
    # residue 1 in all 3; residue 2 in 2/3; with frac 0.5 -> {1,2}
    assert mode_consensus(fp, ["a", "b", "c"], frac=0.5) == [1, 2]
    # frac 0.99 -> only residue 1 (in all)
    assert mode_consensus(fp, ["a", "b", "c"], frac=0.99) == [1]
