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
| binder-eval-af2 env | ~5 GB | ~1.5 GB | ColabDesign + JAX CUDA |
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
| F2 | `--headless` mode for configurator (accept JSON config, skip prompts) | Part F |
| F6 | Multi-chain binder support in BoltzGen YAML generation | Part F |

---

## Proteina-Complexa on aarch64

> **Status:** Planned. x86_64 integration is complete. Porting to the `aarch64` branch
> follows the Mosaic pattern: try building, identify packages without aarch64 wheels,
> patch them out with `platform_machine != 'aarch64'` markers.

### Key facts

- Core deps (PyTorch 2.7, JAX 0.4.29) have aarch64 CUDA wheels
- Likely blockers: `torchtext`, `torch-geometric` (PyG), `esmj`, `atomworks`
- Approach: clone → attempt build → note failures → write patch function → add to `install_aarch.sh`

### Steps

1. Rebase `aarch64` branch from `master`
2. Clone Proteina-Complexa and attempt naive build
3. Identify failing packages from build log
4. Write `_patch_complexa_pyproject()` to exclude unsupported packages
5. Handle PyTorch CUDA (force-reinstall for sm_121 if needed)
6. Add `install_proteina_complexa()` to `install/install_aarch.sh`
7. Verify end-to-end: install → configure → run → evaluate
