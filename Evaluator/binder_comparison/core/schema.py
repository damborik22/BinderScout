"""Core data structures for the binder comparison tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

SourceTool = Literal["bindcraft", "boltzgen", "mosaic", "pxdesign", "rfaa", "unknown"]


@dataclass
class NativeMetrics:
    """Tool-specific metrics not reproducible via standardised refolding.

    Currently populated only for BindCraft sequences, which go through
    PyRosetta relaxation and interface analysis during design.
    """

    dG: float | None = None  # Rosetta interface energy (lower better)
    dSASA: float | None = None  # Buried surface area Å² (higher better)
    shape_complementarity: float | None = None  # Geometric interface fit 0–1 (higher better)
    packstat: float | None = None  # Interface packing quality (higher better)
    hbonds_interface: float | None = None  # H-bond count at interface (higher better)
    hbonds_pct: float | None = None  # H-bonds as % of interface residues
    mpnn_recovery: float | None = None  # MPNN sequence recovery score


@dataclass
class StandardisedMetrics:
    """Metrics produced by running both refolding engines on every binder.

    Every binder gets these, regardless of which tool designed it.

    Canonical columns (iptm, ipae, etc.) are direct copies of Boltz-2 values.
    AF2 columns remain available for cross-validation.
    Boltz2-exclusive metrics (IPSAE family) have no AF2 equivalent.

    Scale notes:
    - pLDDT: expected [0, 1] for both engines
    - PAE: expected in Ångströms for both engines
    - IPSAE: Boltz2-specific score, higher = better interface contact
    """

    # ---- Canonical (Boltz-2 primary) ----
    iptm: float | None = None
    ipae: float | None = None
    pae_bt: float | None = None
    pae_tb: float | None = None
    pae_bb: float | None = None
    plddt_binder_mean: float | None = None
    plddt_binder_min: float | None = None
    plddt_target_mean: float | None = None

    # ---- AF2-specific values (pre-ensemble) ----
    af2_iptm: float | None = None
    af2_ipae: float | None = None
    af2_pae_bt: float | None = None
    af2_pae_tb: float | None = None
    af2_pae_bb: float | None = None
    af2_plddt_binder_mean: float | None = None
    af2_plddt_binder_min: float | None = None
    af2_plddt_target_mean: float | None = None

    # ---- Boltz2-specific values (pre-ensemble) ----
    boltz_iptm: float | None = None
    boltz_ipae: float | None = None
    boltz_pae_bt: float | None = None
    boltz_pae_tb: float | None = None
    boltz_pae_bb: float | None = None
    boltz_plddt_binder_mean: float | None = None
    boltz_plddt_binder_min: float | None = None
    boltz_plddt_target_mean: float | None = None

    # ---- Boltz2-exclusive (no AF2 equivalent) ----
    bt_ipsae: float | None = None  # Binder→target IPSAE, 6-sample avg
    tb_ipsae: float | None = None  # Target→binder IPSAE
    ipsae_min: float | None = None  # min(bt, tb) — worst-case interface contact
    ipsae_valid: int | None = None  # 1 = interface detected, 0 = no contact
    bt_iptm: float | None = None  # Directional interface pTM
    binder_ptm: float | None = None  # Binder fold quality
    intra_contact: float | None = None  # Within-binder contacts
    target_contact: float | None = None  # Binder-target contacts
    pTMEnergy: float | None = None  # Boltz2 energy proxy (lower better)


@dataclass
class PerResidueData:
    """Raw per-residue arrays from refolding engines.

    Both are normalised to [binder | target] ordering:
    - Boltz2 native: [binder | target] — no change needed
    - AF2 native: [target | binder] — must be swapped on load

    pLDDT shape: [L_b + L_t]
    PAE shape:   [L_b + L_t, L_b + L_t]
    """

    binder_length: int | None = None
    af2_plddt: np.ndarray | None = None
    af2_pae: np.ndarray | None = None
    boltz_plddt: np.ndarray | None = None
    boltz_pae: np.ndarray | None = None


@dataclass
class ExtractedBinder:
    """Intermediate representation after sequence extraction but before refolding."""

    binder_id: str
    sequence: str
    source_tool: SourceTool
    native: NativeMetrics = field(default_factory=NativeMetrics)


@dataclass
class MetricResult:
    """Full result for one binder after extraction, refolding, and ensemble."""

    binder_id: str
    sequence: str
    source_tool: SourceTool
    standardised: StandardisedMetrics = field(default_factory=StandardisedMetrics)
    native: NativeMetrics = field(default_factory=NativeMetrics)
    per_residue: PerResidueData = field(default_factory=PerResidueData)
    model_weights: dict[str, float] = field(default_factory=lambda: {"af2": 0.6, "boltz2": 0.4})

    def to_flat_dict(self) -> dict:
        """Flatten all metrics into a single dict for CSV export."""
        d: dict = {
            "binder_id": self.binder_id,
            "sequence": self.sequence,
            "source_tool": self.source_tool,
        }
        # Standardised
        for fname in StandardisedMetrics.__dataclass_fields__:
            d[fname] = getattr(self.standardised, fname)
        # Native
        for fname in NativeMetrics.__dataclass_fields__:
            d[f"native_{fname}"] = getattr(self.native, fname)
        return d


@dataclass
class ComparisonReport:
    """Aggregated results for the full comparison run."""

    results: list[MetricResult]
    summary_statistics: dict[str, dict[str, float]]  # metric → {mean, std, min, max}
    z_scores: dict[str, dict[str, float]]  # binder_id → metric → z_score
    rankings: dict[str, list[str]]  # metric → ordered binder_ids
    model_weights: dict[str, float] = field(default_factory=lambda: {"af2": 0.6, "boltz2": 0.4})


# Metrics where lower is better (for correct ranking direction)
LOWER_IS_BETTER = frozenset(
    {
        "ipae",
        "pae_bt",
        "pae_tb",
        "pae_bb",
        "af2_ipae",
        "af2_pae_bt",
        "af2_pae_tb",
        "af2_pae_bb",
        "boltz_ipae",
        "boltz_pae_bt",
        "boltz_pae_tb",
        "boltz_pae_bb",
        "pTMEnergy",
    }
)

# Canonical metric names → Boltz-2 source column.
# These columns are promoted directly (no ensemble averaging).
BOLTZ2_METRIC_MAP = {
    # canonical_name: boltz2_col
    "iptm": "boltz_iptm",
    "ipae": "boltz_ipae",
    "pae_bt": "boltz_pae_bt_mean",
    "pae_tb": "boltz_pae_tb_mean",
    "pae_bb": "boltz_pae_bb_mean",
    "plddt_binder_mean": "boltz_plddt_binder_mean",
    "plddt_binder_min": "boltz_plddt_binder_min",
    "plddt_target_mean": "boltz_plddt_target_mean",
}

# Boltz2-exclusive columns (after boltz_ prefix added by merger)
BOLTZ2_EXCLUSIVE_COLS = [
    "boltz_bt_ipsae",  # Mosaic aux (max aggregation) — renamed to bt_ipsae_aux
    "boltz_tb_ipsae",  # Mosaic aux — renamed to tb_ipsae_aux
    "boltz_ipsae_min",  # Mosaic aux — renamed to ipsae_min_aux
    "boltz_ipsae_valid",
    "boltz_bt_iptm",
    "boltz_binder_ptm",
    "boltz_intra_contact",
    "boltz_target_contact",
    "boltz_pTMEnergy",
]

# All standardised metrics that get z-scored (excluding boolean ipsae_valid).
# Use post-ensemble-rename names: ensemble.py renames boltz_ipsae_min → ipsae_min_aux, etc.
# PAE-based DunbrackLab ipSAE columns are added by report.py after merging.
# compute_statistics() filters to columns present in df, so absent ones are silently skipped.
ZSCORE_METRICS = list(BOLTZ2_METRIC_MAP.keys()) + [
    # Mosaic aux ipSAE (max aggregation, renamed by ensemble.py with _aux suffix)
    "bt_ipsae_aux",
    "tb_ipsae_aux",
    "ipsae_min_aux",
    # Boltz2-exclusive (non-ipSAE, renamed by ensemble.py)
    "binder_ptm",
    "intra_contact",
    "target_contact",
    "pTMEnergy",
    # Boltz-2 PAE-based ipSAE (DunbrackLab formula, 10 Å cutoff)
    "boltz_pae_bt_ipsae",
    "boltz_pae_tb_ipsae",
    "boltz_pae_ipsae_min",
    # AF2 PAE-based ipSAE (DunbrackLab formula, 10 Å cutoff)
    "af2_bt_ipsae",
    "af2_tb_ipsae",
    "af2_ipsae_min",
    # ipTM computed independently from PAE matrices
    "boltz_pae_iptm",
    "af2_pae_iptm",
]
