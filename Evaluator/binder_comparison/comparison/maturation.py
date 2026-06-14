"""Design maturation — pick the next computational round from binding results.

Grafted from BindMaster 2's Maturation Agent: given the best affinity seen so far (an
experimental Kd in nM, or an in-silico proxy mapped to nM-equivalents), choose how to
improve — explore backbone space, redesign the sequence, or fine-tune residues — and
which parents to carry forward. Pure decision logic (no I/O, no pandas), the same shape
as ``autosize.autosize_decision``; the actual partial-diffusion / MPNN run is delegated to
the design tools by the caller.

Thresholds follow BindMaster 2 (weak >500 nM, moderate >50 nM) and are overridable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

PARTIAL_DIFFUSION = "partial_diffusion"
MPNN_REDESIGN = "mpnn_redesign"
MUTATION_SCAN = "mutation_scan"
DONE = "done"

# Expected fold-improvement per strategy (BindMaster 2 estimates), for the report.
EXPECTED_IMPROVEMENT: dict[str, str] = {
    PARTIAL_DIFFUSION: "2-10x (local backbone exploration via partial diffusion)",
    MPNN_REDESIGN: "2-5x (sequence optimization on a fixed backbone)",
    MUTATION_SCAN: "1.2-2x (point-mutation fine-tuning)",
    DONE: "n/a",
}


@dataclass
class MaturationPlan:
    """The chosen maturation strategy plus the parents to carry into the next round."""

    strategy: str  # partial_diffusion | mpnn_redesign | mutation_scan | done
    reason: str
    best_affinity_nM: float | None
    expected_improvement: str
    parent_design_ids: list[str]
    round_number: int

    def to_dict(self) -> dict:
        return asdict(self)


def decide_maturation_strategy(
    best_affinity_nM: float | None,
    *,
    target_affinity_nM: float | None = None,
    partial_threshold_nM: float = 500.0,
    mpnn_threshold_nM: float = 50.0,
) -> tuple[str, str]:
    """Return ``(strategy, reason)`` from the best affinity seen (lower nM = tighter).

    - no measurement → sequence redesign (cheapest backbone-preserving default)
    - meets ``target_affinity_nM`` → done
    - > ``partial_threshold_nM`` (weak) → explore backbone space (partial diffusion)
    - > ``mpnn_threshold_nM`` (moderate) → redesign the sequence on the backbone
    - otherwise (strong) → fine-tune individual residues (mutation scan)
    """
    if best_affinity_nM is None:
        return MPNN_REDESIGN, "no affinity measurement yet — default to sequence optimization"
    if target_affinity_nM is not None and best_affinity_nM <= target_affinity_nM:
        return DONE, f"best {best_affinity_nM:g} nM meets target {target_affinity_nM:g} nM — stop"
    if best_affinity_nM > partial_threshold_nM:
        return PARTIAL_DIFFUSION, f"weak ({best_affinity_nM:g} nM > {partial_threshold_nM:g}) — explore backbone space"
    if best_affinity_nM > mpnn_threshold_nM:
        return MPNN_REDESIGN, f"moderate ({best_affinity_nM:g} nM) — optimize the sequence on this backbone"
    return MUTATION_SCAN, f"strong ({best_affinity_nM:g} nM) — fine-tune individual residues"


def plan_maturation(
    affinities: dict[str, float],
    *,
    round_number: int = 1,
    top_k: int = 5,
    target_affinity_nM: float | None = None,
    partial_threshold_nM: float = 500.0,
    mpnn_threshold_nM: float = 50.0,
) -> MaturationPlan:
    """Build a ``MaturationPlan`` from ``{design_id: affinity_nM}`` (lower = tighter).

    Selects the strategy from the best affinity, then the parents to carry forward: the
    ``top_k`` tightest binders for backbone/sequence strategies, just the single best for a
    mutation scan, none when done. An empty mapping → sequence-redesign default with no
    parents (cold start).
    """
    best_id, best_aff = (None, None)
    if affinities:
        best_id, best_aff = min(affinities.items(), key=lambda kv: kv[1])

    strategy, reason = decide_maturation_strategy(
        best_aff,
        target_affinity_nM=target_affinity_nM,
        partial_threshold_nM=partial_threshold_nM,
        mpnn_threshold_nM=mpnn_threshold_nM,
    )

    if strategy == DONE or not affinities:
        parents: list[str] = []
    elif strategy == MUTATION_SCAN:
        parents = [best_id] if best_id is not None else []
    else:
        ranked = sorted(affinities.items(), key=lambda kv: kv[1])
        parents = [pid for pid, _ in ranked[:top_k]]

    return MaturationPlan(
        strategy=strategy,
        reason=reason,
        best_affinity_nM=best_aff,
        expected_improvement=EXPECTED_IMPROVEMENT[strategy],
        parent_design_ids=parents,
        round_number=round_number,
    )
