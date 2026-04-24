# PLAN — AF3 + Protein Hunter + RFD3 refactor (v2, platform-split)

Major architecture shift: evaluation is split by platform. Design happens on x86 (RTX 3090, 24 GB), evaluation happens on DGX Spark (GH200, 128 GB unified). This lets us use AF3 only where it has enough VRAM, and lets the x86 box focus on the design-heavy workload.

## Platform split

| Platform | Design tools | Evaluation engines |
|---|---|---|
| **x86_64** (RTX 3090, 24 GB) | BindCraft, BoltzGen, Mosaic, **RFD3**, PXDesign, Proteina-Complexa, **Protein Hunter** | Boltz-2 + **Protenix** |
| **aarch64 — DGX Spark** (GH200, 128 GB) | Same as above where supported | Boltz-2 + Protenix + **AF3 v3.0.2** |

**Hybrid workflow:** run `bindmaster configure` + `run_all.sh` on x86, `rsync runs/<name>/ spark:~/BindMaster/runs/`, run `bindmaster evaluate runs/<name>` on Spark. No code change needed — just a documented recipe in the README.

---

## Parts (revised)

| Part | Change | Platforms |
|---|---|---|
| **I** | Remove AF2 refolding from Evaluator | both |
| **J** | **Protenix** refolder (replaces AF2's role as 2nd engine on x86) | both |
| **K** | **AF3 v3.0.2** refolder (3rd engine) | aarch64 only |
| **L** | Protein Hunter with **all 6 modalities** | x86 primary, aarch64 best-effort |
| **M** | RFD3 replaces RFAA — **RFAA deleted**, docs keep recipe for manual re-install | both |
| **N** | Distributed workflow docs (design on x86, evaluate on Spark) | both |

---

## Decisions confirmed (from user)

1. **AF3 is aarch64-only.** x86 gets Boltz-2 + Protenix. No AF3 code path for x86.
2. **RFAA deleted** (not deprecated). Installer removes the env + clone. Keep a `docs/rfaa_manual_reinstall.md` stub with the commit SHAs + patch list so the user can hand-reproduce if ever needed.
3. **AF3 native install** on Spark (no Docker).
4. **Protein Hunter — all 6 modalities** (protein, cyclic peptide, ligand via CCD, ligand via SMILES, DNA, RNA).
5. **AF3 weights** — user submits Google Form today, implementation on Spark starts once weights arrive.

---

## Part I — Remove AF2 refolding from Evaluator

**Unchanged from v1 plan.** Strip `binder-eval-af2` env, `refold_af2.py`, `af2_*` schema, AF2 report sections. Keep all three AF2 uses *outside* Evaluator:
- BindCraft design uses ColabDesign/AF2 internally
- PXDesign uses AF2 as an internal eval step
- Proteina-Complexa uses AF2 cross-val optionally

~25 files touched. Full checklist in my earlier audit (see Evaluator removal list in research findings).

**After Part I, `agreement_count` temporarily becomes single-engine (Boltz-2 only).** Parts J and K restore multi-engine counts (and with a platform-aware denominator: 2 on x86, up to 3 on aarch64).

---

## Part J — Protenix as the universal 2nd engine

Why Protenix: ByteDance's open-source AlphaFold3 re-implementation, already installed as part of `bindmaster_pxdesign` conda env at v0.5.0. It runs comfortably on 24 GB (PXDesign uses it for its own eval on the 3090). Same AF3-architecture metrics (pTM, ipTM, PAE, pLDDT), permissive license, commercial use fine.

**Pre-implementation research (half-day):** audit how PXDesign currently invokes Protenix — find the Python entry point, output format, required config shape. The `bindmaster_pxdesign` env already has everything we need; we just need to write a thin refolder wrapper.

**New files:**
- `Evaluator/envs/binder-eval-protenix.yml` — or more likely, reuse `bindmaster_pxdesign` directly (that env already has Protenix + CUDA + deps)
- `Evaluator/scripts/refold_protenix.py` — takes sequences + target, writes CSV with `protenix_*` columns
- `Evaluator/binder_comparison/refolding/protenix_runner.py`
- `Evaluator/binder_comparison/cli/refold_protenix.py` — `binder-compare refold-protenix` subcommand

**Schema additions (mirrors AF3):**
- `protenix_iptm`, `protenix_ptm`, `protenix_ranking_score`
- `protenix_plddt_binder_mean`, `protenix_plddt_binder_min`
- `protenix_pae_bt_mean`, `protenix_pae_tb_mean`, `protenix_pae_bb_mean`
- `protenix_bt_ipsae`, `protenix_tb_ipsae`, `protenix_ipsae_min`

**Orchestration:** `Evaluator/evaluate.sh` Step-2 becomes "Protenix refolding" (replaces old AF2 step). Skippable with `--skip-protenix`.

**Risks:**
- Protenix v0.5.0 is pinned inside PXDesign with 5 post-install patches. As long as we ride PXDesign's patched env, no issues.
- 24 GB VRAM ceiling: for binder-target ≤450 tokens, fine; may need chunking for longer.
- AF3-parent architecture means PAE ordering works the same way as AF3 (token order = input order → target first, binder second).

**Acceptance:** `binder-compare refold-protenix --sequences seqs.fasta --target-seq SEQ -o protenix.csv` produces a CSV with all `protenix_*` columns. `bindmaster evaluate` picks it up and includes Protenix + Boltz-2 in the agreement count.

---

## Part K — AF3 v3.0.2 refolder (aarch64 / DGX Spark only)

**Conditional install path.** `install/install_aarch.sh` gets a new `install_af3()` function. `install/install.sh` (x86) does not offer AF3 at all — no conda env, no CLI subcommand.

**Env:** `binder-eval-af3` on aarch64 (Python 3.12, JAX 0.9.1 with aarch64 CUDA wheels, `dm-haiku==0.0.16`, `tokamax==0.0.11`).

**Weights flow:**
1. User submits Google Form today (https://forms.gle/svvpY4u2jsHEwWYS6)
2. Google replies in 2-3 business days with download link
3. User runs `bindmaster install --tool af3 --af3-weights <path>` on Spark — installer validates + stores path in `~/.bindmaster/af3_weights_path`
4. Evaluate auto-picks up the path, else skips

**New files (aarch64 path):**
- `Evaluator/envs/binder-eval-af3.yml`
- `Evaluator/scripts/refold_af3.py` — batch writer (one JSON per pair) → `run_alphafold.py --input_dir ... --run_data_pipeline=false --force_output_dir`
- `Evaluator/binder_comparison/refolding/af3_runner.py`
- `Evaluator/binder_comparison/cli/refold_af3.py`

**Schema additions (`af3_*`):** symmetric with `protenix_*` above — `af3_iptm`, `af3_ptm`, `af3_ranking_score`, `af3_plddt_binder_mean` (rescaled 0-100 → 0-1), `af3_pae_*`, `af3_ipsae_min`, etc.

**Restored:** `agreement_count` becomes `sum(engines_with_ipsae_min > 0.61)` where engines = `{boltz, protenix, af3}` and the denominator is platform-aware (2 on x86, 3 on Spark with weights present, 2 otherwise).

**Tokamax aarch64 risk:** the only new unknown. JAX 0.9.1 + CUDA 12 has aarch64 wheels confirmed, Blackwell is officially supported in v3.0.2. If tokamax breaks on GH200, fall back to documented `XLA_FLAGS` workaround from the AF3 README.

**Acceptance (on Spark):**
- `bindmaster install --tool af3 --af3-weights /data/af3` completes + smoke tests `run_alphafold.py --help`
- `binder-compare refold-af3 --sequences seqs.fasta --target-seq SEQ --weights-dir /data/af3 -o af3.csv` on a 3-sequence test — all `af3_*` columns populated
- Full evaluate on PDL1 smoke target produces a report with a 3-engine agreement count

---

## Part L — Protein Hunter (all 6 modalities)

Clone `yehlincho/Protein-Hunter@d4bd951` into `BindMaster/Protein-Hunter/`. Conda env `bindmaster_protein_hunter` (Py 3.10), upstream `setup.sh` does conda + pip.

**Weight reuse:**
- Symlink `BindMaster/LigandMPNN/model_params/` → `Protein-Hunter/LigandMPNN/model_params/`
- Boltz-2 cache path = `~/.boltz/` (same dir Mosaic populates — no duplicate download)
- Chai-1 weights download fresh on first use (~5 GB)

**Shortcut:** wrapper script `BindMaster/bin/protein-hunter` activates the env and shells to `python $REPO/boltz_ph/design.py "$@"` (default) or `--chai` flag switches to `chai_ph/design.py`.

**Configurator pages (new):**
- Tool toggle: Protein Hunter yes/no
- Backbone: Boltz-2 (default) / Chai-1
- **Modality (full 6-way choice):**
  - Protein binder
  - Cyclic peptide (`--cyclic`)
  - Small-molecule via CCD (`--ligand_ccd`)
  - Small-molecule via SMILES (`--ligand_smiles`)
  - DNA binder (`--nucleic_seq --nucleic_type dna`)
  - RNA binder (`--nucleic_seq --nucleic_type rna`)
- Target sequence (extracted from PDB/CIF by configurator; multi-chain via `:`)
- Hotspots → `--contact_residues`
- Binder length range (`--min_protein_length`/`--max_protein_length`)
- Design count + cycles, ipTM threshold, %X

**Templates:** one `run_protein_hunter.sh.template` per modality (6 templates, or one with modality switch).

**Evaluator extractor:** `Evaluator/binder_comparison/extractors/protein_hunter.py`
- Default: parse `summary_high_iptm.csv` (high-quality filter)
- `--all-protein-hunter-designs` flag → `summary_all_runs.csv`
- Emit tool-colored entries in report (new color assignment in `_TOOL_COLOURS_NGL`)

**aarch64 best-effort:** pyrosetta has no aarch64 wheel; chai-lab fork untested. Initial aarch64 approach: clone + try install with `install_aarch.sh`, warn if pyrosetta step fails, document as known limitation. If critical, patch to replace pyrosetta with a no-op for analysis steps.

**License gotcha:** upstream root `LICENSE` file is missing despite README claiming MIT. Open an upstream issue/PR to add it before releasing BindMaster with this integration.

**Acceptance:**
- `bindmaster install --tool protein-hunter` succeeds on x86
- Configurator generates 6 different run scripts (one per modality) correctly
- Smoke test: `--num_designs 3 --num_cycles 2` on PDL1 target finishes, writes `summary_high_iptm.csv`
- Evaluator picks up PH outputs and includes them in the report

---

## Part M — RFD3 replaces RFAA (hard delete)

**Delete cleanly:**
- Remove `install_rfaa()` + uninstall branch from both installers
- Remove `rf_diffusion_all_atom/` + `LigandMPNN/` clones on next install (`bindmaster install --uninstall --tool rfaa` still works for existing users)
- Remove configurator's RFAA page
- Remove `Evaluator/binder_comparison/extractors/rfaa.py`
- Remove all RFAA references from `run_all.sh` template generation

**Add `docs/rfaa_manual_reinstall.md`** — pin commit SHAs, patch list (`idealize_backbone.py`, `residue_constants.py np.int → np.int64`), clone + conda env commands. For users who have old `runs/` and want to reproduce without BindMaster orchestration.

**Install RFD3:**
- PyPI install: `pip install "rc-foundry[rfd3]"` (pinned `v0.1.9`)
- Conda env `bindmaster_rfd3` (Py 3.12, PyTorch ≥2.2 + CUDA)
- `foundry install rfd3 --checkpoint-dir BindMaster/weights/foundry` downloads weights
- **aarch64: works!** No DGL dependency, so the Grace-Hopper blocker is gone. Enable in `install_aarch.sh` for the first time.

**Shortcut:** `BindMaster/bin/rfd3` → activates env + shells to `rfd3 "$@"` (Hydra entry point).

**Configurator page (new, replaces old RFAA page):**
- Input PDB/CIF
- Contig string (Hydra `InputSpecification`)
- `select_hotspots` (dict form)
- `ligand` (CCD or SMILES) when ligand binder
- `partial_t` for motif scaffolding
- `n_batches`, `diffusion_batch_size`, `inference_sampler.num_timesteps`

**No post-install patches needed** (AtomWorks replaces openfold structure normalization).

**Evaluator extractor:** new `extractors/rfd3.py`, parse Hydra output structure. LigandMPNN sequence design is optional (RFD3 includes a built-in but the docs recommend MPNN refinement — inherit via `foundry`'s `models/mpnn`).

**Acceptance:**
- `bindmaster install --tool rfd3` on x86 and aarch64 (**first time**)
- `rfd3 design out_dir=/tmp/smoke inputs=examples/smoke_ppi.yaml n_batches=1 diffusion_batch_size=2 inference_sampler.num_timesteps=20` completes in <60 s
- `bindmaster install --uninstall --tool rfaa` removes the legacy env
- Configurator + run script work for both protein binder and ligand binder modalities

---

## Part N — Distributed workflow docs

New section in `README.md` + `docs/distributed_workflow.md`:

```
# Typical workflow (x86 design + Spark evaluate)

# On x86 dev box:
bindmaster configure  # target.pdb, enabled tools, no AF3
bash runs/<name>/run_all.sh
rsync -av runs/<name>/ spark:~/BindMaster/runs/<name>/

# On DGX Spark:
bindmaster evaluate runs/<name>  # Boltz-2 + Protenix + AF3 (3-engine agreement)
rsync -av spark:~/BindMaster/runs/<name>/report/ ./runs/<name>/report/
```

Optional convenience scripts:
- `scripts/push_to_spark.sh <run_name>` — one-line rsync + ssh command
- `scripts/pull_report.sh <run_name>` — reverse

No code change to evaluate itself — it already works wherever the envs are installed.

---

## Implementation order — max parallelism with AF3 weight wait

```
Day 1-2   Part I (AF2 removal)              on master, single PR
Day 2-3   Part J (Protenix refolder)        depends on I
Day 3-5   Part L (Protein Hunter, x86)      independent PR
Day 5-7   Part M (RFD3, delete RFAA)        independent PR — touches both installers
Day 7-8   Part N (workflow docs)            after I, J, L, M land
          ↓ PARALLEL: user submits AF3 Google Form on day 1
          ↓ Google replies days 3-4
Day 8-10  Part K (AF3 on Spark)             depends on weights arrival + J
Day 10-11 End-to-end integration test       on both platforms
Day 11    CHANGELOG → v0.8.0, tag, merge
```

## Branch strategy

- Parent feature branch: `refactor/af3-rfd3-ph`
- Sub-branches for PRs: `part/I-remove-af2`, `part/J-protenix`, `part/K-af3`, `part/L-protein-hunter`, `part/M-rfd3`
- Each sub-PR green CI (ruff + shellcheck + docker smoke) before merging up

## Quick smoke tests per part

| Part | Smoke test |
|---|---|
| I | `bindmaster evaluate runs/smoke_pdl1 --metric ipsae_min --top 5` → Boltz-2-only report, no AF2 cols |
| J | `binder-compare refold-protenix --sequences 3_seqs.fasta --target-seq SEQ -o protenix.csv` — all `protenix_*` cols |
| K | (on Spark, after weights) `binder-compare refold-af3 --sequences 3_seqs.fasta --target-seq SEQ --weights-dir $BINDMASTER_AF3_WEIGHTS -o af3.csv` |
| L | Per modality: `conda run -n bindmaster_protein_hunter python Protein-Hunter/boltz_ph/design.py --num_designs 2 --num_cycles 2 --protein_seqs <PDL1> ...` |
| M | `rfd3 design out_dir=/tmp/rfd3_smoke inputs=examples/smoke_ppi.yaml n_batches=1 diffusion_batch_size=2 inference_sampler.num_timesteps=20` |

## End-to-end integration test (Part N1)

1. On x86: clean install, then `bindmaster configure` with PDL1, enabling BindCraft, BoltzGen, Mosaic, PXDesign, Proteina-Complexa, Protein Hunter (all 6 modalities across 6 runs), RFD3. Skip BindCraft AF2 eval for speed.
2. Run `bash runs/PDL1_all/run_all.sh` — shortened to 3 designs per tool
3. Extract + refold with Boltz-2 + Protenix on x86 → check `agreement_count ∈ {0, 1, 2}`, no `af2_*` columns
4. rsync `runs/PDL1_all/` to Spark
5. On Spark: re-run `bindmaster evaluate runs/PDL1_all` — `agreement_count ∈ {0, 1, 2, 3}`, AF3 columns present
6. Open report HTML, verify all tool colors + AF3 ranking + 3D viewer.

Done when both x86 and Spark reports render and tool list matches enabled set.
