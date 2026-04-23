#!/usr/bin/env bash
# BindMaster Evaluator — run a full evaluation
#
# Usage:
#   bash evaluate.sh --sequences sequences.fasta \
#                    --target-seq "MGFQKFSPF..." \
#                    --output ./results
#
# Required:
#   --sequences    path to FASTA (or CSV / one-per-line) with binder sequences
#   --target-seq   full target amino acid sequence (for Boltz-2 complex assembly)
#   --output       output directory
#
# Optional:
#   --skip-boltz2  skip Boltz-2 refolding (use existing boltz2_results.csv in output dir)
#   --resume       resume interrupted run — skip already-completed binders
#
# Future refolding engines (Protenix on x86, AlphaFold 3 on aarch64 / DGX Spark)
# will add optional steps between Boltz-2 and the report stage.

set -euo pipefail

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
    # shellcheck source=/dev/null
    [[ -f "$_conda_sh" ]] && { source "$_conda_sh"; break; }
done

# aarch64/Blackwell: set env vars for JAX and PyTorch CUDA compilation
if [[ "$(uname -m)" == "aarch64" ]]; then
    export JAX_PLATFORMS=cpu
    export TORCH_CUDA_ARCH_LIST="12.0"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- locate Mosaic venv (written by install.sh) ----------------------------
MOSAIC_VENV_FILE="$SCRIPT_DIR/envs/mosaic_venv_path"
if [[ -f "$MOSAIC_VENV_FILE" ]]; then
    MOSAIC_VENV="$(cat "$MOSAIC_VENV_FILE")"
else
    echo "Error: Mosaic venv path not found. Run bash install.sh first." >&2
    exit 1
fi
[[ -f "$MOSAIC_VENV/bin/binder-compare" ]] || {
    echo "Error: binder-compare not found in $MOSAIC_VENV. Run bash install.sh again." >&2
    exit 1
}

SEQUENCES=""
TARGET_SEQ=""
OUTPUT=""
SKIP_BOLTZ2=0
RESUME=0

# --- parse arguments -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sequences)   SEQUENCES="$2";   shift 2 ;;
        --target-seq)  TARGET_SEQ="$2";  shift 2 ;;
        --output|-o)   OUTPUT="$2";      shift 2 ;;
        --skip-boltz2) SKIP_BOLTZ2=1;    shift ;;
        --resume)      RESUME=1;         shift ;;
        -h|--help)
            sed -n '2,20p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# --- validate ---------------------------------------------------------------
[[ -z "$SEQUENCES" ]]  && { echo "Error: --sequences required"; exit 1; }
[[ -z "$TARGET_SEQ" ]] && { echo "Error: --target-seq required"; exit 1; }
[[ -z "$OUTPUT" ]]     && { echo "Error: --output required"; exit 1; }
[[ -f "$SEQUENCES" ]]  || { echo "Error: sequences file not found: $SEQUENCES"; exit 1; }

mkdir -p "$OUTPUT"
SEQUENCES="$(realpath "$SEQUENCES")"
OUTPUT="$(realpath "$OUTPUT")"

echo "=== BindMaster Evaluator ==="
echo "Sequences : $SEQUENCES"
echo "Output    : $OUTPUT"
echo ""

# --- Step 0: Normalise sequences to FASTA ----------------------------------
FASTA="$OUTPUT/sequences.fasta"
echo "[step 0] Parsing sequences → $FASTA"
conda run -n binder-eval binder-compare parse-seqs \
    --input  "$SEQUENCES" \
    --output "$FASTA"
SEQUENCES="$FASTA"

# --- Step 1: Boltz-2 refolding ---------------------------------------------
BOLTZ2_CSV="$OUTPUT/boltz2_results.csv"

if [[ $SKIP_BOLTZ2 -eq 1 ]]; then
    echo "[step 1/2] Boltz-2 refolding — skipped (using existing $BOLTZ2_CSV)"
    [[ -f "$BOLTZ2_CSV" ]] || { echo "Error: $BOLTZ2_CSV not found"; exit 1; }
else
    echo "[step 1/2] Boltz-2 refolding  (Mosaic venv)..."
    BOLTZ2_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && BOLTZ2_RESUME_FLAG="--resume"
    "$MOSAIC_VENV/bin/binder-compare" refold-boltz2 \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$BOLTZ2_CSV" \
        $BOLTZ2_RESUME_FLAG
fi

# --- Step 2: Report --------------------------------------------------------
echo "[step 2/2] Generating report   (binder-eval)..."
conda run -n binder-eval binder-compare report \
    --boltz2-results "$BOLTZ2_CSV" \
    --sequences      "$SEQUENCES" \
    -o               "$OUTPUT/report"

echo ""
echo "=== Done ==="
echo "Report : $OUTPUT/report/report.html"
echo "Metrics: $OUTPUT/report/metrics.csv"
