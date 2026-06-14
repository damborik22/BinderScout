"""Tests for the affinity composite (Part N: ipsae_min × |dG/dSASA|)."""

import math

import pytest
from binder_comparison.comparison.affinity import affinity_composite

pd = pytest.importorskip("pandas")
from binder_comparison.comparison.affinity import add_affinity_composite  # noqa: E402


def test_composite_value():
    # 0.8 × |−30 / 1000| = 0.8 × 0.03 = 0.024
    assert affinity_composite(0.8, -30.0, 1000.0) == pytest.approx(0.024)


def test_more_favorable_dg_scores_higher():
    strong = affinity_composite(0.8, -50.0, 1000.0)
    weak = affinity_composite(0.8, -10.0, 1000.0)
    assert strong > weak


def test_zero_dsasa_is_nan():
    assert math.isnan(affinity_composite(0.8, -30.0, 0.0))


def test_missing_input_is_nan():
    assert math.isnan(affinity_composite(None, -30.0, 1000.0))
    assert math.isnan(affinity_composite(0.8, None, 1000.0))


def test_df_helper_adds_column_and_coerces_strings():
    df = pd.DataFrame(
        {
            "ipsae_min": ["0.8", "0.5"],
            "interface_dG": [-30.0, -10.0],
            "interface_dSASA": [1000.0, 500.0],
        }
    )
    out = add_affinity_composite(df)
    assert out["affinity_composite"].tolist() == pytest.approx([0.024, 0.01])


def test_df_helper_noop_without_source_columns():
    df = pd.DataFrame({"ipsae_min": [0.8]})  # no energy columns
    out = add_affinity_composite(df)
    assert "affinity_composite" not in out.columns


def test_df_helper_nan_on_zero_dsasa():
    df = pd.DataFrame({"ipsae_min": [0.8], "interface_dG": [-30.0], "interface_dSASA": [0.0]})
    out = add_affinity_composite(df)
    assert math.isnan(out["affinity_composite"].iloc[0])
