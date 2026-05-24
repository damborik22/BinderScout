# BindMaster Conda Environments

Environments are generated dynamically by the install scripts based on `uname -m`.
Do not create static .yml files with hardcoded CUDA versions.

## bindmaster_rfaa
| Platform | PyTorch | CUDA | Notes |
|----------|---------|------|-------|
| aarch64 (DGX Spark) | 2.5.* | 12.6 | Grace Blackwell GB10 |
| x86_64 (workstations) | 2.1.* | 12.1 | RTX 3090, A5000, RTX 3060 |

## bindmaster_pxdesign
| Platform | PyTorch | CUDA | CUTLASS SM |
|----------|---------|------|------------|
| aarch64 (DGX Spark) | 2.5.* | 12.6 | SM100 (Blackwell) |
| x86_64 (workstations) | 2.1.* | 12.1 | SM80;SM86;SM89 |

## Install commands (same on every machine — arch auto-detected)
    bash scripts/install_rfaa.sh
    bash scripts/install_pxdesign.sh
