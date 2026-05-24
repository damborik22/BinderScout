# Mosaic

**Engine:** JAX-based composite-objective gradient hallucination over continuous sequence relaxation, with a unified interface to 8 structure predictors (Boltz-1, Boltz-2, AF2, OpenFold3, ProtenixMini/Tiny/Base/2025) + ProteinMPNN/ESM2/AbLang/stability/n-gram. **Design-time confidence only — no internal AF2 cross-validation.**
**Role:** design
**Status:** stable (in BindMaster v0.7.0)
**Environment:** `Mosaic/.venv` (uv, Python 3.12, JAX+CUDA)

## Principle

Mosaic relaxes the discrete binder sequence into a soft PSSM and optimizes it by gradient descent through one or more differentiable structure predictors. Lineage: ColabDesign → RSO → BindCraft, but rather than hallucinating against a single AF2-Multimer pass, Mosaic lets you compose differentiable losses across multiple models — binder–target contacts from Boltz-2, monomer foldability from a second Boltz-2 call, ProteinMPNN sequence recovery, ESM likelihood, stability priors, custom terms — into one loss. Because every model is reimplemented in the same JAX backend (via `joltz` for Boltz-1/2), gradients flow cleanly across the stack without container plumbing. The optimizer (default `simplex_APGM`) walks the PSSM for `n_steps`; sequences are sampled from the converged distribution.

Because hallucination uses the predictor *itself* as the design oracle, design-time confidence overstates real binding likelihood. Cross-validation must come from the BindMaster evaluator (Boltz-2 refold + Protenix + AF3), not from Mosaic itself.

## Strengths

- **Composable objectives.** Combine binder + monomer stability + off-target avoidance + ESM/MPNN priors + custom terms in one optimization. No other tool in the BindMaster stack does this.
- **Cross-model gradient flow.** All models in one JAX runtime → run Boltz-2 + Protenix + ProteinMPNN together without orchestration overhead.
- **Cheap custom losses.** New loss terms are JIT-compatible callable pytrees, a few lines each.
- **Optimizer swappable.** `simplex_APGM` (default), projected GD on hypercube, RSO-box, custom.
- **Multi-target.** DNA / RNA / small-molecule targets via Boltz/Protenix.
- **Pre-cycling speedup.** Protenix family supports running recycling on the target alone before design.

## Weaknesses

- **Not turnkey.** Authors explicitly position Mosaic as a framework, not a tuned method. Learning rates, loss weights, and optimizer hyperparameters often need per-problem tuning.
- **No internal cross-val.** Design-time confidence is from the predictor being optimized against. Real validation only happens at the evaluator stage. This is by design but means raw Mosaic confidence is the most over-optimistic of any tool in the stack.
- **Design-time features lack sidechains.** AF3-style models use UNK/G for the reference-atom channel during design; sidechains only appear on re-prediction with target-only features. Loss terms requiring sidechain geometry don't work directly.
- **JIT cost.** First call to each compiled function is slow. Tuning sessions need to be interactive (notebook/marimo) or every iteration recompiles.
- **No diversity prior.** Pure hallucination converges to similar backbones from similar seeds. Diversity comes from seed/init variation or post-hoc clustering.
- **Memory.** Composite losses with multiple structure predictors stack GPU memory fast.

## Pick when

- Objective is multi-constraint and you want a single joint optimization (binder + monomer + off-target + solubility).
- Running a Karpathy-style loss-tuning inner loop where rapid iteration on objective weights matters.
- Target is rigid or template-steerable; flexible targets need explicit template steering.
- You need DNA/RNA/small-molecule binders via Boltz/Protenix with gradient signal through the predictor.
- You want test-time compute (more recycling/sampling steps) on the design predictor itself.

## Avoid when

- You want a tuned "press button, get binders" workflow → **BindCraft** is the well-trodden path with internal AF2 cross-val baked in.
- You need backbone-level diversity → **RFD3** or **BoltzGen** (diffusion-based, sample diverse backbones).
- Early target characterization, no time to tune loss weights → start with BindCraft or BoltzGen.
- GPU memory is tight and you can't afford composite-loss stacking.

## Outputs the evaluator parses

- `designs.csv` — per-design sequence + Mosaic-internal metrics (Boltz-2 confidence at design time, `ranking_loss`).
- `is_top` column marks the ~40 refolded designs out of typically ~800 total. **Evaluator defaults to `is_top=1` only**; pass `--all-mosaic-designs` to include the rest.
- After evaluator re-fold: `.cif` structure + PAE `.npz` → `bt_ipsae`, `tb_ipsae`, `ipsae_min`.

Mosaic's native `ranking_loss` is preserved in `summary.csv`; `bt_ipsae` / `ipsae_min` from the evaluator provide cross-method comparison over the merged design pool. The evaluator is an unbiased judge across tools, not a replacement for Mosaic's internal ranking — both are signals.

**Parser quirks:**
- `designs.csv` can mix old 11-column and new 13-column formats when multiple workers run concurrently. Parser may misalign — documented in `Evaluator/docs/pipeline_reference.md`.
- `target_sequence` column may contain `"REPLACE_ME"` (template placeholder when the run script wasn't fully configured). Evaluator's CSV fallback skips these rows.
- PAE matrix is native `[binder|target]` ordering (Boltz-2 convention) — column prefix `boltz_pae_*` to distinguish from `protenix_*` / `af3_*`.
- pLDDT scale is [0,1] (Boltz-2 native, not the [0,100] AF3 convention).
- `refold_boltz2.py` appends to CSV — check for duplicate `run_id` if rerun after partial failure.

## Key knobs

| Knob | Typical | Notes |
|---|---|---|
| `binder_length` | 60–120 | Set per target; longer binders score lower on `ipsae_min` (r ≈ −0.78). |
| `recycling_steps` (design) | 3 | More = better gradient signal, more memory. |
| `recycling_steps` (Protenix target pre-cycle) | 5–10 | Run once on target alone before design — wall-time saver. |
| Optimizer | `simplex_APGM` | Momentum 0.3–0.9. |
| `n_steps` | 50–150 | More for harder targets. |
| `stepsize` | 0.1–0.15 | Tune first if convergence is poor. |
| Template steering | `force: true` | Strongest hard constraint for flexible targets. |
| Loss weights | per problem | Main tuning surface; the inner-loop knob. |
| `target_sequence` | actual sequence | **Never leave as `"REPLACE_ME"`** — evaluator silently skips those rows. |

## Sources

- Repo: https://github.com/escalante-bio/mosaic
- JAX-Boltz translation dependency: https://github.com/nboyd/joltz
- Conceptual lineage: ColabDesign (sokrypton/ColabDesign), BindCraft, RSO, "high-level programming language for generative protein design" (biorxiv 2022.12.21.521526)
- No formal paper as of 2026-05; README-driven project from Escalante Bio
- iPSAE formula reference: DunbrackLab 2025 (`d0_res` variant, uniform 10 Å PAE cutoff in BindMaster evaluator)
