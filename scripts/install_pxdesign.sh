#!/usr/bin/env bash
# scripts/install_pxdesign.sh — Install PXDesign for BindMaster
# Supports: aarch64 (DGX Spark / Grace Blackwell) and x86_64 (workstations)
# Usage: bash scripts/install_pxdesign.sh [PXDESIGN_INSTALL_DIR]

set -euo pipefail

# ── Architecture detection ─────────────────────────────────────────────────
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"

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

PXDESIGN_DIR="${1:-/home/david/tools/PXDesign}"
CUTLASS_DIR="${CUTLASS_PATH:-/home/david/cutlass}"
ENV_NAME="bindmaster_pxdesign"

echo "=== BindMaster: Installing PXDesign ==="
echo "Install dir:  $PXDESIGN_DIR"
echo "CUTLASS dir:  $CUTLASS_DIR"
echo ""

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

# 3. Generate arch-specific environment YAML and create conda env
echo ">>> Creating conda environment: ${ENV_NAME} (arch=${ARCH})"
ENV_YAML=$(mktemp /tmp/bindmaster_pxdesign_env_XXXX.yml)
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
conda env create -f "$ENV_YAML" --force
rm "$ENV_YAML"

# 4. Install PXDesign in editable mode
echo ">>> Installing PXDesign package..."
conda run -n "$ENV_NAME" \
    bash -c "cd $PXDESIGN_DIR && pip install -e ."

# 5. Download external tool weights
echo ">>> Downloading tool weights and CCD cache..."
conda run -n "$ENV_NAME" \
    bash -c "cd $PXDESIGN_DIR && bash download_tool_weights.sh"

# 6. Set environment variables
if ! grep -q "CUTLASS_PATH" ~/.bashrc; then
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
echo "  python -m pytest /home/david/BindMaster/tests/tools/pxdesign/ -v"
