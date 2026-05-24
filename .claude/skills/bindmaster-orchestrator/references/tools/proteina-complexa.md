# Proteina-Complexa

**Engine:** Fully-atomistic flow-matching generative model (built on La-Proteina) **unifying generative and hallucination paradigms via inference-time optimization**. Generates backbone, sidechain, and sequence jointly from random noise, then refines via search-based test-time compute (beam search, best-of-N, MCTS, FK steering) using AF2 / RF3 / force-field reward models. (NVIDIA, ICLR 2026 Oral)
**Role:** design
**Status:** stable (in BindMaster v0.7.0); requires Ubuntu 22.04+ (GLIBC); 2 GPUs default for parallel gen+eval
**Environment:** `Proteina-Complexa/.venv` (uv, Python 3.12); shares AF2 weights with BindCraft

## Principle

Most binder design tools live on one side of a binary: generative diffusion (RFD3, BoltzGen — sample from a prior, then evaluate) or hallucination (BindCraft, Mosaic — gradient-optimize a sequence through a predictor). Proteina-Complexa argues this is a false dichotomy and combines both. It pretrains a flow-based model on a synthetic dataset of binder-target pairs (Teddymer, ~45K PDB multimers + Foldseek-clustered AFDB dimers), then at inference time runs search-based optimization with the generative prior as the proposal distribution and external reward models (AF2 / RF3 folding, force fields) as the scoring function. Inference is the four-stage pipeline `generate → filter → evaluate → analyze`.

The flow-matching backbone uses *partially latent* generation: protein backbone modeled explicitly, sidechain details + sequence captured in a fixed-size latent. New proteins are sampled iteratively from random noise via stochastic sampling. This is a different paradigm from RFD3 (atomic diffusion) or BoltzGen (latent diffusion over backbone): Proteina-Complexa generates all atomic coordinates and sequence jointly in a single end-to-end pass.

Three model variants on NGC, each with its own (model + autoencoder) checkpoint pair:
- **Protein Binder** (`complexa.ckpt` + `complexa_ae.ckpt`) — protein targets
- **Ligand Binder** (`complexa_ligand.ckpt` + `complexa_ligand_ae.ckpt`) — small-molecule targets (LoRA)
- **AME (Motif Scaffolding)** (`complexa_ame.ckpt` + `complexa_ame_ae.ckpt`) — motif + ligand scaffolding (LoRA)

## Strengths

- **Unified generative + hallucination.** Combines diffusion-style sampling diversity with search-driven refinement against arbitrary reward models. SOTA on computational binder benchmarks per the paper.
- **Sidechains and sequence jointly.** Unlike RFD3 (atom positions then MPNN) or BoltzGen (backbone then inverse-folding), Proteina-Complexa outputs full atomistic structure including sidechains and the binder sequence in one pass.
- **Reward-model agnostic.** AF2, RF3, AbsciBind, force fields, custom rewards — plug in any differentiable or non-differentiable scoring function. Reward weights are configurable per run.
- **Four search algorithms.** Single-pass, best-of-N, beam-search, MCTS, and Feynman-Kac steering — each appropriate for different compute budgets and exploration vs. exploitation balance.
- **AME variant.** First-class motif scaffolding with ligand context — supports enzyme design as a natural extension of the binder framework.
- **Wet-lab validated.** Per project page, designs validated experimentally across diverse targets (separate validation PDF on project website).
- **Built-in diversity metrics.** Foldseek + MMseqs2 clustering in the analysis step computes structural and sequence diversity over the generated pool.

## Weaknesses

- **GLIBC requirement.** Ubuntu 22.04+ or equivalent. Older systems must use the Docker option. Real constraint for shared HPC environments.
- **2-GPU default.** `gen_njobs=2 eval_njobs=2` in pipeline configs; override to 1 on single-GPU setups.
- **Setup complexity.** Hydra + OmegaConf config tree, three checkpoint files per pipeline variant, separate `.env` for community model paths (AF2, ESM, RF3, dssp, sc, foldseek, mmseqs). The `complexa init` wizard helps but full setup is non-trivial.
- **NVIDIA license.** Open Model License Agreement for the model weights (Apache 2.0 for the code itself). Review terms for commercial use.
- **JAX recompilation overhead.** AF2 reward model uses JAX; first sample of an eval job pays ~20s build + compile cost (subsequent samples ~1–5s). Recompiles once per unique sequence length.
- **`dssp` and `sc` binaries not bundled.** Must be obtained from FreeBindCraft repo or built locally.
- **aarch64 not yet ported.** Per BindMaster CLAUDE.md known issues: "Proteina-Complexa: Not yet ported to aarch64. See `docs/plans.md` for the porting plan." Needs PyTorch Geometric + torchtext aarch64 wheel patches (same approach as Mosaic).
- **tmol install fragile.** Some Python 3.12 setups hit llvmlite/numba version conflicts (workaround documented in README).

## Pick when

- Need atomistic structure + sequence output in one pass (no separate inverse-folding step).
- Compute budget allows search-based test-time optimization (beam-search, MCTS) — Proteina-Complexa is designed to scale with compute and the paper shows it dominates other methods at higher compute budgets.
- Want reward-model flexibility — plug in AF2, RF3, AbsciBind, custom rewards.
- Designing for motif-scaffolding tasks with ligand context (use AME model).
- Multiple GPUs available (2+ recommended).
- Diversity-aware analysis is wanted out of the box (Foldseek + MMseqs2 clustering).

## Avoid when

- Single-GPU setup with tight memory — default config wants 2 GPUs.
- aarch64 / DGX Spark target — not yet ported.
- Quick exploratory design — full pipeline setup overhead is higher than **BindCraft** (a JSON config) or **Mosaic** (a Python script).
- You don't want to manage community model paths (AF2, RF3, etc.) — **BindCraft** or **BoltzGen** are more self-contained.
- Sub-Ubuntu-22.04 system without Docker — GLIBC blocks the UV install.

## Outputs the evaluator parses

**Pipeline output structure** (`complexa design`):

- `generate/` — raw flow-matching samples (structure + sequence)
- `filter/` — after reward-based filtering
- `evaluate/` — structure prediction validation (AF2, ESMFold, RF3 — configurable)
- `analyze/` — aggregate metrics, success filtering, diversity

**Native metrics surfaced in result CSVs:**

- **Binder refolding metrics** — RMSD between generated and refolded structure (AF2 and RF3 modes)
- **Monomer designability / codesignability** — does the binder fold to the intended structure alone?
- **Motif RMSD** (AME only) — scaffold-to-motif alignment quality
- **Joint motif + binder eval** — combined success criteria for AME
- **Foldseek + MMseqs2 diversity** — structural and sequence clustering over the population
- **Reward scores** — AF2 reward, RF3 reward, force-field reward (whichever were used)
- **Sequence designer outputs** — Self (no redesign) / ProteinMPNN / SolubleMPNN / LigandMPNN

**Evaluator step (BindMaster):**

Proteina-Complexa outputs go through the BindMaster evaluator the same as other tools — Boltz-2 refold (uniform 10 Å iPSAE), and (via Parts J/K) Protenix + AF3 refold for cross-method `agreement_count`. Both Proteina-Complexa's native reward scores and diversity metrics, and the evaluator's `ipsae_min`, are preserved in `summary.csv` — Proteina-Complexa's internal ranking is its native view; the evaluator adds method-agnostic comparison across the full BindMaster pool.

## Key knobs

Configuration is in Hydra YAML; CLI overrides via `++key=value`.

| Knob | Typical | Notes |
|---|---|---|
| Pipeline config | `search_binder_local_pipeline.yaml` (protein) | One of four: protein binder, ligand binder, AME, monomer motif. |
| `ckpt_path` / `ckpt_name` | NGC checkpoint | Model + autoencoder pair per variant. |
| `gen_njobs` / `eval_njobs` | 2 / 2 | GPU parallelism for generate and evaluate stages. Override to 1 on single GPU. |
| `generation.task_name` | e.g. `02_PDL1` | Target identifier from `assets/target_data/`. |
| Search algorithm | beam-search, MCTS, best-of-N, single-pass | Set in pipeline YAML or via CLI. Beam-search default for protein binder pipeline. |
| Reward model weights | AF2 / RF3 / force-field / AbsciBind | Configure in `configs/pipeline/binder/binder_generate.yaml`. Multi-reward weighted sum. |
| Sequence designer | `self` / `ProteinMPNN` / `SolubleMPNN` / `LigandMPNN` | `self` = no separate sequence design step (model output sequence used directly). |
| `num_samples` per target | per problem | Set via search algorithm config. |
| Evaluation set | AF2, ESMFold, RF3 (configurable) | Choose which structure predictors validate each generated design. |
| Success thresholds | per pipeline | Defined in `docs/EVALUATION_METRICS.md` per evaluation type. |
| `.env` paths | AF2_DIR, ESM_DIR, RF3_CKPT_PATH, RF3_EXEC_PATH, SC_EXEC, FOLDSEEK_EXEC, MMSEQS_EXEC, DSSP_EXEC | Community model + bioinformatics binary paths; required before any inference. |
| AME chain convention | ligand on chain A as `L:0`, motif on chain B | Mandatory for AME pipeline; malformed input causes silent failures. |
| `complexa validate` | run before `design` | Catches config resolution errors early. |

## Sources

- Paper: Didi et al. 2026, "Scaling Atomistic Protein Binder Design with Generative Pretraining and Test-Time Compute," ICLR 2026 Oral (https://openreview.net/forum?id=qmCpJtFZra)
- Related: Geffner et al. 2026, "La-Proteina: Atomistic Protein Generation via Partially Latent Flow Matching," ICLR 2026
- Foundation: Geffner et al. 2025, "Proteina: Scaling Flow-based Protein Structure Generative Models," ICLR 2025
- Wet-lab validation: Didi et al. 2026, "Latent Generative Search Unlocks de novo Design of Untapped Biomolecular Interactions at Scale"
- Project page: https://research.nvidia.com/labs/genair/proteina-complexa/
- Repo: https://github.com/NVIDIA-Digital-Bio/Proteina-Complexa (branch `dev`)
- Model card: https://github.com/NVIDIA-Digital-Bio/Proteina-Complexa/blob/dev/assets/model_card/overview.md
- Checkpoints (NGC): https://catalog.ngc.nvidia.com/orgs/nvidia/teams/clara/models/proteina_complexa
- Code license: NVIDIA Open Model License Agreement (code) + Apache 2.0
