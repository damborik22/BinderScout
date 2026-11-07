"""Scoring reads the engine panel: the second slot is selectable, the default is untouched.

A synthetic pool is built in the test itself (no GPU, no refold). The same numbers are
held under ``af3_*`` and, renamed, under ``protenix_*``; the two panels must score them
identically, and an engine outside the panel must never leak into the mean.
"""

import pytest

pytest.importorskip("pandas")

import numpy as np
import pandas as pd
from binder_comparison.comparison import confidence_gate, foldseek, scoring, self_consistency
from binder_comparison.comparison.scoring import (
    apply_screening_thresholds,
    compute_agreement,
    compute_consensus_ipsae,
    compute_consensus_iptm,
    rank_designs,
)
from binder_comparison.core.engines import resolve_panel

_BOLTZ = [0.90, 0.80, 0.70, 0.60, 0.55, 0.40]
_SECOND = [0.85, 0.82, 0.30, 0.65, np.nan, 0.45]
_ESM = [0.88, 0.70, 0.75, np.nan, 0.50, 0.35]


def _pool(second: str = "af3", *, with_other: str | None = None) -> pd.DataFrame:
    """Six designs; the second slot's iptm/ipsae/pdb columns carry the real engine name."""
    data = {
        "binder_id": [f"d{i}" for i in range(6)],
        "boltz_pae_iptm": _BOLTZ,
        f"{second}_pae_iptm": _SECOND,
        "esmfold2_pae_iptm": _ESM,
        "boltz_pae_ipsae_min": [0.9, 0.7, 0.5, 0.65, 0.3, 0.2],
        f"{second}_ipsae_min": [0.8, 0.9, 0.2, 0.7, np.nan, 0.1],
        "esmfold2_ipsae_min": [0.85, 0.6, 0.7, np.nan, 0.62, 0.1],
    }
    if with_other:
        data[f"{with_other}_pae_iptm"] = [0.99] * 6
        data[f"{with_other}_ipsae_min"] = [0.99] * 6
    return pd.DataFrame(data)


def test_protenix_panel_ranks_a_renamed_pool_exactly_as_the_af3_panel_ranks_the_original():
    af3 = rank_designs(compute_consensus_iptm(_pool("af3")))
    px_panel = resolve_panel("protenix")
    px = rank_designs(compute_consensus_iptm(_pool("protenix"), panel=px_panel), panel=px_panel)
    for col in ("rank", "consensus_iptm_mean", "consensus_iptm_n", "passes_engine_gate", "binder_id"):
        pd.testing.assert_series_equal(af3[col], px[col], check_names=False)


def test_rank_designs_alone_computes_the_consensus_from_the_panel():
    px_panel = resolve_panel("protenix")
    one_step = rank_designs(_pool("protenix"), panel=px_panel)
    two_step = rank_designs(compute_consensus_iptm(_pool("protenix"), panel=px_panel), panel=px_panel)
    pd.testing.assert_frame_equal(one_step, two_step)


def test_the_protenix_panel_ignores_af3_columns_in_the_same_frame():
    panel = resolve_panel("protenix")
    both = _pool("protenix", with_other="af3")
    out = compute_consensus_iptm(both, panel=panel)
    assert out["consensus_iptm_n"].max() <= 3
    # The af3 value is not an input: change it, the mean does not move.
    changed = both.assign(af3_pae_iptm=0.01)
    again = compute_consensus_iptm(changed, panel=panel)
    pd.testing.assert_series_equal(out["consensus_iptm_mean"], again["consensus_iptm_mean"])
    # ...and it equals the mean over boltz / protenix / esmfold2 only.
    expect = both[["boltz_pae_iptm", "protenix_pae_iptm", "esmfold2_pae_iptm"]].mean(axis=1)
    pd.testing.assert_series_equal(out["consensus_iptm_mean"], expect, check_names=False)
    # rank_designs must not let it through either.
    r1 = rank_designs(both, panel=panel)
    r2 = rank_designs(changed, panel=panel)
    pd.testing.assert_series_equal(r1["rank"], r2["rank"])
    pd.testing.assert_series_equal(r1["consensus_iptm_n"], r2["consensus_iptm_n"])


def test_the_default_panel_ignores_protenix_columns():
    both = _pool("af3", with_other="protenix")
    out = compute_consensus_iptm(both)
    assert out["consensus_iptm_n"].max() <= 3
    changed = compute_consensus_iptm(both.assign(protenix_pae_iptm=0.01))
    pd.testing.assert_series_equal(out["consensus_iptm_mean"], changed["consensus_iptm_mean"])


def test_default_panel_equals_the_panel_none_call():
    df = _pool("af3")
    default = resolve_panel("af3")
    pd.testing.assert_frame_equal(compute_consensus_iptm(df), compute_consensus_iptm(df, panel=default))
    pd.testing.assert_frame_equal(compute_consensus_ipsae(df), compute_consensus_ipsae(df, panel=default))
    pd.testing.assert_frame_equal(rank_designs(df), rank_designs(df, panel=default))
    pd.testing.assert_frame_equal(apply_screening_thresholds(df), apply_screening_thresholds(df, panel=default))
    pd.testing.assert_frame_equal(compute_agreement(df), compute_agreement(df, panel=default))


def test_panel_none_still_reads_the_module_level_column_list(monkeypatch):
    """test_ranking_is_pinned monkeypatches the name; the default path must still consult it."""
    df = _pool("af3")
    monkeypatch.setattr(scoring, "_ENGINE_IPTM_COLS", ["boltz_pae_iptm", "af3_pae_iptm"])
    assert compute_consensus_iptm(df)["consensus_iptm_n"].max() == 2


def test_gate_warning_names_the_panels_columns():
    panel = resolve_panel("protenix")
    empty = pd.DataFrame({"binder_id": ["a"], "af3_pae_iptm": [0.9]})  # nothing of the protenix panel
    with pytest.warns(UserWarning) as rec:
        rank_designs(empty, panel=panel)
    text = " ".join(str(w.message) for w in rec)
    assert "protenix_pae_iptm" in text and "af3_pae_iptm" not in text


def test_consensus_ipsae_follows_the_panel():
    panel = resolve_panel("protenix")
    both = _pool("protenix", with_other="af3")
    out = compute_consensus_ipsae(both, panel=panel)
    expect = both[["boltz_pae_ipsae_min", "protenix_ipsae_min", "esmfold2_ipsae_min"]].mean(axis=1)
    pd.testing.assert_series_equal(out["consensus_ipsae_min_mean"], expect, check_names=False)
    assert out["consensus_ipsae_min_n"].max() <= 3


def test_agreement_count_follows_the_panel():
    panel = resolve_panel("protenix")
    both = _pool("protenix", with_other="af3")
    out = compute_agreement(both, panel=panel)
    # the af3 column (0.99 everywhere) would add 1 to every count if it were read
    expect = (
        (both["boltz_pae_ipsae_min"] > 0.61).astype(int)
        + (both["protenix_ipsae_min"] > 0.61).astype(int)
        + (both["esmfold2_ipsae_min"] > 0.61).astype(int)
    )
    assert list(out["agreement_count"]) == list(expect)
    assert out["agreement_denom"].max() == 3
    # a per-engine threshold keyed by the engine's name applies to the second slot
    strict = compute_agreement(both, panel=panel, engine_thresholds={"protenix": 0.95})
    assert strict["agreement_count"].sum() < out["agreement_count"].sum()


def test_screening_thresholds_follow_the_panel():
    panel = resolve_panel("protenix")
    both = _pool("protenix", with_other="af3")
    out = apply_screening_thresholds(both, panel=panel)
    assert "passes_protenix_filter" in out.columns
    assert "passes_af3_filter" not in out.columns
    assert list(out["passes_protenix_filter"].fillna(False)) == list(both["protenix_ipsae_min"].fillna(0) > 0.61)
    loose = apply_screening_thresholds(both, panel=panel, engine_thresholds={"protenix": 0.1})
    assert loose["passes_protenix_filter"].sum() > out["passes_protenix_filter"].sum()
    # the default call still emits the af3 flag and never a protenix one
    default = apply_screening_thresholds(_pool("af3"))
    assert "passes_af3_filter" in default.columns and "passes_protenix_filter" not in default.columns


def test_structure_path_remap_follows_the_panel(tmp_path):
    out_dir = tmp_path / "refold_protenix"
    out_dir.mkdir()
    (out_dir / "d0_protenix.pdb").write_text("x")
    df = pd.DataFrame(
        {"binder_id": ["d0"], "protenix_pdb": ["/elsewhere/refold_protenix/d0_protenix.pdb"], "af3_pdb": ["/n/af3.pdb"]}
    )
    with pytest.warns(UserWarning, match="REMAPPED"):
        out = scoring.remap_structure_paths(df, {"protenix": tmp_path}, panel=resolve_panel("protenix"))
    assert out["protenix_pdb"][0] == str(out_dir / "d0_protenix.pdb")
    assert out["af3_pdb"][0] == "/n/af3.pdb"  # not in the panel: left alone


def test_pae_path_resolution_stops_at_any_registered_engine_directory(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x_pae.npy").write_text("x")
    # A path that names refold_protenix is never remapped to a file below the base that merely
    # shares its name -- the same bound the AF3 directory has.
    p = scoring._resolve_pae_path("/gone/refold_protenix/sub/x_pae.npy", tmp_path)
    assert p is None


def test_confidence_gate_reads_the_second_engine_of_the_panel():
    df = pd.DataFrame(
        {
            "boltz_iptm": [0.9],
            "protenix_iptm": [0.1],
            "protenix_plddt_binder_mean": [0.9],
            "protenix_pae_bt_mean": [4.0],
            "protenix_pae_tb_mean": [6.0],
            "af3_iptm": [0.9],
            "af3_pae_bt_mean": [4.0],
            "af3_pae_tb_mean": [6.0],
        }
    )
    out = confidence_gate.annotate_confidence_gate(df, panel=resolve_panel("protenix"))
    assert "af3_ipae_ang" not in out.columns
    assert "protenix_ipae_ang" in out.columns
    assert "protenix_iptm<0.5" in out["confidence_fail_reasons"][0]
    default = confidence_gate.annotate_confidence_gate(df)
    assert "af3_ipae_ang" in default.columns and "protenix_ipae_ang" not in default.columns


def test_self_consistency_and_foldseek_follow_the_panel():
    literal = {"boltz": "boltz_pdb", "af3": "af3_pdb", "esmfold2": "esmfold2_pdb"}
    assert self_consistency.engine_pdb_cols(None) == literal
    assert literal == self_consistency._ENGINE_PDB_COLS
    default = resolve_panel()
    assert {e.name: e.pdb_cols[0] for e in default.engines} == self_consistency._ENGINE_PDB_COLS
    assert foldseek._DEFAULT_PDB_COLS == ("boltz_pdb", "af3_pdb", "esmfold2_pdb", "pdb")
    assert (*(e.pdb_cols[0] for e in default.engines), "pdb") == foldseek._DEFAULT_PDB_COLS
    assert self_consistency.engine_pdb_cols(resolve_panel("protenix")) == {
        "boltz": "boltz_pdb",
        "protenix": "protenix_pdb",
        "esmfold2": "esmfold2_pdb",
    }
    assert foldseek.panel_pdb_cols(resolve_panel("protenix")) == ("boltz_pdb", "protenix_pdb", "esmfold2_pdb", "pdb")
    assert foldseek.panel_pdb_cols(None) == ("boltz_pdb", "af3_pdb", "esmfold2_pdb", "pdb")


def test_the_default_gate_engines_do_not_follow_the_candidate_map(monkeypatch):
    """Adding a protenix row to _IPTM_COLS must not put Protenix into the DEFAULT panel's gate."""
    monkeypatch.setitem(confidence_gate._IPTM_COLS, "protenix", ("protenix_iptm",))
    df = pd.DataFrame(
        {
            "boltz_iptm": [0.9],
            "protenix_iptm": [0.9],
            "protenix_pae_bt_mean": [4.0],
            "protenix_pae_tb_mean": [6.0],
            "af3_iptm": [0.9],
            "af3_pae_bt_mean": [4.0],
            "af3_pae_tb_mean": [6.0],
        }
    )
    out = confidence_gate.annotate_confidence_gate(df)
    assert "protenix_ipae_ang" not in out.columns
    assert "af3_ipae_ang" in out.columns


def test_rank_designs_with_a_panel_recomputes_a_stale_consensus():
    """A consensus computed under the AF3 panel must not be ranked under the Protenix panel's name."""
    af3_scored = compute_consensus_iptm(_pool("af3"))
    px = resolve_panel("protenix")
    frame = af3_scored.rename(columns={"af3_pae_iptm": "protenix_pae_iptm", "af3_ipsae_min": "protenix_ipsae_min"})
    frame["protenix_pae_iptm"] = 0.5  # the stale consensus no longer matches the columns
    ranked = rank_designs(frame, panel=px)
    expect = frame[["boltz_pae_iptm", "protenix_pae_iptm", "esmfold2_pae_iptm"]].mean(axis=1)
    pd.testing.assert_series_equal(
        ranked.set_index("binder_id")["consensus_iptm_mean"].sort_index(),
        pd.Series(
            expect.values, index=pd.Index(frame["binder_id"], name="binder_id"), name="consensus_iptm_mean"
        ).sort_index(),
    )
