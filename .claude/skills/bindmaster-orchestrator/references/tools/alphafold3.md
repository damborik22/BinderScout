# AlphaFold 3

**Engine:** Native DeepMind AlphaFold 3 — the reference AF3-class predictor. Diffusion-based all-atom structure prediction over proteins, nucleic acids, ligands, ions, modified residues, and post-translational modifications. The model and architecture other AF3-class systems (Boltz, Protenix, Chai) reimplement.
**Role:** refolding — BindMaster's **canonical 2nd engine** (Part K, landed). Runs on any CUDA host; gated weights, so opt in with `--tool af3`
**Status:** stable (Part K landed); v3.0.2 in BindMaster's environment
**Environment:** `binder-eval-af3` conda env, Python 3.12 (separate from the design-tool envs; builds on x86_64 and aarch64)

## Principle

AlphaFold 3 (Abramson, Adler, Dunger, Evans, Jumper et al. 2024, *Nature*) extended AlphaFold 2 from single-modality protein folding to full biomolecular structure prediction — proteins, nucleic acids, ligands, ions, modified residues, PTMs. Architectural change: AF2's structure module (built around residue frames and IPA) was replaced by a diffusion-based all-atom generation module operating directly over atomic coordinates. This is the same paradigm Boltz-2 and Protenix later adopted.

AF3 remains the **reference model** in this lineage. Boltz-2 (MIT) and Protenix (ByteDance) are independent reimplementations trained on similar but distinct datasets. Whatever they get right, AF3 is the baseline they were measured against — and whatever they get wrong, AF3 is the natural fall-back for cross-validation.

In BindMaster, AF3 is the **canonical 2nd refolder engine** (Part K, landed). It's hosted in a separate conda env because the DeepMind-provided pipeline has a different MSA stack and database layout.

**It is not aarch64-only.** AF3 runs on any CUDA host: measured ~4.4 GiB peak for 258-391-token complexes (24 GB RTX 3090), so a consumer card is enough in our size regime. DGX Spark is the lab's primary host because that is where the unified-memory headroom lives, not because of a platform restriction. The one real gate is the **gated weights** — AF3 is `--tool af3`, not part of `--tool all`.

The full refolder set on every platform is **ESMFold2 (default) + Boltz-2 + AF3**. Protenix is *not* a refolder — Part J was reverted 2026-07-26.

**Critical to the orchestrator: AF3 is clean against six of the seven design tools.** None of them runs AF3 itself — not BindCraft (AF2), not Mosaic (Boltz-2), not BoltzGen (Boltz-2), not Protein-Hunter (Boltz-2 or Chai), not RFD3 (RF3), not Proteina-Complexa (AF2/RF3 reward models). **The exception is PXDesign**, whose internal engine is Protenix — an AF3 reimplementation — so an AF3 refold of a PXDesign binder is partly self-judging; use ESMFold2 as the clean read there. ESMFold2 is the only engine clean against all seven. The cost of AF3 is wall-time and the gated-weights request, not hardware.

## Strengths

- **Reference AF3-class accuracy.** The model the other AF3-class predictors are measured against.
- **Independent of six of the seven design tools.** None of them runs AF3 internally, so its contribution to `consensus_iptm_mean` is uncorrelated with the design lineage — except for PXDesign, where Protenix makes it partly self-judging. See the bias matrix in `README.md`.
- **Strong PTM modeling.** AF3's joint modeling of standard residues and post-translational modifications outperforms AF2 + PTM hacks. Relevant for designs targeting phosphorylated / methylated / glycosylated sites.
- **Native ligand and ion support.** Same paradigm as Boltz-2/Protenix but with the original training pipeline.
- **DeepMind's MSA pipeline.** Curated and aligned to AF3's training distribution; arguably the highest-quality MSA stack of the three refolders.
- **Reference benchmark for everything else.** When Boltz-2 and ESMFold2 disagree, AF3 is the independent third read. (Protenix is not a refolder — Part J was reverted 2026-07-26.)

## Weaknesses

- **Gated weights.** AF3 parameters require a DeepMind access request, so AF3 is `--tool af3` rather than part of `--tool all`. A host with the env but no weights degrades to a 2-engine run — announced up front by `evaluate.sh`'s weights preflight, not silently — and with `consensus_iptm_n = 2` every design then misses the default `--min-engines 3` gate. Either place the weights or pass `--min-engines 2`.
- **Slowest of the three refolders.** Diffusion + recycling + AF3's deeper trunk → highest wall-time per refold.
- **pLDDT scale is `[0,100]`** (AF3 convention), not [0,1] like Boltz-2 and Protenix. **BindMaster evaluator rescales by /100** before comparing — manual readers of raw AF3 output must apply this divisor.
- **PAE matrix is target-first ordering.** BindMaster evaluator transposes to `[binder|target]` for consistency with Boltz-2.
- **License constraint.** AF3 model weights are released under DeepMind's AlphaFold 3 license — academic / non-commercial use without explicit DeepMind agreement. Different from Boltz-2 (MIT) and Protenix (Apache 2.0); check terms before commercial use.
- **GPU memory.** Heaviest of the three for similar complexes. DGX Spark hardware was selected partly to clear this requirement.
- **MSA pipeline overhead.** AF3's MSA stack is more demanding to set up than Boltz's MMseqs2 server option.

## When this engine's signal is most important

- **The decisive cross-check.** AF3 is independent of every design tool's lineage except PXDesign's — valuable precisely where Boltz-2 is not. Read it when Boltz-2 and ESMFold2 disagree (`consensus_iptm_spread`).
- **Same-model-bias suspects.** For Mosaic, BoltzGen and Protein-Hunter (Boltz-2 bias), AF3 refold is a clean independent signal. **Not for PXDesign:** its internal engine is Protenix, an AF3 reimplementation, so AF3 is *correlated* there — see the bias matrix in `README.md`. ESMFold2 is the clean read for PXDesign.
- **PTM-bearing targets.** AF3 is the strongest predictor in the pool for phosphorylated, methylated, glycosylated, or otherwise modified targets — relevant for therapeutic targets like ApoE4 if PTM-conditioning is in scope.
- **Final-pool ranking.** AF3 is one of the three engines whose mean *is* the ranking: a design refolded by all three clears the default `--min-engines 3` gate and is scored on `consensus_iptm_mean`. That — not `agreement_count` — is the strongest in-silico recommendation BindMaster can produce.

## When this engine's signal should be weighted down

- **Not applicable from a same-model perspective** — no design tool in the BindMaster pool uses AF3 internally.
- **The only practical caveats are availability and cost:**
  - On x86 clusters where AF3 isn't available, the `agreement_count` denominator is 2 (Boltz-2 + Protenix), not 3. Orchestrator must adjust thresholds.
  - For very large pools (>1000 designs), AF3 may be too slow to run on every design. Use Boltz-2 and Protenix first to triage; reserve AF3 for the survivors.

## Outputs the evaluator parses

**Structural outputs:**

- `.cif` structure — atomistic mmCIF; target on first chain, binder on second
- PAE matrix `.npz` — **target-first ordering**, BindMaster evaluator **transposes to `[binder|target]`**
- pLDDT array — **[0,100] scale**, BindMaster evaluator **rescales to [0,1]** before comparison
- `ranking_confidence` — AF3's internal composite score

**Native metrics in AF3 prediction output:**

- `iptm` — interface predicted TM-score
- `ptm` — overall predicted TM-score
- `ranking_confidence` — composite (typically `0.8 * iptm + 0.2 * ptm` or similar)
- `chain_pair_iptm` — pairwise iPTM per chain pair
- `plddt_complex` — mean pLDDT (in `[0,100]`, rescaled by evaluator)
- `plddt_binder` — mean pLDDT over binder chain
- `pae_complex` — mean PAE over complex
- `pae_binder_target` — mean PAE between binder and target
- `model_random_seed` — seed used for diffusion sampling (relevant for ensemble runs)

**iPSAE outputs (computed by BindMaster evaluator):**

- `af3_bt_ipsae` — binder→target directional iPSAE
- `af3_tb_ipsae` — target→binder directional iPSAE
- `af3_ipsae_min` — minimum of the two
- All computed with uniform 10 Å PAE cutoff and DunbrackLab 2025 `d0_res` variant

**Column prefixing:** `af3_*` distinguishes from `boltz_*` and `protenix_*`.

**Cross-engine agreement_count:**

The orchestrator's primary cross-method comparator. Per CLAUDE.md `Critical domain facts`:

> Ranking uses agreement_count (how many engines agree ipsae_min > 0.61) as primary sort, then ipsae_min desc

With all three engines available, `agreement_count ∈ {0, 1, 2, 3}`. With only Boltz-2 + Protenix (x86 environments), denominator is 2 — the orchestrator should track which engines were available per design.

## Key knobs

| Knob | Typical | Notes |
|---|---|---|
| `num_diffusion_samples` | 5 | Diffusion ensemble; more → better mean confidence but linear wall-time. |
| `num_recycles` | 10 | AF3's default; more is slower with diminishing returns. |
| `random_seed` | per design | Ensembling across seeds is the standard inference-time scaling option. |
| Model variant | AF3 v3.0.2 (BindMaster) | Pinned version in `binder-eval-af3` env. |
| MSA pipeline | DeepMind native | Different stack from Boltz-2 / Protenix; requires AF3-format MSA inputs. |
| Template input | optional | Templates supported per AF3 paper; relevant for refolding against known structures. |
| Database paths | env vars | UniRef, MGnify, BFD, etc. — set in `binder-eval-af3` env. |
| GPU | aarch64 / DGX Spark | x86 not supported in BindMaster integration. |
| `--use_msa_for_af3` (from Protein-Hunter) | passes MSA through to AF3 | Relevant only when Protein-Hunter triggers AF3 cross-val during design — not BindMaster's main refold path. |

## Sources

- Paper: Abramson, Adler, Dunger, Evans, Jumper et al. 2024, "Accurate structure prediction of biomolecular interactions with AlphaFold 3," *Nature* 630, 493–500
- Repo: https://github.com/google-deepmind/alphafold3
- BindMaster integration: `binder-eval-af3` conda env (Python 3.12), AF3 v3.0.2, any CUDA host; canonical 2nd engine, Part K landed. Opt in with `--tool af3` (gated weights)
- pLDDT rescaling: BindMaster evaluator divides AF3 pLDDT by 100 for consistency with Boltz-2 / Protenix `[0,1]` convention
- PAE transposition: target-first → `[binder|target]` applied automatically by BindMaster evaluator
- iPSAE formula: DunbrackLab 2025 `d0_res` variant; CLAUDE.md `Evaluation metrics` section
- License: AlphaFold 3 model parameters license (DeepMind) — verify terms for use; differs from Boltz-2 (MIT) and Protenix (Apache 2.0)
