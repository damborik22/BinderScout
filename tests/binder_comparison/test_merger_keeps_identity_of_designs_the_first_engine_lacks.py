"""A design the FIRST engine's CSV does not contain must keep its identity columns.

`merge_refold_results` outer-joins the engine CSVs on `sequence` and used to drop
every later engine's copy of the passthrough columns (`binder_length`,
`target_sequence`, `run_id`), "preferring the first engine's values". For a design
the first engine never scored there ARE no first-engine values, so the outer join
left NaN and the later engine's real value was thrown away.

`binder_length` is what the report slices each PAE matrix with. Without it every
engine's PAE-derived ipTM/ipSAE for that design is NaN, `consensus_iptm_n` is 0,
and the design is ranked last with no warning -- measured on the archived TfR1
pool, where the victim was the rank-20 design (rank 20 -> 394). Two independent
reviewers found it on 2026-11-03.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from binder_comparison.comparison.merger import merge_refold_results  # noqa: E402

TARGET = "T" * 30
A, B, C = "AAAAKKKKLL", "CCCCDDDDMM", "EEEEFFFFNNN"


def _csv(path, rows):
    pd.DataFrame(
        [
            {"idx": i, "run_id": f"r{i}", "sequence": s, "target_sequence": TARGET, "binder_length": len(s), "iptm": v}
            for i, (s, v) in enumerate(rows, start=1)
        ]
    ).to_csv(path, index=False)
    return path


def _merged(tmp_path, anchor_rows, af3_rows, esm_rows):
    return merge_refold_results(
        _csv(tmp_path / "boltz.csv", anchor_rows),
        af3_csv=_csv(tmp_path / "af3.csv", af3_rows),
        esmfold2_csv=_csv(tmp_path / "esm.csv", esm_rows),
    )


def test_a_design_absent_from_the_first_engine_keeps_binder_length(tmp_path):
    m = _merged(tmp_path, [(A, 0.8), (B, 0.7)], [(A, 0.8), (B, 0.7), (C, 0.9)], [(A, 0.8), (B, 0.7), (C, 0.9)])
    row = m.loc[m["sequence"] == C].iloc[0]
    assert row["binder_length"] == len(C), (
        f"binder_length is {row['binder_length']!r} for a design only the later engines scored. "
        "Every PAE slice for it is then NaN and it is ranked last with no warning."
    )


def test_a_design_absent_from_the_first_engine_keeps_target_and_run_id(tmp_path):
    m = _merged(tmp_path, [(A, 0.8)], [(A, 0.8), (C, 0.9)], [(A, 0.8), (C, 0.9)])
    row = m.loc[m["sequence"] == C].iloc[0]
    assert row["target_sequence"] == TARGET
    assert isinstance(row["run_id"], str) and row["run_id"], "run_id was dropped with the engine's duplicate column"


def test_the_first_engines_values_still_win_where_it_has_them(tmp_path):
    """Coalescing must fill gaps, never overwrite: 'prefer the first engine' still holds."""
    boltz = _csv(tmp_path / "boltz.csv", [(A, 0.8)])
    af3 = _csv(tmp_path / "af3.csv", [(A, 0.8)])
    df = pd.read_csv(af3)
    df["run_id"] = "from-af3"
    df.to_csv(af3, index=False)
    m = merge_refold_results(boltz, af3_csv=af3)
    assert m.loc[m["sequence"] == A, "run_id"].iloc[0] == "r1"


def test_only_one_engine_is_unchanged(tmp_path):
    m = merge_refold_results(_csv(tmp_path / "boltz.csv", [(A, 0.8), (C, 0.9)]))
    assert list(m["binder_length"]) == [len(A), len(C)]


# --- join key and target-column guards (same review, same day) ----------------


def test_case_and_whitespace_do_not_split_a_design(tmp_path):
    """A hand-edited or re-keyed CSV must not turn one design into three single-engine rows."""
    boltz = _csv(tmp_path / "boltz.csv", [(A, 0.8)])
    af3_df = pd.read_csv(_csv(tmp_path / "af3_src.csv", [(A, 0.8)]))
    af3_df["sequence"] = "  " + af3_df["sequence"].str.lower() + " "
    af3_df.to_csv(tmp_path / "af3.csv", index=False)
    esm = _csv(tmp_path / "esm.csv", [(A, 0.8)])
    m = merge_refold_results(boltz, af3_csv=tmp_path / "af3.csv", esmfold2_csv=esm)
    assert len(m) == 1, f"one design became {len(m)} rows: {list(m['sequence'])}"
    assert m[["boltz_iptm", "af3_iptm", "esmfold2_iptm"]].notna().all(axis=1).iloc[0]


def test_a_csv_without_target_sequence_warns_that_the_target_cannot_be_checked(tmp_path):
    boltz = _csv(tmp_path / "boltz.csv", [(A, 0.8)])
    af3 = pd.read_csv(_csv(tmp_path / "af3.csv", [(A, 0.8)])).drop(columns=["target_sequence"])
    af3.to_csv(tmp_path / "af3b.csv", index=False)
    with pytest.warns(UserWarning, match="cannot be checked"):
        merge_refold_results(boltz, af3_csv=tmp_path / "af3b.csv")
