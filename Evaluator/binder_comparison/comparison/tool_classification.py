"""Per-tool classification + fairness annotations surfaced in the report (Item 5).

Each generative tool has its own bias that head-to-head comparisons mask:

* BoltzGen (nano) generates sequences within a fixed VHH framework
  (every sequence starts with EVQLVESGGGLVQPGGS…) — that's CDR redesign,
  not de-novo. Should be scored against the H-CDR-redesign baseline, not
  averaged with de-novo backbones from Mosaic / PXDesign.
* BoltzGen (protein) when convergence fails (mean ipSAE_min < 0.2) the
  output is essentially noise. Report should mark it FAILED RUN rather
  than letting the noise drag down the pool aggregates.
* RFD3's native metric is ProteinMPNN sequence recovery — a self-
  consistency score for the backbone, not interface quality.
* Protein-Hunter's default pool comes from ``summary_high_iptm.csv``
  (already iPTM + %X-filtered). Comparing its mean iPTM to other tools'
  unfiltered pools inflates Protein-Hunter's standing. Surface the
  pre-filtered status so the reader sees it without grepping.

This module is the single source of truth for these per-tool framings.
:func:`tool_classification` returns the lookup; the report calls it once.
Extractors can override the runtime fields (``pool_pre_filtered``,
``source_csv``) via :py:meth:`SequenceExtractor.extractor_metadata`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolClassification:
    """Static per-tool framing surfaced in the report."""

    tool_name: str
    display_name: str
    modality: str
    pool_pre_filtered_default: bool
    source_csv_default: str | None
    native_metric_interpretation: str
    convergence_check: str | None
    """Human-readable description of what counts as a failed run for this tool.

    The matching runtime check is in :func:`convergence_status`. Storing the
    natural-language description here so the report can show it next to the
    badge ("FAILED RUN: mean ipSAE_min = 0.08 (threshold < 0.20)").
    """


# Static per-tool framing. Single source of truth; report.py consumes this.
TOOL_CLASSIFICATION: dict[str, ToolClassification] = {
    "bindcraft": ToolClassification(
        tool_name="bindcraft",
        display_name="BindCraft",
        modality="de-novo",
        pool_pre_filtered_default=False,
        source_csv_default="final_design_stats.csv",
        native_metric_interpretation=(
            "AF2 ipTM from the design-time hallucination (biased — BindCraft "
            "optimises for it). Reported alongside Rosetta interface ΔG / SC / "
            "MPNN sequence recovery."
        ),
        convergence_check=None,
    ),
    "boltzgen": ToolClassification(
        tool_name="boltzgen",
        display_name="BoltzGen",
        modality="de-novo",
        pool_pre_filtered_default=False,
        source_csv_default="final_designs_metrics_*.csv",
        native_metric_interpretation=(
            "BoltzGen's own design-time ipSAE_min (biased — same model class as "
            "the Boltz-2 cross-validator). Cross-engine refold against AF3 + "
            "ESMFold2 is the unbiased signal."
        ),
        convergence_check="mean(consensus_ipsae_min_mean) < 0.20 ⇒ FAILED RUN",
    ),
    "boltzgen_nano": ToolClassification(
        tool_name="boltzgen_nano",
        display_name="BoltzGen (nano)",
        modality="vhh-cdr-redesign",
        pool_pre_filtered_default=False,
        source_csv_default="final_designs_metrics_*.csv",
        native_metric_interpretation=(
            "VHH CDR redesign — sequences are generated inside a fixed "
            "EVQLVESGGGLVQPGGS… framework. NOT de-novo binder design. Comparable "
            "to other CDR-redesign tools, not to Mosaic / PXDesign / BindCraft "
            "de-novo backbones."
        ),
        convergence_check="mean(consensus_ipsae_min_mean) < 0.20 ⇒ FAILED RUN",
    ),
    "boltzgen_protein": ToolClassification(
        tool_name="boltzgen_protein",
        display_name="BoltzGen (protein)",
        modality="de-novo",
        pool_pre_filtered_default=False,
        source_csv_default="final_designs_metrics_*.csv",
        native_metric_interpretation=(
            "BoltzGen's own design-time ipSAE_min for free-length de-novo. Cross-engine refold is the unbiased signal."
        ),
        convergence_check="mean(consensus_ipsae_min_mean) < 0.20 ⇒ FAILED RUN",
    ),
    "mosaic": ToolClassification(
        tool_name="mosaic",
        display_name="Mosaic",
        modality="de-novo",
        pool_pre_filtered_default=True,
        source_csv_default="designs.csv (is_top=1 filter)",
        native_metric_interpretation=(
            "Boltz-2 gradient hallucination loss (the metric Mosaic optimised). "
            "Heavily biased toward Boltz-2; cross-engine refold against AF3 + "
            "ESMFold2 is the unbiased signal."
        ),
        convergence_check=None,
    ),
    "pxdesign": ToolClassification(
        tool_name="pxdesign",
        display_name="PXDesign",
        modality="de-novo",
        pool_pre_filtered_default=False,
        source_csv_default="summary.csv",
        native_metric_interpretation=(
            "AF2 ipTM (af2_iptm). PXDesign overfits to AF2 — native rank and "
            "refold rank routinely diverge. Use the refold rank for selection."
        ),
        convergence_check=None,
    ),
    "proteina_complexa": ToolClassification(
        tool_name="proteina_complexa",
        display_name="Proteina-Complexa",
        modality="de-novo (flow matching)",
        pool_pre_filtered_default=False,
        source_csv_default="sequences.csv",
        native_metric_interpretation=(
            "AF2 reward from inference-time optimisation. Mosaic-style bias — trust the cross-engine refold."
        ),
        convergence_check=None,
    ),
    "rfd3": ToolClassification(
        tool_name="rfd3",
        display_name="RFD3",
        modality="diffusion-then-mpnn",
        pool_pre_filtered_default=False,
        source_csv_default="sequences.csv",
        native_metric_interpretation=(
            "ProteinMPNN sequence recovery — measures backbone self-consistency, "
            "NOT interface quality. Treat as a fold-stability sanity check; the "
            "interface signal comes entirely from the cross-engine refold."
        ),
        convergence_check=None,
    ),
    "protein_hunter": ToolClassification(
        tool_name="protein_hunter",
        display_name="Protein-Hunter",
        modality="de-novo",
        pool_pre_filtered_default=True,
        source_csv_default="summary_high_iptm.csv (iPTM + %X filter)",
        native_metric_interpretation=(
            "Boltz-2 / Chai-1 cycle iPTM from hallucination — biased "
            "(self-consistency). Cross-engine refold is the unbiased signal."
        ),
        convergence_check=None,
    ),
}


@dataclass(frozen=True)
class ExtractorMetadata:
    """Runtime metadata supplied per extractor instance.

    Returned by :py:meth:`SequenceExtractor.extractor_metadata` to record what
    the extractor actually read for THIS pool, overriding static defaults.
    """

    pool_pre_filtered: bool
    source_csv: str | None
    notes: str | None = None


DEFAULT_EXTRACTOR_METADATA = ExtractorMetadata(
    pool_pre_filtered=False,
    source_csv=None,
    notes=None,
)


def get_classification(tool_name: str) -> ToolClassification | None:
    """Look up a tool's static classification; case-insensitive on tool_name."""
    if tool_name is None:
        return None
    return TOOL_CLASSIFICATION.get(str(tool_name).lower())


def convergence_status(tool_name: str, mean_consensus_ipsae_min_mean: float | None) -> tuple[bool, str | None]:
    """Apply the per-tool convergence rule. Returns ``(failed, reason)``.

    Rules currently only apply to BoltzGen family (where convergence failure
    is a known mode); other tools return ``(False, None)`` unconditionally.
    """
    cls = get_classification(tool_name)
    if cls is None or cls.convergence_check is None:
        return (False, None)
    if mean_consensus_ipsae_min_mean is None:
        return (False, None)
    try:
        if float(mean_consensus_ipsae_min_mean) < 0.20:
            return (True, f"mean consensus_ipsae_min_mean = {float(mean_consensus_ipsae_min_mean):.3f} < 0.20")
    except (TypeError, ValueError):
        return (False, None)
    return (False, None)
