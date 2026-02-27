"""Z-score normalisation utilities."""

from __future__ import annotations

import numpy as np
import pandas as pd


def zscore(values: np.ndarray) -> np.ndarray:
    """Z-score a 1-D array, returning zeros if std == 0. NaNs are preserved."""
    out = np.full_like(values, np.nan, dtype=float)
    mask = ~np.isnan(values)
    if mask.sum() < 2:
        return out
    mean = np.nanmean(values)
    std = np.nanstd(values)
    if std == 0.0:
        out[mask] = 0.0
    else:
        out[mask] = (values[mask] - mean) / std
    return out


def zscore_dataframe(
    df: pd.DataFrame,
    columns: list[str],
    suffix: str = "_z",
) -> pd.DataFrame:
    """Add z-scored columns to *df* with the given suffix.

    Columns not present in *df* are silently skipped.
    Returns the augmented dataframe (does not modify in place).
    """
    result = df.copy()
    for col in columns:
        if col not in df.columns:
            continue
        result[col + suffix] = zscore(df[col].values.astype(float))
    return result


def minmax_normalize(values: np.ndarray) -> np.ndarray:
    """Min-max scale to [0, 1]. NaNs are preserved."""
    out = np.full_like(values, np.nan, dtype=float)
    mask = ~np.isnan(values)
    if mask.sum() < 2:
        return out
    lo, hi = np.nanmin(values), np.nanmax(values)
    if hi == lo:
        out[mask] = 0.5
    else:
        out[mask] = (values[mask] - lo) / (hi - lo)
    return out
