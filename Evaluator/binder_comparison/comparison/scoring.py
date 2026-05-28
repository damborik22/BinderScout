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

from pathlib import Path

import numpy as np
import pandas as pd

# ---- Thresholds from Overath et al. 2025 ----
IPSAE_PASS_THRESHOLD = 0.61  # F1-maximising threshold across 15 targets
IPSAE_HIGH_THRESHOLD = 0.80  # High-confidence binder
IPSAE_MIN_THRESHOLD = 0.40  # Below this → very unlikely binder
SHAPE_COMP_PREFILTER = 0.62  # Pre-filter from meta-analysis
RMSD_BINDER_PREFILTER = 3.73  # Å, pre-filter from meta-analysis

# PAE cutoff for Dunbrack ipSAE formula (Å).
# Uniform 10 Å for all engines so that ipSAE scores are directly comparable
# across Boltz-2 and other refolders (Protenix on x86, AF3 on aarch64).
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
# Generic PAE → DunbrackLab ipSAE loader (for Protenix, AF3, and future engines)
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
    ``{prefix}_ipsae_max`` where ``prefix`` is e.g. "protenix" or "af3".

    Args:
        df:              DataFrame with engine refolding results.
        pae_file_col:    Column containing paths to PAE .npy files.
        binder_length_col: Column with binder sequence length.
        pae_cutoff:      PAE cutoff in Å (default 10 Å, uniform across engines).
        base_dir:        Base directory for resolving relative PAE file paths.
        prefix:          Output column prefix (e.g. 'protenix', 'af3').
        ordering:        'binder_target' or 'target_binder' — how the PAE matrix
                         is laid out. Protenix and AF3 both default to
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
        prefix:          Column name prefix ('boltz', 'protenix', or 'af3').
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
    "protenix": IPSAE_PASS_THRESHOLD,  # 0.61
    "af3": IPSAE_PASS_THRESHOLD,  # 0.61 — DunbrackLab cutoff was tuned for AF3
    "af2": 0.30,  # informational only; AF2 distribution caps low
}

# Map engine key → DunbrackLab PAE-derived ipsae_min column.
# NOTE: Boltz uses the prefixed `boltz_pae_*` columns (special add_boltz_ipsae_from_files
# pipeline), while Protenix/AF3/AF2 use plain `<engine>_ipsae_min` (from add_ipsae_from_pae_files).
_ENGINE_IPSAE_COLS: dict[str, str] = {
    "boltz": "boltz_pae_ipsae_min",
    "protenix": "protenix_ipsae_min",
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
        passes_boltz_filter, passes_protenix_filter, passes_af3_filter
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

    Adds column 'agreement_count' (0–3: Boltz-2, Protenix, AF3 over their thresholds).
    """
    result = df.copy()
    thresholds = {**DEFAULT_ENGINE_THRESHOLDS, **(engine_thresholds or {})}
    engine_cols = {
        "boltz": "boltz_pae_ipsae_min",
        "protenix": "protenix_ipsae_min",
        "af3": "af3_ipsae_min",
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
