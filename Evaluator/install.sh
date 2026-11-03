#!/usr/bin/env bash
# BinderScout Evaluator — environment setup
# Run once after cloning the repository:
#   bash install.sh
#
# Creates one conda environment:
#   binder-eval     extract + report  (lightweight, no ML)
#
# For Boltz-2 refolding the Mosaic environment from the BinderScout installer
# is used. Mosaic must be installed first:
#   cd /path/to/BinderScout && bash install/install.sh --tool mosaic
#
# The additional refolding engines (AF3, ESMFold2) are
# installed by the main BinderScout installer's `--tool af3` and `--tool esmfold2`
# flags — not here.
#
# Prerequisites:
#   - conda (miniforge/miniconda)
#   - Mosaic installed via BinderScout installer (provides Boltz-2)
#   - GPU with CUDA drivers (required for refold steps)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
# A listed env counts only when its parent directory is one of conda's envs_dirs: the listing
# also carries envs of OTHER bases (~/.conda/environments.txt) and plain `-p` prefix envs, and
# neither can be addressed with `-n <name>` from this base, so the installer cannot use them.
BS_ENV_PREFIX=""
BS_ENV_JSON=""    # `conda env list --json`, kept until a command that may change the envs ran
BS_ENVS_DIRS=""   # `conda config --show envs_dirs --json`; "-" once asked and unanswered
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
        if [[ -z "${BS_ENVS_DIRS}" ]]; then
            BS_ENVS_DIRS="$("${base}/bin/conda" config --show envs_dirs --json 2>/dev/null || true)"
            if [[ -z "${BS_ENVS_DIRS}" ]]; then BS_ENVS_DIRS="-"; fi
        fi
        while IFS= read -r line; do
            line="${line#*\"}"
            line="${line%\"*}"
            if [[ "${line}" == /* && "${line##*/}" == "${name}" && -d "${line}" ]]; then
                while IFS= read -r d; do
                    d="${d#*\"}"
                    d="${d%\"*}"
                    if [[ "${d}" == /* && -d "${d}" && "${line%/*}" -ef "${d}" ]]; then
                        BS_ENV_PREFIX="${line}"
                        return 0
                    fi
                done < <(printf '%s\n' "${BS_ENVS_DIRS}" | tr ',' '\n')
            fi
        done < <(printf '%s\n' "${BS_ENV_JSON}" | tr ',' '\n')
    fi
    BS_ENV_PREFIX="${base}/envs/${name}"
    return 1
}
# <<< binderscout-conda-block <<<

bs_source_conda "${_BINDERSCOUT_DIR}" || {
    echo "Error: conda not found (looked at \$BINDERSCOUT_CONDA, ${_BINDERSCOUT_DIR}/conda, \$CONDA_EXE, \$CONDA_PREFIX, PATH and the usual install locations)." >&2
    echo "       Install it with 'binderscout install --tool evaluator', or export BINDERSCOUT_CONDA=<its base directory>." >&2
    exit 1
}

echo "=== BinderScout Evaluator — install ==="
echo "Repo: $REPO_DIR"
echo ""

# ---------------------------------------------------------------------------
# 0. Locate Mosaic venv (created by BinderScout installer)
# ---------------------------------------------------------------------------
echo "[0/2] Locating Mosaic venv (Boltz-2 environment)..."

MOSAIC_VENV=""

if [[ -n "${MOSAIC_DIR:-}" && -f "$MOSAIC_DIR/.venv/bin/python" ]]; then
    MOSAIC_VENV="$MOSAIC_DIR/.venv"
fi

if [[ -z "$MOSAIC_VENV" ]]; then
    for _candidate in \
        "$(dirname "$REPO_DIR")/Mosaic/.venv" \
        "${HOME}/Documents/BinderScout/Mosaic/.venv" \
        "${HOME}/BinderScout/Mosaic/.venv"; do
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
    echo "  created by the BinderScout installer. Please install it first:"
    echo ""
    echo "    cd /path/to/BinderScout"
    echo "    bash install/install.sh --tool mosaic"
    echo ""
    echo "  Then re-run this script, or set MOSAIC_DIR before running:"
    echo "    MOSAIC_DIR=/path/to/BinderScout/Mosaic bash install.sh"
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
echo "      BinderScout installer (--tool af3 / --tool esmfold2) and are"
echo "      auto-detected by evaluate.sh when their conda envs exist."
