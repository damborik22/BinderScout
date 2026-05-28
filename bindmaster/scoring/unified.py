"""
BindMaster Unified Scoring
==========================
Provides BinderScore — a common data structure that every tool's output
can be mapped into for cross-tool comparison.

IMPORTANT: Existing tool scoring is NOT changed. BinderScore is additive —
existing workflows continue to use their own CSVs. This layer is only
activated when BINDMASTER_ENABLE_UNIFIED_SCORING=true.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum


class ToolOrigin(str, Enum):
    BINDCRAFT = "bindcraft"
    BOLTZGEN = "boltzgen"
    MOSAIC = "mosaic"
    PXDESIGN = "pxdesign"


@dataclass
class BinderScore:
    """
    Unified scoring record for a single designed protein binder.
    Populated by tool-specific adapters. All score fields are Optional
    to accommodate tools that don't provide every metric.

    Composite score formula:
        composite = (
            0.40 * normalize(iptm, 0, 1)        # Higher is better
          + 0.30 * normalize(plddt_binder, 0, 1) # Higher is better
          + 0.30 * (1 - normalize(ipae, 0, 30))  # Lower is better
        )
    When a term is unavailable, weights are redistributed proportionally.
    """

    # --- Identity ---
    design_id: str
    origin: ToolOrigin
    pdb_path: str
    target_name: str
    binder_length: int

    # --- Structural confidence ---
    plddt_binder: float | None = None
    iptm: float | None = None
    ptm: float | None = None
    ipae: float | None = None
    pae_interaction: float | None = None

    # --- Geometry ---
    binder_rmsd: float | None = None
    complex_rmsd: float | None = None

    # --- Filter pass/fail (PXDesign-style booleans) ---
    passes_af2ig_easy: bool | None = None
    passes_af2ig_strict: bool | None = None
    passes_protenix_basic: bool | None = None
    passes_protenix_strict: bool | None = None

    # --- Ligand-specific ---
    ligand_ccd_code: str | None = None
    ligand_contact_residues: int | None = None

    # --- Computed composite ---
    composite_score: float | None = field(default=None, init=False)

    def __post_init__(self):
        self.composite_score = self._compute_composite()

    def _compute_composite(self) -> float | None:
        """Compute composite score from available metrics."""
        terms = {}

        best_iptm = self.iptm
        if best_iptm is not None:
            terms["iptm"] = (0.40, best_iptm)

        if self.plddt_binder is not None:
            terms["plddt"] = (0.30, self.plddt_binder)

        best_ipae = self.ipae if self.ipae is not None else self.pae_interaction
        if best_ipae is not None:
            normalized = 1.0 - min(best_ipae / 30.0, 1.0)
            terms["ipae"] = (0.30, normalized)

        if not terms:
            return None

        total_weight = sum(w for w, _ in terms.values())
        composite = sum((w / total_weight) * v for w, v in terms.values())
        return round(composite, 4)

    def passes_any_filter(self) -> bool:
        """True if the design passes at least one binary filter."""
        return any(
            [
                self.passes_af2ig_easy,
                self.passes_af2ig_strict,
                self.passes_protenix_basic,
                self.passes_protenix_strict,
            ]
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["origin"] = self.origin.value
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


# --- Adapter functions: tool-specific dicts -> BinderScore ---


def from_pxdesign_record(
    record: dict,
    design_id: str,
    target_name: str,
    binder_length: int,
    pdb_path: str = "",
) -> BinderScore:
    """Convert a PXDesign results_parser record to BinderScore."""
    return BinderScore(
        design_id=design_id,
        origin=ToolOrigin.PXDESIGN,
        pdb_path=pdb_path,
        target_name=target_name,
        binder_length=binder_length,
        plddt_binder=record.get("af2_plddt"),
        iptm=record.get("ptx_iptm") or record.get("af2_iptm"),
        ptm=record.get("ptx_ptm"),
        ipae=record.get("af2_ipae"),
        binder_rmsd=record.get("af2_binder_rmsd"),
        complex_rmsd=record.get("ptx_complex_rmsd"),
        passes_af2ig_easy=record.get("passes_af2ig_easy"),
        passes_af2ig_strict=record.get("passes_af2ig_strict"),
        passes_protenix_basic=record.get("passes_protenix_basic"),
        passes_protenix_strict=record.get("passes_protenix_strict"),
    )


