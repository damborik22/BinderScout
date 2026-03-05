#!/usr/bin/env bash
# BindMaster Evaluator — interactive launcher
# Run this script to evaluate a set of binder sequences.

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
    # shellcheck disable=SC1090
    [[ -f "$_conda_sh" ]] && { source "$_conda_sh"; break; }
done

EVALUATOR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMPDIR_EVAL="$(mktemp -d)"

# Always pause before exit so the window doesn't vanish
_finish() {
    local code=$?
    rm -rf "$TMPDIR_EVAL"
    echo ""
    if [[ $code -ne 0 ]]; then
        echo "ERROR: evaluation failed (exit code $code)."
        echo "Scroll up to see the error message."
    fi
    read -rp "Press Enter to close..." _
}
trap _finish EXIT

echo "=============================="
echo "  BindMaster Evaluator"
echo "=============================="
echo ""

# --- sequences ---------------------------------------------------------------
echo "Binder sequences — paste directly or enter a file path."
echo "Accepted: FASTA, one per line, comma-separated, semicolon-separated,"
echo "          or a CSV/TSV file with a 'sequence' column."
echo "When pasting, press Enter then Ctrl-D when done."
echo ""
read -e -p "> " SEQUENCES_INPUT
SEQUENCES_INPUT="${SEQUENCES_INPUT/#\~/$HOME}"

if [[ -f "$SEQUENCES_INPUT" ]]; then
    SEQUENCES_FILE="$SEQUENCES_INPUT"
else
    SEQUENCES_FILE="$TMPDIR_EVAL/input_sequences.txt"
    echo "$SEQUENCES_INPUT" > "$SEQUENCES_FILE"
fi

# --- target PDB --------------------------------------------------------------
echo ""
read -e -p "Path to target structure (.pdb or .cif): " TARGET_PDB
TARGET_PDB="${TARGET_PDB/#\~/$HOME}"
[[ -f "$TARGET_PDB" ]] || { echo "Error: file not found: $TARGET_PDB"; exit 1; }

# Extract target sequence from PDB automatically
echo ""
echo "Extracting target sequence from PDB..."
TARGET_SEQ="$(conda run -n binder-eval python3 -c "
from binder_comparison.io.read import parse_pdb_sequence
print(parse_pdb_sequence('${TARGET_PDB//\'/\'\\\'\'}'))")" \
    || { echo "Error: could not extract sequence from PDB — check the file is a valid PDB."; exit 1; }

[[ -z "$TARGET_SEQ" ]] && { echo "Error: PDB contained no readable sequence."; exit 1; }

echo "Target: ${#TARGET_SEQ} aa — ${TARGET_SEQ:0:60}$([ ${#TARGET_SEQ} -gt 60 ] && echo '...' || true)"

# --- output ------------------------------------------------------------------
echo ""
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEFAULT_OUTPUT="$(pwd)/results_${TIMESTAMP}"
read -e -p "Output directory [${DEFAULT_OUTPUT}]: " OUTPUT
OUTPUT="${OUTPUT:-$DEFAULT_OUTPUT}"
OUTPUT="${OUTPUT/#\~/$HOME}"

echo ""
echo "--- Starting evaluation ---"
echo ""

bash "$EVALUATOR_DIR/evaluate.sh" \
    --sequences  "$SEQUENCES_FILE" \
    --target-seq "$TARGET_SEQ" \
    --target-pdb "$TARGET_PDB" \
    --output     "$OUTPUT"

echo ""
echo "Done. Report: $OUTPUT/report/report.html"
