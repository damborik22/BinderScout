"""Is a new sequence-only screen telling us something SoluProt already does?

Several 2.0 items share one premise: that the Loschmidt sequence screens
(SoluProt, TmProt, AggreProt) largely restate the same hydrophobicity/charge
signal, so a new one earns its environment only if it decorrelates from the one
we already run. D3's verdict makes that explicit — *proceed when rank
correlation vs ``soluprot_score`` is low AND it separates expression failures.*

The premise is testable and should not be assumed. Measured on 436 designs from
a real 2VDY pool, TmProt vs SoluProt came out at Spearman **-0.090** —
essentially uncorrelated, so the premise is false for at least one member of
the family.

This module is the harness for that test. It is deliberately screen-agnostic:
give it two per-sequence CSVs and it reports the correlation between every pair
of numeric columns, so a screen that emits several candidate reductions (as
AggreProt does) is answered in one pass rather than one run per reduction.

``scipy`` is not in the ``binder-eval`` environment, so Spearman is computed as
Pearson over ranks rather than by pulling in a dependency for one function.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# |rho| at or above which two screens are considered to be saying the same
# thing. D3 says "low" without a number; this is the line drawn, and it is a
# named constant so a future argument is about the number rather than about
# where it lives.
REDUNDANT_ABOVE = 0.70
INDEPENDENT_BELOW = 0.40


@dataclass(frozen=True)
class ColumnPair:
    left: str
    right: str
    n: int
    spearman: float
    pearson: float

    @property
    def verdict(self) -> str:
        a = abs(self.spearman)
        if a >= REDUNDANT_ABOVE:
            return "redundant"
        if a < INDEPENDENT_BELOW:
            return "independent"
        return "partial"


def _spearman(a: pd.Series, b: pd.Series) -> float:
    return float(np.corrcoef(a.rank(), b.rank())[0, 1])


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c != "sequence" and pd.api.types.is_numeric_dtype(df[c])]


def load_screen(path: str | Path) -> pd.DataFrame:
    """Load a per-sequence screen CSV, deduplicated on ``sequence``.

    Deduplication is not optional. Real screen outputs carry repeated
    sequences — two tools emitting the same binder is ordinary — and a merge on
    a duplicated key silently multiplies rows, which is the defect that once
    corrupted `rank` (see ``cli/report.py::_merge_by_sequence``). Here it would
    quietly weight some designs more heavily than others in the correlation.
    """
    df = pd.read_csv(path)
    if "sequence" not in df.columns:
        raise ValueError(f"{path} has no 'sequence' column; cannot join screens")
    return df.drop_duplicates("sequence", keep="first")


def compare_screens(left: pd.DataFrame, right: pd.DataFrame) -> list[ColumnPair]:
    """Correlate every numeric column of *left* against every one of *right*."""
    merged = left.merge(right, on="sequence", how="inner", suffixes=("_l", "_r"), validate="1:1")
    out: list[ColumnPair] = []
    for lc in _numeric_columns(left):
        for rc in _numeric_columns(right):
            lcol = f"{lc}_l" if f"{lc}_l" in merged.columns else lc
            rcol = f"{rc}_r" if f"{rc}_r" in merged.columns else rc
            pair = merged[[lcol, rcol]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(pair) < 3 or pair[lcol].nunique() < 2 or pair[rcol].nunique() < 2:
                continue
            out.append(
                ColumnPair(
                    left=lc,
                    right=rc,
                    n=len(pair),
                    spearman=_spearman(pair[lcol], pair[rcol]),
                    pearson=float(np.corrcoef(pair[lcol], pair[rcol])[0, 1]),
                )
            )
    return out


def format_report(pairs: list[ColumnPair]) -> str:
    if not pairs:
        return "no comparable numeric column pairs"
    w = max(len(f"{p.left} vs {p.right}") for p in pairs)
    lines = [f"{'pair'.ljust(w)}  {'n':>5}  {'spearman':>9}  {'pearson':>8}  verdict"]
    for p in sorted(pairs, key=lambda x: -abs(x.spearman)):
        lines.append(
            f"{f'{p.left} vs {p.right}'.ljust(w)}  {p.n:5d}  {p.spearman:+9.3f}  {p.pearson:+8.3f}  {p.verdict}"
        )
    return "\n".join(lines)
