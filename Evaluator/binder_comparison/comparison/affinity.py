"""Interface-energy affinity ranking (Part N).

The two-stage / consensus ranking separates binders from non-binders but does **not** rank
*affinity among binders* (see docs/completed_plans.md Part N). The affinity score here is the interface
energy *density* ``|dG / dSASA|`` — interface energy per buried Å² — computed by Rosetta's
InterfaceAnalyzer in the ``BindCraft`` conda env (PyRosetta is installed there on every
platform we run BindCraft on, including aarch64 / Spark). Structure confidence (``ipsae_min``)
is used only as a binder **gate**, NOT as a multiplier.

WHY pure ``|dG/dSASA|`` and not ``ipsae_min × |dG/dSASA|``: on the Adaptyv 4-target benchmark
(experimental Kd, 291 binders) ``ipsae_min`` carries no affinity signal among binders
(Spearman vs log10 Kd: pooled b2 −0.09 / mean +0.13 / max +0.09; macro ≈ +0.04, sign flips
per target). Multiplying that near-zero, sign-unstable term onto ``|dG/dSASA|`` only injects
variance and can locally flip the ranking without adding affinity information. So we GATE on
``ipsae_min`` (a valid ~0.70-AUC binder screen) and rank the survivors on the pure energy
density; ``ipsae_min`` stays as a reported diagnostic column.

This module is the pure scoring layer; the Rosetta computation lives in
``Evaluator/scripts/interface_energy.py``.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# Project-standard ipsae_min binder threshold (CLAUDE.md quality tiers: > 0.61 = a real
# binding prediction). Used to GATE non-binders out of the affinity ranking.
DEFAULT_AFFINITY_GATE = 0.61


def interface_energy_density(dg: float | None, dsasa: float | None) -> float:
    """``|dG / dSASA|`` — interface energy density; higher = stronger predicted affinity.

    ``dg`` is the separated interface energy (REU, negative = favorable); ``dsasa`` is the
    interface buried area (Å²). Returns NaN if either input is missing or ``dsasa`` is 0.
    """
    if dg is None or dsasa is None:
        return math.nan
    try:
        dg, dsasa = float(dg), float(dsasa)
    except (TypeError, ValueError):
        return math.nan
    if dsasa == 0 or math.isnan(dsasa) or math.isnan(dg):
        return math.nan
    return abs(dg / dsasa)


def add_affinity_ranking(
    df: pd.DataFrame,
    *,
    ipsae_col: str = "ipsae_min",
    dg_col: str = "interface_dG",
    dsasa_col: str = "interface_dSASA",
    gate_threshold: float = DEFAULT_AFFINITY_GATE,
    score_col: str = "affinity_energy_density",
    gate_col: str = "passes_affinity_gate",
) -> pd.DataFrame:
    """Add the gate-then-pure-ΔG affinity columns, vectorized.

    Adds:
        ``affinity_energy_density`` — pure ``|dG/dSASA|`` (NO ipsae_min multiplier),
            NaN where the energy is missing or dSASA is 0. (Skipped entirely if the
            energy columns are absent.)
        ``passes_affinity_gate``   — ``ipsae_min >= gate_threshold`` (the binder gate).
            True for every row when the ipsae column is absent (can't gate → don't drop
            anything); NaN ipsae sorts as not-passing.

    Rank affinity among binders by sorting ``passes_affinity_gate`` desc, then
    ``affinity_energy_density`` desc — the gate culls non-binders, the density ranks the rest.
    """
    result = df.copy()
    if {dg_col, dsasa_col} <= set(result.columns):
        dg = pd.to_numeric(result[dg_col], errors="coerce")
        dsasa = pd.to_numeric(result[dsasa_col], errors="coerce")
        with np.errstate(divide="ignore", invalid="ignore"):
            density = (dg / dsasa).abs()
        result[score_col] = density.where(dsasa != 0, np.nan)
    if ipsae_col in result.columns:
        ipsae = pd.to_numeric(result[ipsae_col], errors="coerce")
        result[gate_col] = (ipsae >= gate_threshold).fillna(False)
    else:
        result[gate_col] = True
    return result
