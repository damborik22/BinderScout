"""Per-metric statistics, z-scores, and rankings for the comparison report."""

from __future__ import annotations

import pandas as pd

from ..core.normalization import zscore_dataframe
from ..core.schema import LOWER_IS_BETTER, ZSCORE_METRICS


def compute_statistics(
    df: pd.DataFrame,
    group_col: str = "source_tool",
) -> dict:
    """Compute z-scores, rankings, and per-tool summary statistics.

    Args:
        df:        Merged DataFrame after ensemble computation.
        group_col: Column used to group summaries (default: 'source_tool').

    Returns:
        dict with keys:
          'df_with_zscores' : original df augmented with *_z columns
          'summary'         : {tool: {metric: {mean, std, median, n}}}
          'rankings'        : {metric: [sequence, ...] ordered best→worst}
    """
    present_zscore_cols = [c for c in ZSCORE_METRICS if c in df.columns]
    df_z = zscore_dataframe(df, present_zscore_cols)

    summary = _per_group_summary(df, group_col, present_zscore_cols)
    rankings = _rank_sequences(df)

    return {
        "df_with_zscores": df_z,
        "summary": summary,
        "rankings": rankings,
    }


def _per_group_summary(
    df: pd.DataFrame,
    group_col: str,
    metric_cols: list[str],
) -> dict:
    """Build {group_value: {metric: {mean, std, median, n}}} dict."""
    if group_col not in df.columns:
        groups = {"all": df}
    else:
        groups = {name: grp for name, grp in df.groupby(group_col)}

    summary: dict = {}
    for group_name, grp in groups.items():
        summary[str(group_name)] = {}
        for col in metric_cols:
            if col not in grp.columns:
                continue
            vals = pd.to_numeric(grp[col], errors="coerce").dropna()
            if len(vals) == 0:
                continue
            summary[str(group_name)][col] = {
                "mean": float(vals.mean()),
                "std": float(vals.std()),
                "median": float(vals.median()),
                "min": float(vals.min()),
                "max": float(vals.max()),
                "n": len(vals),
            }
    return summary


def _rank_sequences(df: pd.DataFrame) -> dict[str, list[str]]:
    """Return {metric: [sequence, ...]} ordered from best to worst.

    Sequence column is used as the identifier; falls back to row index.
    """
    id_col = "sequence" if "sequence" in df.columns else None

    rankings: dict[str, list[str]] = {}
    for col in ZSCORE_METRICS:
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        valid_mask = vals.notna()
        if valid_mask.sum() == 0:
            continue

        ascending = col in LOWER_IS_BETTER
        order = vals[valid_mask].sort_values(ascending=ascending).index

        if id_col:
            rankings[col] = df.loc[order, id_col].tolist()
        else:
            rankings[col] = order.tolist()

    return rankings
