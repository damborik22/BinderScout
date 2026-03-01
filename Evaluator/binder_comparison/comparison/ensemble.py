"""Compute weighted ensemble metrics from AF2 and Boltz2 refolding results.

For each of the 8 standardised metrics, compute:
    ensemble = af2_weight * af2_value + boltz2_weight * boltz2_value

If only one model has a value for a given sequence, that value is used
unweighted (the comparison is still unbiased across the batch because every
sequence is evaluated by the same engines — it just means one engine failed
for that particular sequence).

Boltz2-exclusive metrics (IPSAE family, binder_ptm, pTMEnergy, etc.) are
passed through unchanged under their boltz_* column names.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.schema import ENSEMBLE_METRIC_MAP

# Renaming map: merged column → clean pre-ensemble column name for display
#
# Mosaic aux ipSAE values use max aggregation (optimisation metric) — rename
# them to *_aux to distinguish from DunbrackLab PAE-based ipSAE (mean
# aggregation, evaluation metric) which is added later by report.py.
_BOLTZ2_DISPLAY_RENAMES = {
    "boltz_bt_ipsae": "bt_ipsae_aux",
    "boltz_tb_ipsae": "tb_ipsae_aux",
    "boltz_ipsae_min": "ipsae_min_aux",
    "boltz_ipsae_valid": "ipsae_valid",
    "boltz_bt_iptm": "bt_iptm",
    "boltz_binder_ptm": "binder_ptm",
    "boltz_intra_contact": "intra_contact",
    "boltz_target_contact": "target_contact",
    "boltz_pTMEnergy": "pTMEnergy",
}


def compute_ensemble_metrics(
    df: pd.DataFrame,
    af2_weight: float = 0.6,
    boltz2_weight: float = 0.4,
) -> pd.DataFrame:
    """Add ensemble columns to *df* and return the augmented DataFrame.

    Input columns expected (from merger.py):
      Boltz2: boltz_iptm, boltz_ipae, boltz_pae_bt_mean, boltz_pae_tb_mean,
              boltz_pae_bb_mean, boltz_plddt_binder_mean, boltz_plddt_binder_min,
              boltz_plddt_target_mean
      AF2:    af2_iptm, af2_ipae, af2_pae_bt_mean, af2_pae_tb_mean,
              af2_pae_bb_mean, af2_plddt_binder_mean, af2_plddt_binder_min,
              af2_plddt_target_mean

    Output columns added:
      iptm, ipae, pae_bt, pae_tb, pae_bb,
      plddt_binder_mean, plddt_binder_min, plddt_target_mean
    Plus renamed Boltz2-exclusive columns (bt_ipsae, tb_ipsae, …).
    """
    result = df.copy()
    total_w = af2_weight + boltz2_weight

    for ensemble_name, (boltz_col, af2_col) in ENSEMBLE_METRIC_MAP.items():
        b = _to_float_series(result, boltz_col)
        a = _to_float_series(result, af2_col)

        b_ok = ~np.isnan(b)
        a_ok = ~np.isnan(a)
        both = b_ok & a_ok
        only_a = a_ok & ~b_ok
        only_b = b_ok & ~a_ok

        ensemble = np.full(len(result), np.nan)
        ensemble[both] = (af2_weight * a[both] + boltz2_weight * b[both]) / total_w
        ensemble[only_a] = a[only_a]
        ensemble[only_b] = b[only_b]

        result[ensemble_name] = ensemble

    # Rename Boltz2-exclusive columns for cleaner output
    result = result.rename(columns=_BOLTZ2_DISPLAY_RENAMES)

    return result


def _to_float_series(df: pd.DataFrame, col: str) -> np.ndarray:
    """Return column as float array with NaN for missing/invalid values."""
    if col not in df.columns:
        return np.full(len(df), np.nan)
    return pd.to_numeric(df[col], errors="coerce").values.astype(float)
