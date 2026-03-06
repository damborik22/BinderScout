"""Promote Boltz-2 metrics as canonical columns (no ensemble averaging).

For each of the 8 standardised metrics, the canonical column (e.g. ``iptm``,
``ipae``) is a direct copy of the corresponding ``boltz_*`` source column.
AF2 columns (``af2_iptm``, ``af2_ipae``, etc.) remain in the DataFrame for
cross-validation but are not used for ranking or scoring.

Boltz2-exclusive metrics (IPSAE family, binder_ptm, pTMEnergy, etc.) are
passed through unchanged under their boltz_* column names.

Note: despite the module name, no ensemble averaging takes place.  This module
exists for historical reasons and may be renamed in a future refactor.
"""

from __future__ import annotations

import pandas as pd

from ..core.schema import BOLTZ2_METRIC_MAP

# Renaming map: merged column → clean column name for display
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
) -> pd.DataFrame:
    """Add canonical metric columns to *df* by promoting Boltz-2 values.

    Input columns expected (from merger.py):
      Boltz2: boltz_iptm, boltz_ipae, boltz_pae_bt_mean, boltz_pae_tb_mean,
              boltz_pae_bb_mean, boltz_plddt_binder_mean, boltz_plddt_binder_min,
              boltz_plddt_target_mean

    Output columns added:
      iptm, ipae, pae_bt, pae_tb, pae_bb,
      plddt_binder_mean, plddt_binder_min, plddt_target_mean
    Plus renamed Boltz2-exclusive columns (bt_ipsae_aux, tb_ipsae_aux, …).
    """
    result = df.copy()

    for canonical_name, boltz_col in BOLTZ2_METRIC_MAP.items():
        if boltz_col in result.columns:
            result[canonical_name] = pd.to_numeric(result[boltz_col], errors="coerce")
        else:
            result[canonical_name] = float("nan")

    # Rename Boltz2-exclusive columns for cleaner output
    result = result.rename(columns=_BOLTZ2_DISPLAY_RENAMES)

    return result
