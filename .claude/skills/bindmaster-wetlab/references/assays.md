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
3. **Stability / QC** — is the binder a real, folded, stable protein?
   - **SDS-PAGE** — purity + integrity after expression (± reducing agent for disulfides).
   - **Panta** (NanoTemper nanoDSF + DLS) — thermal stability (**Tm**) + **aggregation** / colloidal stability.
   - **CD** (circular dichroism) — secondary-structure content + thermal melt (confirms a folded,
     cooperatively-unfolding protein, not a molten globule).

   This is the in-vitro counterpart of the in-silico **monomer QC** (`bindmaster-evaluator` `qc.md`)
   and the binder **surface-hydrophobicity** developability flag: a design that failed monomer-RMSD
   or has large hydrophobic patches is the one to watch for low Tm / aggregation here.

## Test matrices — a clean → complex ladder (`WetLabConfig.test_matrices`)
Where binding is measured, in increasing physiological realism (each step adds developability signal):
1. **purified** — clean affinity (the default; what BLI/SPR/FIDA above use).
2. **crude_extract** — binding in a **cell lysate** background → **specificity** (does it still hit the
   target amid thousands of other proteins?). Pairs naturally with **cell-free expression**.
3. **plasma** — binding in **serum/plasma** → physiological binding + **serum stability** (proteolysis,
   off-target/albumin binding) — the developability bar for a therapeutic-track binder.
Advance a design down the ladder only as it survives the prior step.

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
