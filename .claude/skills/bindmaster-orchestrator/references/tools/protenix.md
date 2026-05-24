# Protenix

**Engine:** AF3-class diffusion-based all-atom structure predictor from ByteDance AI4S. Open-source AlphaFold3 reimplementation with multiple checkpoint variants (Protenix-v2 ~464 M params, Protenix-v1 base ~368 M, Protenix-Mini ~lightweight, Protenix-Mini-Tmpl with template support). Outperformed AF3 on diverse benchmarks at matched training cutoff per the v1 paper; v2 adds antibody-antigen and ligand-plausibility improvements.
**Role:** refolding (BindMaster Part J, in progress); also used internally at design time by **PXDesign** (which is built on Protenix)
**Status:** in progress (Part J integration); checkpoint variants stable upstream
**Environment:** `bindmaster_pxdesign` (shared with PXDesign — single conda env services both design and refolding roles)

## Principle

Protenix is ByteDance's open-source AF3-class biomolecular structure predictor. Same paradigm as AlphaFold3 and Boltz-2 — diffusion over all-atom coordinates with full multi-modal support (protein, ligand, nucleic acid, modified residues) — but a different training run, different data curation, and a different architectural lineage from MIT's Boltz family. This independence from Boltz-2 is the architectural reason Protenix is in the BindMaster evaluator: it provides a *second AF3-class signal* whose disagreement with Boltz-2 is informative.

Released in waves:
- **Protenix-v0.5.0** (2025-05) — first release, no templates, no RNA MSA
- **Protenix-Mini** (2025-07) — lightweight variant, drastic inference-cost reduction
- **Protenix-v1** (2026-02) — full feature set (MSA, RNA MSA, template), matches AF3 at same training cutoff
- **Protenix-v2** (2026-04) — 464 M params, antibody-antigen gains, ligand plausibility update

In BindMaster, Protenix is being added as a **second refolder engine** alongside Boltz-2 (Part J of the evaluator roadmap). The motivation is **engine disagreement as signal**: a design tool whose output `ipsae_min` agrees across both Boltz-2 and Protenix gets `agreement_count = 2`, which is a more decisive signal than either engine alone. The BindMaster CLAUDE.md `Critical domain facts` calls this out as the primary driver of cross-method ranking.

**Critical to the orchestrator:** Protenix is used by PXDesign internally during design. PXDesign outputs already have Protenix scores baked into their composite ranking, so Protenix refold of PXDesign outputs is *not* fully independent. For PXDesign, the orchestrator should weight Boltz-2 and AF3 refolds more.

## Strengths

- **AF3-class accuracy, open source.** v1 paper shows Protenix outperforms AlphaFold3 across diverse benchmarks at the same training cutoff and inference budget. v2 widens the gap on antibody-antigen tasks.
- **Architecturally independent of Boltz-2.** Different team (ByteDance vs MIT), different training run, different code base. This is the cleanest cross-AF3-class signal in the BindMaster pool.
- **Four checkpoint tiers** trade speed for accuracy: Mini (fast), Base v0.5 (no RNA MSA / template), Base v1 (full features at AF3 parity), v2 (best accuracy, 464 M). The orchestrator can pick per-cost-budget — Mini for high-throughput, v2 for final-pool ranking.
- **Template support** (mini_tmpl, v1, v2) — useful when refolding against a known target conformation. PXDesign uses this combination.
- **Inference-time scaling** — Protenix-v1 shows log-linear gains by increasing sampling budget from several to hundreds of candidates on challenging targets (antibody-antigen). Configurable trade between cost and accuracy.
- **Atom-level contact and pocket constraints** (since 2025-07) — supports physical-prior conditioning during inference.
- **Apache 2.0 license** — fully open for commercial use, no AF3-style restrictions.
- **PXMeter benchmark suite** included for reproducible evaluation across structure prediction models.
- **CCD cache** location overridable via `PROTENIX_DATA_ROOT_DIR`; can be shared with PXDesign.

## Weaknesses

- **Same-model overlap with PXDesign.** PXDesign outputs already use Protenix internally — refold is not a clean independent check. For PXDesign-designed outputs, Boltz-2 and AF3 give cleaner cross-validation.
- **PAE ordering convention is target-first.** Outputs PAE matrix with target chain first; BindMaster evaluator transposes to `[binder|target]` for consistency with Boltz-2 native ordering. Manual readers of raw Protenix output need to apply this transpose.
- **Part J integration still in progress** — refolder code path not fully stable in BindMaster evaluator yet.
- **Newer than AF2** — same caveat as Boltz-2; less battle-tested in production.
- **Custom CUDA kernels** in the install path; BindMaster applies post-install patches (`pxdbench` `NumpyEncoder`, `configs_infer.py` num_workers, CUDA arch for Blackwell sm_120). If packages are upgraded manually, patches must be reapplied.
- **`requirements.txt` pins `torch==2.3.1` (CPU-only).** BindMaster installer force-reinstalls PyTorch with CUDA after `requirements.txt`. Manual `pip install -r requirements.txt` without the followup breaks GPU support.

## When this engine's signal is most important

- **The single most-independent AF3-class check on Boltz-2-trained designs.** Mosaic, BoltzGen, and Protein-Hunter outputs all have Boltz-2 same-model bias. Protenix refold is the clean independent signal — and the cheapest one to obtain (no DGX Spark / aarch64 required, unlike AF3).
- **Antibody-antigen designs.** Protenix-v2 has the strongest reported performance on antibody-antigen interface prediction in the pool.
- **Designs where Boltz-2 reports high `ipsae_min` but design lineage suggests bias.** Disagreement is the signal — orchestrator should escalate when Boltz-2 says yes and Protenix says no.
- **When AF3 is unavailable.** On x86 clusters where AF3 (Part K) isn't accessible, Protenix is the only independent AF3-class signal alongside Boltz-2.

## When this engine's signal should be weighted down

- **PXDesign outputs.** PXDesign uses Protenix internally — refold is correlated. The orchestrator should weight Boltz-2 and AF3 more for PXDesign outputs.
- **Antibody-antigen targets without v2 checkpoint** — if running v1 (or v0.5 which lacks templates and RNA MSA), interface prediction is closer to Boltz-2 baseline; the independence gain is smaller.

## Outputs the evaluator parses

**Structural outputs:**

- `.cif` structure — atomistic mmCIF, target on first chain, binder on second
- PAE matrix `.npz` — **target-first ordering**, BindMaster evaluator **transposes to `[binder|target]`** for consistency with Boltz-2 native
- pLDDT array — **[0,1] scale**, matches BindMaster convention (same as Boltz-2)

**Native metrics in Protenix prediction output:**

- `iptm` — interface predicted TM-score
- `ptm` — overall predicted TM-score
- `plddt_complex` — mean pLDDT over the entire complex
- `plddt_binder` — mean pLDDT over binder chain
- `pae_complex` — mean PAE over the complex
- `pae_binder_target` — mean PAE between binder and target
- `ranking_score` — Protenix's internal composite ranking metric (typically a weighted blend of iPTM, pTM, and clash penalties)

**Per checkpoint:**

When BindMaster runs the three PXDesign-used variants (base, mini, mini_tmpl), the evaluator records confidence from each — useful for orchestrator to see within-Protenix variance:

- `protenix_base_ipsae_min`, `protenix_mini_ipsae_min`, `protenix_mini_tmpl_ipsae_min`
- High variance across the three within-Protenix variants is itself a flag (sequence is borderline)

**iPSAE outputs (computed by BindMaster evaluator):**

- `protenix_bt_ipsae` — binder→target directional iPSAE
- `protenix_tb_ipsae` — target→binder directional iPSAE
- `protenix_ipsae_min` — minimum of the two
- All computed with uniform 10 Å PAE cutoff and DunbrackLab 2025 `d0_res` variant

**Column prefixing:** `protenix_*` distinguishes from `boltz_*` and `af3_*` columns.

## Key knobs

| Knob | Typical | Notes |
|---|---|---|
| Checkpoint | `protenix_base_default_v1.0.0` (or `protenix-v2`, or one of mini variants) | Speed/accuracy trade. v2 is most accurate; mini variants are for high-throughput. |
| Input JSON | per design | One JSON per design+target; supports atom-level contact/pocket constraints since 2025-07. |
| `-n` (model name) | per checkpoint | `protenix pred -i input.json -o ./output -n <model>`. |
| `recycling_steps` | 3–5 | More recycles → slower, marginally better. |
| `num_diffusion_samples` | 5 (default) or up to hundreds for hard targets | Inference-time scaling — log-linear accuracy gains on antibody-antigen up to ~100s of samples. |
| MSA | required for v1/v2 | Pre-compute and pass via JSON `msa` field — same convention as PXDesign. |
| RNA MSA | v1+ only | Required for nucleic-acid targets; not supported in v0.5. |
| Template | mini_tmpl, v1, v2 | Use when refolding against known conformation. |
| `--dtype` | `bf16` (modern GPU) / `fp32` (V100) | Mixed precision. |
| `--use_fast_ln` | `True` (modern) | Fast layer-norm kernel. |
| `--use_deepspeed_evo_attention` | `True` (modern) | DeepSpeed attention kernel. |
| `PROTENIX_DATA_ROOT_DIR` | env var | CCD cache override; share with PXDesign for disk-space efficiency. |
| `--load_checkpoint_dir` | default `./release_data/checkpoint` | Override checkpoint location. |

## Sources

- Protenix-v2 paper: Zhang et al. 2026, "Protenix-v2: Broadening the Reach of Structure Prediction and Biomolecular Design," bioRxiv 2026.04.10.717613
- Protenix-v1 paper: Zhang et al. 2026, "Protenix-v1: Toward High-Accuracy Open-Source Biomolecular Structure Prediction," bioRxiv 2026.02.05.703733
- Protenix-Mini paper: arXiv 2507.11839
- Repo: https://github.com/bytedance/Protenix
- PXMeter (benchmarking suite): https://github.com/bytedance/PXMeter
- Web server (free): https://protenix-server.com
- BindMaster install patches: see CLAUDE.md "PXDesign site-packages patches" — apply to `protenix` (CUDA arch) on reinstall
- License: Apache 2.0
