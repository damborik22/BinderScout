# PXDesign — Worker Operations

**Env:** conda env `bindmaster_pxdesign` (Python 3.11)
**Run-script template:** `bindmaster_examples/run_pxdesign.sh.template`
**Engine reference:** `bindmaster-orchestrator/references/tools/pxdesign.md`

## Source-of-truth files

| File / directory | What it tells you |
|---|---|
| **`<out_dir>/design_outputs/<task_name>/summary.csv`** | Ranked binders with composite score (PXDesign's internal ranking) |
| `<out_dir>/design_outputs/<task_name>/<design_id>/` | Per-design directories with PXDesign-d diffusion output, MPNN sequences, Protenix predictions, AF2-IG complex + monomer |
| sbatch `.out` | First-run includes ~minutes of kernel compilation |
| `<out_dir>/logs/` | Per-stage logs if PXDesign was configured to write them |

## Pre-flight specific to PXDesign

- **Tool weights downloaded:** `download_tool_weights.sh` must have run once. Auto-downloads on first launch otherwise — accept the one-time delay.
- **`PROTENIX_DATA_ROOT_DIR`** set if CCD cache is not in default location (`${project_root}/release_data/ccd_cache`).
- **PyTorch with CUDA** (not the CPU-only torch from `requirements.txt`). If you ran `pip install -r requirements.txt` manually without the installer's followup, you have CPU torch. See `troubleshooting.md` §5.5.
- **Post-install patches applied:** the BindMaster `install/install.sh` patches `protenix` (CUDA arch for Blackwell sm_120), `pxdbench` (`NumpyEncoder` JSON serialization), and `configs_infer.py` (num_workers). These are reapplied on each install but lost on manual `pip install --upgrade`. Verify with `install.sh --pxdesign --check` (if available) or rerun the installer.
- **MSA path** in YAML pre-computed and exists. PXDesign supports per-target MSA in `target.chains.<id>.msa`; pre-compute saves significant per-design time.

## OOM / hardware limits

| GPU class | Behavior |
|---|---|
| 24 GB | OOMs on most non-trivial targets; ship to ≥48 GB |
| 48 GB | Fine for moderate targets |
| 80+ GB | Fine for everything |

Modern GPU (A100/H100/H200) recommended for the bf16 + DeepSpeed Evo Attention kernel optimizations. Older GPUs (V100) need `--dtype fp32 --use_deepspeed_evo_attention False`.

## Common errors

- **CPU-only torch after manual `pip install -r requirements.txt`** → `troubleshooting.md` §5.5. Reinstall torch with CUDA.
- **CUDA arch errors on Blackwell sm_120** → post-install patches reverted. See `troubleshooting.md` §5.6.
- **First-run kernel compilation appears wedged** — typically takes 5-15 minutes. Don't kill in the first hour just because progress looks frozen. Check `~/.cache/torch_extensions/` for compilation artifacts.
- **`NumpyEncoder` JSON serialization error from `pxdbench`** — install patch reverted. Re-run installer.
- **Missing `mol_lib/<CCD>.pkl`** — CCD cache incomplete. Re-run `download_tool_weights.sh`.

## Wedge / kill criteria

- **No progress in `design_outputs/<task_name>/` after kernel compilation completes + 1 h** — wedge.
- **`summary.csv` row count not growing after first-batch hour** — wedge.
- **Wall exceeds 2× initial estimate** — kill.

## Packaging recipe

```bash
cd ~/runs/<TARGET>-<machine>-pxdesign/
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_PXDesign_<machine>.tar.gz \
    design_outputs/<task_name>/ \
    <task_name>.yaml \
    run.sh *.out
```

For `_final`:

```bash
tar czf /muni-disk/<TARGET>/RESULTS/<TARGET>_PXDesign_<machine>_final.tar.gz \
    design_outputs/<task_name>/summary.csv \
    design_outputs/<task_name>/<top-N-design-ids>/ \
    <task_name>.yaml
```

## Reporting back

```markdown
🔄 → ✅ | SLURM <id> done. <N_sample> designs sampled, <accepted> in summary.csv.
Composite score top: <x>; AF2-IG iPTM top: <y>; Protenix iPTM top: <z>.
Wall: <h> on <GPU>. Compute: <GPU-h>.
Packaged: <TARGET>_PXDesign_<machine>.tar.gz (<size>).
```

**Note about cross-validation:** PXDesign uses Protenix internally as its design-time evaluator. The orchestrator's Part J Protenix refolder shares this — for PXDesign outputs, Boltz-2 and AF3 give cleaner independent cross-validation than Protenix refold does. See `bindmaster-orchestrator/references/tools/README.md`.
