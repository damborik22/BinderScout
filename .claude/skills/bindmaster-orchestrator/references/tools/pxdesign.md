# PXDesign

**Engine:** Diffusion-based de novo binder generator (PXDesign-d) trained on top of the Protenix AF3-class predictor. Paired with Protenix and AF2-IG confidence models for selection. Uses ProteinMPNN for sequence design and AF2 for downstream complex/monomer evaluation. End-to-end pipeline: diffusion → MPNN → AF2 evaluation → ranked summary.
**Role:** design (with own internal evaluation chain)
**Status:** stable (in BindMaster v0.7.0); patches applied automatically on install for CUDA arch compatibility (sm_120), JSON serialization, and dataloader config
**Environment:** conda env `bindmaster_pxdesign` (Python 3.11); requires ~12 GB of model weights (Protenix base + mini + mini_tmpl + PXDesign diffusion + AF2 + MPNN)

## Principle

PXDesign is ByteDance AI4S's binder design suite. The design model (PXDesign-d) is a diffusion generator that uses a Protenix-trained representation as its structural prior. The end-to-end pipeline runs:

1. **Diffusion** — PXDesign-d samples N candidate binder structures conditioned on target structure, hotspots, and binder length.
2. **MPNN** — ProteinMPNN designs sequences for the generated backbones.
3. **Protenix evaluation** — Protenix base / mini / mini_tmpl checkpoints score the designed complexes (the same Protenix used as a refolder in the BindMaster evaluator Part J).
4. **AF2-IG evaluation** — AF2 with initial guess (binder atom positions provided as starting point) does the final confidence prediction on both the complex and the monomer.
5. **Ranking** — composite score from confidence + interface metrics, written to `summary.csv` in `<out_dir>/design_outputs/<task_name>/`.

The headline experimental result: across 7 therapeutic targets, PXDesign delivers 17–82% nanomolar hits on 6 of them. This is one of the highest reported in-vivo success rates in the recent literature.

Two run modes (controlled by `--preset`):
- **`default`** — fast, fewer samples per stage
- **`extended`** — recommended for production; more samples, more thorough filtering

Because PXDesign internally uses Protenix as part of its evaluation chain, and the BindMaster evaluator's Part J Protenix refolder shares the same conda env (`bindmaster_pxdesign`), there's overlap: a PXDesign run produces designs that have already been Protenix-scored before they enter the BindMaster evaluator's cross-method comparison.

## Strengths

- **Strong wet-lab track record.** 17–82% nanomolar hit rate across 6/7 therapeutic targets is among the strongest in the recent binder-design literature.
- **End-to-end with internal AF2-IG evaluation.** Like BindCraft, PXDesign comes with built-in cross-validation — Protenix for design-time evaluation plus AF2-IG (initial-guess mode) for the final complex/monomer scoring.
- **Three-model evaluation ensemble.** Protenix base + mini + mini_tmpl give a confidence ensemble before AF2 runs.
- **Web server available.** ByteDance hosts a free web server (https://protenix-server.com/) running the exact paper pipeline. Often the fastest path to first results without local setup.
- **CCD cache shared with BindMaster.** Override via `PROTENIX_DATA_ROOT_DIR`; reuses Protenix's CCD cache across pipelines.
- **YAML config is simple.** Target file, chain crop, hotspots, MSA path, binder length — five fields for a baseline run.
- **MSA pre-compute recommended.** YAML `msa` field points to a pre-computed MSA directory, avoiding per-run MSA generation.
- **Multi-mode precision.** Modern GPUs (A100/H100): `--dtype bf16 --use_fast_ln True --use_deepspeed_evo_attention True`. Older GPUs (V100): `--dtype fp32 --use_deepspeed_evo_attention False`.

## Weaknesses

- **Heavy install.** Requires a `download_tool_weights.sh` step for external tool weights (AF2, MPNN) plus first-run auto-downloads of Protenix checkpoints. First run involves model loading + kernel compilation (one-time delay).
- **Patches applied at install time.** Per BindMaster CLAUDE.md known issues: "PXDesign site-packages patches: The installer applies post-install patches to `protenix` (CUDA arch), `pxdbench` (NumpyEncoder), and `configs_infer.py` (num_workers). These patches are reapplied on each install but would be lost if packages are upgraded manually."
- **`requirements.txt` pins `torch==2.3.1` (CPU-only).** Per CLAUDE.md: "The installer force-reinstalls PyTorch with CUDA after requirements.txt. Do not run `pip install -r requirements.txt` manually without reinstalling PyTorch afterward."
- **Web server has rate limits.** Free tier; wet-lab campaigns can apply for additional quota (>90% approval rate within a week per the README).
- **Aarch64 needs CUDA-arch patches.** Blackwell sm_120 patches automated; still possible to break with manual env changes.
- **Custom CUDA kernels.** Compilation step adds installation complexity and a kernel cache.
- **Composite scoring is opaque from the orchestrator's view.** PXDesign produces a ranked `summary.csv`, but the composite ranking weights blend Protenix confidence, AF2-IG confidence, and interface metrics in a way that's hard to decompose vs. the evaluator's uniform iPSAE.

## Pick when

- Therapeutic-relevant target where in-vivo hit rate matters more than diversity — PXDesign's track record is the strongest in the design pool.
- Want internal multi-model confidence ensemble before the BindMaster evaluator stage — Protenix base+mini+mini_tmpl plus AF2-IG.
- Pre-computed MSA available — speeds up the pipeline considerably.
- Modern GPU (A100/H100) — full bf16 + DeepSpeed Evo Attention optimization gives best wall time.
- Don't want to maintain a local install — the web server runs the exact paper pipeline.

## Avoid when

- Single-target quick iteration with limited compute — full pipeline is heavier than **Mosaic** or hand-rolled **Protein-Hunter** workflows.
- Backbone diversity is the top priority — **RFD3** or **BoltzGen** sample more diverse backbones.
- You're already running Protenix as a separate refolder in the evaluator — PXDesign's internal Protenix evaluation overlaps with the evaluator's Part J Protenix refolder. Not harmful, but the orchestrator should know they're not fully independent signals.
- Custom CUDA kernel compilation is blocked on your cluster — the web server is the safer path.

## Outputs the evaluator parses

**Output directory** (`<out_dir>/design_outputs/<task_name>/`):

- `summary.csv` — ranked designs with composite score
- Per-design subdirectories with:
  - PXDesign-d diffusion output (backbone CIF/PDB)
  - MPNN-designed sequences
  - Protenix predictions (base / mini / mini_tmpl)
  - AF2-IG complex prediction
  - AF2-IG monomer prediction

**Native metrics:**

- **Protenix confidence:** `pTM`, `iPTM`, `pLDDT`, `PAE` matrix (from base / mini / mini_tmpl — three signals)
- **AF2-IG complex:** `pLDDT`, `pTM`, `iPTM`, `pAE`, `i_pAE`, `Hotspot_RMSD`
- **AF2-IG monomer:** `Binder_pLDDT`, `Binder_pTM`, `Binder_RMSD`
- **MPNN:** `sequence_recovery` per design
- **Composite score:** PXDesign's internal ranking metric (weighted blend, defined in `pxdbench`)

**Evaluator step (BindMaster):**

PXDesign outputs feed the standard evaluator — Boltz-2 refold with uniform 10 Å iPSAE producing `bt_ipsae`, `tb_ipsae`, `ipsae_min`. The evaluator's Part J Protenix refolder is the same model PXDesign uses internally; the orchestrator should weight that overlap when interpreting `agreement_count`. PXDesign's full native metric battery (Protenix ensemble, AF2-IG complex+monomer, MPNN sequence recovery) is preserved in `summary.csv` alongside the evaluator's cross-method `ipsae_min` — the evaluator is an unbiased judge across tools, not a replacement for PXDesign's internal ranking.

## Key knobs

**YAML (`<task_name>.yaml`):**

| Knob | Typical | Notes |
|---|---|---|
| `target.file` | target.cif | Target structure (`.pdb` or `.cif`). |
| `target.chains.<id>.crop` | e.g. `["1-116"]` | Region of target to keep. |
| `target.chains.<id>.hotspots` | e.g. `[40, 99, 107]` | Interface residues — drives diffusion conditioning. |
| `target.chains.<id>.msa` | path to MSA dir | Pre-computed MSA (recommended for speed and quality). |
| `binder_length` | 60–120 | Length of binder to design. |

**CLI (`pxdesign pipeline`):**

| Knob | Typical | Notes |
|---|---|---|
| `--preset` | `default` or `extended` | `extended` for production. Sets sample counts and filter thresholds. |
| `-i` / `-o` | path | Input YAML / output directory. |
| `--N_sample` | 10–100+ | Number of diffusion samples (per preset baseline). |
| `--dtype` | `bf16` (modern GPU) or `fp32` (V100) | Mixed precision. |
| `--use_fast_ln` | `True` (modern) / `False` (V100) | Fast layer norm kernel. |
| `--use_deepspeed_evo_attention` | `True` (modern) / `False` (V100) | DeepSpeed attention kernel. |
| `--load_checkpoint_dir` | `./release_data/checkpoint` (default) | Override checkpoint location. |
| `PROTENIX_DATA_ROOT_DIR` | env var | Override CCD cache location. |

## Sources

- Project page: https://protenix.github.io/pxdesign/
- Technical report: https://github.com/bytedance/PXDesign/blob/main/assets/technical_report.pdf
- Web server: https://protenix-server.com/
- Repo: https://github.com/bytedance/PXDesign
- Foundation model (used internally): Protenix (https://github.com/bytedance/Protenix)
- Wet-lab plan additional quota: https://bytedance.larkoffice.com/share/base/form/shrcnqYD7eNfSg9fy10pv6kxHAg
- Authors: ByteDance AI4S team
- BindMaster install notes: see CLAUDE.md "PXDesign site-packages patches" and "PXDesign requirements.txt" in Known issues
