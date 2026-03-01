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
5. ipSAE computed from PAE via Dunbrack formula (PAE cutoff 10 Å Boltz-2, 15 Å AF2, d0 per-residue)
6. Ranking: ipSAE_min primary, iptm secondary, plddt_binder_mean tertiary
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ---- Thresholds from Overath et al. 2025 ----
IPSAE_PASS_THRESHOLD = 0.61  # F1-maximising threshold across 15 targets
IPSAE_HIGH_THRESHOLD = 0.80  # High-confidence binder
IPSAE_MIN_THRESHOLD = 0.40  # Below this → very unlikely binder
SHAPE_COMP_PREFILTER = 0.62  # Pre-filter from meta-analysis
RMSD_BINDER_PREFILTER = 3.73  # Å, pre-filter from meta-analysis

# PAE cutoffs for Dunbrack ipSAE formula (Å)
# DunbrackLab recommends 10 Å for Boltz-1/2 and AF3, 15 Å for AlphaFold2
IPSAE_PAE_CUTOFF_BOLTZ = 10.0
IPSAE_PAE_CUTOFF_AF2 = 15.0
IPSAE_PAE_CUTOFF = IPSAE_PAE_CUTOFF_AF2  # backwards compat default


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

    The key difference from Mosaic aux ipSAE is the PAE cutoff (10 Å vs 15 Å)
    and d0 computation (per-residue d0_res vs per-chain).

    Args:
        pae:           PAE matrix in Ångströms, shape [L_total, L_total].
        binder_length: Number of binder residues (L_b).
        pae_cutoff:    PAE filter threshold in Å (default: 15 Å for AF2,
                       use 10 Å for Boltz-2).
        ordering:      'binder_target' (Boltz2 native, [binder|target]) or
                       'target_binder' (AF2 native, [target|binder]).
                       AF2 arrays are transposed internally to [binder|target].

    Returns:
        dict with keys: bt_ipsae, tb_ipsae, ipsae_min, ipsae_max, ipsae_valid
    """
    pae = np.asarray(pae, dtype=float)
    L = pae.shape[0]
    L_b = binder_length
    L_t = L - L_b

    if L_b <= 0 or L_t <= 0:
        return dict(bt_ipsae=np.nan, tb_ipsae=np.nan, ipsae_min=np.nan, ipsae_max=np.nan, ipsae_valid=0)

    # Normalise to [binder | target] ordering
    if ordering == "target_binder":
        # AF2 native: [target | binder] → swap to [binder | target]
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
# AF2 ipSAE from saved PAE files
# ---------------------------------------------------------------------------


def add_af2_ipsae_from_files(
    df: pd.DataFrame,
    pae_file_col: str = "af2_pae_file",
    binder_length_col: str = "binder_length",
    pae_cutoff: float = IPSAE_PAE_CUTOFF_AF2,
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Load AF2 PAE .npy files and compute ipSAE scores, adding them to df.

    Adds columns: af2_bt_ipsae, af2_tb_ipsae, af2_ipsae_min, af2_ipsae_max.

    AF2 PAE arrays are stored in [target | binder] ordering by refold_Version6,
    so 'target_binder' ordering is used.

    Args:
        df:              DataFrame with AF2 refolding results.
        pae_file_col:    Column containing paths to PAE .npy files.
        binder_length_col: Column with binder sequence length.
        pae_cutoff:      PAE cutoff in Å (default 15 Å).
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
            scores = compute_ipsae_from_pae(pae, int(L_b), pae_cutoff, ordering="target_binder")
            bt_ipsae_vals.append(scores["bt_ipsae"])
            tb_ipsae_vals.append(scores["tb_ipsae"])
            min_vals.append(scores["ipsae_min"])
            max_vals.append(scores["ipsae_max"])
        except Exception as e:
            import warnings

            warnings.warn(f"Failed to compute AF2 ipSAE for {pae_path}: {e}")
            bt_ipsae_vals.append(np.nan)
            tb_ipsae_vals.append(np.nan)
            min_vals.append(np.nan)
            max_vals.append(np.nan)

    result["af2_bt_ipsae"] = bt_ipsae_vals
    result["af2_tb_ipsae"] = tb_ipsae_vals
    result["af2_ipsae_min"] = min_vals
    result["af2_ipsae_max"] = max_vals

    return result


# ---------------------------------------------------------------------------
# Boltz-2 ipSAE from saved PAE files
# ---------------------------------------------------------------------------


def add_boltz_ipsae_from_files(
    df: pd.DataFrame,
    pae_file_col: str = "boltz_pae_file",
    binder_length_col: str = "binder_length",
    pae_cutoff: float = IPSAE_PAE_CUTOFF_BOLTZ,
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
        pae_cutoff:      PAE cutoff in Å (default 10 Å for Boltz-2).
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
# Screening thresholds and tier classification
# ---------------------------------------------------------------------------


def apply_screening_thresholds(df: pd.DataFrame) -> pd.DataFrame:
    """Add Boolean screening flags and quality tier column.

    Flags added:
        passes_ipsae_filter   : ipsae_min > 0.61 (primary computational screen)
        passes_ipsae_strict   : ipsae_min > 0.80 (high-confidence binders)
        passes_shape_prefilter: native_shape_complementarity > 0.62 (when available)

    Tier column (quality_tier):
        'high'    : ipsae_min > 0.80
        'medium'  : ipsae_min > 0.61
        'low'     : ipsae_min > 0.40
        'reject'  : ipsae_min <= 0.40 or NaN
    """
    result = df.copy()

    # Determine best available ipsae_min column
    ipsae_col = _best_ipsae_col(result)

    if ipsae_col is not None:
        vals = pd.to_numeric(result[ipsae_col], errors="coerce")
        result["passes_ipsae_filter"] = vals > IPSAE_PASS_THRESHOLD
        result["passes_ipsae_strict"] = vals > IPSAE_HIGH_THRESHOLD

        def _tier(v):
            if pd.isna(v):
                return "reject"
            if v > IPSAE_HIGH_THRESHOLD:
                return "high"
            if v > IPSAE_PASS_THRESHOLD:
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
# Adaptyv-method ranking
# ---------------------------------------------------------------------------


def rank_by_adaptyv_method(df: pd.DataFrame) -> pd.DataFrame:
    """Rank binders using the Adaptyv/meta-analysis hierarchy.

    Primary:   ipsae_min (descending — higher is better)
    Secondary: iptm       (descending)
    Tertiary:  plddt_binder_mean (descending)

    Adds a column 'adaptyv_rank' (1 = best).
    Filters: ipsae_valid == 1 (interface detected) are shown first.
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

    # Primary: ipSAE_min
    if ipsae_col is not None:
        sort_keys.append(ipsae_col)
        ascending.append(False)

    # Secondary: iptm (ensemble preferred)
    for col in ["iptm", "boltz_iptm", "af2_iptm"]:
        if col in result.columns:
            sort_keys.append(col)
            ascending.append(False)
            break

    # Tertiary: pLDDT
    for col in ["plddt_binder_mean", "boltz_plddt_binder_mean", "af2_plddt_binder_mean"]:
        if col in result.columns:
            sort_keys.append(col)
            ascending.append(False)
            break

    if sort_keys:
        result = result.sort_values(sort_keys, ascending=ascending, na_position="last")

    result["adaptyv_rank"] = range(1, len(result) + 1)

    # Clean up temporary column
    if "_ipsae_valid_sort" in result.columns:
        result = result.drop(columns=["_ipsae_valid_sort"])

    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _best_ipsae_col(df: pd.DataFrame) -> str | None:
    """Return the best available ipsae_min column name.

    Preference order: PAE-based DunbrackLab columns first (post-hoc, correct
    formula), then Mosaic aux columns (optimisation-time, max aggregation).
    """
    for col in [
        "ipsae_min",  # ensemble-renamed DunbrackLab PAE-based
        "boltz_pae_ipsae_min",  # Boltz-2 PAE-based (DunbrackLab, 10 Å cutoff)
        "af2_ipsae_min",  # AF2 PAE-based (DunbrackLab, 15 Å cutoff)
        "ipsae_min_aux",  # Mosaic aux (max aggregation, renamed)
        "boltz_ipsae_min",  # Mosaic aux (pre-rename)
    ]:
        if col in df.columns:
            return col
    return None
