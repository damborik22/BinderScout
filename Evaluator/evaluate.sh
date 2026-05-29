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
#   --skip-boltz2          skip Boltz-2 refolding (use existing boltz2_results.csv)
#   --skip-protenix        skip Protenix refolding (default: auto-detect bindmaster_pxdesign env)
#   --protenix-env ENV     conda env for Protenix (default: bindmaster_pxdesign)
#   --skip-af3             skip AF3 refolding (default: auto-detect binder-eval-af3 env)
#   --af3-env ENV          conda env for AF3 (default: binder-eval-af3)
#   --skip-esmfold2        skip ESMFold2 refolding (default: auto-detect binder-eval-esmfold2 env)
#   --esmfold2-env ENV     conda env for ESMFold2 (default: binder-eval-esmfold2)
#   --esmfold2-model V     ESMFold2 checkpoint: fast | full (default: fast)
#   --skip-soluprot        skip SoluProt solubility screen (default: auto-detect binder-eval-soluprot env)
#   --soluprot-env ENV     conda env for SoluProt (default: binder-eval-soluprot)
#   --soluprot-threshold N pass threshold for soluprot_score (default: 0.5; paper value)
#   --soluprot-filter      drop sequences scoring below the threshold from FASTA BEFORE
#                          refolding — saves GPU time on designs we wouldn't pursue.
#                          Off by default; the score still lands in the report either way.
#   --primary-engine ENG   primary ranking engine: boltz | protenix | af3 | esmfold2 (default: boltz)
#   --resume               resume interrupted run

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
PROTENIX_ENV="bindmaster_pxdesign"
SKIP_AF3=0
AF3_ENV="binder-eval-af3"
SKIP_ESMFOLD2=0
ESMFOLD2_ENV="binder-eval-esmfold2"
ESMFOLD2_MODEL="fast"
SKIP_SOLUPROT=0
SOLUPROT_ENV="binder-eval-soluprot"
SOLUPROT_THRESHOLD=0.5
SOLUPROT_FILTER=0
PRIMARY_ENGINE="boltz"
RESUME=0

# --- parse arguments -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sequences)      SEQUENCES="$2";    shift 2 ;;
        --target-seq)     TARGET_SEQ="$2";   shift 2 ;;
        --output|-o)      OUTPUT="$2";       shift 2 ;;
        --skip-boltz2)    SKIP_BOLTZ2=1;     shift ;;
        --skip-protenix)  SKIP_PROTENIX=1;   shift ;;
        --protenix-env)   PROTENIX_ENV="$2"; shift 2 ;;
        --skip-af3)       SKIP_AF3=1;        shift ;;
        --af3-env)        AF3_ENV="$2";      shift 2 ;;
        --skip-esmfold2)  SKIP_ESMFOLD2=1;   shift ;;
        --esmfold2-env)   ESMFOLD2_ENV="$2"; shift 2 ;;
        --esmfold2-model) ESMFOLD2_MODEL="$2"; shift 2 ;;
        --skip-soluprot)     SKIP_SOLUPROT=1;          shift ;;
        --soluprot-env)      SOLUPROT_ENV="$2";        shift 2 ;;
        --soluprot-threshold) SOLUPROT_THRESHOLD="$2"; shift 2 ;;
        --soluprot-filter)   SOLUPROT_FILTER=1;        shift ;;
        --primary-engine)
            PRIMARY_ENGINE="$2"
            case "$PRIMARY_ENGINE" in
                boltz|protenix|af3|esmfold2) ;;
                *) echo "Error: --primary-engine must be one of: boltz, protenix, af3, esmfold2 (got '$PRIMARY_ENGINE')" >&2; exit 1 ;;
            esac
            shift 2 ;;
        --resume)         RESUME=1;          shift ;;
        -h|--help)
            sed -n '2,32p' "$0" | grep '^#' | sed 's/^# \?//'
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
        echo "        (requires >100 GB unified/device memory; see Evaluator/envs/binder-eval-af3.yml)"
        echo ""
        SKIP_AF3=1
    fi
fi

# Auto-detect ESMFold2 availability unless user skipped it
if [[ $SKIP_ESMFOLD2 -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${ESMFOLD2_ENV}"; then
        echo "[note] conda env '${ESMFOLD2_ENV}' not found — ESMFold2 refolding will be skipped."
        echo "        (install with: bindmaster install --tool esmfold2; see Evaluator/envs/binder-eval-esmfold2.yml)"
        echo ""
        SKIP_ESMFOLD2=1
    fi
fi

# Auto-detect SoluProt availability unless user skipped it
if [[ $SKIP_SOLUPROT -eq 0 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${SOLUPROT_ENV}"; then
        echo "[note] conda env '${SOLUPROT_ENV}' not found — SoluProt solubility screen will be skipped."
        echo "        (install with: bindmaster install --tool soluprot; x86 only)"
        echo ""
        SKIP_SOLUPROT=1
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
ESMFOLD2_CSV="$OUTPUT/esmfold2_results.csv"
SOLUPROT_CSV="$OUTPUT/soluprot_results.csv"

# Step counter: 1 (report) + 1 per engine not skipped + 1 if SoluProt ran
N_STEPS=1  # report
[[ $SKIP_BOLTZ2 -eq 0 ]]   && (( N_STEPS++ ))
[[ $SKIP_PROTENIX -eq 0 ]] && (( N_STEPS++ ))
[[ $SKIP_AF3 -eq 0 ]]      && (( N_STEPS++ ))
[[ $SKIP_ESMFOLD2 -eq 0 ]] && (( N_STEPS++ ))
[[ $SKIP_SOLUPROT -eq 0 ]] && (( N_STEPS++ ))
STEP=1

# --- Step 0.5: SoluProt solubility screen (optional, runs before refolding) ─
# Runs before any refold engine so --soluprot-filter can drop sub-threshold
# sequences and save GPU time. The score lands in the report either way.
if [[ $SKIP_SOLUPROT -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] SoluProt screen     (conda env: ${SOLUPROT_ENV}, threshold: ${SOLUPROT_THRESHOLD})..."
    conda run -n "${SOLUPROT_ENV}" binder-compare filter-soluprot \
        --sequences "$SEQUENCES" \
        -o          "$SOLUPROT_CSV" \
        --threshold "$SOLUPROT_THRESHOLD"

    if [[ $SOLUPROT_FILTER -eq 1 ]]; then
        # Hard filter: rewrite the FASTA, keeping only sequences whose
        # soluprot_passes==1 row in the CSV. Saves refold time downstream.
        FILTERED_FASTA="$OUTPUT/sequences.soluble.fasta"
        conda run -n binder-eval python - "$SOLUPROT_CSV" "$SEQUENCES" "$FILTERED_FASTA" <<'PY'
import csv, sys
csv_path, fasta_in, fasta_out = sys.argv[1], sys.argv[2], sys.argv[3]
soluble: set[str] = set()
with open(csv_path) as fh:
    for row in csv.DictReader(fh):
        if row.get("soluprot_passes") in ("1", "True", "true"):
            seq = (row.get("sequence") or "").strip().upper()
            if seq:
                soluble.add(seq)
n_in = n_kept = 0
header, body = None, []
def flush(out):
    global n_in, n_kept
    if header is None:
        return
    n_in += 1
    seq = "".join(body).strip().upper()
    if seq in soluble:
        out.write(header)
        for line in body:
            out.write(line)
        n_kept += 1
with open(fasta_in) as fh_in, open(fasta_out, "w") as fh_out:
    for line in fh_in:
        if line.startswith(">"):
            flush(fh_out)
            header = line
            body = []
        else:
            body.append(line)
    flush(fh_out)
print(f"[soluprot-filter] kept {n_kept} of {n_in} sequences (threshold {soluble and 'configured' or 'n/a'})", file=sys.stderr)
PY
        SEQUENCES="$FILTERED_FASTA"
        echo "[soluprot-filter] downstream refolding will run on $SEQUENCES"
    fi
    (( STEP++ ))
fi

if [[ $SKIP_BOLTZ2 -eq 1 ]]; then
    echo "[step ${STEP}/${N_STEPS}] Boltz-2 refolding — skipped (using existing $BOLTZ2_CSV)"
    [[ -f "$BOLTZ2_CSV" ]] || { echo "Error: $BOLTZ2_CSV not found"; exit 1; }
else
    echo "[step ${STEP}/${N_STEPS}] Boltz-2 refolding  (Mosaic venv)..."
    BOLTZ2_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && BOLTZ2_RESUME_FLAG="--resume"
    "$MOSAIC_VENV/bin/binder-compare" refold-boltz2 \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$BOLTZ2_CSV" \
        $BOLTZ2_RESUME_FLAG
fi
(( STEP++ ))

# --- Step 2: Protenix refolding (optional) ---------------------------------
if [[ $SKIP_PROTENIX -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] Protenix refolding  (conda env: ${PROTENIX_ENV})..."
    PROTENIX_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && PROTENIX_RESUME_FLAG="--resume"
    conda run -n "${PROTENIX_ENV}" binder-compare refold-protenix \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$PROTENIX_CSV" \
        --output-dir "$OUTPUT/refold_protenix" \
        $PROTENIX_RESUME_FLAG
    (( STEP++ ))
fi

# --- Step 3: AF3 refolding (optional) --------------------------------------
if [[ $SKIP_AF3 -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] AF3 refolding       (conda env: ${AF3_ENV})..."
    AF3_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && AF3_RESUME_FLAG="--resume"
    conda run -n "${AF3_ENV}" binder-compare refold-af3 \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$AF3_CSV" \
        --output-dir "$OUTPUT/refold_af3" \
        $AF3_RESUME_FLAG
    (( STEP++ ))
fi

# --- Step 4: ESMFold2 refolding (optional) ---------------------------------
if [[ $SKIP_ESMFOLD2 -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] ESMFold2 refolding  (conda env: ${ESMFOLD2_ENV})..."
    ESMFOLD2_RESUME_FLAG=""
    [[ $RESUME -eq 1 ]] && ESMFOLD2_RESUME_FLAG="--resume"
    conda run -n "${ESMFOLD2_ENV}" binder-compare refold-esmfold2 \
        --sequences  "$SEQUENCES" \
        --target-seq "$TARGET_SEQ" \
        -o           "$ESMFOLD2_CSV" \
        --output-dir "$OUTPUT/refold_esmfold2" \
        --model      "${ESMFOLD2_MODEL}" \
        $ESMFOLD2_RESUME_FLAG
    (( STEP++ ))
fi

# --- Report ----------------------------------------------------------------
echo "[step ${STEP}/${N_STEPS}] Generating report   (binder-eval)..."
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
if [[ $SKIP_ESMFOLD2 -eq 0 && -f "$ESMFOLD2_CSV" ]]; then
    REPORT_ARGS+=(--esmfold2-results "$ESMFOLD2_CSV")
fi
if [[ $SKIP_SOLUPROT -eq 0 && -f "$SOLUPROT_CSV" ]]; then
    REPORT_ARGS+=(--soluprot-results "$SOLUPROT_CSV")
fi
REPORT_ARGS+=(--primary-engine "$PRIMARY_ENGINE")
conda run -n binder-eval binder-compare report "${REPORT_ARGS[@]}"

echo ""
echo "=== Done ==="
echo "Report : $OUTPUT/report/report.html"
echo "Metrics: $OUTPUT/report/metrics.csv"
