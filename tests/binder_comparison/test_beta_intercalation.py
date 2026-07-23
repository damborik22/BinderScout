"""Tests for the β-intercalation detector + report exclusion."""

import pandas as pd
from binder_comparison.comparison.beta_intercalation import is_intercalating


def test_is_intercalating_thresholds():
    assert is_intercalating(0, 0) is False  # clean surface binder
    assert is_intercalating(2, 0) is False  # below any-side threshold, no both-side
    assert (
        is_intercalating(3, 0) is False
    )  # any-side alone never triggers by default (single-sided is opt-in via min_xbridge)
    assert is_intercalating(1, 2) is True  # ≥2 both-side (interior) even if few any-side
    assert is_intercalating(-1, -1) is False  # DSSP failed → don't drop on unknown


def test_is_intercalating_custom_thresholds():
    assert is_intercalating(4, 0, min_xbridge=5) is False
    assert is_intercalating(5, 0, min_xbridge=5) is True


def test_report_excludes_intercalators():
    from binder_comparison.cli.report import _attach_beta_results

    df = pd.DataFrame({"binder_id": ["a", "b", "c"], "x": [1, 2, 3]})
    beta = pd.DataFrame(
        {"binder_id": ["a", "b", "c"], "n_xbridge": [0, 12, 1], "beta_intercalates": ["false", "true", "false"]}
    )
    tmp = "/tmp/_beta_test.csv"
    beta.to_csv(tmp, index=False)
    # advisory (no exclude): all 3 rows kept, column joined
    adv = _attach_beta_results(df, tmp, exclude=False)
    assert len(adv) == 3 and "beta_intercalates" in adv.columns
    # exclude: the intercalating row 'b' is dropped
    kept = _attach_beta_results(df, tmp, exclude=True)
    assert len(kept) == 2 and "b" not in set(kept["binder_id"])
