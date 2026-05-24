# Boltz-2

**Engine:** AF3-class diffusion-based all-atom structure predictor with joint affinity-prediction head. Trained jointly on complex structure prediction and binding affinity, achieving FEP-level affinity accuracy at ~1000× speed per the paper. Successor to Boltz-1 (the first fully open-source AF3-class predictor).
**Role:** refolding (primary in BindMaster); also used internally at design time by Mosaic, BoltzGen, and Protein-Hunter
**Status:** stable; the BindMaster default refolder, currently active on all platforms
**Environment:** shares `Mosaic/.venv` (same conda env as Mosaic — single JAX/CUDA install services both)

## Principle

Boltz-2 is from the MIT group (Passaro, Corso, Wohlwend, Jaakkola, Barzilay). It extends Boltz-1's AF3-class structure-prediction architecture with a jointly-trained affinity head, so a single forward pass produces a complex structure *and* a binding-affinity estimate. The headline claim from the paper is that Boltz-2's affinity prediction approaches physics-based FEP+ accuracy while running ~1000× faster — a step change in early-stage in-silico screening throughput.

In BindMaster, Boltz-2 is the **default refolding engine for every design**. After a design tool (Mosaic, BoltzGen, BindCraft, RFD3, PXDesign, Protein-Hunter, Proteina-Complexa) produces a sequence + target context, the evaluator re-folds the complex with Boltz-2 and computes iPSAE under the DunbrackLab 2025 `d0_res` formula with a uniform 10 Å PAE cutoff. The refold is what produces the `boltz_*` columns in `summary.csv`.

**Critical to the orchestrator:** three design tools (Mosaic, BoltzGen, Protein-Hunter) use Boltz-2 internally during design. For those tools' outputs, the Boltz-2 refold is *not* an independent check — it's the same model the design was optimized against. The agreement_count signal from Boltz-2 alone is therefore not sufficient for those tools; Protenix and AF3 refold agreement matters more.

## Strengths

- **AF3-class accuracy.** Per the paper, matches or exceeds AlphaFold3 on the standard structure benchmarks; Boltz-1 was already the first fully open AF3-competitive model and Boltz-2 builds on that.
- **Joint affinity prediction.** `affinity_pred_value` (regression on log10 IC50 in μM) plus `affinity_probability_binary` (binder-vs-decoy classifier on [0,1]). Used by BoltzGen's `affinity` pipeline step for small-molecule targets.
- **Native multi-modal.** Protein, peptide, small molecule (CCD or SMILES), DNA, RNA, modified residues, custom ligands.
- **Fast.** Faster than native AF3 in like-for-like comparisons. Practical to run at design-pool scale.
- **MIT license.** Code and weights free for academic and commercial use.
- **NVIDIA cuEquivariance acceleration.** On recent NVIDIA GPUs Boltz-2 uses cuEquivariance kernels for the equivariant attention.
- **Convenient defaults.** pLDDT on [0,1], PAE in raw Angstroms, native `[binder|target]` chain ordering — matches BindMaster's evaluator conventions without transposition or rescaling.
- **MSA server option.** `--use_msa_server` calls ColabFold MMseqs2 server, removing the local MSA management burden.

## Weaknesses

- **Same-model self-judging.** The structural cost: Mosaic, BoltzGen, and Protein-Hunter all use Boltz-2 internally during design, so Boltz-2 refolding of those tools' outputs has correlated bias. Independence concerns apply specifically to those tools — BindCraft, RFD3, PXDesign, and Proteina-Complexa are independent of Boltz-2 at design time and their Boltz-2 refold signal is clean.
- **Affinity head is dataset-dependent.** `affinity_pred_value` and `affinity_probability_binary` come from different training datasets with different supervisions per the README. `affinity_pred_value` (log10 IC50) is for ligand-optimization stages; `affinity_probability_binary` is for hit discovery (binder/decoy detection). Using the wrong one for the wrong stage gives misleading results.
- **GPU memory.** Diffusion-based prediction with full atomistic detail is memory-heavy on large complexes.
- **Newer than AF2.** Less battle-tested than AlphaFold2 — adoption is recent, edge cases still being discovered.

## When this engine's signal is most important

- **Default cross-check for every design.** Boltz-2 is the baseline signal — `bt_ipsae` / `tb_ipsae` / `ipsae_min` from Boltz-2 refold are the headline columns the orchestrator should read first.
- **BindCraft outputs.** BindCraft uses AF2 internally; Boltz-2 refold gives a fully independent AF3-class check. High Boltz-2 `ipsae_min` agreement on BindCraft designs is one of the strongest signals in the pool.
- **RFD3 outputs.** RFD3 + MPNN is independent of Boltz-2 design lineage; Boltz-2 refold is a clean cross-validation.
- **PXDesign outputs.** PXDesign uses Protenix internally; Boltz-2 refold is independent of that.
- **Proteina-Complexa outputs.** Uses AF2/RF3 reward models internally, not Boltz-2 — refold is independent.
- **Small-molecule binder ranking** — pair the structural refold with the affinity head's `affinity_probability_binary` for hit discovery, or `affinity_pred_value` for lead optimization.

## When this engine's signal should be weighted down

- **Mosaic outputs.** Mosaic's design loss can include Boltz-2 confidence terms directly. Refold signal is correlated.
- **BoltzGen outputs.** BoltzGen runs Boltz-2 internally as its `folding` pipeline step. The evaluator's Boltz-2 refold is the same model — not a fully independent check. CLAUDE.md flags this: "Sequences designed for Boltz-2 often don't cross-validate well" (CALCA: 1/50 BoltzGen designs passed `ipsae_min > 0.61`).
- **Protein-Hunter (Boltz edition) outputs.** Hallucinates against Boltz-2; same caveat.
- **For these three tools, treat Protenix and AF3 agreement as the more decisive signal.** The orchestrator's `agreement_count` ranking handles this naturally — disagreement between Boltz-2 (high `ipsae_min`) and Protenix/AF3 (low `ipsae_min`) flags the same-model bias.

## Outputs the evaluator parses

**Structural outputs:**

- `.cif` structure — native mmCIF with sidechains, target on first declared chain, binder on second
- PAE matrix `.npz` — **native `[binder|target]` chain ordering**, no transposition needed
- pLDDT array — **[0,1] scale**, matches BindMaster convention

**Native metrics in Boltz-2 prediction output:**

- `iptm` — interface predicted TM-score
- `ptm` — overall predicted TM-score
- `plddt_complex` — mean pLDDT over the entire complex
- `plddt_binder` — mean pLDDT over binder chain
- `pae_complex` — mean PAE over the complex
- `pae_binder_target` — mean PAE between binder and target
- `chain_pair_iptm` — pairwise iPTM per chain pair

**Affinity head (when `affinity` step runs):**

- `affinity_pred_value` — regression on log10(IC50 in μM). **For ligand optimization (hit-to-lead, lead-opt).**
- `affinity_probability_binary` — classifier on [0,1]. **For binder/decoy detection (hit discovery).**

**iPSAE outputs (computed by BindMaster evaluator from PAE matrix):**

- `boltz_bt_ipsae` — binder→target directional iPSAE
- `boltz_tb_ipsae` — target→binder directional iPSAE
- `boltz_ipsae_min` — minimum of the two ("weakest link", Overath 2025 finding: single best experimental binding predictor)
- All computed with **uniform 10 Å PAE cutoff** and DunbrackLab 2025 `d0_res` variant

**Column prefixing:** All Boltz-2-derived columns in `summary.csv` are prefixed `boltz_` to distinguish from `protenix_*` and `af3_*` columns in the merged cross-method table.

## Key knobs

| Knob | Typical | Notes |
|---|---|---|
| `boltz predict` input | YAML | One file per target+design, or a directory for batch processing. |
| `--use_msa_server` | on (refolding) | ColabFold MMseqs2 server for MSA. Off → single-sequence prediction (faster, less accurate). |
| Model version | latest by default | `boltz predict` uses the latest checkpoint automatically; pin if you want reproducibility. |
| `recycling_steps` | 3–5 | More recycles → slower, marginally better. 3 is a good balance for design-pool refolding. |
| `diffusion_samples` | 1–25 | Multiple samples → average over diffusion uncertainty. BindMaster default is 1 for refolding. |
| `affinity` step | optional | Activated by BoltzGen's `affinity` pipeline step; also callable directly via the affinity model checkpoint. |
| Write full PAE | enabled | `.npz` output required for evaluator iPSAE computation. |
| GPU | required for production | CPU mode works but is significantly slower per the README. |
| `~/.boltz/` cache | required | Houses checkpoints (`boltz2_conf.ckpt` ~2.3 GB, `boltz2_aff.ckpt` ~2.1 GB) and `mols/` (CCD components, ~45k `.pkl` files). Missing `mols/ALA.pkl` → `ValueError: CCD component ALA not found!`. Bootstrap with `download_boltz2(cache=Path.home()/'.boltz')` (positional Path arg, not str). |

## Sources

- Boltz-2 paper: Passaro, Corso, Wohlwend, Reveiz, Thaler, Somnath, Getz, Portnoi, Roy, Stark, Kwabi-Addo, Beaini, Jaakkola, Barzilay 2025, "Boltz-2: Towards Accurate and Efficient Binding Affinity Prediction," bioRxiv 2025.06.14.659707
- Boltz-1 paper: Wohlwend et al. 2024, "Boltz-1: Democratizing Biomolecular Interaction Modeling," bioRxiv 2024.11.19.624167
- Repo: https://github.com/jwohlwend/boltz
- JAX translation (used by Mosaic): https://github.com/nboyd/joltz
- Slack: https://boltz.bio/join-slack
- iPSAE formula reference: DunbrackLab 2025 `d0_res` variant; CLAUDE.md `Evaluation metrics` section
- License: MIT
