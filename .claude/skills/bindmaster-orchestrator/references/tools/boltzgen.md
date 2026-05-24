# BoltzGen

**Engine:** Diffusion-based binder backbone generation (two BoltzGen-1 checkpoints, "diverse" + "adherence", ensembled) → BoltzGen inverse-folding model for sequences → Boltz-2 for refolding/affinity → analysis → diversity-aware filtering. **End-to-end pipeline with built-in Boltz-2 cross-validation refolding.**
**Role:** design (end-to-end pipeline including own refolding)
**Status:** stable (in BindMaster v0.7.0)
**Environment:** conda env `BoltzGen` (Python 3.12); requires ~6 GB Boltz-1 weights, auto-downloaded on first use, resumable

## Principle

BoltzGen is the most integrated pipeline in the BindMaster stack. Unlike Mosaic (gradient hallucination) or BindCraft (AF2 hallucination), BoltzGen samples backbones from a diffusion prior, then designs sequences with its own inverse-folding model, then re-folds with Boltz-2 (target + monomer), then ranks. The pipeline runs seven discrete steps that can be invoked individually with `--steps`:

1. **`design`** — diffusion model generates `num_designs` candidate backbones from a YAML spec
2. **`inverse_folding`** — BoltzGen's inverse-folding model designs sequences for those backbones (typically 1 sequence per backbone, configurable)
3. **`folding`** — Boltz-2 re-folds binder + target complex
4. **`design_folding`** — Boltz-2 re-folds binder alone (monomer foldability check; disabled for peptide/nanobody protocols)
5. **`affinity`** — Boltz-2 affinity predictor (small-molecule targets only)
6. **`analysis`** — compute design-quality metrics (RMSD, PLIP H-bonds, ΔSASA, AA composition)
7. **`filtering`** — diversity-aware ranking down to `budget` final designs

Two design checkpoints are loaded by default (`boltzgen1_diverse` + `boltzgen1_adherence`), each producing half the designs. The diversity-aware filter takes a quality-vs-diversity tradeoff parameter `alpha` (0 = quality-only, 1 = diversity-only). The filter step is decoupled and very fast (~15s) so it can be rerun with different criteria without redesigning.

## Strengths

- **End-to-end.** Backbone → sequence → refold → analyze → filter in one pipeline. Most integrated tool in the BindMaster stack.
- **Built-in Boltz-2 cross-validation refolding.** Akin to BindCraft's AF2-multimer cross-val. Designs that fail refolding are filtered before they leave the pipeline.
- **Diversity-aware final selection.** `alpha` parameter directly tunes quality-vs-diversity in the final budget; no other tool offers this natively.
- **Composition bias filter.** `--filter_biased` caps ALA/GLY/GLU/LEU/VAL composition outliers (default on); prevents pathological homopolymer-like designs.
- **Multi-modal targets.** Six built-in protocols: protein-anything, peptide-anything (cyclic supported), protein-small_molecule (with affinity prediction), antibody-anything (CDR design), nanobody-anything, protein-redesign.
- **Two-checkpoint ensemble.** `boltzgen1_diverse` (broader sampling) + `boltzgen1_adherence` (closer to constraints) — equal split by default, configurable.
- **Fast filtering rerun.** Filter step is decoupled (~15s); ideal for criterion tuning on a generated population.
- **YAML design spec is expressive.** Supports binding-site restriction, structure groups (specified vs. unspecified geometry), redesign regions, secondary-structure preferences, non-designed scaffolding chains, disulfide constraints, peptide stapling via ligand bonds.
- **Resumable.** `--reuse` reuses existing intermediate designs across all pipeline steps.

## Weaknesses

- **Compute heavy.** The recommended scale is 10,000–60,000 intermediate designs. A100-class GPU recommended; first-time design+refold loop is non-trivial wall time per design.
- **Low cross-tool pass rate.** Per BindMaster CLAUDE.md known issues: "In CALCA target testing, only 1/50 BoltzGen designs passed the `ipsae_min > 0.61` threshold. Sequences designed for Boltz-2 often don't cross-validate well." The internal Boltz-2 refold is the same model as the evaluator's default refold, so its quality signal isn't fully independent.
- **Same-model self-judging.** Internal refolding uses Boltz-2; the evaluator's default refolding is also Boltz-2. Adding Protenix and AF3 to the evaluator (Parts J, K) gives BoltzGen the independent cross-checks it currently lacks.
- **AA composition outliers a known issue.** The `--filter_biased` default exists because BoltzGen tends to produce ALA/GLY-heavy designs without the cap.
- **mmCIF residue indexing.** Uses `label_asym_id` (mmCIF canonical), not `auth_asym_id`. Misuse will silently mis-specify binding sites. Always use `boltzgen check` and visualize before running.
- **Designed-residue sidechain coordinates are zero** in `intermediate_designs_inverse_folded/*.cif` (only backbone atoms have real coordinates); use `refold_cif/` outputs for downstream geometry.

## Pick when

- Multi-modal target — peptide / antibody / nanobody / small molecule / DNA — BoltzGen has the most flexible YAML and dedicated protocols.
- Want a diversity-optimized final set (`alpha` tunes this directly; **RFD3** is also diverse but doesn't have native diversity filtering).
- Want a built-in cross-validation refolding step before the evaluator stage.
- Compute is plentiful and you can run 10,000+ intermediate designs.
- Cyclic peptide design, stapled peptides, or disulfide-constrained binders — YAML supports these natively.

## Avoid when

- Compute / time tight — **Mosaic** is cheaper per design, **BindCraft** more tuned per trajectory.
- Need sequences that cross-validate well against *non-Boltz* models — the same-model self-judging issue (see Weaknesses) shows up in the BindMaster pool's `ipsae_min` agreement count.
- Target is protein-protein only and you want a battle-tested default — **BindCraft** is simpler and the iPTM-gameable critique applies less when you re-rank with `ipsae_min` anyway.
- Quick exploratory design with small intermediate counts (<1000) — BoltzGen's diversity selection is calibrated for larger pools.

## Outputs the evaluator parses

**Output directory structure (after `boltzgen run`):**

- `intermediate_designs/` — raw output of design step (backbones only)
- `intermediate_designs_inverse_folded/` — after sequence design
  - `refold_cif/` — Boltz-2 refolded complex structures (primary input for evaluator)
  - `refold_design_cif/` — Boltz-2 refolded binder alone (monomer)
  - `aggregate_metrics_analyze.csv`, `per_target_metrics_analyze.csv`
- `final_ranked_designs/` — diversity-filtered output
  - `intermediate_ranked_<N>_designs/` — top-N quality designs
  - `final_<budget>_designs/` — quality + diversity set
  - `all_designs_metrics.csv` — all designs seen by filtering
  - `final_designs_metrics_<budget>.csv` — final selected set
  - `results_overview.pdf` — diagnostic plots

**Native metrics in the CSVs** (orchestration-relevant subset):

- `refolding_rmsd` — RMSD between BoltzGen design and Boltz-2 refold (lower = better)
- `filter_rmsd_design` — design-monomer RMSD
- `plip_hbonds_refolded` — PLIP-detected H-bonds in refolded complex
- `delta_sasa_refolded` — ΔSASA in refolded complex
- `design_ALA`, `design_GLY`, etc. — per-AA composition fractions
- `largest_hydrophobic_patch` — surface hydrophobicity (omitted for peptide/nanobody protocols)
- Boltz-2 native confidence: `iptm`, `plddt`, `pae_*` (in `[binder|target]` ordering)

**Evaluator step (BindMaster):**

The evaluator re-folds with Boltz-2 using the uniform 10 Å PAE cutoff and DunbrackLab 2025 iPSAE formula, producing `bt_ipsae`, `tb_ipsae`, `ipsae_min` (column prefix `boltz_*` to distinguish from `protenix_*` and `af3_*`). BoltzGen's own metrics and the evaluator's cross-method `ipsae_min` are preserved side by side — the evaluator is an unbiased comparator across tools, not a replacement for BoltzGen's internal ranking.

## Key knobs

| Knob | Typical | Notes |
|---|---|---|
| `--protocol` | `protein-anything` | One of six: protein-anything, peptide-anything, protein-small_molecule, antibody-anything, nanobody-anything, protein-redesign. Determines defaults and which steps run. |
| `--num_designs` | 10,000–60,000 | Number of intermediate designs. README explicitly says <100 is for testing. |
| `--budget` | 5–50 | Final diversity-optimized set size. |
| `--alpha` | 0.001 (protein) / 0.01 (peptide) | Quality-vs-diversity tradeoff: 0 = quality only, 1 = diversity only. |
| `--filter_biased` | `true` | Caps ALA/GLY/GLU/LEU/VAL outliers. Disable only if you've verified composition. |
| `--additional_filters` | per problem | Hard filter expressions like `'design_ALA<0.3' 'filter_rmsd_design<2.5'`. Quote with `'` to escape shell. |
| `--metrics_override` | per problem | Per-metric inverse-importance weights for ranking. Format `metric_name=weight`. `weight=none` drops a metric. |
| `--refolding_rmsd_threshold` | 3.0 | RMSD-based filter threshold (lower = stricter). |
| `--size_buckets` | optional | Cap designs in size ranges: `10-20:5 20-30:10`. |
| `--diffusion_batch_size` | 1 (<100 designs) / 10 (else) | Designs in a batch share length when randomly sampled — keep small if you want length diversity. |
| `--design_checkpoints` | both default | Two-checkpoint ensemble (`diverse` + `adherence`). |
| `--step_scale` | scheduled | Diffusion step scale (fixed override possible, default uses a schedule). |
| `--noise_scale` | scheduled | Diffusion noise scale (similar). |
| `--steps` | all | Run only specified pipeline steps. Use `filtering` alone for fast filter retuning. |
| `--reuse` | off | Resumes interrupted runs without losing progress. |
| `--cache` | `~/.cache` | Where models (~6 GB) are downloaded. Override with `$HF_HOME`. |

## Sources

- Paper: Stark et al. 2025, "BoltzGen: Toward Universal Binder Design," bioRxiv 2025.11.20.689494
- Project hub: https://hannes-stark.com/assets/boltzgen.pdf
- Repo: https://github.com/HannesStark/boltzgen
- Folding dependency: Boltz-2 (https://github.com/jwohlwend/boltz) for refolding and affinity prediction
- License: MIT
