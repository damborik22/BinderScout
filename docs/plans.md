# BindMaster — Development Plans

This document consolidates all active and future development plans.
Completed plans are archived in [docs/completed_plans.md](completed_plans.md).

---

## Part I: Pre-packed Standalone Distribution (future)

> **Status:** Planned, not started. Depends on Part H (complete).
>
> **Goal:** Ship BindMaster as a single archive that requires zero installation, zero internet,
> and zero system permissions on the target server. Extract, set PATH, run.

### Overview

Use `conda-pack` to create relocatable archives of every conda environment, bundle them
with the Mosaic uv venv, tool source code, and model weights into a single distributable
tar.gz. An `unpack.sh` script on the target machine extracts and patches paths.

```
Build machine (full internet, GPU)         Target server (restricted, air-gapped OK)
─────────────────────────────────          ──────────────────────────────────────────
bindmaster install --tool all              tar xzf bindmaster-standalone-*.tar.gz
bindmaster pack --output FILE              cd BindMaster
                                           bash unpack.sh
   produces:                               export PATH="$(pwd)/bin:$PATH"
   bindmaster-standalone-v0.8.0-           bindmaster configure
     x86_64-cuda124.tar.gz                 bash runs/myrun/run_all.sh
   (~10-20 GB compressed)
```

### Checklist

- [ ] I1. Add `conda-pack` dependency + verify env packing works
- [ ] I2. Create `pack/build_pack.sh` — build relocatable archive on dev machine
- [ ] I3. Create `pack/unpack.sh` — extract + fix paths on target server
- [ ] I4. Create `pack/manifest.py` — version/checksum metadata
- [ ] I5. Add `bindmaster pack` subcommand to CLI
- [ ] I6. Handle Mosaic uv venv relocation (shebang + pyvenv.cfg patching)
- [ ] I7. BoltzGen weights optional inclusion (`--include-boltzgen-weights`)
- [ ] I8. Platform build matrix (x86_64-cuda124, aarch64-cuda130)
- [ ] I9. Documentation: `docs/standalone_pack.md`
- [ ] I10. CI/release: GitHub Actions build + publish to Releases

### Size estimates

| Component | Raw | Compressed | Notes |
|---|---|---|---|
| Miniforge3 base (stripped) | ~500 MB | ~200 MB | Remove pkgs/, docs |
| BindCraft env | ~12 GB | ~4 GB | Includes PyRosetta, JAX, CUDA |
| BindCraft AF2 weights | ~4 GB | ~3.5 GB | 15 x .npz files |
| BoltzGen env | ~8 GB | ~3 GB | PyTorch + CUDA 12.1 |
| BoltzGen weights | ~6 GB | ~5 GB | Exclude by default |
| Mosaic venv | ~6 GB | ~2 GB | JAX + Boltz-2 + CUDA |
| binder-eval env | ~2 GB | ~500 MB | Lightweight |
| binder-eval-af3 / -esmfold2 envs | ~5 GB | ~1.5 GB | The two non-Boltz refold engines |
| **Total (no model weights)** | **~34 GB** | **~11 GB** | |
| **Total (all weights)** | **~44 GB** | **~20 GB** | |

### Risks

| Risk | Mitigation |
|---|---|
| glibc version mismatch | Check in `unpack.sh`, document requirements |
| CUDA driver too old | Check `nvidia-smi` in `unpack.sh`, warn |
| Archive too large for GitHub Releases (2 GB limit) | Split archives or external hosting (Zenodo) |
| Mosaic venv path patching misses files | Delete `__pycache__/`, smoke test in `unpack.sh` |

---

## Deferred Items

| Item | Description | Original part |
|---|---|---|
| F6 | Multi-chain binder support in BoltzGen YAML generation | Part F |

*F2 (`--headless` configurator) shipped 2026-07-26 as `configurator --config <file>` replay —
`write_run_config` / `load_run_config` / `cmd_from_config` / `--run`, with 8 tests.*

---

## Proteina-Complexa on aarch64 (DGX Spark) — NOT VIABLE

> **Status: DEPRECATED 2026-07-29. Do not run production Proteina-Complexa on Spark.**
> This is a throughput verdict, not an install failure — the port works. It reopens only if
> a CUDA-enabled `jaxlib` for aarch64 / sm_121 becomes available (see "What would reopen it").

### What is actually true

Upstream `complexa` (`NVIDIA-Digital-Bio/proteina-complexa` @ `916eaae`) **is installed and
working** on BM5 — uv venv, Python 3.12.12, torch 2.13.0+cu130, GB10 visible at sm_121. It has
produced real two-chain designs on that box (2026-07-13), and re-running the same config
reproduces them byte-identically. The port is **not a different algorithm**: both Spark and the
x86 fleet run one reward model (`af2folding`, `i_pae = -1.0`, every other weight 0.0), and none
of the platform workarounds touches the generation path —

- the hand-written `torch_scatter` shim is never entered (`fold_emb` is absent from
  `ckpts/complexa.ckpt`, so `FoldEmbeddingSeqFeat` is never constructed);
- `tmol` is never constructed under the binder configs — and its CUDA kernels **do** build at
  sm_121 (verified, 22.9 s / 64.1 s);
- `rf3` is installed and working (rc-foundry 0.2.0, 1.9 GB checkpoint) — the older "rf3 deferred"
  note is stale;
- `foldseek` / `mmseqs` really are missing, but they only feed analyze-stage diversity/novelty
  reporting, all try/except-wrapped. Nothing is gated on them.

### Why it is deprecated anyway — the AF2 reward has no GPU on aarch64

There is no CUDA `jaxlib` wheel for aarch64, so `jax.devices()` returns `[CpuDevice(id=0)]` and
the AF2 reward — the *only* reward in the composite — runs on CPU. That is structural, not a
`JAX_PLATFORMS` pin.

The production recipe on Clara is `search.algorithm=mcts, n_simulations=8`, whose reward budget
is fixed by construction: `nsamples x (1 + 8x4)` = **3300 AF2 calls per 100-design replicate**.

| | H200 (Clara) | GB10 (Spark) |
|---|---|---|
| per AF2 call | <= 2.46 s | **~320 s** |
| 100-design replicate (generate) | 2.25 h | **12.2 days** |
| ApoE4 campaign, 5 replicates | 16 h 12 m | ~61 days |
| PC-v3, 50 replicates | ~2 weeks | **~1.7 years** |

Threading does not rescue it: AF2-on-CPU asymptotes at ~4 of 20 cores (latency-bound on many
small ops), and even an impossible perfect 20-core scale-out leaves 122 days for PC-v3. The
`evaluate` stage adds a second CPU wall, since `binder_folding_method: colabdesign` is also JAX.

### Two traps

**Do not "solve" it with `best-of-n`.** best-of-n and single-pass cost ~1 AF2 call per sample
(~18 h per 100 designs, genuinely viable) *precisely because they never consult the reward during
generation* — `best_of_n_search.py` and `single_pass_generation.py` never call
`compute_reward_from_samples`. MCTS was adopted on 2VDY because it beat best-of-n **10x at
iPTM >= 0.85 in a third of the wall clock**. Running best-of-n on Spark is not the same search
made slower; it is the search we already rejected.

**Do not expect identical designs from any two machines, ever.** `generate.py:596` deliberately
enables TF32 (SM-generation-specific kernels), there is no `use_deterministic_algorithms`, no
`cudnn.deterministic` and no `CUBLAS_WORKSPACE_CONFIG` anywhere in the tree, and a 400-step SDE
amplifies the drift. Bit-identity holds only for **same box + same stack + same config**. Even
there, `dataloader.batch_size` alone changes the designs at a fixed seed (verified), so `seed=X`
is not a sufficient provenance record — `gen_njobs`, `search.max_batch_size`, `nres.low/high`,
`best_of_n.replicas` and `filter.filter_samples_limit` all move the output too. The achievable
bar is *same generative distribution*, and by that bar the Spark port is legitimately equivalent.
Under MCTS specifically, CPU-vs-GPU AF2 floats are backpropagated into the node statistics, so
they change the search **trajectory**, not merely the ranking.

### What would reopen it

1. A CUDA-enabled `jaxlib` for aarch64 / sm_121. This is the whole blocker.
2. Or a **GPU-native reward** instead of AF2. `rf3` is already installed on Spark and PC supports
   an rf3 folding reward (commented out at `binder_generate.yaml:194-213`). That is a different
   objective, so designs would differ from Clara's by construction — a new experiment, not parity.

### If someone still packages the install (worth doing on its own merits)

The install is three tracked edits — `pyproject.toml` cu126 -> cu130, the JAX GPU->CPU fallback in
`rewards/alphafold2_reward.py:125-129`, and a target block — plus **one untracked `torch_scatter`
shim living only inside the venv**, invisible to git and destroyed by any `uv sync`. That shim is
the most fragile part of the setup. Also unpatched: `search/sequence_hallucination.py:154` still
hard-codes `jax.devices("gpu")[device_id]` with no fallback — inert today
(`refinement.algorithm: null`) but it will hard-fail on aarch64 the moment refinement is enabled.

**Not to be confused with `jproteina-complexa`** — the escalante-bio JAX reimplementation that
ships inside the Mosaic venv. That one genuinely works on aarch64 and produced the 150-design CBG
run, but it is a different implementation with different weights
(`~/.cache/jproteina_complexa/weights_v2`), not upstream `complexa`.

---

## Part N: Binding ΔG / interface-energy metric — completed

Landed 2026-06-16 **with a negative result**: no in-silico metric ranks affinity *among*
binders. The plan that stood here is superseded; the outcome and the shipped
gate-then-density form are archived in
[docs/completed_plans.md](completed_plans.md).
