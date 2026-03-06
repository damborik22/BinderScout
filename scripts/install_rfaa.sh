#!/usr/bin/env bash
# scripts/install_rfaa.sh — Install RFDiffusionAA for BindMaster
# Supports: aarch64 (DGX Spark / Grace Blackwell) and x86_64 (workstations)
# Usage: bash scripts/install_rfaa.sh [RFAA_INSTALL_DIR]

set -euo pipefail

# ── Architecture detection ─────────────────────────────────────────────────
ARCH=$(uname -m)
echo "Detected architecture: $ARCH"

if [ "$ARCH" = "aarch64" ]; then
    PYTORCH_VERSION="2.5.*"
    CUDA_VERSION="12.6"
    PYTORCH_CUDA_PKG="pytorch-cuda=12.6"
    EXTRA_CONDA_CHANNELS="-c nvidia/label/cuda-12.6.0"
elif [ "$ARCH" = "x86_64" ]; then
    PYTORCH_VERSION="2.1.*"
    CUDA_VERSION="12.1"
    PYTORCH_CUDA_PKG="pytorch-cuda=12.1"
    EXTRA_CONDA_CHANNELS=""
else
    echo "Unsupported architecture: $ARCH"
    exit 1
fi

echo "PyTorch: ${PYTORCH_VERSION}  |  CUDA: ${CUDA_VERSION}"
# ──────────────────────────────────────────────────────────────────────────

RFAA_DIR="${1:-/home/david/tools/rf_diffusion_all_atom}"
WEIGHTS_URL="http://files.ipd.uw.edu/pub/RF-All-Atom/weights/RFDiffusionAA_paper_weights.pt"
WEIGHTS_DIR="/home/david/bindmaster_weights/rfaa"
ENV_NAME="bindmaster_rfaa"

echo "=== BindMaster: Installing RFDiffusionAA ==="
echo "Install dir: $RFAA_DIR"
echo "Weights dir: $WEIGHTS_DIR"
echo ""

# 1. Clone repo
if [ ! -d "$RFAA_DIR" ]; then
    echo ">>> Cloning rf_diffusion_all_atom..."
    git clone https://github.com/baker-laboratory/rf_diffusion_all_atom.git "$RFAA_DIR"
else
    echo ">>> Repo already exists at $RFAA_DIR"
fi
cd "$RFAA_DIR"
git submodule init && git submodule update

# 2. Generate arch-specific environment YAML and create conda env
echo ">>> Creating conda environment: ${ENV_NAME} (arch=${ARCH})"
ENV_YAML=$(mktemp /tmp/bindmaster_rfaa_env_XXXX.yml)
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
  - conda-forge::numpy>=1.24
  - conda-forge::scipy>=1.10
  - conda-forge::biopython>=1.81
  - pip:
    - hydra-core>=1.3
    - omegaconf>=2.3
    - e3nn>=0.5.1
    - opt-einsum
    - pydantic>=2.0
EOF
conda env create -f "$ENV_YAML" --force
rm "$ENV_YAML"

# 3. Install rf2aa submodule
echo ">>> Installing rf2aa submodule..."
conda run -n "$ENV_NAME" pip install -e "$RFAA_DIR/rf2aa/"

# 4. Download weights
mkdir -p "$WEIGHTS_DIR"
WEIGHTS_FILE="$WEIGHTS_DIR/RFDiffusionAA_paper_weights.pt"
if [ ! -f "$WEIGHTS_FILE" ]; then
    echo ">>> Downloading RFAA weights (~600 MB)..."
    wget -q --show-progress -O "$WEIGHTS_FILE" "$WEIGHTS_URL"
else
    echo ">>> Weights already downloaded: $WEIGHTS_FILE"
fi

# 5. Set environment variables
if ! grep -q "BINDMASTER_RFAA_ROOT" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "# BindMaster RFDiffusionAA (arch=${ARCH})" >> ~/.bashrc
    echo "export BINDMASTER_RFAA_ROOT=$RFAA_DIR" >> ~/.bashrc
    echo "export BINDMASTER_RFAA_WEIGHTS=$WEIGHTS_FILE" >> ~/.bashrc
    echo ">>> Added env vars to ~/.bashrc — run: source ~/.bashrc"
fi

# 6. Smoke test
echo ">>> Running smoke test..."
conda run -n "$ENV_NAME" python -c "
import sys
sys.path.insert(0, '$RFAA_DIR')
import chemical
import kinematics
import torch
print(f'PyTorch {torch.__version__}  |  CUDA {torch.version.cuda}')
print(f'GPU available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
"

echo ""
echo "=== Installation complete! (arch=${ARCH}) ==="
echo ""
echo "Next steps:"
echo "  source ~/.bashrc"
echo "  conda activate ${ENV_NAME}"
echo "  python -m pytest /home/david/BindMaster/tests/tools/rfaa/ -v"
