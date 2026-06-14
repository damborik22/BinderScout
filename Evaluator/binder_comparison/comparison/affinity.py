"""Interface-energy affinity composite (Part N).

The two-stage / consensus ranking separates binders from non-binders but does **not** rank
*affinity among binders* (see docs/plans.md Part N). BindMaster 2's best single affinity
predictor (per Overath 2025) is ``ipsae_min × |dG / dSASA|`` — interface confidence times
interface energy *density*. The ΔG and ΔSASA come from Rosetta's InterfaceAnalyzer, run in
the ``BindCraft`` conda env (PyRosetta is installed there on every platform we run BindCraft
on, including aarch64 / Spark — so this is NOT x86-only). This module is the pure scoring
layer; the Rosetta computation lives in ``Evaluator/scripts/interface_energy.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def affinity_composite(ipsae_min: float | None, dg: float | None, dsasa: float | None) -> float:
    """``ipsae_min × |dG / dSASA|`` — higher = stronger predicted affinity.

    ``dg`` is the separated interface energy (REU, negative = favorable); ``dsasa`` is the
    interface buried area (Å²). Returns NaN if any input is missing or ``dsasa`` is 0.
    """
    if ipsae_min is None or dg is None or dsasa is None:
        return math.nan
    try:
        ipsae_min, dg, dsasa = float(ipsae_min), float(dg), float(dsasa)
    except (TypeError, ValueError):
        return math.nan
    if dsasa == 0 or math.isnan(dsasa) or math.isnan(dg) or math.isnan(ipsae_min):
        return math.nan
    return ipsae_min * abs(dg / dsasa)


def add_affinity_composite(
    df: pd.DataFrame,
    *,
    ipsae_col: str = "ipsae_min",
    dg_col: str = "interface_dG",
    dsasa_col: str = "interface_dSASA",
    out_col: str = "affinity_composite",
) -> pd.DataFrame:
    """Add the affinity composite column, vectorized. No-op if a source column is absent."""
    result = df.copy()
    if not {ipsae_col, dg_col, dsasa_col} <= set(result.columns):
        return result
    ipsae = pd.to_numeric(result[ipsae_col], errors="coerce")
    dg = pd.to_numeric(result[dg_col], errors="coerce")
    dsasa = pd.to_numeric(result[dsasa_col], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        comp = ipsae * (dg / dsasa).abs()
    comp = comp.where(dsasa != 0, np.nan)
    result[out_col] = comp
    return result
