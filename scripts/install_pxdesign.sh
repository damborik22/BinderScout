#!/usr/bin/env bash
# scripts/install_pxdesign.sh — MANUAL FALLBACK installer for PXDesign
#
# ┌─ READ THIS FIRST ────────────────────────────────────────────────────────┐
# │ The SUPPORTED way to install PXDesign is:                                │
# │                                                                          │
# │     bindmaster install --tool pxdesign                                   │
# │                                                                          │
# │ (install/install.sh on x86_64, install/install_aarch.sh on aarch64).      │
# │ That is what the docs and skills point at, and it does considerably more  │
# │ than this script: pins the PXDesign commit, installs the Protenix fork +  │
# │ PXDesignBench + ColabDesign + the dm-haiku/JAX CUDA pins, applies all the │
# │ post-install compatibility patches (configs_infer num_workers, pxdbench   │
# │ NumpyEncoder + MPNN error handling, lazy ProtenixFilter, protenix         │
# │ LayerNorm CPU fallback), writes the CPATH/CUTLASS_PATH activate.d hooks   │
# │ and the unversioned .so dev symlinks, and runs the JIT-kernel smoke test. │
# │                                                                          │
# │ THIS script is a stripped-down manual fallback for standing up a bare     │
# │ bindmaster_pxdesign env on a host where the full installer cannot run.    │
# │ It does NOT apply any of the patches or hooks listed above. Its one       │
# │ addition over the canonical path is per-architecture PyTorch/CUDA/CUTLASS │
# │ SM selection (aarch64 Blackwell SM 100 vs x86_64 SM 80;86;89).            │
# └──────────────────────────────────────────────────────────────────────────┘
#
# Usage:
#   bash scripts/install_pxdesign.sh [PXDESIGN_INSTALL_DIR] [--force]
#
# Options:
#   --force   Delete and recreate the conda env if it already exists.
#             WITHOUT this flag an existing env is REUSED, never destroyed —
#             the env also hosts the CPATH/CUTLASS activate.d hooks written by
#             install/install.sh, so blowing it away breaks a working install.
#             Same convention as install/install.sh's confirm_destructive().
#   -h|--help Show this help.
#
# Environment:
#   CUTLASS_PATH        CUTLASS checkout directory   (default: $HOME/cutlass)
#   PXDESIGN_ENV_NAME   conda env name               (default: bindmaster_pxdesign)

set -euo pipefail

# ── Paths (derived from this script's location — never hardcoded) ──────────
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/.." && pwd)

FORCE=false
PXDESIGN_DIR_ARG=""

usage() {
    sed -n '2,38p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --force) FORCE=true ;;
        -h|--help) usage; exit 0 ;;
        --*) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
        *)
            if [ -n "$PXDESIGN_DIR_ARG" ]; then
                echo "Unexpected extra argument: $1" >&2; exit 1
            fi
            PXDESIGN_DIR_ARG="$1"
            ;;
    esac
    shift
done

# ── Architecture detection ─────────────────────────────────────────────────
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"

# EXTRA_CONDA_CHANNELS is pre-existing dead code (the env is built from a YAML
# spec, which carries its own channels) — kept as-is, only silenced.
# shellcheck disable=SC2034
if [ "$ARCH" = "aarch64" ]; then
    PYTORCH_VERSION="2.5.*"
    CUDA_VERSION="12.6"
    PYTORCH_CUDA_PKG="pytorch-cuda=12.6"
    EXTRA_CONDA_CHANNELS="-c nvidia/label/cuda-12.6.0"
    CUTLASS_ARCHS="100"
elif [ "$ARCH" = "x86_64" ]; then
    PYTORCH_VERSION="2.1.*"
    CUDA_VERSION="12.1"
    PYTORCH_CUDA_PKG="pytorch-cuda=12.1"
    EXTRA_CONDA_CHANNELS=""
    CUTLASS_ARCHS="80;86;89"
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi

echo "PyTorch: ${PYTORCH_VERSION}  |  CUDA: ${CUDA_VERSION}  |  CUTLASS SM: ${CUTLASS_ARCHS}"
# ──────────────────────────────────────────────────────────────────────────

# Default install locations match install/install.sh: PXDesign lives inside the
# BindMaster checkout, CUTLASS at $HOME/cutlass (what the activate.d hook reads).
PXDESIGN_DIR="${PXDESIGN_DIR_ARG:-${REPO_ROOT}/PXDesign}"
CUTLASS_DIR="${CUTLASS_PATH:-${HOME}/cutlass}"
ENV_NAME="${PXDESIGN_ENV_NAME:-bindmaster_pxdesign}"

echo "=== BindMaster: Installing PXDesign (manual fallback) ==="
echo "Canonical path: bindmaster install --tool pxdesign"
echo "Install dir:  $PXDESIGN_DIR"
echo "CUTLASS dir:  $CUTLASS_DIR"
echo ""

env_exists() {
    conda env list | awk '{print $1}' | grep -Fxq "$1"
}

# 1. Clone PXDesign repo
if [ ! -d "$PXDESIGN_DIR" ]; then
    echo ">>> Cloning PXDesign..."
    git clone https://github.com/bytedance/PXDesign.git "$PXDESIGN_DIR"
else
    echo ">>> Repo already exists at $PXDESIGN_DIR"
fi
cd "$PXDESIGN_DIR"
git submodule init && git submodule update

# 2. CUTLASS v3.5.1
if [ ! -d "$CUTLASS_DIR" ]; then
    echo ">>> Cloning CUTLASS v3.5.1 (SM arch: ${CUTLASS_ARCHS})..."
    git clone --branch v3.5.1 --depth 1 \
        https://github.com/NVIDIA/cutlass.git "$CUTLASS_DIR"
else
    echo ">>> CUTLASS already at $CUTLASS_DIR"
fi

# 3. Create conda env (reuse an existing one unless --force was passed)
#
# Deleting the env is DESTRUCTIVE: bindmaster_pxdesign carries the CPATH /
# CUTLASS_PATH activate.d hooks and the .so dev symlinks written by
# install/install.sh, plus hours of downloaded wheels. So it is opt-in behind
# --force, mirroring install.sh (confirm_destructive / FORCE).
if env_exists "$ENV_NAME"; then
    if [ "$FORCE" = true ]; then
        echo ">>> Removing existing '${ENV_NAME}' env (--force)"
        conda env remove -n "$ENV_NAME" -y
    else
        echo ">>> Conda environment '${ENV_NAME}' already exists — reusing it."
        echo "    The remaining steps are idempotent; pass --force to rebuild from scratch."
    fi
fi

if ! env_exists "$ENV_NAME"; then
    echo ">>> Creating conda environment: ${ENV_NAME} (arch=${ARCH})"
    ENV_YAML=$(mktemp "${TMPDIR:-/tmp}/bindmaster_pxdesign_env_XXXX.yml")
    cat > "$ENV_YAML" << EOF
name: ${ENV_NAME}
channels:
  - pytorch
  - nvidia
  - conda-forge
  - defaults
dependencies:
  - python=3.10
  - pip
  - pytorch::pytorch=${PYTORCH_VERSION}
  - pytorch::${PYTORCH_CUDA_PKG}
  - conda-forge::cmake>=3.26
  - conda-forge::ninja
  - pip:
    - deepspeed>=0.14
    - pydantic>=2.0
    - pyyaml>=6.0
    - biopython>=1.81
EOF
    conda env create -f "$ENV_YAML"
    rm "$ENV_YAML"
fi

# 4. Install PXDesign in editable mode
echo ">>> Installing PXDesign package..."
conda run -n "$ENV_NAME" \
    bash -c "cd $PXDESIGN_DIR && pip install -e ."

# 5. Download external tool weights
echo ">>> Downloading tool weights and CCD cache..."
conda run -n "$ENV_NAME" \
    bash -c "cd $PXDESIGN_DIR && bash download_tool_weights.sh"

# 6. Set environment variables
if ! grep -q "CUTLASS_PATH" ~/.bashrc 2>/dev/null; then
    echo "" >> ~/.bashrc
    echo "# BindMaster PXDesign / CUTLASS (arch=${ARCH})" >> ~/.bashrc
    echo "export CUTLASS_PATH=$CUTLASS_DIR" >> ~/.bashrc
    echo "export CUTLASS_NVCC_ARCHS=$CUTLASS_ARCHS" >> ~/.bashrc
    echo ">>> Added CUTLASS env vars to ~/.bashrc — run: source ~/.bashrc"
fi

# 7. Smoke test
echo ">>> Running smoke test..."
conda run -n "$ENV_NAME" python -c "
import pxdesign
import torch
import platform
print(f'PXDesign import OK')
print(f'PyTorch {torch.__version__}  |  CUDA {torch.version.cuda}')
print(f'GPU available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
print(f'Arch: {platform.machine()}')
"

echo ""
echo "=== Installation complete! (arch=${ARCH}) ==="
echo ""
echo "Next steps:"
echo "  source ~/.bashrc"
echo "  conda activate ${ENV_NAME}"
echo "  cd ${REPO_ROOT} && bindmaster configure"
echo ""
echo "NOTE: this fallback skips the compatibility patches and activate.d hooks"
echo "      that 'bindmaster install --tool pxdesign' applies. If PXDesign fails"
echo "      at runtime (protenix LayerNorm / DS4Sci EvoformerAttention JIT,"
echo "      pxdbench JSON errors), re-run the canonical installer."
