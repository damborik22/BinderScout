"""Core data structures for the binder comparison tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

SourceTool = Literal[
    "bindcraft",
    "boltzgen",
    "mosaic",
    "pxdesign",
    "rfd3",
    "proteina_complexa",
    "protein_hunter",
    "unknown",
]


@dataclass
class NativeMetrics:
    """Design-time metrics produced by the source tool itself.

    Each tool's `extract()` populates the fields prefixed by its name. The
    serialization in `MetricResult.to_flat_dict()` adds `native_` to every
    column, so e.g. `mosaic_ipsae_min_design` becomes `native_mosaic_ipsae_min_design`
    in the final CSV. This lets us compare "what the design tool thinks about
    its own output" vs "what the refold engines say" side by side.
    """

    # ---- BindCraft (PyRosetta interface analysis) ----
    dG: float | None = None  # Rosetta interface energy (lower better)
    dSASA: float | None = None  # Buried surface area Å² (higher better)
    shape_complementarity: float | None = None  # Geometric interface fit 0–1 (higher better)
    packstat: float | None = None  # Interface packing quality (higher better)
    hbonds_interface: float | None = None  # H-bond count at interface (higher better)
    hbonds_pct: float | None = None  # H-bonds as % of interface residues
    mpnn_recovery: float | None = None  # MPNN sequence recovery score

    # ---- BoltzGen (Boltz-1 internal eval) ----
    # `bg_design_ipsae_min` is BG's own ipSAE; ρ vs Boltz-2 refold ipSAE = +0.84.
    # `bg_final_rank` is a composite (diversity+pTM+hbond+RMSD); ρ vs refold ipSAE = -0.15.
    # See INVESTIGATION_RANKING_DISCREPANCY.md §5.
    bg_design_ipsae_min: float | None = None
    bg_final_rank: int | None = None

    # ---- Mosaic (design-time Boltz-2 from hallucination objective) ----
    mosaic_ranking_loss: float | None = None  # Primary native rank (loss; lower better)
    mosaic_iptm_design: float | None = None  # Design-time ipTM (from iptm_aux column)
    mosaic_ipsae_min_design: float | None = None  # Design-time ipsae_min
    mosaic_bt_iptm: float | None = None  # Directional binder→target pTM
    mosaic_binder_ptm: float | None = None  # Binder monomer pTM
    mosaic_plddt_aux: float | None = None  # Design-time pLDDT (avg)

    # ---- PXDesign (AF2-IG + Protenix internal eval) ----
    # `pxdesign_protenix_iptm` overlaps with the evaluator's Part-J Protenix refold,
    # since PXDesign uses the same Protenix v0.5.0 internally. Both columns are kept
    # because PXDesign's run is biased toward its own designs.
    pxdesign_composite_score: float | None = None  # PXDesign's internal ranking
    pxdesign_af2_iptm: float | None = None
    pxdesign_af2_ipae: float | None = None  # PAE (lower better)
    pxdesign_protenix_iptm: float | None = None
    pxdesign_sequence_recovery: float | None = None  # MPNN recovery

    # ---- Proteina-Complexa (AF2 self-eval during generation reward phase) ----
    complexa_self_iptm: float | None = None  # self_complex_i_pTM
    complexa_self_ipae: float | None = None  # self_complex_i_pAE (lower better)
    complexa_self_plddt: float | None = None  # self_complex_pLDDT
    complexa_self_scrmsd: float | None = None  # Self-consistency RMSD (lower better)
    complexa_af2_reward: float | None = None  # AF2 reward (if used as reward model)
    complexa_rf3_reward: float | None = None  # RF3 reward (if used as reward model)

    # ---- Protein-Hunter (per-cycle Boltz-2 from hallucination loop) ----
    # `iptm_cycle` is per-row; `iptm_best` is the best across cycles for that run.
    protein_hunter_iptm_cycle: float | None = None
    protein_hunter_iptm_best: float | None = None
    protein_hunter_plddt: float | None = None
    protein_hunter_sequence_recovery: float | None = None

    # ---- RFD3 (foundry structural metadata + MPNN recovery) ----
    # RFD3 produces backbones; the "metrics" are structural integrity checks rather
    # than predictive confidence scores like the others.
    rfd3_n_chainbreaks: int | None = None
    rfd3_n_clashing: int | None = None
    rfd3_helix_fraction: float | None = None
    rfd3_sequence_recovery: float | None = None

    # ---- SoluProt (sequence-only E. coli solubility screen, Hon et al. 2021) ----
    # Not a refold engine; runs before refolding and adds a probability that the
    # designed sequence will express solubly. Used as a filter to drop sequences
    # we wouldn't pursue experimentally, not as a re-ranker.
    soluprot_score: float | None = None  # 0–1 probability (higher = more soluble)
    soluprot_passes: bool | None = None  # score >= threshold used when scoring ran


@dataclass
class StandardisedMetrics:
    """Metrics produced by refolding every extracted binder with Boltz-2.

    Every binder gets these, regardless of which tool designed it.

    Canonical columns (iptm, ipae, etc.) are direct copies of Boltz-2 values.
    Boltz2-exclusive metrics (IPSAE family) are pass-through.

    Scale notes:
    - pLDDT: expected [0, 1]
    - PAE: expected in Ångströms
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

    # ---- Boltz2-specific values (pre-ensemble) ----
    boltz_iptm: float | None = None
    boltz_ipae: float | None = None
    boltz_pae_bt: float | None = None
    boltz_pae_tb: float | None = None
    boltz_pae_bb: float | None = None
    boltz_plddt_binder_mean: float | None = None
    boltz_plddt_binder_min: float | None = None
    boltz_plddt_target_mean: float | None = None

    # ---- Boltz2-exclusive ----
    bt_ipsae: float | None = None  # Binder→target IPSAE, 6-sample avg
    tb_ipsae: float | None = None  # Target→binder IPSAE
    ipsae_min: float | None = None  # min(bt, tb) — worst-case interface contact
    ipsae_valid: int | None = None  # 1 = interface detected, 0 = no contact
    bt_iptm: float | None = None  # Directional interface pTM
    binder_ptm: float | None = None  # Binder fold quality
    intra_contact: float | None = None  # Within-binder contacts
    target_contact: float | None = None  # Binder-target contacts
    pTMEnergy: float | None = None  # Boltz2 energy proxy (lower better)

    # ---- Protenix v0.5.0 values (universal 2nd engine; rides bindmaster_pxdesign env) ----
    # pLDDT is rescaled 0-100 → 0-1 on ingest so it's directly comparable to Boltz-2.
    protenix_iptm: float | None = None
    protenix_ptm: float | None = None
    protenix_ranking_score: float | None = None  # 0.8*iptm + 0.2*ptm + 0.5*disorder - 100*has_clash
    protenix_plddt_binder_mean: float | None = None
    protenix_plddt_binder_min: float | None = None
    protenix_plddt_target_mean: float | None = None
    protenix_pae_bt: float | None = None
    protenix_pae_tb: float | None = None
    protenix_pae_bb: float | None = None
    # DunbrackLab PAE-based ipSAE (added by report.py post-merge)
    protenix_bt_ipsae: float | None = None
    protenix_tb_ipsae: float | None = None
    protenix_ipsae_min: float | None = None

    # ---- AlphaFold 3 v3.0.2 values (aarch64 / DGX Spark only; wired in Part K) ----
    af3_iptm: float | None = None
    af3_ptm: float | None = None
    af3_ranking_score: float | None = None
    af3_plddt_binder_mean: float | None = None
    af3_plddt_binder_min: float | None = None
    af3_plddt_target_mean: float | None = None
    af3_pae_bt: float | None = None
    af3_pae_tb: float | None = None
    af3_pae_bb: float | None = None
    af3_bt_ipsae: float | None = None
    af3_tb_ipsae: float | None = None
    af3_ipsae_min: float | None = None


@dataclass
class PerResidueData:
    """Raw per-residue arrays from the Boltz-2 refolding engine.

    Normalised to [binder | target] ordering (Boltz-2 native).

    pLDDT shape: [L_b + L_t]
    PAE shape:   [L_b + L_t, L_b + L_t]
    """

    binder_length: int | None = None
    boltz_plddt: np.ndarray | None = None
    boltz_pae: np.ndarray | None = None
    protenix_pae: np.ndarray | None = None
    af3_pae: np.ndarray | None = None


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
    model_weights: dict[str, float] = field(default_factory=lambda: {"boltz2": 1.0})

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
    model_weights: dict[str, float] = field(default_factory=lambda: {"boltz2": 1.0})


# Metrics where lower is better (for correct ranking direction)
LOWER_IS_BETTER = frozenset(
    {
        "ipae",
        "pae_bt",
        "pae_tb",
        "pae_bb",
        "boltz_ipae",
        "boltz_pae_bt",
        "boltz_pae_tb",
        "boltz_pae_bb",
        "protenix_pae_bt",
        "protenix_pae_tb",
        "protenix_pae_bb",
        "af3_pae_bt",
        "af3_pae_tb",
        "af3_pae_bb",
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
    # Protenix DunbrackLab ipSAE + summary metrics
    "protenix_iptm",
    "protenix_ptm",
    "protenix_ranking_score",
    "protenix_plddt_binder_mean",
    "protenix_bt_ipsae",
    "protenix_tb_ipsae",
    "protenix_ipsae_min",
    "protenix_pae_iptm",
    # AF3 DunbrackLab ipSAE + summary metrics (aarch64 / DGX Spark only)
    "af3_iptm",
    "af3_ptm",
    "af3_ranking_score",
    "af3_plddt_binder_mean",
    "af3_bt_ipsae",
    "af3_tb_ipsae",
    "af3_ipsae_min",
    "af3_pae_iptm",
    # ipTM computed independently from PAE matrices
    "boltz_pae_iptm",
]
