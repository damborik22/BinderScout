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


def overall_rank(
    df: pd.DataFrame,
    weights: dict[str, float] | None = None,
) -> pd.Series:
    """Compute a composite rank score for each binder.

    Uses z-scored metrics. For lower-is-better metrics, the z-score is negated
    so that a higher composite always means better.

    Default weights are informed by Overath et al. (2025) meta-analysis:
    - ipsae_min: weight 4.0 — dominant primary metric
      (1.4× better average precision than ipAE across 3,766 designs; Boltz2-only)
    - iptm: weight 2.0 — strong secondary metric (Boltz-2)
    - ipae: weight 1.5 — tertiary (Boltz-2)
    - plddt_binder_mean: weight 1.0 — quaternary
    - all others: weight 0.5 — supplementary

    Args:
        df:      DataFrame after compute_statistics (must have *_z columns).
        weights: Optional dict of {metric: weight}. If provided, overrides
                 ALL defaults. To adjust individual weights, pass only the
                 metrics you want to change; others keep their defaults.

    Returns:
        Series of composite scores indexed like *df*.
    """
    z_cols = [c for c in df.columns if c.endswith("_z") and c[:-2] in ZSCORE_METRICS]
    if not z_cols:
        raise ValueError("No z-score columns found. Run compute_statistics first.")

    # Default weights per Overath et al. (2025): ipSAE_min dominates.
    # Key names match post-ensemble-rename column names (e.g. ipsae_min, not boltz_ipsae_min).
    # af2_ipsae_min_z is optional (only when PAE files are available); missing z-cols are skipped.
    _default_weights: dict[str, float] = {
        # Primary — Dunbrack ipSAE_min from Boltz2 (best single metric, 1.4× > ipAE)
        "ipsae_min_z": 4.0,
        # Secondary — iptm (Boltz-2)
        "iptm_z": 2.0,
        # IPSAE directional (corroborates ipsae_min)
        "bt_ipsae_z": 1.5,
        "tb_ipsae_z": 1.5,
        # Interface PAE (ensemble)
        "ipae_z": 1.5,
        # binder pLDDT
        "plddt_binder_mean_z": 1.0,
        "plddt_binder_min_z": 0.8,
    }
    # Merge caller-supplied overrides over defaults; all others get 0.5
    effective_weights = dict(_default_weights)
    if weights is not None:
        effective_weights.update(weights)

    composite = pd.Series(0.0, index=df.index)
    total_w = 0.0

    for z_col in z_cols:
        metric = z_col[:-2]  # strip '_z'
        w = effective_weights.get(z_col, effective_weights.get(metric + "_z", 0.5))
        sign = -1.0 if metric in LOWER_IS_BETTER else 1.0
        vals = pd.to_numeric(df[z_col], errors="coerce").fillna(0.0)
        composite += w * sign * vals
        total_w += w

    if total_w > 0:
        composite /= total_w

    return composite
