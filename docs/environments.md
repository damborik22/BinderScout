# BinderScout Conda Environments

Environments are generated dynamically by the install scripts based on `uname -m`.
Do not create static .yml files with hardcoded CUDA versions.

The canonical environment table — all eleven, with their Python versions and managers —
lives in **`CLAUDE.md`** ("Environments"). This file covers only the PXDesign env, whose
PyTorch/CUDA pins differ per architecture.

## Install commands

```bash
bindmaster install --tool pxdesign      # or: --tool all
```

This selects the installer for the host architecture automatically
(`install/install.sh` on x86_64, `install/install_aarch.sh` on aarch64) and applies the
required patches and hooks.

> **Do not use `scripts/install_pxdesign.sh`.** That script is a stripped-down manual
> fallback, kept only for hand-driven per-arch debugging, and its own header says so. It
> applies none of the patches or hooks the supported path installs, and its PyTorch/CUDA
> pins (2.1.\*/12.1 on x86_64, 2.5.\*/12.6 on aarch64, plus `CUTLASS_ARCHS`) are its own —
> they do not match either installer.

## bindmaster_pxdesign — what the supported installers pin

| Platform | PyTorch | CUDA wheel index | Source |
|----------|---------|------------------|--------|
| x86_64 (workstations) | 2.6.0 (pinned) | cu124 | `install/install.sh` (`CUDA_VERSION="12.4"`) |
| aarch64 (DGX Spark) | unpinned (latest for the index) | cu130 | `install/install_aarch.sh` (`CUDA_VERSION="13.0"`) |

x86_64 gets its CUDA components at env-creation time from the `nvidia` channel
(`pytorch-cuda=12.4 cuda-nvcc=12.4 cuda-cudart-dev=12.4`); the pinned
`nvidia/label/cuda-12.4.0` channel is used for one optional package only,
`libcusparse-dev` (JIT headers, tolerated on failure). aarch64 has no conda
`pytorch-cuda` package, which is why its torch is installed unpinned from the cu130
index.

Captured pins live in `install/locks/` — **x86_64 only** (`_constraints()` refuses to
apply them on another architecture), and for 10 of the 11 environments:
`binder-eval-af3` has no lock, because its weights are gated and the env was absent on
the capture host. See `install/locks/EVIDENCE.md`.
