"""Tests for the combined candidates.csv builder (comparison/candidates.py).

Covers the invariants the feature is built around:
  - canonical native-block order + refold block LAST (variants slot under base tool)
  - in-pool filter (never-refolded native designs dropped)
  - backbone collapse (one row per design_group, best native rank kept)
  - design_group native-rank lookup for refold reps (a refold rep that is a
    different MPNN sibling than the native-best one still resolves its rank)
  - "Ranking refolded" is the SAME dense rank in both blocks
  - no blank metric cells for refolded designs; full-chain seq column preferred
"""

import pytest

pd = pytest.importorskip("pandas")
from binder_comparison.comparison.candidates import (  # noqa: E402
    build_candidates_table,
    collapse_native_df,
    display_tool_name,
    order_tools,
)


def test_order_tools_canonical_then_variants_then_unknown():
    tools = ["rfd3", "boltzgen_protein", "mosaic", "bindcraft", "boltzgen_nano", "zzz_tool"]
    assert order_tools(tools) == [
        "bindcraft",
        "boltzgen_nano",  # variants slot under "boltzgen" by prefix, alphabetical
        "boltzgen_protein",
        "mosaic",
        "rfd3",
        "zzz_tool",  # unknown last
    ]


def _full_df():
    # Two backbones for bindcraft (each with an MPNN sibling) + one mosaic design.
    # rank is the full-pool ordering (siblings included); is_representative
    # marks the best-ranked row per design_group.
    return pd.DataFrame(
        {
            "binder_id": ["bc_t1_mpnn1", "bc_t1_mpnn2", "bc_t2_mpnn1", "mos_1"],
            "source_tool": ["bindcraft", "bindcraft", "bindcraft", "mosaic"],
            "sequence": ["AAAA", "AAAB", "CCCC", "MMMM"],
            "design_group": ["bc_t1", "bc_t1", "bc_t2", "mos_1"],
            "binder_length": [10, 10, 12, 30],
            "consensus_iptm_mean": [0.90, 0.88, 0.70, 0.95],
            "consensus_ipsae_min_mean": [0.80, 0.78, 0.60, 0.85],
            "native_soluprot_score": [0.5, 0.5, 0.6, 0.7],
            "rank": [2, 3, 4, 1],
            "is_representative": [True, False, True, True],
        }
    )


def _df_display(full):
    """Like cli/report.py: collapse to representatives, never renumber.

    `rank` stays each SEQUENCE's own, so the shortlist skips a number where a
    sibling was collapsed and every row can quote the rank of the exact sequence
    it names.
    """
    return full[full["is_representative"]].sort_values("rank").reset_index(drop=True).copy()


def _write(tmp_path, name, df):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return str(p)


def test_collapse_prefers_full_chain_and_filters_in_pool(tmp_path):
    seq_to_group = {"AAAA": "bc_t1", "CCCC": "bc_t2"}
    # BoltzGen-style CSV: `sequence` is a truncated CDR, full chain in
    # designed_chain_sequence — collapse must key on the full chain.
    native = pd.DataFrame(
        {
            "sequence": ["cdr1", "cdr2"],
            "designed_chain_sequence": ["AAAA", "ZZZZ"],  # ZZZZ not in pool
        }
    )
    out = collapse_native_df(_write(tmp_path, "bg.csv", native), seq_to_group)
    assert list(out["_seq_key"]) == ["AAAA"]  # full-chain match; ZZZZ dropped (not refolded)


def test_collapse_warns_when_stale_csv_matches_nothing_in_pool(tmp_path):
    # A stale native CSV (tool re-run since it was written) matches no pool
    # sequence, so the in-pool filter empties it and the tool's whole native
    # block disappears. That must be loud — silently dropping a tool the caller
    # explicitly asked for is how a shortlist ships missing a design tool.
    native = pd.DataFrame({"sequence": ["OLD1", "OLD2"]})
    path = _write(tmp_path, "stale.csv", native)
    with pytest.warns(UserWarning, match="refold pool"):
        out = collapse_native_df(path, {"AAAA": "bc_t1"})
    assert out.empty


def test_build_candidates_full(tmp_path):
    full = _full_df()
    disp = _df_display(full)
    # bindcraft native CSV in native-rank order. Both bc_t1 siblings are listed,
    # and the tool ranks AAAB above AAAA while our refold prefers AAAA — the real
    # BindCraft case (it rates l127_s975277_mpnn3 4th; we rate its sibling _mpnn4
    # higher). Includes a never-refolded design (XXXX) that must be dropped.
    bindcraft = pd.DataFrame({"Sequence": ["AAAB", "AAAA", "XXXX", "CCCC"]})
    mosaic = pd.DataFrame({"sequence": ["MMMM"]})
    tool_csvs = {
        "bindcraft": _write(tmp_path, "bc.csv", bindcraft),
        "mosaic": _write(tmp_path, "mos.csv", mosaic),
    }
    t = build_candidates_table(full, disp, tool_csvs, n_native=20, n_refold=30)

    # No blank cells anywhere.
    assert int(t.map(lambda x: str(x).strip() == "").to_numpy().sum()) == 0

    # Native blocks first (canonical order), refold block last.
    sets = list(dict.fromkeys(t["Set"]))
    assert sets == ["Native top-20", "Refold top-30"]  # this call passes n_refold=30 explicitly
    native_order = list(dict.fromkeys(t[t["Set"].str.startswith("Native")]["Method"]))
    assert native_order == ["BindCraft", "Mosaic"]  # display names, not join keys

    # bindcraft native block reproduces the TOOL's list: XXXX dropped (never
    # refolded), but BOTH bc_t1 siblings kept and numbered 1,2,3 with no holes.
    # Backbone collapse is for OUR shortlist only — it must not rewrite the
    # tool's own top-N (doing so renumbered BindCraft's as 1,2,3,4,7,8,11,…).
    bc_nat = t[(t["Set"].str.startswith("Native")) & (t["Method"] == "BindCraft")]
    assert list(bc_nat["Primary sequence"]) == ["AAAB", "AAAA", "CCCC"]
    assert list(bc_nat["Ranking native"]) == [1, 2, 3]

    # THE POINT: the refold block's bc_t1 row holds AAAA, so it must print AAAA's
    # OWN native rank (2) — not AAAB's 1, which is a different sequence.
    refold = t[t["Set"].str.startswith("Refold")]
    bc_ref = refold[refold["Method"] == "BindCraft"]
    bc_t1_row = bc_ref[bc_ref["Primary sequence"] == "AAAA"]
    assert list(bc_t1_row["Ranking native"]) == [2]

    # Every rank is its own sequence's: AAAA refolds at 2, AAAB at 3. The refold
    # block therefore skips 3 — AAAB was collapsed as a sibling of AAAA.
    assert list(bc_t1_row["Ranking refolded"]) == [2]
    assert list(bc_nat[bc_nat["Primary sequence"] == "AAAB"]["Ranking refolded"]) == [3]
    assert sorted(refold["Ranking refolded"]) == [1, 2, 4]

    # Length is a plain int, not a float.
    assert all(isinstance(v, int) for v in t["Length"])


def test_warns_when_a_native_csv_only_partly_covers_the_pool(tmp_path):
    """A native CSV missing some pool designs leaves blank native ranks — say so.

    collapse_native_df already shouts when a tool's CSV matches NOTHING in the
    pool. The partial case was silent: on the 2VDY combined pool three snapshots
    covered 47–48 of their tool's 50 designs, so 7 designs had no native rank and
    two of them surfaced as blank cells in the refold top-50 with no explanation.
    """
    full = _full_df()
    disp = _df_display(full)
    # bindcraft's CSV covers backbone bc_t1 but omits CCCC (bc_t2), which IS in
    # the refold pool — so bc_t2's refold row can resolve no native rank.
    tool_csvs = {"bindcraft": _write(tmp_path, "bc.csv", pd.DataFrame({"Sequence": ["AAAB"]}))}
    with pytest.warns(UserWarning, match="native rank"):
        t = build_candidates_table(full, disp, tool_csvs, n_native=20, n_refold=30)
    # the unresolvable rows are still emitted, just with a blank native rank
    refold = t[t["Set"].str.startswith("Refold")]
    assert (refold["Ranking native"] == "").any()


def test_native_row_is_one_real_design(tmp_path):
    """Every metric in a native row must belong to the design it names.

    A backbone's native-best sibling and its refold representative can be
    DIFFERENT sequences (bindcraft MPNN siblings). Showing one sibling's
    sequence/ipTM next to the other's refold rank makes a row that describes no
    real design: the reader looks up the stated rank and finds different
    numbers. Measured on the shipped CALCA top-50 pool, 10 of 140 native rows
    were such chimeras — e.g. bindcraft native #4 carried mpnn3's ipTM (0.917,
    true rank 26) beside mpnn4's rank (22, ipTM 0.921).
    """
    full = _full_df()
    disp = _df_display(full)
    # bc_t1's best NATIVE row is the mpnn2 sibling (AAAB); its refold
    # representative is the mpnn1 sibling (AAAA) — deliberately different.
    tool_csvs = {"bindcraft": _write(tmp_path, "bc.csv", pd.DataFrame({"Sequence": ["AAAB", "CCCC"]}))}
    t = build_candidates_table(full, disp, tool_csvs, n_native=20, n_refold=30)

    nat = t[t["Set"].str.startswith("Native")]
    by_seq = full.set_index("sequence")
    # a rank identifies a DESIGN, so it must resolve to this row's backbone
    rank_to_group = dict(zip(full["rank"], full["design_group"], strict=False))
    seq_to_group = dict(zip(full["sequence"], full["design_group"], strict=False))
    for _, row in nat.iterrows():
        seq = row["Primary sequence"]
        shown_rank = row["Ranking refolded"]
        # the row's own metrics
        assert row["Mean_ipTM"] == round(by_seq.loc[seq, "consensus_iptm_mean"], 3)
        assert row["Length"] == by_seq.loc[seq, "binder_length"]
        # …and the rank it prints must belong to THIS design, not another one
        assert rank_to_group[shown_rank] == seq_to_group[seq], (
            f"native row names {seq} (design {seq_to_group[seq]}) but prints rank "
            f"{shown_rank}, which belongs to design {rank_to_group[shown_rank]}"
        )
    # no native row may be left without a cross-reference
    assert not (nat["Ranking refolded"].astype(str).str.strip() == "").any()


def test_refold_only_when_no_tool_csvs():
    full = _full_df()
    disp = _df_display(full)
    t = build_candidates_table(full, disp, None)
    assert set(t["Set"]) == {"Refold top-50"}
    # No native CSVs → "Ranking native" is unresolvable (blank), but every other
    # column is populated from the refold pool.
    assert (t["Ranking native"].astype(str).str.strip() == "").all()
    other = t.drop(columns=["Ranking native"])
    assert int(other.map(lambda x: str(x).strip() == "").to_numpy().sum()) == 0


def test_tool_names_are_human_readable():
    """The Method column is for a reader, so it must not print raw keys.

    Join keys (`source_tool`, `--tool-csv` names) stay lowercase; this is display
    only. Variants keep their qualifier so the two BoltzGen modes stay apart, and
    an unknown tool passes through rather than being mangled.
    """
    assert display_tool_name("protein_hunter") == "Protein Hunter"
    assert display_tool_name("rfd3") == "RFDiffusion3"
    assert display_tool_name("proteina_complexa") == "Proteina-Complexa"
    assert display_tool_name("pxdesign") == "PXDesign"
    assert display_tool_name("boltzgen") == "BoltzGen"
    assert display_tool_name("bindcraft") == "BindCraft"
    assert display_tool_name("mosaic") == "Mosaic"
    # variants keep their qualifier
    assert display_tool_name("boltzgen_protein") == "BoltzGen (protein)"
    assert display_tool_name("boltzgen_nano") == "BoltzGen (nano)"
    # unknown / empty pass through untouched
    assert display_tool_name("some_new_tool") == "some_new_tool"
    assert display_tool_name("") == ""


def test_candidates_method_column_uses_display_names(tmp_path):
    full = _full_df()
    disp = _df_display(full)
    tool_csvs = {"bindcraft": _write(tmp_path, "bc.csv", pd.DataFrame({"Sequence": ["AAAB", "CCCC"]}))}
    t = build_candidates_table(full, disp, tool_csvs, n_native=20, n_refold=30)
    assert "bindcraft" not in set(t["Method"])
    assert "BindCraft" in set(t["Method"])
