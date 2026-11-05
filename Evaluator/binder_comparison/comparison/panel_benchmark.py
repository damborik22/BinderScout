"""Panel comparison for the AF3-replacement benchmark.

Compares the ROC AUC (binder vs non-binder, per target) of one panel's mean ipTM against another's
on the same labelled pool, with a paired bootstrap that resamples designs within each target.
Pure maths on a DataFrame; no engine is run here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Pass-rule thresholds, fixed before any candidate is run (design doc, Part 1).
MACRO_FLOOR = -0.02
TARGET_FLOOR = -0.05


def panel_consensus(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Row mean over ``cols``. A blank engine blanks the design (skipna=False), never a smaller mean."""
    return df[cols].astype(float).mean(axis=1, skipna=False)


def _auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """ROC AUC by the rank (Mann-Whitney) statistic, average ranks for ties. NaN if one class is empty."""
    n_pos = int(labels.sum())
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = pd.Series(scores).rank(method="average").to_numpy()
    return float((ranks[labels].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _labels(df: pd.DataFrame, label_col: str) -> tuple[np.ndarray, np.ndarray]:
    """(has_label mask, bool labels). Null labels are unlabelled, never negatives; non-bool values are refused."""
    col = df[label_col]
    has = col.notna().to_numpy()
    bad = [v for v in col[has] if not isinstance(v, bool | np.bool_)]
    if bad:
        raise ValueError(f"label column {label_col!r} must hold booleans or nulls, found {bad[0]!r}")
    return has, np.array([bool(v) if h else False for v, h in zip(col, has, strict=True)])


def _aligned(df: pd.DataFrame, score: pd.Series) -> np.ndarray:
    return score.reindex(df.index).to_numpy(dtype=float)


def per_target_auc(
    df: pd.DataFrame, score: pd.Series, *, target_col: str = "target", label_col: str = "binds"
) -> dict[str, float]:
    """ROC AUC of ``score`` per target. Unlabelled and unscored designs are dropped; one-class target -> NaN."""
    has, lab = _labels(df, label_col)
    sc = _aligned(df, score)
    keep = has & np.isfinite(sc)
    targets = df[target_col].to_numpy()
    return {str(t): _auc(lab[keep & (targets == t)], sc[keep & (targets == t)]) for t in sorted(set(targets))}


def paired_bootstrap_diff(
    df: pd.DataFrame,
    score_a: pd.Series,
    score_b: pd.Series,
    *,
    n_boot: int = 2000,
    seed: int = 0,
    target_col: str = "target",
    label_col: str = "binds",
) -> dict:
    """Macro AUC(score_a) - AUC(score_b), with a within-target paired bootstrap interval.

    Only designs that are labelled and scored by both are used. Each iteration resamples every target at its
    own size, with the same design indices for both scores. The macro difference averages the targets that have
    an AUC under both scores; a target with none in a resample is skipped for that resample only.
    """
    has, lab = _labels(df, label_col)
    a, b = _aligned(df, score_a), _aligned(df, score_b)
    keep = has & np.isfinite(a) & np.isfinite(b)
    targets_all = df[target_col].to_numpy()
    groups = {
        str(t): (lab[keep & (targets_all == t)], a[keep & (targets_all == t)], b[keep & (targets_all == t)])
        for t in sorted(set(targets_all))
    }

    def diff(la: np.ndarray, sa: np.ndarray, sb: np.ndarray) -> float:
        return _auc(la, sa) - _auc(la, sb)

    def macro(diffs: list[float]) -> float:
        usable = [d for d in diffs if np.isfinite(d)]
        return float(np.mean(usable)) if usable else float("nan")

    per_target = {t: diff(*g) for t, g in groups.items()}
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        ds = []
        for la, sa, sb in groups.values():
            idx = rng.integers(0, len(la), len(la))
            ds.append(diff(la[idx], sa[idx], sb[idx]))
        boots[i] = macro(ds)
    if np.isfinite(boots).any():
        ci_low, ci_high = (float(x) for x in np.nanpercentile(boots, [2.5, 97.5]))
    else:
        ci_low = ci_high = float("nan")
    return {
        "macro_diff": macro(list(per_target.values())),
        "ci_low": ci_low,
        "ci_high": ci_high,
        "per_target_diff": per_target,
    }


def passes(result: dict) -> tuple[bool, list[str]]:
    """Apply the three-part rule to a ``paired_bootstrap_diff`` result; return (ok, failed clause names).

    a: the 95% interval does not lie wholly below zero; b: the point estimate is not worse than -0.02;
    c: no target is worse than -0.05 (a target without an AUC is not judged). A missing macro difference
    fails a and b rather than passing.
    """
    failed = []
    if not result["ci_high"] >= 0:
        failed.append("a")
    if not result["macro_diff"] >= MACRO_FLOOR:
        failed.append("b")
    if any(d < TARGET_FLOOR for d in result["per_target_diff"].values() if np.isfinite(d)):
        failed.append("c")
    return not failed, failed
