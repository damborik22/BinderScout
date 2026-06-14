# Assay selection — the lab's Adaptyv workflow

Designs are submitted to **Adaptyv Bio** (express + characterize); the `wetlab` subcommand
(`comparison/wetlab.recommend_assay`) emits this panel. The funnel is **quick yes/no → deep
kinetics → solution-phase affinity**:

1. **Screen — BLI** (bio-layer interferometry) on *all submitted designs*: quick yes/no binding
   plus first-pass kinetics. This is the throughput tier — it decides which designs are real binders.
2. **Lead characterization** on the top hits (the two-stage + `affinity` shortlist, ~5–10):
   - **SPR** (Biacore) — gold-standard kinetics (kon/koff/KD).
   - **FIDA** (flow-induced dispersion analysis) — solution-phase Kd, **immobilization-free**:
     robust for targets that don't immobilize well and a check against surface artifacts.

## What governs the choices
- **Adaptyv submission count**, not assay type, is the budget lever: every submitted design gets
  BLI; only the leads go to SPR + FIDA. So `--top`/`--budget` set *how many designs to submit*.
- Pair with **monomer QC** (`bindmaster-evaluator` `qc.md`): a context-dependent fold may express
  poorly — flag it before spending a submission slot.
- Confirm with **SPR + FIDA together** for the final leads: agreement between an immobilized
  (SPR) and a solution (FIDA) Kd is the strongest in-vitro evidence before declaring a hit.

## Feeds maturation
The Kd from BLI/SPR/FIDA is what `binder-compare mature` reads (`--affinity-col kd_nM`) to choose
the next round (`maturation.md`). Pre-experimentally, the `affinity` composite stands in as the proxy.

## Caveats
- Adaptyv / BLI / SPR / FIDA is *this lab's* stack — assay availability and cost are lab-specific;
  override the panel via the plan config.
- `TODO:` Adaptyv per-design cost → submission-count math for a given budget.
