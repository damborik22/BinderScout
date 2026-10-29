# Worker Troubleshooting

Common problems that have bitten the campaign and how to resolve them. Organized by symptom.

---

## 1. Env activation fails with `unbound variable: NVCC_PREPEND_FLAGS`

**Cause:** the conda env uses cuda-nvcc activate.d hooks that reference unset env vars. Strict mode (`set -u`) trips on the unset variable.

**Fix:** wrap `conda activate` with `set +u` / `set -u`:

```bash
set +u
conda activate <env_name>
set -u
```

The canonical run-script templates at `bindmaster_examples/run_*.sh.template` already do this. If you're hitting this, you're hand-writing a run script — don't. Use the template.

---

## 2. PyRosetta `DAlphaBall.gcc` fails with missing libgfortran

**Symptom (BindCraft):** in the inner log `<run>/bindcraft/outputs/*.log`:

```
DAlphaBall.gcc: error while loading shared libraries:
libgfortran.so.5: cannot open shared object file: No such file or directory
```

Or sometimes propagated as a generic `subprocess returned non-zero exit status 127`.

**Cause:** PyRosetta's `DAlphaBall.gcc` subprocess strips inherited env vars under SLURM. Even if `LD_LIBRARY_PATH` is set in your shell, the subprocess doesn't see it.

**Fix:** set `LD_LIBRARY_PATH` AND `LD_PRELOAD` **inline on the python command** with absolute paths:

```bash
LD_LIBRARY_PATH=/path/to/libgfortran/dir:$LD_LIBRARY_PATH \
LD_PRELOAD=/path/to/libgfortran.so.5 \
python -u ./bindcraft.py --settings ...
```

The exact path varies per machine — find it with:

```bash
find / -name "libgfortran.so.5" 2>/dev/null
# Typical: /opt/conda/envs/<env>/lib/libgfortran.so.5
# or:      /usr/lib/x86_64-linux-gnu/libgfortran.so.5
```

Nothing shipped sets these for BindCraft: `bindmaster_examples/` has no BindCraft template, and the configurator's generated `run_bindcraft.sh` launches `python -u ./bindcraft.py` with no `LD_LIBRARY_PATH` or `LD_PRELOAD`. Add both to that line yourself.

---

## 3. Slurm `.err` shows generic error but no traceback

**Symptom:** `<run>/slurm-<jobid>.err` contains something like:

```
Traceback (most recent call last):
  File "<wrapper>", line X, in <module>
    main()
RuntimeError: Job failed
```

But not the *actual* exception that caused it.

**Cause:** Slurm `.err` only captures wrapper-level exceptions. Real Python tracebacks live in the tool's inner log.

**Fix:** check the right log for your tool:

| Tool | Where the real traceback lives |
|---|---|
| **BindCraft** | `<run>/bindcraft/outputs/*.log` (inner) — usually the most recent timestamp |
| **BindCraft (outer wrapper)** | `<run>/bindcraft.log` |
| **BoltzGen** | `<run>/log.txt` or sbatch `.out` |
| **Mosaic** | stdout in sbatch `.out` (Mosaic doesn't have a separate log file) |
| **Protein-Hunter** | stdout/stderr only (sbatch `.out`/`.err`, or `run.log` in driven mode) — Protein-Hunter writes no log file |
| **PXDesign** | sbatch `.out` for runtime and for the Protenix `layer_norm` kernel's compile log (that kernel builds in the `bindmaster_pxdesign` env's `site-packages/protenix/model/layer_norm/`); the DeepSpeed EvoformerAttention kernel, used only with `--use_deepspeed_evo_attention True`, builds silently in `~/.cache/torch_extensions/` and its compiler output appears only in the failure traceback |
| **Proteina-Complexa** | `$PC/logs/design_pipeline_*/<stage>.log` for `generate`, `filter`, `evaluate`, `analyze` (read the stage that failed; `generate` with `gen_njobs` > 1 and `evaluate` with `eval_njobs` > 1 write `<stage>_job<N>.log` instead) |
| **RFD3** | `<run>/foundry.log` + sbatch `.out` |

If the inner log is empty or only contains warnings, the failure is likely a startup issue (env activation, GPU not detected, cache missing) — check `nvidia-smi`, env activation, and the tool-specific cache verification in `pre-flight.md` §7.

---

## 4. GPU OOM (out of memory)

**Symptom:** `CUDA out of memory. Tried to allocate X GiB. GPU 0 has a total capacity of Y GiB...` or `cudaErrorMemoryAllocation`.

**Diagnosis:**

```bash
nvidia-smi
# Note: total memory, what's currently allocated, by what process
```

**Common patterns:**

### 4.1 Wrong GPU class for the tool + target combination

| Combination | Hard floor |
|---|---|
| BindCraft, binder length ≥130 aa, hotspots ON | 48+ GB |
| BindCraft, binder length ≥145 aa, any | 48+ GB |
| BindCraft on H200/GH200 | up to 200 aa fine |
| PXDesign on 24 GB target ≥300 aa | won't fit, ship to ≥48 GB |
| Mosaic on 24 GB target ≥300 aa | won't fit, ship to ≥48 GB |
| Protein-Hunter on 24 GB target ≥300 aa | won't fit, ship to ≥48 GB |
| Proteina-Complexa on 24 GB target ≥300 aa | won't fit, ship to ≥48 GB (smaller targets run on one 24 GB card: BindMaster launches `search_binder_local_pipeline.yaml`, `gen_njobs: 1`) |

The orchestrator's assignment should match a feasible combination, but if you're hitting OOM on the *first batch*, the assumption was wrong. Report it.

### 4.2 Mid-run OOM on Ampere class (RFD3 specifically)

**Symptom:** RFD3 runs fine for batches 1-6, then OOMs on batch 7 around the 75% memory mark. Peak live allocation is only ~15 GiB but the failure happens with ~6 GiB unallocated-but-reserved.

**Cause:** PyTorch memory fragmentation. The default allocator can't coalesce the unallocated reserved chunks for the next 3 GiB allocation.

**Fix:** set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before launching:

```bash
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
rfd3 design out_dir=... inputs=...
```

The `bindmaster_examples/run_rfd3.sh.template` sets this. If you hand-rolled a script, add it.

Recovery: after the OOM, `out_dir/` will have N partial outputs. RFD3 doesn't resume (`Found N existing example IDs` is informational, not skip-behavior — it re-runs everything). Workaround: move completed `<id>.cif.gz`/`<id>.json` pairs aside, run with smaller `n_designs`, then put them back.

### 4.3 JAX preallocation hogging memory

**Symptom (BindCraft, Mosaic, anything JAX):** JAX preallocates 75% of GPU memory by default (`XLA_PYTHON_CLIENT_MEM_FRACTION`). Other processes can't use the GPU. Sometimes OOM even though "your process" is the only one.

**Fix (discrete card, e.g. the x86 fleet):**

```bash
export XLA_PYTHON_CLIENT_PREALLOCATE=false
# or shrink the pool below the 0.75 default (setting 0.75 itself changes nothing):
export XLA_PYTHON_CLIENT_MEM_FRACTION=0.5
```

The generated x86 `run_bindcraft.sh` sets neither, so these take effect there as written. Mosaic and the Boltz-2 / AF3 refolders set their own memory policy (`Evaluator/binder_comparison/refolding/memory_policy.py`; AF3 in `Evaluator/scripts/refold_af3.py`) and force `PREALLOCATE=true`, so an exported `PREALLOCATE=false` is silently overwritten there. Change their fraction instead: `MOSAIC_XLA_MEM_FRACTION` / `BOLTZ2_XLA_MEM_FRACTION` / `AF3_XLA_MEM_FRACTION` (a plain `XLA_PYTHON_CLIENT_MEM_FRACTION` also works).

**On Spark (GB10) do not use `PREALLOCATE=false` outside the CUDA MPS cap (`tools/gpu_mem_guard.sh`):** the GPU pool *is* the 121.7 GiB of system RAM, JAX's default 0.75 already reserves ~91 GiB of it, and `PREALLOCATE=false` with no ceiling grows into the shared pool with no fail-fast (the slow-starve path). Cap the fraction instead, as the generated `run_bindcraft.sh` does on aarch64 (`BINDCRAFT_GPU_GIB`, default 24) and the engines above do.

### 4.4 JAX RSS leak (BindCraft long runs)

**Symptom (BindCraft):** process RSS grows monotonically over days. The 2VDY campaign's <node3> hit 58 GB RSS after 9 days; killed by the kernel.

**Detection:** monitor RSS periodically:

```bash
ps aux | grep bindcraft | awk '{print $6/1024/1024 " GB"}'
```

**Mitigation:** kill criterion in your assignment should be `process RSS > 50 GB`. Document the kill in PROGRESS.md, restart from where you left off: relaunch with the same `design_path`. BindCraft resumes by counting the `*.pdb` files directly in `Accepted/` and `Trajectory/Relaxed/` and appending to the existing `*_stats.csv` files; `Accepted/Ranked/` is wiped and rebuilt only when the target number of designs is reached.

---

## 5. Tool-specific cache failures

### 5.1 Boltz-2: `ValueError: CCD component ALA not found!`

**Cause:** `~/.boltz/mols/ALA.pkl` is missing. Either the cache wasn't downloaded, or it was downloaded with a buggy version.

**Fix:**

```bash
python -c "from boltz.main import download_boltz2; from pathlib import Path; download_boltz2(cache=Path.home()/'.boltz')"
```

Note: positional `Path` argument. Passing a `str` silently no-ops on some versions of `boltz`. Verify:

```bash
ls ~/.boltz/mols/ALA.pkl
ls ~/.boltz/mols/ | wc -l        # should be ~45000+
```

### 5.2 Protein-Hunter: invalid `--msa_mode single_sequence`

**Cause:** the valid values are `single` or `mmseqs`. `single_sequence` is a common typo that raises `argparse: invalid choice`.

**Fix:** use the right flag:

```bash
# For no-MSA / de novo / unknown targets
--msa_mode single

# For known targets in databases (recommended — see learnings.md §1)
--msa_mode mmseqs
```

### 5.3 RFD3: `Invalid checkpoint: rfd3`

**Cause:** environment variable is `FOUNDRY_CHECKPOINT_DIRS` (plural-S). Singular `FOUNDRY_CHECKPOINT_DIR` is silently ignored.

**Fix:**

```bash
export FOUNDRY_CHECKPOINT_DIRS=/path/to/your/checkpoints
# (colon-separated for multiple paths)
foundry install rfd3 --checkpoint-dir /path/to/your/checkpoints
```

Verify:

```bash
foundry list-installed
```

### 5.4 RFD3 + MPNN: `chain-id strings, got <class 'int'>`

**Cause:** `--designed_chains` was passed as `B` (bare letter, parsed as something other than JSON) or `1` (parsed as int).

**Fix:** pass as a JSON list of letter strings:

```bash
mpnn --designed_chains '["B"]' --is_legacy_weights True ...
```

Single-quote to escape the shell. The `--is_legacy_weights True` is also required for the `.pt`-format weights from `foundry install proteinmpnn`.

### 5.5 PXDesign: torch CPU-only after manual `pip install -r requirements.txt`

**Cause:** PXDesign's `requirements.txt` pins `torch==2.3.1` (CPU-only). The installer (`install.sh`) force-reinstalls PyTorch with CUDA *after* `requirements.txt`. If you ran `pip install -r requirements.txt` manually without the followup, you'll have CPU-only torch.

**Fix:** reinstall CUDA torch into the activated `bindmaster_pxdesign` env yourself. Re-running the x86 installer does not currently do it: in its "Reinstalling PyTorch with CUDA" step (`install_pxdesign()` in `install/install.sh`) two comment lines sit inside a `\` continuation, so the `mamba run -n bindmaster_pxdesign` (or `conda run`) call is handed no command and the step fails, and the `pip install` after it runs in the installer's own shell, never in this env.

```bash
pip uninstall torch -y
pip install "torch==2.6.0" --index-url https://download.pytorch.org/whl/cu124
```

`2.6.0` is the pin in `install/locks/bindmaster_pxdesign.txt`; `cu124` is the x86 installer's default CUDA (`CUDA_VERSION` in `install/install.sh`, overridden by `--cuda`). On aarch64 the pin is `TORCH_PXDESIGN` on the cu130 index in `install/install_aarch.sh`.

### 5.6 PXDesign / Protenix: post-install patches reverted

**Cause:** the installers patch after installing. `install/install.sh` (x86) patches `protenix` (`layer_norm.py` CUDA-JIT fallback), `pxdbench` (`NumpyEncoder` JSON serialization, MPNN error JSON, lazy `ProtenixFilter` import) and `configs_infer.py` (num_workers); `install/install_aarch.sh` patches `protenix` (`torch_ext_compile.py`: CUDA arch sm_120 and `-std=c++20`), `pxdbench` (`NumpyEncoder`, MPNN error JSON, AF2 eval `use_bfloat16=False`) and `configs_infer.py`. These are reapplied on each install but lost if you `pip install --upgrade` manually.

**Fix:** rerun `bindmaster install --tool pxdesign` to reapply the patches. There is no `--pxdesign` flag; the installer selects tools with `--tool <name>`. The re-run reuses the existing `bindmaster_pxdesign` env rather than aborting, but it re-executes every later step (pip installs, patches, weights script, JIT smoke test: idempotent but network-bound), not just the patches. It also clears `.install_state/pxdesign` first and rewrites it only if the run completes, so on a box with other installed tools a re-run that dies partway leaves the configurator treating PXDesign as not installed until a later run completes. On x86 the `Reinstalling PyTorch with CUDA` step in `install/install.sh` is broken: `conda run -n bindmaster_pxdesign` gets no command and logs as a failed step (the run carries on), and the `pip install torch==2.6.0 --force-reinstall` runs in your calling shell instead. Do not launch the re-run from a shell with another conda env active (`base` included), or that env's torch stack is force-reinstalled.

### 5.7 Protein-Hunter: `pyrosetta-installer` rename

**Cause:** no release of `pyrosetta-installer` (0.0.1 through 0.1.2, the latest as of 2026-10) has ever had `download_pyrosetta`; the entry point is `install_pyrosetta`. Install scripts that call `download_pyrosetta` fail with `ImportError: cannot import name 'download_pyrosetta'`.

**Fix:** BindMaster's `install/install.sh` already calls `install_pyrosetta`. Fresh manual envs need to call `install_pyrosetta` (not `download_pyrosetta`).

---

## 6. Output verification fails

### 6.1 BindCraft: `Accepted/` shows 4 empty subdirs but you expected designs

**Cause:** `Accepted/` always has 4 placeholder subdirs (`Ranked/`, `Animation/`, `Plots/`, `Pickle/`) even with zero accepts. `ls Accepted/` is not a valid completion signal.

**Fix:** check the actual source-of-truth:

```bash
wc -l final_design_stats.csv        # row count = accepts + header
head -1 final_design_stats.csv      # confirm it's the header row
```

If `final_design_stats.csv` is just the header (0 accepts), the run produced nothing usable — report as a failure with the configuration that didn't work.

### 6.2 Protein-Hunter: `summary_high_iptm.csv` has more rows than `--num_designs`

**Cause:** Each cycle that crosses `--high_iptm_threshold` gets a row, so a 7-cycle run with several passing cycles produces more rows than designs. Expected behavior.

**Fix:** none needed. The orchestrator's evaluator de-dupes per design. Report row count and design count separately:

```
PH: 50 num_designs, 7 cycles each, 133 cycle-passes in summary_high_iptm.csv.
```

### 6.3 Protein-Hunter: "No structure was generated for run N"

**Cause:** None of the N cycles produced a sequence under the `--percent_X` alanine cap. Not a failure — it's the alanine-bias filter doing its job.

**Fix:** none needed. The final-run row may be absent from `summary_all_runs.csv`; that's normal.

### 6.4 Mosaic: `designs.csv` mixes 11-col and 13-col rows

**Cause:** Multiple workers wrote concurrently with different schema versions. Documented in `Evaluator/docs/pipeline_reference.md`.

**Fix:** don't try to fix the CSV yourself. The orchestrator's evaluator auto-detects column count per row. Pass it through as-is.

### 6.5 RFD3: `Found N existing example IDs` prints but it still re-runs everything

**Cause:** The `skip_existing` flag in `rfd3 design` doesn't actually skip — it prints the count, then re-runs all `n_batches` and overwrites. No built-in resume.

**Fix:** if mid-run crash, move completed `<id>.cif.gz`/`<id>.json` pairs aside, run with smaller `n_designs`, then put them back. Or accept the cost of re-running.

---

## 7. Reinit warnings on RFD3 weight load

**Symptom:** when starting `rfd3 design`, you see warnings like:

```
foundry.utils.weights: Failed to apply policy: 'copy' to
'model.token_initializer.chunked_pairwise_embedder.*':
Falling back to policy: 'reinit'
```

**Cause:** the v0.1.9 RFD3 checkpoint wasn't trained with the chunked low-memory code path. These warnings come from the code path trying to load weights that don't exist in the checkpoint.

**Fix:** none. These warnings are benign. Output structures verify clean. Don't waste time chasing these.

---

## 8. Per-machine known issues

### HPC cluster

- VPN-only access to the shared archive (need storage VPN). VPN switches require announcement in PROGRESS.md.
- L40S nodes have 48 GB — fine for most tools at moderate target sizes. H200 nodes are the 141 GB option.
- SLURM partition: confirm in the assignment.

### <node2> / <node3>

- Local lab workstations, direct the shared archive mount usually. No VPN dance.
- 24 GB GPUs (3090-class) — has the BindCraft length ceilings documented above.
- <node3>'s 2VDY BindCraft RSS leak was the kernel killing the process at ~58 GB.

### Spark (DGX Spark)

- aarch64 — only some tools ported. Don't accept Proteina-Complexa assignments here: it is deprecated on aarch64 as a throughput verdict, not an install failure (the production MCTS recipe projects to ~12 days per 100-design replicate vs ~2.25 h on one H200), and `install_aarch.sh --tool proteina-complexa` exits with that explanation. Run it on x86, and do not switch it to `best-of-n` to compensate.
- Hosts the AF3 v3.0.2 refolder (`binder-eval-af3` env), the Boltz-2 refolder (`Mosaic/.venv`), and the ESMFold2 refolder (`binder-eval-esmfold2`) for the orchestrator's local cross-engine refold. If Spark is also doing worker duty, be careful not to clash refolder runs with worker design runs on the same GPU.
- VPN routing: Spark may route to the HPC cluster via a "VPN-on-Spark" mode if configured — that's primarily for orchestrator-driven remote sessions, not worker-side runs.

---

## When you've exhausted this file

If the symptom doesn't match anything here:

1. Check the inner log per §3.
2. Check `tools/<tool>.md` for tool-specific quirks.
3. Check `bindmaster-orchestrator/references/learnings.md` §6 and §7 for env trap and log-location lessons.
4. Check the BindMaster repo's `CLAUDE.md` `Known issues` section.
5. If still stuck, append a TODO entry to PROGRESS.md Worker updates with full symptom + tried-fixes, and ask the orchestrator/user.
