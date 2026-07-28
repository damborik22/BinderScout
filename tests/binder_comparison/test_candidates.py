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
    disp = full[full["is_representative"]].sort_values("rank").reset_index(drop=True).copy()
    disp["rank"] = range(1, len(disp) + 1)  # dense, like cli/report.py
    return disp


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
    # bindcraft native CSV in native-rank order; the best-native row of bc_t1 is
    # the mpnn2 sibling (AAAB), NOT the refold representative (AAAA). Includes a
    # never-refolded design (XXXX) that must be dropped.
    bindcraft = pd.DataFrame({"Sequence": ["AAAB", "XXXX", "CCCC"]})
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
    assert sets == ["Native top-20", "Refold top-30"]
    native_order = list(dict.fromkeys(t[t["Set"].str.startswith("Native")]["Method"]))
    assert native_order == ["bindcraft", "mosaic"]

    # bindcraft native block: XXXX dropped (not refolded), bc_t1 collapsed to one
    # row (AAAB kept — best native rank), dense native rank 1..N.
    bc_nat = t[(t["Set"].str.startswith("Native")) & (t["Method"] == "bindcraft")]
    assert list(bc_nat["Primary sequence"]) == ["AAAB", "CCCC"]
    assert list(bc_nat["Ranking native"]) == [1, 2]

    # The bc_t1 refold representative (AAAA) is a DIFFERENT sibling than the
    # native-best (AAAB); its refold-block "Ranking native" still resolves to
    # bc_t1's native rank (1) via design_group.
    refold = t[t["Set"].str.startswith("Refold")]
    bc_ref = refold[refold["Method"] == "bindcraft"]
    bc_t1_row = bc_ref[bc_ref["Primary sequence"] == "AAAA"]
    assert list(bc_t1_row["Ranking native"]) == [1]

    # "Ranking refolded" is the SAME dense rank in both blocks for a backbone.
    # bc_t1's refold rep AAAA is dense rank 2; its native row (AAAB) must show 2.
    assert list(bc_t1_row["Ranking refolded"]) == [2]
    assert list(bc_nat[bc_nat["Primary sequence"] == "AAAB"]["Ranking refolded"]) == [2]

    # Length is a plain int, not a float.
    assert all(isinstance(v, int) for v in t["Length"])


def test_refold_only_when_no_tool_csvs():
    full = _full_df()
    disp = _df_display(full)
    t = build_candidates_table(full, disp, None)
    assert set(t["Set"]) == {"Refold top-30"}
    # No native CSVs → "Ranking native" is unresolvable (blank), but every other
    # column is populated from the refold pool.
    assert (t["Ranking native"].astype(str).str.strip() == "").all()
    other = t.drop(columns=["Ranking native"])
    assert int(other.map(lambda x: str(x).strip() == "").to_numpy().sum()) == 0
