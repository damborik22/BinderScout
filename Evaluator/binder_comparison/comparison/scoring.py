"""Scoring pipeline informed by the Adaptyv Bio Nipah competition and meta-analysis.

Key references:
- Overath et al. (2025): "Predicting Experimental Success in De Novo Binder Design:
  A Meta-Analysis of 3,766 Experimentally Characterised Binders"
  bioRxiv 2025.08.14.670059 — 3,766 designs, 15 targets, 436 confirmed binders (11.6%)
- Dunbrack Lab ipSAE paper: "Rēs ipSAE loquuntur" (2025), bioRxiv 2025.02.10.637595
- Adaptyv Bio Nipah competition (2025), proteinbase.com

Key findings implemented here:
1. ipSAE_min (min of bt and tb) is the best single metric — 1.4× precision vs ipAE
2. Threshold ipSAE_min > 0.61 maximises F1; > 0.8 is high-confidence
3. Best composite: ipSAE_min × |ΔG/ΔSASA|  (median AP = 0.58 across 15 targets)
4. Pre-filter: shape_complementarity > 0.62 when available (from BindCraft)
5. ipSAE computed from PAE via Dunbrack formula (uniform 10 Å cutoff, d0_res per-residue)
6. Ranking: quality_tier primary, agreement_count secondary, ipSAE_min tertiary
"""

from __future__ import annotations

import math
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# ---- Thresholds from Overath et al. 2025 ----
IPSAE_PASS_THRESHOLD = 0.61  # F1-maximising threshold across 15 targets
IPSAE_HIGH_THRESHOLD = 0.80  # High-confidence binder
IPSAE_MIN_THRESHOLD = 0.40  # Below this → very unlikely binder
SHAPE_COMP_PREFILTER = 0.62  # Pre-filter from meta-analysis
RMSD_BINDER_PREFILTER = 3.73  # Å, pre-filter from meta-analysis

# ---- Cross-engine support gate for the two-stage screen ----
# The pipeline runs exactly three independent refold engines (Boltz-2, AF3,
# ESMFold2), so the default demands agreement from all of them. Two is the floor:
# a "cross-engine" consensus built from one engine is just that engine's opinion,
# and for Mosaic/Protein-Hunter designs that engine is the one that designed them.
MIN_ENGINES_DEFAULT = 3
MIN_ENGINES_FLOOR = 2

# PAE cutoff for Dunbrack ipSAE formula (Å).
# Uniform 10 Å for all engines so that ipSAE scores are directly comparable
# across Boltz-2 and the other refolders (AF3, ESMFold2).
# Overath et al. (2025) thresholds (0.61, 0.80) were calibrated with a 10 Å
# cutoff on AF3 data.
IPSAE_PAE_CUTOFF = 10.0


# ---------------------------------------------------------------------------
# Dunbrack ipSAE formula
# ---------------------------------------------------------------------------


def _d0(n_qualifying: int | np.ndarray) -> float | np.ndarray:
    """Compute d0 from the count of qualifying residues (PAE < cutoff).

    From Dunbrack et al. (2025):
        d0 = max(1.0, 1.24 * (N - 15)^(1/3) - 1.8)
    """
    n = np.maximum(np.asarray(n_qualifying, dtype=float), 27.0)
    return np.maximum(1.0, 1.24 * (n - 15.0) ** (1.0 / 3.0) - 1.8)


def _psae_row(pae_row: np.ndarray, pae_cutoff: float) -> float:
    """Compute per-residue ipSAE score for one source residue i.

    ipSAE_i = mean of [1 / (1 + (PAE_ij / d0)^2)] for j where PAE_ij < cutoff.
    d0 is computed from the count of qualifying j residues.

    Returns 0.0 if no qualifying pairs exist.
    """
    qualifying = pae_row[pae_row < pae_cutoff]
    n = len(qualifying)
    if n == 0:
        return 0.0
    d0 = _d0(n)
    return float(np.mean(1.0 / (1.0 + (qualifying / d0) ** 2)))


def compute_ipsae_from_pae(
    pae: np.ndarray,
    binder_length: int,
    pae_cutoff: float = IPSAE_PAE_CUTOFF,
    *,
    ordering: str = "binder_target",
) -> dict[str, float]:
    """Compute ipSAE scores from a full PAE matrix.

    Implements the DunbrackLab (2025) d0res formula:
        ipSAE_A→B = max_i [ pSAE_i ] over all source residues i in A
        pSAE_i = mean_j[ 1 / (1 + (PAE_ij / d0_i)^2) ] for j in B with PAE_ij < cutoff
        d0_i = max(1.0, 1.24 * (N_cutoff_i - 15)^(1/3) - 1.8)
        N_cutoff_i = count of j with PAE_ij < cutoff

    Cross-validated against DunbrackLab ipsae package v1.0.1
    (ipsae_d0res_asym values match to floating-point precision).

    The key difference from Mosaic aux ipSAE is the d0 computation
    (per-residue d0_res vs per-chain).

    Args:
        pae:           PAE matrix in Ångströms, shape [L_total, L_total].
        binder_length: Number of binder residues (L_b).
        pae_cutoff:    PAE filter threshold in Å (default: 10 Å, uniform
                       across engines).
        ordering:      'binder_target' (Boltz-2 native, [binder|target]) or
                       'target_binder' (arrays transposed internally to
                       [binder|target]).

    Returns:
        dict with keys: bt_ipsae, tb_ipsae, ipsae_min, ipsae_max, ipsae_valid
    """
    pae = np.asarray(pae, dtype=float)
    if pae.ndim != 2 or pae.shape[0] != pae.shape[1]:
        raise ValueError(f"PAE must be a square 2D matrix, got shape {pae.shape}")
    L = pae.shape[0]
    L_b = binder_length
    L_t = L - L_b

    if L_b <= 0 or L_t <= 0:
        return dict(bt_ipsae=np.nan, tb_ipsae=np.nan, ipsae_min=np.nan, ipsae_max=np.nan, ipsae_valid=0)

    # Normalise to [binder | target] ordering
    if ordering == "target_binder":
        # [target | binder] input → swap to [binder | target]
        pae = np.block(
            [
                [pae[L_t:, L_t:], pae[L_t:, :L_t]],  # binder-binder, binder-target
                [pae[:L_t, L_t:], pae[:L_t, :L_t]],  # target-binder, target-target
            ]
        )

    # pae_bt[i, j]: PAE(binder_i → target_j), i.e. row = binder, col = target
    pae_bt = pae[:L_b, L_b:]  # shape [L_b, L_t]
    pae_tb = pae[L_b:, :L_b]  # shape [L_t, L_b]

    # Binder → target (bt): for each binder residue i, score over target residues j
    # DunbrackLab d0res: max over source residues (confirmed against ipsae package v1.0.1)
    bt_scores = np.array([_psae_row(pae_bt[i], pae_cutoff) for i in range(L_b)])
    bt_ipsae = float(np.max(bt_scores)) if len(bt_scores) > 0 else 0.0

    # Target → binder (tb): for each target residue i, score over binder residues j
    tb_scores = np.array([_psae_row(pae_tb[i], pae_cutoff) for i in range(L_t)])
    tb_ipsae = float(np.max(tb_scores)) if len(tb_scores) > 0 else 0.0

    ipsae_min = float(np.nanmin([bt_ipsae, tb_ipsae]))
    ipsae_max = float(np.nanmax([bt_ipsae, tb_ipsae]))
    ipsae_valid = int(ipsae_min > 0.0 and not np.isnan(ipsae_min))

    return dict(
        bt_ipsae=bt_ipsae,
        tb_ipsae=tb_ipsae,
        ipsae_min=ipsae_min,
        ipsae_max=ipsae_max,
        ipsae_valid=ipsae_valid,
    )


def _resolve_pae_path(
    pae_path: str | None,
    base_dir: str | Path | None,
) -> Path | None:
    """Try to resolve a PAE file path, returning None if not found.

    Resolution order:
        1. As-is (absolute or relative to CWD).
        2. Relative to *base_dir* (for CSVs whose paths are relative to an
           output directory different from CWD).
    """
    if pae_path is None or (isinstance(pae_path, float) and np.isnan(pae_path)):
        return None
    p = Path(str(pae_path))
    if p.exists():
        return p
    if base_dir is not None:
        candidate = Path(base_dir) / p
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Boltz-2 ipSAE from saved PAE files
# ---------------------------------------------------------------------------


def add_boltz_ipsae_from_files(
    df: pd.DataFrame,
    pae_file_col: str = "boltz_pae_file",
    binder_length_col: str = "binder_length",
    pae_cutoff: float = IPSAE_PAE_CUTOFF,
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Load Boltz-2 PAE .npy files and compute DunbrackLab ipSAE scores.

    Adds columns: boltz_pae_bt_ipsae, boltz_pae_tb_ipsae, boltz_pae_ipsae_min,
                  boltz_pae_ipsae_max.

    Boltz-2 PAE arrays are in [binder | target] ordering (native), so
    'binder_target' ordering is used.

    Args:
        df:              DataFrame with Boltz-2 refolding results.
        pae_file_col:    Column containing paths to PAE .npy files.
        binder_length_col: Column with binder sequence length.
        pae_cutoff:      PAE cutoff in Å (default 10 Å, uniform across engines).
        base_dir:        Base directory for resolving relative PAE file paths.
    """
    result = df.copy()

    if pae_file_col not in df.columns:
        return result

    bt_ipsae_vals, tb_ipsae_vals, min_vals, max_vals = [], [], [], []

    for _, row in df.iterrows():
        pae_path = row.get(pae_file_col)
        L_b = row.get(binder_length_col)

        resolved = _resolve_pae_path(pae_path, base_dir)
        if pd.isna(pae_path) or pd.isna(L_b) or resolved is None:
            bt_ipsae_vals.append(np.nan)
            tb_ipsae_vals.append(np.nan)
            min_vals.append(np.nan)
            max_vals.append(np.nan)
            continue

        try:
            pae = np.load(str(resolved))
            scores = compute_ipsae_from_pae(pae, int(L_b), pae_cutoff, ordering="binder_target")
            bt_ipsae_vals.append(scores["bt_ipsae"])
            tb_ipsae_vals.append(scores["tb_ipsae"])
            min_vals.append(scores["ipsae_min"])
            max_vals.append(scores["ipsae_max"])
        except Exception as e:
            import warnings

            warnings.warn(f"Failed to compute Boltz-2 ipSAE for {pae_path}: {e}")
            bt_ipsae_vals.append(np.nan)
            tb_ipsae_vals.append(np.nan)
            min_vals.append(np.nan)
            max_vals.append(np.nan)

    result["boltz_pae_bt_ipsae"] = bt_ipsae_vals
    result["boltz_pae_tb_ipsae"] = tb_ipsae_vals
    result["boltz_pae_ipsae_min"] = min_vals
    result["boltz_pae_ipsae_max"] = max_vals

    return result


# ---------------------------------------------------------------------------
# Generic PAE → DunbrackLab ipSAE loader (for AF3, ESMFold2, and future engines)
# ---------------------------------------------------------------------------


def add_ipsae_from_pae_files(
    df: pd.DataFrame,
    pae_file_col: str,
    binder_length_col: str = "binder_length",
    pae_cutoff: float = IPSAE_PAE_CUTOFF,
    base_dir: str | Path | None = None,
    *,
    prefix: str,
    ordering: str = "target_binder",
) -> pd.DataFrame:
    """Load saved PAE .npy files and add DunbrackLab ipSAE columns to *df*.

    Engine-agnostic version of ``add_boltz_ipsae_from_files``. Adds columns
    ``{prefix}_bt_ipsae``, ``{prefix}_tb_ipsae``, ``{prefix}_ipsae_min``,
    ``{prefix}_ipsae_max`` where ``prefix`` is e.g. "af3" or "esmfold2".

    Args:
        df:              DataFrame with engine refolding results.
        pae_file_col:    Column containing paths to PAE .npy files.
        binder_length_col: Column with binder sequence length.
        pae_cutoff:      PAE cutoff in Å (default 10 Å, uniform across engines).
        base_dir:        Base directory for resolving relative PAE file paths.
        prefix:          Output column prefix (e.g. 'af3', 'esmfold2').
        ordering:        'binder_target' or 'target_binder' — how the PAE matrix
                         is laid out. AF3 and ESMFold2 both default to
                         'target_binder' because we always put target first in
                         the input JSON.
    """
    result = df.copy()

    if pae_file_col not in df.columns:
        return result

    bt_ipsae_vals, tb_ipsae_vals, min_vals, max_vals = [], [], [], []

    for _, row in df.iterrows():
        pae_path = row.get(pae_file_col)
        L_b = row.get(binder_length_col)

        resolved = _resolve_pae_path(pae_path, base_dir)
        if pd.isna(pae_path) or pd.isna(L_b) or resolved is None:
            bt_ipsae_vals.append(np.nan)
            tb_ipsae_vals.append(np.nan)
            min_vals.append(np.nan)
            max_vals.append(np.nan)
            continue

        try:
            pae = np.load(str(resolved))
            scores = compute_ipsae_from_pae(pae, int(L_b), pae_cutoff, ordering=ordering)
            bt_ipsae_vals.append(scores["bt_ipsae"])
            tb_ipsae_vals.append(scores["tb_ipsae"])
            min_vals.append(scores["ipsae_min"])
            max_vals.append(scores["ipsae_max"])
        except Exception as e:
            import warnings

            warnings.warn(f"Failed to compute {prefix} ipSAE for {pae_path}: {e}")
            bt_ipsae_vals.append(np.nan)
            tb_ipsae_vals.append(np.nan)
            min_vals.append(np.nan)
            max_vals.append(np.nan)

    result[f"{prefix}_bt_ipsae"] = bt_ipsae_vals
    result[f"{prefix}_tb_ipsae"] = tb_ipsae_vals
    result[f"{prefix}_ipsae_min"] = min_vals
    result[f"{prefix}_ipsae_max"] = max_vals

    return result


# ---------------------------------------------------------------------------
# ipTM from saved PAE files (computed independently of model-reported values)
# ---------------------------------------------------------------------------


def add_iptm_from_pae_files(
    df: pd.DataFrame,
    pae_file_col: str,
    binder_length_col: str = "binder_length",
    ordering: str = "binder_target",
    prefix: str = "boltz",
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Load PAE .npy files and compute ipTM, adding columns to df.

    Adds columns: {prefix}_pae_iptm (independently computed from PAE matrix).

    Args:
        df:              DataFrame with refolding results.
        pae_file_col:    Column containing paths to PAE .npy files.
        binder_length_col: Column with binder sequence length.
        ordering:        PAE matrix ordering ('binder_target' or 'target_binder').
        prefix:          Column name prefix ('boltz', 'af3', or 'esmfold2').
        base_dir:        Base directory for resolving relative PAE file paths.
    """
    result = df.copy()

    if pae_file_col not in df.columns:
        return result

    iptm_vals = []

    for _, row in df.iterrows():
        pae_path = row.get(pae_file_col)
        L_b = row.get(binder_length_col)

        resolved = _resolve_pae_path(pae_path, base_dir)
        if pd.isna(pae_path) or pd.isna(L_b) or resolved is None:
            iptm_vals.append(np.nan)
            continue

        try:
            pae = np.load(str(resolved))
            scores = compute_iptm_from_pae(pae, int(L_b), ordering=ordering)
            iptm_vals.append(scores["iptm"])
        except Exception as e:
            import warnings

            warnings.warn(f"Failed to compute ipTM for {pae_path}: {e}")
            iptm_vals.append(np.nan)

    result[f"{prefix}_pae_iptm"] = iptm_vals

    return result


# ---------------------------------------------------------------------------
# Screening thresholds and tier classification
# ---------------------------------------------------------------------------


# Per-engine iPSAE thresholds — calibrated for the DunbrackLab 2025 formula at 10 Å cutoff.
# AF2 caps low on short targets (per INVESTIGATION_RANKING_DISCREPANCY.md §6); kept informational.
DEFAULT_ENGINE_THRESHOLDS: dict[str, float] = {
    "boltz": IPSAE_PASS_THRESHOLD,  # 0.61
    "af3": IPSAE_PASS_THRESHOLD,  # 0.61 — DunbrackLab cutoff was tuned for AF3
    "esmfold2": IPSAE_PASS_THRESHOLD,  # 0.61 — same cutoff until empirical calibration suggests otherwise
    "af2": 0.30,  # informational only; AF2 distribution caps low
}

# Map engine key → DunbrackLab PAE-derived ipsae_min column.
# NOTE: Boltz uses the prefixed `boltz_pae_*` columns (special add_boltz_ipsae_from_files
# pipeline), while AF3/ESMFold2 use plain `<engine>_ipsae_min` (from add_ipsae_from_pae_files).
_ENGINE_IPSAE_COLS: dict[str, str] = {
    "boltz": "boltz_pae_ipsae_min",
    "af3": "af3_ipsae_min",
    "esmfold2": "esmfold2_ipsae_min",
    "af2": "af2_ipsae_min",
}


def apply_screening_thresholds(
    df: pd.DataFrame,
    primary_engine: str = "boltz",
    engine_thresholds: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Add Boolean screening flags and quality tier column.

    Per-engine flags added (when the corresponding PAE-derived ipsae column is present):
        passes_boltz_filter, passes_af3_filter, passes_esmfold2_filter
        passes_af2_filter_informational  (AF2 uses a relaxed 0.30 cutoff; informational only)

    Aggregate flags (derived from `primary_engine` so existing reports still work):
        passes_ipsae_filter   : primary engine's ipsae_min > its threshold
        passes_ipsae_strict   : primary engine's ipsae_min > 0.80 (high-confidence)

    Other:
        passes_shape_prefilter: native_shape_complementarity > 0.62 (when available)

    Tier column (quality_tier) is derived from the **primary engine's** ipsae_min:
        'high'    : > 0.80
        'medium'  : > 0.61
        'low'     : > 0.40
        'reject'  : <= 0.40 or NaN
    """
    result = df.copy()
    thresholds = {**DEFAULT_ENGINE_THRESHOLDS, **(engine_thresholds or {})}

    # Per-engine pass flags (one per engine actually present in the data)
    for engine, col in _ENGINE_IPSAE_COLS.items():
        if col not in result.columns:
            continue
        thr = thresholds.get(engine, IPSAE_PASS_THRESHOLD)
        vals = pd.to_numeric(result[col], errors="coerce")
        flag = "passes_af2_filter_informational" if engine == "af2" else f"passes_{engine}_filter"
        result[flag] = vals > thr

    # Primary-engine column for tier / aggregate flags
    primary_col = _ENGINE_IPSAE_COLS.get(primary_engine, _ENGINE_IPSAE_COLS["boltz"])
    if primary_col not in result.columns:
        # fall back to best-available ipsae column (preserves legacy reports)
        primary_col = _best_ipsae_col(result)

    if primary_col is not None:
        vals = pd.to_numeric(result[primary_col], errors="coerce")
        primary_thr = thresholds.get(primary_engine, IPSAE_PASS_THRESHOLD)
        result["passes_ipsae_filter"] = vals > primary_thr
        result["passes_ipsae_strict"] = vals > IPSAE_HIGH_THRESHOLD

        def _tier(v):
            if pd.isna(v):
                return "reject"
            if v > IPSAE_HIGH_THRESHOLD:
                return "high"
            if v > primary_thr:
                return "medium"
            if v > IPSAE_MIN_THRESHOLD:
                return "low"
            return "reject"

        result["quality_tier"] = vals.apply(_tier)
    else:
        result["passes_ipsae_filter"] = None
        result["passes_ipsae_strict"] = None
        result["quality_tier"] = "unknown"

    # Shape complementarity pre-filter (BindCraft native)
    shape_col = "native_shape_complementarity"
    if shape_col in result.columns:
        sc = pd.to_numeric(result[shape_col], errors="coerce")
        result["passes_shape_prefilter"] = sc > SHAPE_COMP_PREFILTER

    return result


# ---------------------------------------------------------------------------
# Composite scores
# ---------------------------------------------------------------------------


def compute_composite_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Add composite scoring columns derived from the meta-analysis.

    Columns added (when inputs are available):

        ipsae_dg_composite:
            ipsae_min × |ΔG / ΔSASA|
            Best composite in Overath et al. 2025 (median AP = 0.58).
            Requires BindCraft native_dG and native_dSASA.
            Lower ΔG (more negative) and higher ΔSASA = better.
            We use the absolute value of ΔG/ΔSASA and multiply, so
            higher composite = better.

        ipsae_shape_composite:
            ipsae_min × shape_complementarity
            Second-best composite from meta-analysis.
            Requires BindCraft native_shape_complementarity.
    """
    result = df.copy()
    ipsae_col = _best_ipsae_col(result)

    if ipsae_col is None:
        return result

    ipsae = pd.to_numeric(result[ipsae_col], errors="coerce")

    # ipSAE_min × |ΔG / ΔSASA|
    dg_col = "native_dG"
    dsasa_col = "native_dSASA"
    if dg_col in result.columns and dsasa_col in result.columns:
        dg = pd.to_numeric(result[dg_col], errors="coerce")
        dsasa = pd.to_numeric(result[dsasa_col], errors="coerce")
        # Avoid division by zero
        with np.errstate(divide="ignore", invalid="ignore"):
            dg_dsasa = np.where(dsasa.abs() > 1.0, np.abs(dg / dsasa), np.nan)
        result["ipsae_dg_composite"] = ipsae * dg_dsasa

    # ipSAE_min × shape_complementarity
    shape_col = "native_shape_complementarity"
    if shape_col in result.columns:
        sc = pd.to_numeric(result[shape_col], errors="coerce")
        result["ipsae_shape_composite"] = ipsae * sc

    return result


# ---------------------------------------------------------------------------
# ipTM computation from PAE matrices
# ---------------------------------------------------------------------------


def compute_iptm_from_pae(
    pae: np.ndarray,
    binder_length: int,
    *,
    ordering: str = "binder_target",
) -> dict[str, float]:
    """Compute ipTM from a full PAE matrix (independently of model-reported values).

    Uses the standard TM-score kernel with global d0 (no PAE cutoff, all
    cross-chain pairs contribute).  This gives an independent ipTM that is
    comparable across engines.

    Formula:
        ipTM(A→B) = max_i∈A [ mean_j∈B ( 1/(1+(PAE_ij/d0)²) ) ]
        d0 = max(1.0, 1.24 * (L_A + L_B - 15)^(1/3) - 1.8)
        ipTM = max(bt, tb)

    Args:
        pae:           PAE matrix in Å, shape [L_total, L_total].
        binder_length: Number of binder residues.
        ordering:      'binder_target' or 'target_binder'.

    Returns:
        dict with keys: bt_iptm, tb_iptm, iptm
    """
    pae = np.asarray(pae, dtype=float)
    if pae.ndim != 2 or pae.shape[0] != pae.shape[1]:
        raise ValueError(f"PAE must be a square 2D matrix, got shape {pae.shape}")
    L = pae.shape[0]
    L_b = binder_length
    L_t = L - L_b

    if L_b <= 0 or L_t <= 0:
        return dict(bt_iptm=np.nan, tb_iptm=np.nan, iptm=np.nan)

    # Normalise to [binder | target] ordering
    if ordering == "target_binder":
        pae = np.block(
            [
                [pae[L_t:, L_t:], pae[L_t:, :L_t]],
                [pae[:L_t, L_t:], pae[:L_t, :L_t]],
            ]
        )

    # Global d0 (uses total chain lengths, no minimum of 27)
    d0 = max(1.0, 1.24 * (L_b + L_t - 15) ** (1.0 / 3.0) - 1.8)

    pae_bt = pae[:L_b, L_b:]  # shape [L_b, L_t]
    pae_tb = pae[L_b:, :L_b]  # shape [L_t, L_b]

    # bt: for each binder residue i, mean TM-kernel over all target residues j
    bt_per_res = np.mean(1.0 / (1.0 + (pae_bt / d0) ** 2), axis=1)
    bt_iptm = float(np.max(bt_per_res)) if len(bt_per_res) > 0 else 0.0

    # tb: for each target residue i, mean TM-kernel over all binder residues j
    tb_per_res = np.mean(1.0 / (1.0 + (pae_tb / d0) ** 2), axis=1)
    tb_iptm = float(np.max(tb_per_res)) if len(tb_per_res) > 0 else 0.0

    return dict(bt_iptm=bt_iptm, tb_iptm=tb_iptm, iptm=float(max(bt_iptm, tb_iptm)))


# ---------------------------------------------------------------------------
# Multi-model agreement scoring
# ---------------------------------------------------------------------------


def compute_agreement(
    df: pd.DataFrame,
    threshold: float = IPSAE_PASS_THRESHOLD,
    engine_thresholds: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Count how many independent refolding engines agree a design passes.

    Uses per-engine thresholds (defaulting to *threshold* for backward compat
    when `engine_thresholds` not supplied). AF2 is **excluded** from the count
    because its DunbrackLab distribution is mis-calibrated on short targets
    (see INVESTIGATION_RANKING_DISCREPANCY.md §6).

    Adds column 'agreement_count' (0–3: Boltz-2, AF3, ESMFold2 over their thresholds).
    """
    result = df.copy()
    thresholds = {**DEFAULT_ENGINE_THRESHOLDS, **(engine_thresholds or {})}
    engine_cols = {
        "boltz": "boltz_pae_ipsae_min",
        "af3": "af3_ipsae_min",
        "esmfold2": "esmfold2_ipsae_min",
    }

    count = pd.Series(0, index=df.index)
    for engine, col in engine_cols.items():
        if col in result.columns:
            vals = pd.to_numeric(result[col], errors="coerce")
            thr = thresholds.get(engine, threshold)
            count += (vals > thr).fillna(False).astype(int)
    result["agreement_count"] = count
    return result


# ---------------------------------------------------------------------------
# Consensus iPTM — benchmark-validated cross-engine binding score
# ---------------------------------------------------------------------------

# Per-engine PAE-recomputed iptm columns (engine-independent, directly comparable —
# computed by add_iptm_from_pae_files). These are preferred over raw model-reported
# iptm because each engine reports iptm on a slightly different convention.
_ENGINE_IPTM_COLS: list[str] = [
    "boltz_pae_iptm",
    "af3_pae_iptm",
    "esmfold2_pae_iptm",
]


def add_chain_iptm_interface(df: pd.DataFrame, prefix: str = "esmfold2") -> pd.DataFrame:
    """Derive the symmetric chain-pair interface iPTM from the refolder's pair columns.

    The ESMFold2 refolder records ``iptm_pair`` (= max off-diagonal of
    ``pair_chains_iptm``) and ``iptm_pair_min`` (= min). For a 2-chain binder
    complex those are the two directional target<->binder interface iPTMs, so their
    mean ``(iptm_pair + iptm_pair_min) / 2`` is the symmetric chain-pair interface
    iPTM — the strongest single binder-vs-non-binder screen on the ProteinBase
    4-target benchmark (macro AUC ≈ 0.745).

    Prefix-aware so one definition serves both column conventions: ``prefix="esmfold2"``
    for the merged report frame (``esmfold2_iptm_pair``), ``prefix=""`` for a raw refold
    CSV (``iptm_pair``). Writes ``{prefix}_chain_iptm_interface`` (or
    ``chain_iptm_interface`` when ``prefix`` is empty); no-op if the pair columns are
    absent.
    """
    result = df.copy()
    p = f"{prefix}_" if prefix else ""
    pair, pair_min = f"{p}iptm_pair", f"{p}iptm_pair_min"
    if {pair, pair_min} <= set(result.columns):
        result[f"{p}chain_iptm_interface"] = (
            pd.to_numeric(result[pair], errors="coerce") + pd.to_numeric(result[pair_min], errors="coerce")
        ) / 2.0
    return result


def compute_consensus_iptm(df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``consensus_iptm`` column = max of the per-engine PAE-recomputed iptms.

    Across the ProteinBase 4-target benchmark (Nipah / EGFR / IL7R / PD-L1, n=175),
    an exhaustive 297-combination search found that the row-wise **max** of the
    engine iptms is the best *deployable, parameter-free* binder-vs-non-binder
    score (macro ROC AUC ≈ 0.75 — at or above the best single engine, and above any
    leave-one-target-out cross-validated fitted model). The intuition: because the
    most-predictive engine differs per target, "trust whichever engine is most
    confident" lands on the right one each time.

    NOTE: this scores *binder vs non-binder*; the same benchmark showed it does **not**
    rank affinity among binders (see docs/plans.md Part N — that needs interface ΔG).

    Adds:
        consensus_iptm        — max over available {engine}_pae_iptm columns (NaN if none).
        consensus_iptm_mean   — mean over available engines (precision re-rank metric).
        consensus_iptm_min    — min over available engines (most conservative engine).
        consensus_iptm_spread — max − min (engine disagreement; NaN if <2 engines).
        consensus_iptm_n      — how many engines contributed (0–4).
    """
    result = df.copy()
    present = [c for c in _ENGINE_IPTM_COLS if c in result.columns]
    if not present:
        result["consensus_iptm"] = np.nan
        result["consensus_iptm_mean"] = np.nan
        result["consensus_iptm_min"] = np.nan
        result["consensus_iptm_spread"] = np.nan
        result["consensus_iptm_n"] = 0
        return result
    numeric = result[present].apply(pd.to_numeric, errors="coerce")
    # max = binder screen (recall); mean/min = consensus re-rank (precision). See
    # rank_by_two_stage and docs/plans.md Part N (exhaustive two-stage analysis).
    result["consensus_iptm"] = numeric.max(axis=1)
    result["consensus_iptm_mean"] = numeric.mean(axis=1)
    result["consensus_iptm_min"] = numeric.min(axis=1)
    # Engine spread = max − min. Only meaningful when ≥2 engines contributed;
    # NaN for single-engine rows (no disagreement to measure). Surfaced in the
    # report's Top-30 as a "single-engine spike" / "engine disagreement" flag.
    result["consensus_iptm_n"] = numeric.notna().sum(axis=1).astype(int)
    spread = result["consensus_iptm"] - result["consensus_iptm_min"]
    spread = spread.where(result["consensus_iptm_n"] >= 2)
    result["consensus_iptm_spread"] = spread
    return result


# Per-engine DunbrackLab ipSAE_min columns (engine-comparable, recomputed from PAE files).
_ENGINE_IPSAE_MIN_COLS: list[str] = [
    "boltz_pae_ipsae_min",
    "af3_ipsae_min",
    "esmfold2_ipsae_min",
]


def compute_consensus_ipsae(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``consensus_ipsae_min_mean`` = mean across engines of the per-engine
    DunbrackLab ipSAE_min.

    Parallels :func:`compute_consensus_iptm`: averages the independent engines'
    interface ipSAE_min (boltz / af3 / esmfold2). The metric being
    averaged is each engine's ``ipsae_min`` (hence ``_min_mean``). Diagnostic /
    reporting column — the primary ranker stays the two-stage iptm.

    Adds:
        consensus_ipsae_min_mean   — mean over available per-engine ipsae_min (NaN if none).
        consensus_ipsae_min_spread — max − min (engine disagreement; NaN if <2 engines).
        consensus_ipsae_min_n      — how many engines contributed (0–4).
    """
    result = df.copy()
    present = [c for c in _ENGINE_IPSAE_MIN_COLS if c in result.columns]
    if not present:
        result["consensus_ipsae_min_mean"] = np.nan
        result["consensus_ipsae_min_spread"] = np.nan
        result["consensus_ipsae_min_n"] = 0
        return result
    numeric = result[present].apply(pd.to_numeric, errors="coerce")
    result["consensus_ipsae_min_mean"] = numeric.mean(axis=1)
    result["consensus_ipsae_min_n"] = numeric.notna().sum(axis=1).astype(int)
    # Engine ipSAE_min disagreement (max − min). NaN for single-engine rows.
    spread = numeric.max(axis=1) - numeric.min(axis=1)
    spread = spread.where(result["consensus_ipsae_min_n"] >= 2)
    result["consensus_ipsae_min_spread"] = spread
    return result


def rank_by_consensus_iptm(df: pd.DataFrame) -> pd.DataFrame:
    """Rank by ``consensus_iptm`` (max-iptm) descending; benchmark-validated binder filter.

    Sort order (better first):
        1. consensus_iptm    — max engine iptm (higher = more likely a binder)
        2. agreement_count   — engines agreeing ipsae_min > threshold (tiebreak)
        3. plddt_binder_mean — fold confidence (tiebreak)

    Adds a column ``consensus_rank`` (1 = best). Does not modify ``adaptyv_rank``;
    the two rankings coexist so the report can offer either.
    """
    result = df.copy()
    if "consensus_iptm" not in result.columns:
        result = compute_consensus_iptm(result)

    sort_keys, ascending = ["consensus_iptm"], [False]
    if "agreement_count" in result.columns:
        sort_keys.append("agreement_count")
        ascending.append(False)
    for col in ("plddt_binder_mean", "boltz_plddt_binder_mean"):
        if col in result.columns:
            sort_keys.append(col)
            ascending.append(False)
            break

    result = result.sort_values(sort_keys, ascending=ascending, na_position="last")
    result["consensus_rank"] = range(1, len(result) + 1)
    return result.reset_index(drop=True)


def rank_by_two_stage(
    df: pd.DataFrame,
    screen_frac: float = 0.5,
    screen_metric: str = "max",
    min_engines: int = MIN_ENGINES_DEFAULT,
) -> pd.DataFrame:
    """Two-stage ranking — the EVALUATOR benchmark recommendation for wet-lab selection.

    Stage 0 — cross-engine support gate. A design scored by a single engine has
    ``consensus_iptm_mean`` equal to that one engine's value (``DataFrame.mean``
    skips NaN), so it would compete against 3-engine means on an incomparable
    scale. Worse, the single engine is often the one biased in the design's favour
    — Mosaic *is* Boltz-2 gradient hallucination, so a Mosaic design that only
    Boltz-2 refolded could top the list on the strength of its own designer. Only
    designs with ``consensus_iptm_n >= min_engines`` are eligible for the screen.
    Default ``MIN_ENGINES_DEFAULT`` (all three of Boltz-2 / AF3 / ESMFold2);
    ``MIN_ENGINES_FLOOR`` is the lowest meaningful value, since "cross-engine"
    requires at least two.

    Stage 1 — screen by the ``screen_metric`` consensus iptm: keep the top
    ``screen_frac`` of the eligible pool (the recall step).
    ``screen_metric="max"`` (default) screens by ``consensus_iptm`` (max over
    engines) — the lenient recall step: keep a design if *any* engine rates it
    highly, so a genuine binder is not dropped just because one engine's per-target
    blind spot drags its mean down. Best on the ProteinBase 4-target benchmark
    (macro AUC ~0.755, "trust whichever engine is most confident").
    ``screen_metric="mean"`` screens by ``consensus_iptm_mean`` instead (stricter —
    the average must be high; Adaptyv macro AUC 0.710 vs 0.689). See docs/plans.md
    Part N.

    Stage 2 — rank survivors by ``consensus_iptm_mean`` (mean engine iptm): the
    precision step — at the sharp end of the list you want designs *all* engines
    agree on. On the benchmark this lifts precision@top-10% to 0.92 vs 0.79 for
    max alone. The default max-screen → mean-rank pairs a lenient recall screen
    with a strict consensus rank (the intended two-stage design).

    Ranks ALL rows (the screen is a flag + ordering, nothing is dropped):
    ``passes_max_screen`` is the primary sort key, so all screen survivors sort
    above all non-survivors regardless of their mean; within each group rows are
    ordered by ``consensus_iptm_mean``, then by ``consensus_iptm_n`` so a design
    backed by more engines outranks an equal mean backed by fewer. The head of the
    list is therefore the genuine two-stage result. Adds:
        passes_max_screen — bool, eligible AND in the top ``screen_frac``
        two_stage_rank    — 1 = best

    Raises:
        ValueError: if ``min_engines`` is below ``MIN_ENGINES_FLOOR``.

    NOTE: this ranks binder-vs-non-binder *confidence*, NOT affinity among binders
    (every confidence metric inverts against Kd — strongest binders score lowest).
    Affinity ranking needs the interface-ΔG term (see comparison.affinity, Part N).

    See docs/plans.md Part N for the exhaustive two-stage analysis.
    """
    result = df.copy()
    if "consensus_iptm" not in result.columns or "consensus_iptm_mean" not in result.columns:
        result = compute_consensus_iptm(result)

    if min_engines < MIN_ENGINES_FLOOR:
        raise ValueError(
            f"min_engines={min_engines} is below the floor of {MIN_ENGINES_FLOOR}: "
            f"a cross-engine consensus needs at least {MIN_ENGINES_FLOOR} engines."
        )

    screen_col = "consensus_iptm_mean" if screen_metric == "mean" else "consensus_iptm"
    cons = pd.to_numeric(result[screen_col], errors="coerce")
    n_eng = pd.to_numeric(result.get("consensus_iptm_n", 0), errors="coerce").fillna(0)
    eligible = cons.notna() & (n_eng >= min_engines)
    n_eligible = int(eligible.sum())

    # Tell the operator when the gate — not the data — emptied the screen, and how
    # to proceed. Silently returning an all-False passes_max_screen looks like
    # "no good designs" when it actually means "not enough engines were run".
    n_available = int(n_eng.max()) if len(n_eng) else 0
    if n_eligible == 0 and cons.notna().any():
        warnings.warn(
            f"[two-stage] no design was refolded by {min_engines}+ engines "
            f"(best coverage in this pool: {n_available}), so nothing passes the Stage-1 screen. "
            f"Run the missing engine(s), or lower the gate with --min-engines "
            f"{max(MIN_ENGINES_FLOOR, n_available)}.",
            stacklevel=2,
        )

    n_keep = math.ceil(n_eligible * screen_frac)
    thr = cons[eligible].nlargest(n_keep).min() if n_keep else float("inf")
    result["passes_max_screen"] = eligible & (cons >= thr)

    sort_keys = ["passes_max_screen", "consensus_iptm_mean", "consensus_iptm_n", "consensus_iptm"]
    ascending = [False, False, False, False]
    for col in ("plddt_binder_mean", "boltz_plddt_binder_mean"):
        if col in result.columns:
            sort_keys.append(col)
            ascending.append(False)
            break
    result = result.sort_values(sort_keys, ascending=ascending, na_position="last")
    result["two_stage_rank"] = range(1, len(result) + 1)
    return result.reset_index(drop=True)


def add_design_groups(df: pd.DataFrame) -> pd.DataFrame:
    """Add a ``design_group`` column collapsing multiple *sequences of one design*.

    Rule: we want the best design, not many near-duplicate variants of it. A
    "design" is a backbone / hallucination trajectory:

      - Protein-Hunter: ``protein_hunter_<run>_c<cycle>`` → one group per *run*
        (cycles are snapshots of one hallucination trajectory; e.g. run 107's
        c5–c8 are 61–80 % identical).
      - BindCraft: ``..._mpnn<N>`` → one group per *trajectory* (MPNN re-designs
        of one AF2 backbone).

    Every other tool emits one design per entry (verified distinct — e.g. Mosaic
    designs from one worker are only ~10 % identical), so the group is the
    binder_id itself. Downstream keeps the best-ranked entry per group.
    """
    result = df.copy()
    if "binder_id" not in result.columns:
        result["design_group"] = [str(i) for i in range(len(result))]
        return result

    def _grp(row: pd.Series) -> str:
        bid = str(row.get("binder_id", ""))
        tool = str(row.get("source_tool", ""))
        if tool == "protein_hunter":
            return re.sub(r"_c\d+$", "", bid)
        if tool == "bindcraft":
            return re.sub(r"_mpnn\d+.*$", "", bid)
        return bid

    result["design_group"] = result.apply(_grp, axis=1)
    return result


# ---------------------------------------------------------------------------
# Adaptyv-method ranking (with agreement)
# ---------------------------------------------------------------------------


def rank_by_adaptyv_method(df: pd.DataFrame) -> pd.DataFrame:
    """Rank binders using the Adaptyv/meta-analysis hierarchy.

    Sort order (all ascending sort key = better first):
        1. quality_tier      — high > medium > low > reject
        2. agreement_count   — how many engines agree ipsae_min > 0.61
        3. ipsae_min         — primary metric (higher = better)
        4. iptm              — secondary (higher = better)
        5. plddt_binder_mean — tertiary (higher = better)

    Adds a column 'adaptyv_rank' (1 = best).
    Rows with ipsae_valid == 1 are shown before those without.
    """
    result = df.copy()
    ipsae_col = _best_ipsae_col(result)

    sort_keys = []
    ascending = []

    # Valid interface first
    if "ipsae_valid" in result.columns:
        result["_ipsae_valid_sort"] = (~result["ipsae_valid"].eq(1)).astype(int)
        sort_keys.append("_ipsae_valid_sort")
        ascending.append(True)

    # Primary: quality tier (high before medium before low before reject)
    if "quality_tier" in result.columns:
        _tier_order = {"high": 0, "medium": 1, "low": 2, "reject": 3, "unknown": 4}
        result["_tier_sort"] = result["quality_tier"].map(_tier_order).fillna(4)
        sort_keys.append("_tier_sort")
        ascending.append(True)

    # Secondary: agreement count (more engines agreeing = better)
    if "agreement_count" in result.columns:
        sort_keys.append("agreement_count")
        ascending.append(False)

    # Tertiary: ipSAE_min
    if ipsae_col is not None:
        sort_keys.append(ipsae_col)
        ascending.append(False)

    # Tertiary: iptm
    for col in ["iptm", "boltz_iptm"]:
        if col in result.columns:
            sort_keys.append(col)
            ascending.append(False)
            break

    # Quaternary: pLDDT
    for col in ["plddt_binder_mean", "boltz_plddt_binder_mean"]:
        if col in result.columns:
            sort_keys.append(col)
            ascending.append(False)
            break

    if sort_keys:
        result = result.sort_values(sort_keys, ascending=ascending, na_position="last")

    result["adaptyv_rank"] = range(1, len(result) + 1)

    # Clean up temporary columns
    for tmp_col in ["_ipsae_valid_sort", "_tier_sort"]:
        if tmp_col in result.columns:
            result = result.drop(columns=[tmp_col])

    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def annotate_wetlab_recommended(
    df: pd.DataFrame,
    *,
    soluprot_passes_col: str = "native_soluprot_passes",
    agreement_min: int = 2,
    min_plddt_binder: float = 0.50,
) -> pd.DataFrame:
    """Item 9: per-design ``wetlab_recommended`` bool + ``wetlab_reason`` string.

    Combines existing advisory signals (SoluProt + agreement_count + binder
    pLDDT min) into a single conservative "would-I-ship-this" annotation. The
    report renders failing rows with a CSS strike-through in the Top-30 — but
    never reorders or drops them. NaN values are treated as "we don't know" and
    do NOT block recommendation (we don't penalise an unknown).

    Rule (all required for recommend=True):
      - SoluProt pass (when known): native_soluprot_passes is True or NaN.
      - Cross-engine agreement: agreement_count >= ``agreement_min`` (when known).
      - Binder fold confidence: plddt_binder_min >= ``min_plddt_binder`` (when known).
      - No FAILED RUN convergence flag from the per-tool classification.
    """
    out = df.copy()
    reasons: list[list[str]] = [[] for _ in range(len(out))]

    if soluprot_passes_col in out.columns:
        sp = out[soluprot_passes_col]
        # bool dtype keeps NaN-friendly semantics if cast carefully
        try:
            sp_bool = sp.apply(lambda v: bool(v) if pd.notna(v) else None)
        except Exception:
            sp_bool = pd.Series([None] * len(out), index=out.index)
        for idx, val in zip(out.index, sp_bool):
            if val is False:
                reasons[out.index.get_loc(idx)].append("SoluProt FAIL")

    if "agreement_count" in out.columns:
        agreement = pd.to_numeric(out["agreement_count"], errors="coerce")
        # agreement_count cannot exceed the number of engines that actually ran, and a
        # single-engine run is a supported, auto-detected configuration (evaluate.sh
        # skips engines whose conda env is absent). Applying the >= 2 rule there failed
        # EVERY design for a reason the operator cannot act on by improving a design,
        # which makes the whole column uninformative. Treat it as unknown instead.
        # Treated as "unknown", consistent with this function's NaN policy: unknowns do
        # not block. Warn once so the operator knows the criterion was not applied.
        n_engines = 0
        if "consensus_iptm_n" in out.columns:
            counts = pd.to_numeric(out["consensus_iptm_n"], errors="coerce")
            n_engines = int(counts.max()) if counts.notna().any() else 0
        if n_engines and n_engines < agreement_min:
            warnings.warn(
                f"[wetlab] only {n_engines} refold engine(s) in this pool, so cross-engine "
                f"agreement (>= {agreement_min}) could not be assessed and was NOT applied to "
                f"wetlab_recommended. Run a second engine before trusting this column.",
                stacklevel=2,
            )
        else:
            for i, val in enumerate(agreement):
                if pd.notna(val) and val < agreement_min:
                    reasons[i].append(f"agreement {int(val)} < {agreement_min}")

    if "plddt_binder_min" in out.columns:
        plddt_min = pd.to_numeric(out["plddt_binder_min"], errors="coerce")
        for i, val in enumerate(plddt_min):
            if pd.notna(val) and val < min_plddt_binder:
                reasons[i].append(f"min pLDDT {val:.2f} < {min_plddt_binder:g}")

    # Per-tool FAILED RUN convergence check (only fires for boltzgen_*).
    if "source_tool" in out.columns and "consensus_ipsae_min_mean" in out.columns:
        from .tool_classification import convergence_status

        # Compute mean once per tool to avoid recomputing per row.
        tool_means = (
            out.assign(_t=out["source_tool"].fillna("").astype(str).str.lower())
            .groupby("_t")["consensus_ipsae_min_mean"]
            .mean()
            .to_dict()
        )
        failed_tools: dict[str, str] = {}
        for tool, mean_val in tool_means.items():
            failed, why = convergence_status(tool, mean_val)
            if failed and why:
                failed_tools[tool] = why
        if failed_tools:
            for i, tool_name in enumerate(out["source_tool"].fillna("").astype(str).str.lower()):
                if tool_name in failed_tools:
                    reasons[i].append(f"tool failed run ({failed_tools[tool_name]})")

    out["wetlab_recommended"] = [len(r) == 0 for r in reasons]
    out["wetlab_reason"] = ["; ".join(r) if r else "" for r in reasons]
    return out


def _best_ipsae_col(df: pd.DataFrame) -> str | None:
    """Return the best available ipsae_min column name.

    Preference order: PAE-based DunbrackLab columns first (post-hoc, correct
    formula), then Mosaic aux columns (optimisation-time, max aggregation).
    """
    for col in [
        "ipsae_min",  # promoted DunbrackLab PAE-based (10 Å cutoff)
        "boltz_pae_ipsae_min",  # Boltz-2 PAE-based (DunbrackLab, 10 Å cutoff)
        "ipsae_min_aux",  # Mosaic aux (max aggregation, renamed)
        "boltz_ipsae_min",  # Mosaic aux (pre-rename)
    ]:
        if col in df.columns:
            return col
    return None
