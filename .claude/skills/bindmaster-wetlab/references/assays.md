# Assay selection

Budget- and throughput-aware, mirroring `comparison/wetlab.recommend_assay` (the `wetlab`
subcommand emits this).

## Tiers (funnel: cheap binary → kinetics → characterization)
1. **Primary screen** — does it bind at all?
   - **> 50 designs** → split-luciferase **NanoBiT** (cheap, high-throughput, binary yes/no).
   - **≤ 50 designs** → **BLI** (label-free, gives kon/koff/KD on every design).
   - **Tight budget** (`--budget` low) with a large pool → fall back to NanoBiT even ≤ 50.
2. **Lead characterization** — **SPR** (Biacore) on the top hits: full kinetics, the affinity
   number you trust. Push **~5–10 leads** (the two-stage + affinity shortlist), not the whole pool.
3. **Orthogonal validation** — **DSF** (thermal stability) early as a cheap expression/fold QC on
   all expressed designs; **ITC** (thermodynamics) on the very top 1–3 leads only (slow, protein-hungry).

## Splitting across tiers
- Screen everything cheaply → BLI/SPR only the screen-positives → ITC only the SPR winners. Each
  tier is ~10× more expensive and lower-throughput than the last, so narrow aggressively.
- Pair assay choice with the **monomer QC** (`bindmaster-evaluator` `qc.md`): a context-dependent
  fold may express poorly — flag it before spending an assay slot.

## Caveats
- These are sensible defaults, **not lab policy** — assay availability and cost are lab-specific;
  override via the plan config.
- `TODO:` per-budget design-count math (how many fit a given $ envelope across the funnel).
