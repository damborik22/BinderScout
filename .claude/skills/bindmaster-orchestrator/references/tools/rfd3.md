# RFD3 (RFdiffusion3)

**Engine:** All-atom diffusion. Generates protein structures atom-by-atom (4 backbone + 10 sidechain atoms per residue; smaller sidechains extended with "virtual atoms" on Cβ). Side-chain aware diffusion enables direct conditioning on atomic-level constraints — H-bond donors/acceptors, burial states, ligand contacts, catalytic geometry. Distributed via the `foundry` umbrella CLI (RosettaCommons). Pairs with `proteinmpnn` (or `ligandmpnn`) for sequence design and `rf3` for refolding.
**Role:** design
**Status:** in active integration in BindMaster (replaces deprecated RFAA; configurator does not yet generate RFD3 run scripts — written by hand from `bindmaster_examples/run_rfd3.sh.template`)
**Environment:** conda env `bindmaster_rfd3` (replaces legacy `bindmaster_rfaa`)

## Principle

RFD3 is the third-generation RFdiffusion model. RFD1 (Watson et al. 2023) diffuses backbone coordinates at residue level. RFD2 (2024) conditions residue-level diffusion on a small number of sidechain atoms. RFD3 (Butcher, Krishna et al. 2025) goes fully atomic — every atom in the design (backbone + sidechain) is diffused jointly. The architectural lineage is AF3 → RFD3: the Baker lab inverted AF3's all-atom diffusion-prediction framework into a diffusion-generation framework. They removed AF3's large sequence-processing trunk (unnecessary when the goal is generation, not prediction) and replaced it with a transformer-based U-Net over atomic coordinates.

Because sidechains and backbone are generated together, RFD3 captures the *physical logic of molecular recognition* — not just the topology of a fold but the chemistry of the interface. This is the key differentiator vs. RFD1 (which couldn't condition on atomic detail) and vs. BindCraft/BoltzGen/Mosaic (which design sequences atop pre-existing or hallucinated backbones).

Reported in the paper:
- **Protein binders.** RFD3 outperforms RFD1 (noise scale 0) on 4 of 5 therapeutic targets (PD-L1, IL-2Rα, IL-7Rα, Tie2, InsulinR); produces more diverse solutions.
- **DNA binders.** ~9% success on unseen DNA sequences (RMSD < 5 Å). Wet-lab tested: 1 of 5 designs binds with EC50 = 5.89 ± 2.15 µM.
- **Enzyme design.** Outperforms RFD2 on 90% of atomic motif enzyme benchmark cases. 35 of 190 cysteine hydrolase designs multi-turnover; best kcat/Km = 3557 M⁻¹s⁻¹.
- **Speed.** ~10× faster than RFD2 (batch generation).
- **Symmetry.** Restored from RFD1 (RFD2 had lost it).

The `foundry` CLI handles installation, checkpoint management, and the inference dispatcher. RFD3 itself is invoked via the standalone `rfd3 design` command.

## Strengths

- **Atom-level conditioning.** Specify H-bond donors/acceptors, burial states, catalytic geometry, ligand contacts — RFD3 is the only design tool in the BindMaster stack with native atomic-level constraint conditioning.
- **Backbone diversity.** Diffusion-sampled backbones cluster more diversely than hallucination-based methods (BindCraft, Mosaic). Reported as a strength vs. RFD1 in the paper.
- **Multi-modal native.** Protein, DNA, RNA, small molecule, enzyme catalytic motifs — same model, different inputs.
- **Side-chain aware sequence outputs.** Generated structures carry sidechains, which `proteinmpnn`/`ligandmpnn` then redesign with the atomic context preserved.
- **Symmetry support.** Symmetric oligomer design (restored from RFD1).
- **10× faster than RFD2.** Batch generation makes large-scale runs feasible.
- **Open-source via RosettaCommons foundry.** Active development, Rosetta Commons support channels.
- **Pairs naturally with RF3.** Independent open-source AF3-class predictor for refolding — gives RFD3 designs a clean cross-validation path that doesn't rely on closed-source models.

## Weaknesses

- **No configurator support yet in BindMaster.** Run scripts written by hand. The template at `bindmaster_examples/run_rfd3.sh.template` is the canonical reference.
- **CLAUDE.md runtime gotchas** — each bit during the CALCA run:
  - **Output format is `.cif.gz`** (compressed mmCIF), NOT `.pdb`. Decompress for tools that need PDB.
  - **Chain IDs in output mmCIF:** target = `A` (preserved residues from input contig), binder = `B` (designed). `label_entity_id` shows 0/1, but actual chain IDs at `label_asym_id` are letters.
  - **MPNN CLI is `mpnn`, not `foundry mpnn`.** The `foundry` umbrella CLI only has `install` / `list-available` / `list-installed` / `clean`. Sequence design is its own console-script.
  - **`mpnn` requires `--is_legacy_weights True`** when called directly (legacy `.pt` format ships from `foundry install proteinmpnn`).
  - **`--designed_chains` wants a JSON list of letter strings**, e.g. `'["B"]'` — not bare `B`, not `1`. Bare digits get parsed as int and rejected with `chain-id strings, got <class 'int'>`.
  - **`FOUNDRY_CHECKPOINT_DIRS` is plural-S.** Singular `FOUNDRY_CHECKPOINT_DIR` is silently ignored. Effect: `rfd3 design` aborts with `Invalid checkpoint: rfd3` even when the `.ckpt` is in your weights dir.
  - **ProteinMPNN weights are NOT bundled with rfd3.** `foundry install rfd3` only fetches `rfd3_latest.ckpt` (~2.5 GB). Run `foundry install proteinmpnn` separately for the ~7 MB `proteinmpnn_v_48_020.pt`. (For ligand binders also `foundry install ligandmpnn`.)
  - **Reinit warnings on weight load are benign.** `foundry.utils.weights: Failed to apply policy: 'copy' to 'model.token_initializer.chunked_pairwise_embedder.*': Falling back to policy: 'reinit'` — these come from the chunked low-memory code path that the v0.1.9 checkpoint wasn't trained with. Output structures verify clean.
  - **MPNN best-of-N filter is manual.** `mpnn --number_of_batches 5` writes 5 sequences per backbone in one `.fa` (each header tagged with `sequence_recovery=...`). Post-process: pick highest-recovery sequence per file, strip target prefix (first `len(target_seq)` chars), remainder is the designed binder.
  - **24 GB Ampere OOM is fragmentation, not capacity.** With `diffusion_batch_size=10 low_memory_mode=true`, peak live allocation ~15 GiB but PyTorch reserves another ~6 GiB unallocated. Around batch 7 the next 3 GiB alloc fails. **Fix:** `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before launching `rfd3 design`. The template sets this. (BM4 2VDY: died at batch 7; relaunched with env var, completed all 20 batches cleanly in 23 h.)
  - **`Found N existing example IDs` is informational, not skip-behavior.** RFD3 prints this when example IDs already exist in `out_dir`, but then re-runs all `n_batches` and overwrites. No built-in resume — mid-run crash → full re-run. Workaround: move completed `<id>.cif.gz`/`<id>.json` pairs aside, run with smaller `n_designs`, then put them back.
- **Paper's experimental validation falls short of Baker lab's earlier work.** Per critical reviews: small N (5 DNA binder designs tested), missing controls (no catalytically-dead enzymes, no binding-dead DNA binders, no experimental structures, no specificity controls). Treat in-silico benchmarks with appropriate skepticism for now.
- **All-atom = more compute per design step.** Mitigated by the 10× speedup vs. RFD2 and batch generation, but still heavier than residue-level RFD1.

## Pick when

- Target requires atomic-level conditioning — DNA / RNA / small-molecule binders, enzyme active site scaffolding, H-bond network design, catalytic motif preservation.
- Want backbone diversity — RFD3's diffusion-sampled backbones cluster diversely (paper's headline advantage vs. RFD1).
- Symmetric oligomer design — RFD3 is the only native option in the BindMaster stack.
- You have time/compute for proper sequence design downstream — `mpnn` step is mandatory and best-of-N post-processing is manual.

## Avoid when

- You need a turnkey configurator-managed run today — BindMaster's configurator doesn't generate RFD3 scripts yet; use the template by hand.
- Single-GPU < 24 GB without `expandable_segments` set — guaranteed OOM mid-run on default settings.
- You need experimentally robust provenance — the paper's wet-lab N is small and missing controls. Still useful for in-silico campaigns; treat as exploratory.
- aarch64 — should be fine architecturally (no DGL dependency like RFAA had), but BindMaster integration not yet tested on Blackwell.

## Outputs the evaluator parses

**Design step output** (`rfd3 design out_dir=...`):

- `<example_id>.cif.gz` — compressed mmCIF, target on chain A + binder on chain B
- `<example_id>.json` — per-design metadata (sampler params, contig, recycling info)
- Per-batch logs

**MPNN step output** (`mpnn --pdb_path_multi ...`):

- `<example_id>.fa` — N sequences per backbone with `sequence_recovery=...` headers
- Post-processing required: pick best-of-N, strip target prefix (first `len(target_seq)` chars)

**Native RFD3 metrics:**

- `n_chainbreaks` — structural integrity check
- `n_clashing` — atomic clash count
- `helix_fraction` / `sheet_fraction` / `loop_fraction` — secondary structure composition
- `sequence_recovery` (from MPNN) — fraction of recovered native-like sequence per backbone

**Evaluator step (BindMaster):**

RFD3 + MPNN outputs go through the standard evaluator — decompress `.cif.gz`, Boltz-2 refold with uniform 10 Å iPSAE → `bt_ipsae`, `tb_ipsae`, `ipsae_min`. RFD3's structural integrity metrics (chainbreaks, clashes, helix fraction) and MPNN's sequence-recovery scores are preserved alongside the evaluator's cross-method `ipsae_min` — the evaluator adds method-agnostic comparison across the design pool.

## Key knobs

| Knob | Where | Typical | Notes |
|---|---|---|---|
| Input contig | JSON spec | per target | Defines target chain residues to preserve, designed-region length, hotspots. See `models/rfd3/docs/input.md`. |
| `out_dir` | CLI | per run | Where `.cif.gz` and `.json` land. |
| `n_designs` | JSON spec | 20–400 | Designs per run. |
| `n_batches` / `diffusion_batch_size` | JSON spec | 20 / 10 | Batch granularity; smaller = lower peak memory but more overhead. |
| `low_memory_mode` | JSON spec | `true` (≤24 GB) | Required for Ampere class GPUs. |
| `num_timesteps` | JSON spec | 50 | Diffusion sampler steps. |
| `n_recycle` | JSON spec | 3 | Self-conditioning recycles during sampling. |
| `noise_scale` | JSON spec | 0 (default) or 0.5 | 0 = deterministic mode; >0 adds noise diversity. |
| `skip_existing` | CLI | `true` | Skip files already in `out_dir`. |
| `PYTORCH_CUDA_ALLOC_CONF` | env var | `expandable_segments:True` | **Required** for 24 GB GPUs to avoid mid-run fragmentation OOM. |
| `FOUNDRY_CHECKPOINT_DIRS` | env var | path:path:... | **Plural-S.** Singular is silently ignored. |
| `mpnn` `--number_of_batches` | CLI | 5 | MPNN best-of-N per backbone. |
| `mpnn` `--designed_chains` | CLI | `'["B"]'` | JSON list of letter strings. Bare letters or ints rejected. |
| `mpnn` `--is_legacy_weights` | CLI | `True` | Required for legacy `.pt` weights from `foundry install proteinmpnn`. |
| `mpnn` model weights | install step | `proteinmpnn_v_48_020.pt` | Separate `foundry install proteinmpnn` step. For ligands also `ligandmpnn`. |

## Sources

- Paper: Butcher, Krishna, Mitra et al. 2025, "De novo Design of All-atom Biomolecular Interactions with RFdiffusion3," bioRxiv 2025.09.18.676967
- Companion: Corley et al. 2025, "Accelerating biomolecular modeling with atomworks and rf3"
- Repo: https://github.com/RosettaCommons/foundry (branch `production`, model at `models/rfd3/`)
- Model README: https://github.com/RosettaCommons/foundry/blob/production/models/rfd3/README.md
- Foundry docs: https://rosettacommons.github.io/foundry/
- Blog (release announcement): https://rosettacommons.org/2025/12/22/rfdiffusion3-is-now-available-in-foundry/
- Lineage: RFdiffusion1 (Watson et al. 2023), RFdiffusion2 (2024, enzymes), AF3 (Abramson et al. 2024)
- Pairs with: ProteinMPNN, LigandMPNN, RF3
