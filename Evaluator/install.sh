#!/usr/bin/env bash
# BindMaster Evaluator — environment setup
# Run once after cloning the repository:
#   bash install.sh
#
# Creates one conda environment:
#   binder-eval     extract + report  (lightweight, no ML)
#
# For Boltz-2 refolding the Mosaic environment from the BindMaster installer
# is used. Mosaic must be installed first:
#   cd /path/to/BindMaster && bash install/install.sh --tool mosaic
#
# The additional refolding engines (AF3, ESMFold2) are
# installed by the main BindMaster installer's `--tool af3` and `--tool esmfold2`
# flags — not here.
#
# Prerequisites:
#   - conda (miniforge/miniconda)
#   - Mosaic installed via BindMaster installer (provides Boltz-2)
#   - GPU with CUDA drivers (required for refold steps)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Initialise conda — prefer local standalone install, then system locations
_BINDMASTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for _conda_sh in \
    "${_BINDMASTER_DIR}/conda/etc/profile.d/conda.sh" \
    "${HOME}/miniforge3/etc/profile.d/conda.sh" \
    "${HOME}/mambaforge/etc/profile.d/conda.sh" \
    "${HOME}/miniconda3/etc/profile.d/conda.sh" \
    "${HOME}/anaconda3/etc/profile.d/conda.sh" \
    "/opt/conda/etc/profile.d/conda.sh" \
    "/opt/miniforge3/etc/profile.d/conda.sh"; do
    # shellcheck disable=SC1090
    [[ -f "$_conda_sh" ]] && { source "$_conda_sh"; break; }
done

echo "=== BindMaster Evaluator — install ==="
echo "Repo: $REPO_DIR"
echo ""

# ---------------------------------------------------------------------------
# 0. Locate Mosaic venv (created by BindMaster installer)
# ---------------------------------------------------------------------------
echo "[0/2] Locating Mosaic venv (Boltz-2 environment)..."

MOSAIC_VENV=""

if [[ -n "${MOSAIC_DIR:-}" && -f "$MOSAIC_DIR/.venv/bin/python" ]]; then
    MOSAIC_VENV="$MOSAIC_DIR/.venv"
fi

if [[ -z "$MOSAIC_VENV" ]]; then
    for _candidate in \
        "$(dirname "$REPO_DIR")/Mosaic/.venv" \
        "${HOME}/Documents/BindMaster/Mosaic/.venv" \
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
    echo "  created by the BindMaster installer. Please install it first:"
    echo ""
    echo "    cd /path/to/BindMaster"
    echo "    bash install/install.sh --tool mosaic"
    echo ""
    echo "  Then re-run this script, or set MOSAIC_DIR before running:"
    echo "    MOSAIC_DIR=/path/to/BindMaster/Mosaic bash install.sh"
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
echo "[1/2] Creating binder-eval..."
conda env create -f "$REPO_DIR/envs/binder-eval.yml" --yes 2>/dev/null || \
    conda env update -f "$REPO_DIR/envs/binder-eval.yml" --prune
# shellcheck disable=SC1087
conda run -n binder-eval pip install -q -e "$REPO_DIR[report]"
echo "      binder-compare version: $(conda run -n binder-eval binder-compare --version)"

# ---------------------------------------------------------------------------
echo ""
echo "=== Installation complete ==="
echo ""
echo "  Boltz-2 (Mosaic venv): $MOSAIC_VENV"
echo "  Extract/report:        conda env binder-eval"
echo ""
echo "Usage:"
echo "  bash evaluate.sh --sequences seqs.fasta --target-seq SEQ --output ./results"
echo ""
echo "Note: the additional refolding engines are installed via the main"
echo "      BindMaster installer (--tool af3 / --tool esmfold2) and are"
echo "      auto-detected by evaluate.sh when their conda envs exist."
