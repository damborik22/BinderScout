# BindMaster Conda Environments

Environments are generated dynamically by the install scripts based on `uname -m`.
Do not create static .yml files with hardcoded CUDA versions.

## bindmaster_pxdesign
| Platform | PyTorch | CUDA | CUTLASS SM |
|----------|---------|------|------------|
| aarch64 (DGX Spark) | 2.5.* | 12.6 | SM100 (Blackwell) |
| x86_64 (workstations) | 2.1.* | 12.1 | SM80;SM86;SM89 |

## Install commands (same on every machine — arch auto-detected)
    bash scripts/install_pxdesign.sh
