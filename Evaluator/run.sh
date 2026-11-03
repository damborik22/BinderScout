#!/usr/bin/env bash
# BinderScout Evaluator — interactive launcher
# Run this script to evaluate a set of binder sequences.

set -euo pipefail

# Initialise conda: one discovery order, shared with the installers and the Python CLI.
_BINDERSCOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# >>> binderscout-conda-block >>>
# ONE answer to "where is conda?" for shell, in the same order as
# binderscout_paths.find_conda_base: $BINDERSCOUT_CONDA, <checkout>/conda, $CONDA_EXE,
# $CONDA_PREFIX, conda/mamba/micromamba on PATH, then the usual install locations. A base
# is valid when it has etc/profile.d/conda.sh (the file every generated script sources).
# No subprocess is run to find it.
# This text is copied VERBATIM into every script that needs it, because the scripts cannot
# share a file (the installer runs before anything else exists). Edit all copies together:
# tests/test_shell_conda_block_is_identical.py fails when they drift.

# bs_conda_candidates [checkout-dir]  -> every directory worth trying, best first
bs_conda_candidates() {
    local repo="${1:-}" home="${HOME:-}" p t
    if [[ -n "${BINDERSCOUT_CONDA:-}" ]]; then
        p="${BINDERSCOUT_CONDA}"
        if [[ "${p}" == \~ || "${p}" == \~/* ]]; then p="${home}${p#\~}"; fi
        printf '%s\n' "${p}"
    fi
    if [[ -n "${repo}" ]]; then printf '%s\n' "${repo}/conda"; fi
    if [[ -n "${CONDA_EXE:-}" ]]; then
        p="$(readlink -f -- "${CONDA_EXE}" 2>/dev/null || true)"
        if [[ -n "${p}" ]]; then printf '%s\n' "${p%/*/*}"; fi
    fi
    if [[ -n "${CONDA_PREFIX:-}" ]]; then
        p="${CONDA_PREFIX%/}"
        if [[ "$(basename -- "$(dirname -- "${p}")")" == "envs" ]]; then
            printf '%s\n' "${p%/*/*}"
        else
            printf '%s\n' "${p}"
        fi
    fi
    for t in conda mamba micromamba; do
        p="$(type -P "${t}" 2>/dev/null || true)"
        if [[ -n "${p}" ]]; then
            p="$(readlink -f -- "${p}" 2>/dev/null || true)"
            if [[ -n "${p}" ]]; then printf '%s\n' "${p%/*/*}"; fi
        fi
    done
    if [[ -n "${home}" ]]; then
        for t in miniforge3 mambaforge miniconda3 anaconda3 conda; do printf '%s\n' "${home}/${t}"; done
    fi
    for t in /opt/conda /opt/miniforge3 /opt/miniconda3 /opt/anaconda3; do printf '%s\n' "${t}"; done
}

# bs_valid_conda_bases [checkout-dir]  -> the candidates that really are a conda base, once each
bs_valid_conda_bases() {
    local c seen=$'\n'
    while IFS= read -r c; do
        if [[ -f "${c}/etc/profile.d/conda.sh" && "${seen}" != *$'\n'"${c}"$'\n'* ]]; then
            seen+="${c}"$'\n'
            printf '%s\n' "${c}"
        fi
    done < <(bs_conda_candidates "${1:-}")
}

# bs_find_conda_base [checkout-dir]  -> the first valid base; status 1 when there is none
bs_find_conda_base() {
    local c
    while IFS= read -r c; do
        printf '%s\n' "${c}"
        return 0
    done < <(bs_valid_conda_bases "${1:-}")
    return 1
}

# bs_source_conda [checkout-dir]  -> find a base, remember it in BS_CONDA_BASE, source its conda.sh
bs_source_conda() {
    local base
    base="$(bs_find_conda_base "${1:-}")" || return 1
    # shellcheck disable=SC2034  # read by the scripts that carry this block
    BS_CONDA_BASE="${base}"
    # shellcheck source=/dev/null
    source "${base}/etc/profile.d/conda.sh"
}

# bs_env_lookup <conda-base> <env-name>  -> sets BS_ENV_PREFIX; status 0 when the env exists
# An env is not always <base>/envs/<name>: $CONDA_ENVS_PATH, a condarc envs_dirs and the
# per-user ~/.conda/envs all put it elsewhere. Order: $CONDA_ENVS_PATH, <base>/envs, then
# conda's own listing (parsed without jq). The old <base>/envs path stays the fallback
# answer, so a caller that builds a path from it behaves exactly as before.
BS_ENV_PREFIX=""
BS_ENV_JSON=""    # `conda env list --json`, kept until a command that may change the envs ran
# shellcheck disable=SC2034  # BS_ENV_PREFIX is read by the callers, not here
bs_env_lookup() {
    local base="${1:-}" name="$2" d line
    local -a dirs=()
    if [[ -n "${CONDA_ENVS_PATH:-}" ]]; then
        IFS=: read -r -a dirs <<< "${CONDA_ENVS_PATH}"
        for d in "${dirs[@]}"; do
            if [[ -n "${d}" && -d "${d}/${name}" ]]; then BS_ENV_PREFIX="${d}/${name}"; return 0; fi
        done
    fi
    if [[ -n "${base}" && -d "${base}/envs/${name}" ]]; then BS_ENV_PREFIX="${base}/envs/${name}"; return 0; fi
    if [[ -n "${base}" && -x "${base}/bin/conda" ]]; then
        if [[ -z "${BS_ENV_JSON}" ]]; then
            BS_ENV_JSON="$("${base}/bin/conda" env list --json 2>/dev/null || true)"
            if [[ -z "${BS_ENV_JSON}" ]]; then BS_ENV_JSON="-"; fi
        fi
        while IFS= read -r line; do
            line="${line#*\"}"
            line="${line%\"*}"
            if [[ "${line}" == /* && "${line##*/}" == "${name}" && -d "${line}" ]]; then
                BS_ENV_PREFIX="${line}"
                return 0
            fi
        done < <(printf '%s\n' "${BS_ENV_JSON}" | tr ',' '\n')
    fi
    BS_ENV_PREFIX="${base}/envs/${name}"
    return 1
}
# <<< binderscout-conda-block <<<

# A miss is reported below, after the exit trap is set, so the launcher window still pauses.
_CONDA_MISSING=0
bs_source_conda "${_BINDERSCOUT_DIR}" || _CONDA_MISSING=1

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

if [[ "${_CONDA_MISSING}" -eq 1 ]]; then
    echo "Error: conda not found (looked at \$BINDERSCOUT_CONDA, ${_BINDERSCOUT_DIR}/conda, \$CONDA_EXE, \$CONDA_PREFIX, PATH and the usual install locations)." >&2
    echo "       Install it with 'binderscout install --tool evaluator', or export BINDERSCOUT_CONDA=<its base directory>." >&2
    exit 1
fi

echo "=============================="
echo "  BinderScout Evaluator"
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

# The target PDB is only the source of $TARGET_SEQ above — evaluate.sh consumes the
# sequence, not the structure. Do not pass --target-pdb: Boltz-2's template mode is
# opt-in and AF3/ESMFold2 have no equivalent, so constraining one engine's target
# backbone would make the per-engine iPTMs non-comparable.
bash "$EVALUATOR_DIR/evaluate.sh" \
    --sequences  "$SEQUENCES_FILE" \
    --target-seq "$TARGET_SEQ" \
    --output     "$OUTPUT"

echo ""
echo "Done. Report: $OUTPUT/report/report.html"
