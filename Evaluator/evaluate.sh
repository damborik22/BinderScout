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
#   --target-seq   full target amino acid sequence (for complex assembly)
#   --output       output directory
#
# Optional:
#   --skip-boltz2       skip Boltz-2 refolding (use existing boltz2_results.csv)
#   --skip-protenix     skip Protenix refolding (default: auto-detect bindmaster_pxdesign env)
#   --skip-af3          skip AF3 refolding (default: auto-detect binder-eval-af3 env)
#   --protenix-env ENV  conda env for Protenix (default: bindmaster_pxdesign)
#   --af3-env ENV       conda env for AF3 (default: binder-eval-af3)
#   --resume            resume interrupted run

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
SKIP_PROTENIX=0
SKIP_AF3=0
PROTENIX_ENV="bindmaster_pxdesign"
AF3_ENV="binder-eval-af3"
RESUME=0

# --- parse arguments -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sequences)     SEQUENCES="$2";    shift 2 ;;
        --target-seq)    TARGET_SEQ="$2";   shift 2 ;;
        --output|-o)     OUTPUT="$2";       shift 2 ;;
        --skip-boltz2)   SKIP_BOLTZ2=1;     shift ;;
        --skip-protenix) SKIP_PROTENIX=1;   shift ;;
        --skip-af3)      SKIP_AF3=1;       shift ;;
        --protenix-env)  PROTENIX_ENV="$2"; shift 2 ;;
        --af3-env)       AF3_ENV="$2";     shift 2 ;;
        --resume)        RESUME=1;          shift ;;
        -h|--help)
            sed -n '2,22p' "$0" | grep '^#' | sed 's/^# \?//'
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

# Auto-detect Protenix availability unless user skipped it
if [[ $SKIP_PROTENIX -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${PROTENIX_ENV}"; then
        echo "[note] conda env '${PROTENIX_ENV}' not found — Protenix refolding will be skipped."
        echo "        (install with: bindmaster install --tool pxdesign)"
        echo ""
        SKIP_PROTENIX=1
    fi
fi

# Auto-detect AF3 availability unless user skipped it
if [[ $SKIP_AF3 -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${AF3_ENV}"; then
        echo "[note] conda env '${AF3_ENV}' not found — AF3 refolding will be skipped."
        echo "        (install with: conda env create -f Evaluator/envs/binder-eval-af3.yml)"
        echo ""
        SKIP_AF3=1
    fi
fi

# --- Step 0: Normalise sequences to FASTA ----------------------------------
FASTA="$OUTPUT/sequences.fasta"
echo "[step 0] Parsing sequences → $FASTA"
conda run -n binder-eval binder-compare parse-seqs \
    --input  "$SEQUENCES" \
    --output "$FASTA"
SEQUENCES="$FASTA"

# --- Step 1: Boltz-2 refolding ---------------------------------------------
BOLTZ2_CSV="$OUTPUT/boltz2_results.csv"
PROTENIX_CSV="$OUTPUT/protenix_results.csv"
AF3_CSV="$OUTPUT/af3_results.csv"
N_STEPS=2
[[ $SKIP_PROTENIX -eq 0 ]] && N_STEPS=$((N_STEPS + 1))
[[ $SKIP_AF3 -eq 0 ]] && N_STEPS=$((N_STEPS + 1))

CUR_STEP=0

CUR_STEP=$((CUR_STEP + 1))
if [[ $SKIP_BOLTZ2 -eq 1 ]]; then
    echo "[step ${CUR_STEP}/${N_STEPS}] Boltz-2 refolding — skipped (using existing $BOLTZ2_CSV)"
    [[ -f "$BOLTZ2_CSV" ]] || { echo "Error: $BOLTZ2_CSV not found"; exit 1; }
else
    echo "[step ${CUR_STEP}/${N_STEPS}] Boltz-2 refolding  (Mosaic venv)..."
    BOLTZ2_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && BOLTZ2_RESUME_FLAG="--resume"
    "$MOSAIC_VENV/bin/binder-compare" refold-boltz2 \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$BOLTZ2_CSV" \
        $BOLTZ2_RESUME_FLAG
fi

# --- Step 2: Protenix refolding (optional) ---------------------------------
if [[ $SKIP_PROTENIX -eq 0 ]]; then
    CUR_STEP=$((CUR_STEP + 1))
    echo "[step ${CUR_STEP}/${N_STEPS}] Protenix refolding  (conda env: ${PROTENIX_ENV})..."
    PROTENIX_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && PROTENIX_RESUME_FLAG="--resume"
    conda run -n "${PROTENIX_ENV}" binder-compare refold-protenix \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$PROTENIX_CSV" \
        --output-dir "$OUTPUT/refold_protenix" \
        $PROTENIX_RESUME_FLAG
fi

# --- Step N-1: AF3 refolding (aarch64 / DGX Spark) -------------------------
if [[ $SKIP_AF3 -eq 0 ]]; then
    CUR_STEP=$((CUR_STEP + 1))
    echo "[step ${CUR_STEP}/${N_STEPS}] AF3 refolding        (conda env: ${AF3_ENV})..."
    AF3_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && AF3_RESUME_FLAG="--resume"
    conda run -n "${AF3_ENV}" binder-compare refold-af3 \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$AF3_CSV" \
        --output-dir "$OUTPUT/refold_af3" \
        $AF3_RESUME_FLAG
fi

# --- Report ----------------------------------------------------------------
echo "[step ${N_STEPS}/${N_STEPS}] Generating report   (binder-eval)..."
REPORT_ARGS=(
    --boltz2-results "$BOLTZ2_CSV"
    --sequences      "$SEQUENCES"
    -o               "$OUTPUT/report"
)
if [[ $SKIP_PROTENIX -eq 0 && -f "$PROTENIX_CSV" ]]; then
    REPORT_ARGS+=(--protenix-results "$PROTENIX_CSV")
fi
if [[ $SKIP_AF3 -eq 0 && -f "$AF3_CSV" ]]; then
    REPORT_ARGS+=(--af3-results "$AF3_CSV")
fi
conda run -n binder-eval binder-compare report "${REPORT_ARGS[@]}"

echo ""
echo "=== Done ==="
echo "Report : $OUTPUT/report/report.html"
echo "Metrics: $OUTPUT/report/metrics.csv"
