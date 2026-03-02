#!/usr/bin/env bash
# BindMaster Evaluator — run a full evaluation
#
# Usage:
#   bash evaluate.sh --sequences sequences.fasta \
#                    --target-seq "MGFQKFSPF..." \
#                    --target-pdb target.pdb \
#                    --output ./results
#
# Both --target-seq and --target-pdb are required:
#   --target-seq  full target amino acid sequence (for Boltz-2 complex assembly)
#   --target-pdb  target PDB file (for AF2 multimer refolding)
#
# Optional:
#   --skip-boltz2   skip Boltz-2 refolding (use existing boltz2_results.csv in output dir)
#   --skip-af2      skip AF2 refolding     (use existing af2_results.csv in output dir)
#   --resume        resume interrupted run — skip already-completed binders in both engines
#   --mosaic-path   path to Mosaic repo root (for AF2's refold_Version6 module)

set -euo pipefail

# Initialise conda so it is available in non-interactive shells
_CONDA_INIT="${HOME}/miniforge3/etc/profile.d/conda.sh"
if [[ -f "$_CONDA_INIT" ]]; then
    # shellcheck source=/dev/null
    source "$_CONDA_INIT"
elif [[ -f "${HOME}/miniconda3/etc/profile.d/conda.sh" ]]; then
    source "${HOME}/miniconda3/etc/profile.d/conda.sh"
elif [[ -f "${HOME}/anaconda3/etc/profile.d/conda.sh" ]]; then
    source "${HOME}/anaconda3/etc/profile.d/conda.sh"
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
TARGET_PDB=""
OUTPUT=""
SKIP_BOLTZ2=0
SKIP_AF2=0
RESUME=0
MOSAIC_PATH=""

# --- parse arguments -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sequences)   SEQUENCES="$2";   shift 2 ;;
        --target-seq)  TARGET_SEQ="$2";  shift 2 ;;
        --target-pdb)  TARGET_PDB="$2";  shift 2 ;;
        --output|-o)   OUTPUT="$2";      shift 2 ;;
        --skip-boltz2) SKIP_BOLTZ2=1;    shift ;;
        --skip-af2)    SKIP_AF2=1;       shift ;;
        --resume)      RESUME=1;         shift ;;
        --mosaic-path) MOSAIC_PATH="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,20p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# --- validate ---------------------------------------------------------------
[[ -z "$SEQUENCES" ]]  && { echo "Error: --sequences required"; exit 1; }
[[ -z "$TARGET_SEQ" ]] && { echo "Error: --target-seq required"; exit 1; }
[[ -z "$TARGET_PDB" ]] && { echo "Error: --target-pdb required"; exit 1; }
[[ -z "$OUTPUT" ]]     && { echo "Error: --output required"; exit 1; }
[[ -f "$SEQUENCES" ]]  || { echo "Error: sequences file not found: $SEQUENCES"; exit 1; }
[[ -f "$TARGET_PDB" ]] || { echo "Error: target PDB not found: $TARGET_PDB"; exit 1; }

mkdir -p "$OUTPUT"
SEQUENCES="$(realpath "$SEQUENCES")"
TARGET_PDB="$(realpath "$TARGET_PDB")"
OUTPUT="$(realpath "$OUTPUT")"

# Convert CIF to PDB if needed (AF2 requires PDB format)
EXT="${TARGET_PDB##*.}"
if [[ "${EXT,,}" == "cif" || "${EXT,,}" == "mmcif" ]]; then
    echo "[setup] Converting CIF → PDB..."
    CONVERTED_PDB="$OUTPUT/target.pdb"
    conda run -n binder-eval-af2 python3 -c "
from binder_comparison.io.read import convert_cif_to_pdb
convert_cif_to_pdb('${TARGET_PDB//\'/\'\\\'\'}', '${CONVERTED_PDB//\'/\'\\\'\'}')
print('[setup] Converted to', '${CONVERTED_PDB//\'/\'\\\'\'}')
"
    TARGET_PDB="$CONVERTED_PDB"
fi

echo "=== BindMaster Evaluator ==="
echo "Sequences : $SEQUENCES"
echo "Target PDB: $TARGET_PDB"
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
    echo "[step 1/3] Boltz-2 refolding — skipped (using existing $BOLTZ2_CSV)"
    [[ -f "$BOLTZ2_CSV" ]] || { echo "Error: $BOLTZ2_CSV not found"; exit 1; }
else
    echo "[step 1/3] Boltz-2 refolding  (Mosaic venv)..."
    BOLTZ2_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && BOLTZ2_RESUME_FLAG="--resume"
    "$MOSAIC_VENV/bin/binder-compare" refold-boltz2 \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$BOLTZ2_CSV" \
        $BOLTZ2_RESUME_FLAG
fi

# --- Step 2: AF2 refolding -------------------------------------------------
AF2_CSV="$OUTPUT/af2_results.csv"

if [[ $SKIP_AF2 -eq 1 ]]; then
    echo "[step 2/3] AF2 refolding — skipped (using existing $AF2_CSV)"
    [[ -f "$AF2_CSV" ]] || { echo "Error: $AF2_CSV not found"; exit 1; }
else
    echo "[step 2/3] AF2 refolding       (binder-eval-af2)..."
    AF2_EXTRA_FLAGS=()
    [[ $RESUME -eq 1 ]] && AF2_EXTRA_FLAGS+=(--resume)
    [[ -n "$MOSAIC_PATH" ]] && AF2_EXTRA_FLAGS+=(--mosaic-path "$MOSAIC_PATH")
    conda run -n binder-eval-af2 binder-compare refold-af2 \
        --sequences  "$SEQUENCES" \
        --target-pdb "$TARGET_PDB" \
        -o           "$AF2_CSV" \
        --output-dir "$OUTPUT/refold_af2" \
        "${AF2_EXTRA_FLAGS[@]}"
fi

# --- Step 3: Report --------------------------------------------------------
echo "[step 3/3] Generating report   (binder-eval)..."
conda run -n binder-eval binder-compare report \
    --boltz2-results "$BOLTZ2_CSV" \
    --af2-results    "$AF2_CSV" \
    --sequences      "$SEQUENCES" \
    -o               "$OUTPUT/report"

echo ""
echo "=== Done ==="
echo "Report : $OUTPUT/report/report.html"
echo "Metrics: $OUTPUT/report/metrics.csv"
