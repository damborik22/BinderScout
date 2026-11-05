"""Tests for the panel-comparison maths used by the AF3-replacement benchmark."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from binder_comparison.comparison import panel_benchmark as pb


def _pool() -> pd.DataFrame:
    """Two targets of different size; the score separates binders perfectly on t1 only."""
    return pd.DataFrame(
        {
            "target": ["t1"] * 6 + ["t2"] * 10,
            "binds": [True, True, True, False, False, False] + [True, False] * 5,
            "good": [0.9, 0.8, 0.7, 0.3, 0.2, 0.1] + [0.5, 0.4, 0.6, 0.3, 0.2, 0.7, 0.45, 0.35, 0.55, 0.25],
            "bad": [0.1, 0.2, 0.3, 0.7, 0.8, 0.9] + [0.5, 0.4, 0.6, 0.3, 0.2, 0.7, 0.45, 0.35, 0.55, 0.25],
        }
    )


def test_blank_engine_blanks_the_design():
    df = pd.DataFrame({"a": [0.8, 0.6, 0.7], "b": [0.6, np.nan, 0.5], "c": [0.7, 0.9, 0.6]})
    out = pb.panel_consensus(df, ["a", "b", "c"])
    assert out.iloc[0] == pytest.approx(0.7)
    assert np.isnan(out.iloc[1])  # one blank engine blanks the design; it is not a 2-engine mean
    assert out.iloc[2] == pytest.approx(0.6)


def test_auc_is_the_rank_statistic_with_average_ranks_for_ties():
    df = pd.DataFrame({"target": ["t"] * 4, "binds": [True, True, False, False]})
    # perfect separation
    assert pb.per_target_auc(df, pd.Series([0.9, 0.8, 0.2, 0.1]))["t"] == 1.0
    # all tied -> 0.5 exactly
    assert pb.per_target_auc(df, pd.Series([0.5, 0.5, 0.5, 0.5]))["t"] == 0.5
    # binder 0.5 ties non-binder 0.5: pair outcomes 1, 1, 0.5, 1 -> 3.5 / 4
    assert pb.per_target_auc(df, pd.Series([0.9, 0.5, 0.5, 0.1]))["t"] == pytest.approx(0.875)


def test_one_class_target_has_nan_auc_and_is_not_averaged_as_half():
    df = pd.DataFrame(
        {
            "target": ["t1"] * 4 + ["t2"] * 3,
            "binds": [True, True, False, False, True, True, True],
        }
    )
    score = pd.Series([0.9, 0.8, 0.2, 0.1, 0.3, 0.2, 0.1])
    auc = pb.per_target_auc(df, score)
    assert auc["t1"] == 1.0
    assert np.isnan(auc["t2"])
    # the macro difference averages only targets with an AUC in both scores
    res = pb.paired_bootstrap_diff(df, score, score + 0.0, n_boot=20, seed=1)
    assert list(res["per_target_diff"]) == ["t1", "t2"]
    assert np.isnan(res["per_target_diff"]["t2"])
    assert res["macro_diff"] == 0.0


def test_nan_labels_are_dropped_not_counted_as_negatives():
    df = pd.DataFrame({"target": ["t"] * 5, "binds": [True, False, np.nan, True, False]}, dtype=object)
    score = pd.Series([0.9, 0.1, 0.95, 0.8, 0.2])  # the unlabelled design scores highest
    assert pb.per_target_auc(df, score)["t"] == 1.0  # as a counted negative it would have cost AUC


def test_non_boolean_labels_are_refused():
    df = pd.DataFrame({"target": ["t"] * 3, "binds": ["yes", "no", "yes"]})
    with pytest.raises(ValueError, match="binds"):
        pb.per_target_auc(df, pd.Series([0.3, 0.2, 0.1]))


def test_bootstrap_resamples_within_target(monkeypatch):
    df = _pool()
    seen: list[int] = []
    real = pb._auc

    def spy(labels, scores):
        seen.append(len(labels))
        return real(labels, scores)

    monkeypatch.setattr(pb, "_auc", spy)
    n_boot = 7
    pb.paired_bootstrap_diff(df, df["good"], df["bad"], n_boot=n_boot, seed=3)
    # each iteration: 2 targets x 2 scores; skip the point-estimate calls made before resampling
    resampled = seen[-4 * n_boot :]
    for i in range(n_boot):
        assert sorted(resampled[4 * i : 4 * i + 4]) == [6, 6, 10, 10]


def test_both_scores_get_the_same_resample():
    df = _pool()
    res = pb.paired_bootstrap_diff(df, df["good"], df["good"].copy(), n_boot=50, seed=5)
    # identical scores on identical resamples differ by exactly zero in every resample
    assert (res["macro_diff"], res["ci_low"], res["ci_high"]) == (0.0, 0.0, 0.0)


def test_bootstrap_is_deterministic_and_reports_direction():
    df = _pool()
    a = pb.paired_bootstrap_diff(df, df["good"], df["bad"], n_boot=200, seed=11)
    b = pb.paired_bootstrap_diff(df, df["good"], df["bad"], n_boot=200, seed=11)
    c = pb.paired_bootstrap_diff(df, df["good"], df["bad"], n_boot=200, seed=12)
    assert a == b
    assert (a["ci_low"], a["ci_high"]) != (c["ci_low"], c["ci_high"])
    assert a["per_target_diff"]["t1"] == 1.0 - 0.0  # A minus B: good is perfect, bad is perfectly inverted
    assert a["macro_diff"] > 0
    assert a["ci_low"] <= a["macro_diff"] <= a["ci_high"]


A_FAIL = "a: interval wholly below 0"
B_FAIL = "b: macro difference worse than -0.02"
C_FAIL = "c: a target worse than -0.05"
D_FAIL = "d: designs without a score"
_FULL = {"n_total": 5, "n_scored": 5, "n_dropped_unscored": 0}


def _result(macro, lo, hi, per_target, coverage=None):
    cov = coverage if coverage is not None else {t: dict(_FULL) for t in per_target}
    return {"macro_diff": macro, "ci_low": lo, "ci_high": hi, "per_target_diff": per_target, "coverage": cov}


def test_passes_requires_all_four_clauses():
    ok, failed = pb.passes(_result(0.0, -0.05, 0.05, {"t1": 0.0, "t2": -0.01}))
    assert ok and failed == []

    ok, failed = pb.passes(_result(-0.01, -0.09, -0.01, {"t1": 0.0, "t2": -0.01}))  # interval wholly below 0
    assert not ok and failed == [A_FAIL]

    ok, failed = pb.passes(_result(-0.03, -0.06, 0.01, {"t1": 0.0, "t2": -0.01}))  # point worse than -0.02
    assert not ok and failed == [B_FAIL]

    ok, failed = pb.passes(_result(0.0, -0.05, 0.05, {"t1": 0.05, "t2": -0.06}))  # one target worse than -0.05
    assert not ok and failed == [C_FAIL]

    dropped = {"t1": dict(_FULL), "t2": {"n_total": 5, "n_scored": 4, "n_dropped_unscored": 1}}
    ok, failed = pb.passes(_result(0.0, -0.05, 0.05, {"t1": 0.0, "t2": 0.0}, coverage=dropped))
    assert not ok and failed == [D_FAIL]  # a-c are unaffected by it

    # boundaries are inclusive, and a NaN per-target diff (one-class target) does not fail clause c
    ok, failed = pb.passes(_result(-0.02, -0.04, 0.0, {"t1": -0.05, "t2": float("nan")}))
    assert ok and failed == []

    # no usable macro difference fails closed
    ok, failed = pb.passes(_result(float("nan"), float("nan"), float("nan"), {}))
    assert not ok and failed == [A_FAIL, B_FAIL]


def test_full_coverage_reports_counts_equal_to_n_total():
    df = _pool()
    res = pb.paired_bootstrap_diff(df, df["good"], df["bad"], n_boot=20, seed=1)
    assert res["coverage"] == {
        "t1": {"n_total": 6, "n_scored": 6, "n_dropped_unscored": 0},
        "t2": {"n_total": 10, "n_scored": 10, "n_dropped_unscored": 0},
    }
    ok, failed = pb.passes(pb.paired_bootstrap_diff(df, df["good"], df["good"].copy(), n_boot=20, seed=1))
    assert ok and failed == []


def test_a_target_blank_under_one_panel_fails_clause_d_and_reports_counts():
    df = _pool()
    blank_a = df["good"].copy()
    blank_a[df["target"] == "t2"] = np.nan  # the candidate produced nothing for the whole of t2
    res = pb.paired_bootstrap_diff(df, blank_a, df["good"], n_boot=20, seed=1)
    assert res["coverage"]["t2"] == {"n_total": 10, "n_scored": 0, "n_dropped_unscored": 10}
    assert res["coverage"]["t1"] == {"n_total": 6, "n_scored": 6, "n_dropped_unscored": 0}
    assert np.isnan(res["per_target_diff"]["t2"])
    assert res["macro_diff"] == 0.0  # the easy subset alone looks fine ...
    ok, failed = pb.passes(res)
    assert not ok and failed == [D_FAIL]  # ... and must not be allowed to pass


def test_one_dropped_design_fails_clause_d_only():
    df = _pool()
    partial = df["good"].copy()
    partial.iloc[0] = np.nan  # one t1 design unscored by A
    res = pb.paired_bootstrap_diff(df, partial, df["good"], n_boot=20, seed=1)
    assert res["coverage"]["t1"] == {"n_total": 6, "n_scored": 5, "n_dropped_unscored": 1}
    assert res["coverage"]["t2"]["n_dropped_unscored"] == 0
    ok, failed = pb.passes(res)
    assert not ok and failed == [D_FAIL]


def test_unlabelled_rows_are_not_counted_as_dropped():
    df = pd.DataFrame({"target": ["t"] * 5, "binds": [True, False, np.nan, True, False]}, dtype=object)
    s = pd.Series([0.9, 0.1, np.nan, 0.8, 0.2])  # the NaN score sits on the unlabelled design
    res = pb.paired_bootstrap_diff(df, s, s.copy(), n_boot=10, seed=0)
    assert res["coverage"]["t"] == {"n_total": 4, "n_scored": 4, "n_dropped_unscored": 0}
