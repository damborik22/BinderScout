#!/usr/bin/env bash
# BindMaster Evaluator — environment setup
# Run once after cloning the repository:
#   bash install.sh
#
# Creates two conda environments:
#   binder-eval     extract + report  (lightweight, no ML)
#   binder-eval-af2 AF2 refolding     (Python 3.10, ColabDesign)
#
# For Boltz-2 refolding the Mosaic environment from the BindMaster-installator
# is used. Mosaic must be installed first:
#   cd /path/to/BindMaster-installator && bash install.sh --tool mosaic
#
# Prerequisites:
#   - conda (miniforge/miniconda)
#   - Mosaic installed via BindMaster-installator (provides Boltz-2)
#   - GPU with CUDA drivers (required for refold steps)
#   - AF2 weights downloaded to $AF2_DATA_DIR (for refold-af2 only)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Initialise conda in this shell
_CONDA_INIT="${HOME}/miniforge3/etc/profile.d/conda.sh"
for _f in "$_CONDA_INIT" \
           "${HOME}/miniconda3/etc/profile.d/conda.sh" \
           "${HOME}/anaconda3/etc/profile.d/conda.sh"; do
    # shellcheck disable=SC1090
    [[ -f "$_f" ]] && { source "$_f"; break; }
done

echo "=== BindMaster Evaluator — install ==="
echo "Repo: $REPO_DIR"
echo ""

# ---------------------------------------------------------------------------
# 0. Locate Mosaic venv (created by BindMaster-installator)
# ---------------------------------------------------------------------------
echo "[0/3] Locating Mosaic venv (Boltz-2 environment)..."

MOSAIC_VENV=""

# Check a user-supplied path first
if [[ -n "${MOSAIC_DIR:-}" && -f "$MOSAIC_DIR/.venv/bin/python" ]]; then
    MOSAIC_VENV="$MOSAIC_DIR/.venv"
fi

# Auto-detect common locations
if [[ -z "$MOSAIC_VENV" ]]; then
    for _candidate in \
        "$(dirname "$REPO_DIR")/BindMaster-installator/Mosaic/.venv" \
        "${HOME}/Documents/BindMaster/BindMaster-installator/Mosaic/.venv" \
        "${HOME}/BindMaster/Mosaic/.venv"; do
        if [[ -f "$_candidate/bin/python" ]]; then
            MOSAIC_VENV="$_candidate"
            break
        fi
    done
fi

if [[ -z "$MOSAIC_VENV" ]]; then
    echo ""
    echo "  ERROR: Could not find the Mosaic virtual environment."
    echo ""
    echo "  The Boltz-2 refolding step uses the Mosaic environment"
    echo "  created by the BindMaster-installator. Please install it first:"
    echo ""
    echo "    cd /path/to/BindMaster-installator"
    echo "    bash install.sh --tool mosaic"
    echo ""
    echo "  Then re-run this script, or set MOSAIC_DIR before running:"
    echo "    MOSAIC_DIR=/path/to/BindMaster-installator/Mosaic bash install.sh"
    echo ""
    exit 1
fi

echo "      Found Mosaic venv: $MOSAIC_VENV"

# Install binder-compare into the Mosaic venv
echo "      Installing binder-compare into Mosaic venv..."
# shellcheck disable=SC1087
"$MOSAIC_VENV/bin/pip" install -q -e "$REPO_DIR[boltz2]"
echo "      binder-compare version: $("$MOSAIC_VENV/bin/binder-compare" --version)"

# Save the venv path so evaluate.sh can find it
mkdir -p "$REPO_DIR/envs"
echo "$MOSAIC_VENV" > "$REPO_DIR/envs/mosaic_venv_path"
echo "      Saved venv path → $REPO_DIR/envs/mosaic_venv_path"

# ---------------------------------------------------------------------------
# 1. binder-eval  (extract + report)
# ---------------------------------------------------------------------------
echo "[1/3] Creating binder-eval..."
conda env create -f "$REPO_DIR/envs/binder-eval.yml" --yes 2>/dev/null || \
    conda env update -f "$REPO_DIR/envs/binder-eval.yml" --prune
# shellcheck disable=SC1087
conda run -n binder-eval pip install -q -e "$REPO_DIR[report]"
echo "      binder-compare version: $(conda run -n binder-eval binder-compare --version)"

# ---------------------------------------------------------------------------
# 2. binder-eval-af2  (AF2 refolding)
# ---------------------------------------------------------------------------
echo "[2/3] Creating binder-eval-af2..."
conda env create -f "$REPO_DIR/envs/binder-eval-af2.yml" --yes 2>/dev/null || \
    conda env update -f "$REPO_DIR/envs/binder-eval-af2.yml" --prune
# shellcheck disable=SC1087
conda run -n binder-eval-af2 pip install -q colabdesign==1.1.1 -e "$REPO_DIR[af2]"
echo "      binder-compare version: $(conda run -n binder-eval-af2 binder-compare --version)"

# ---------------------------------------------------------------------------
echo ""
echo "=== Installation complete ==="
echo ""
echo "  Boltz-2 (Mosaic venv): $MOSAIC_VENV"
echo "  Extract/report:        conda env binder-eval"
echo "  AF2 refolding:         conda env binder-eval-af2"
echo ""
echo "Usage:"
echo "  bash evaluate.sh --sequences seqs.fasta --target-pdb target.pdb --output ./results"
echo ""
echo "Note: AF2 weights (~4 GB) must be present at \$AF2_DATA_DIR."
echo "      See docs/pipeline_reference.md for the expected path."
