#!/usr/bin/env bash
# BinderScout Evaluator — run a full evaluation
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
#   --allow-no-msa         proceed even if the shared target MSA cannot be fetched.
#                          Default: abort. An engine folding single-sequence while the
#                          others use an MSA produces scores that are NOT comparable,
#                          and consensus_iptm_mean averages across engines.
#   --skip-boltz2          skip Boltz-2 refolding (use existing boltz2_results.csv)
#   --skip-af3             skip AF3 refolding (default: auto-detect binder-eval-af3 env)
#   --af3-env ENV          conda env for AF3 (default: binder-eval-af3)
#   --second-engine ENG    which engine fills the SECOND slot of the panel: af3 | protenix.
#                          The panel is always Boltz-2 + <second> + ESMFold2, never four engines.
#                          Explicit wins and is never switched: an unusable explicit engine is
#                          skipped BY NAME. Without the flag the slot is AF3 when its env and
#                          weights are usable OR an af3_results.csv with scored rows is already in --output (then
#                          reported as ever); otherwise Protenix, when its env and weights are
#                          usable OR a protenix_results.csv with scored rows is already there (a notice names the
#                          panel); otherwise the slot is skipped by name. --skip-af3 /
#                          --skip-second given: no second engine, no fallback. Scores from
#                          different panels are not on one scale.
#   --protenix-env ENV     conda env for Protenix (default: binder-eval-protenix); its weights are
#                          read from <checkout>/weights/protenix (binderscout install --tool protenix)
#   --skip-second          skip whichever engine holds the second slot (AF3 or Protenix)
#   --skip-esmfold2        skip ESMFold2 refolding (default: auto-detect binder-eval-esmfold2 env)
#   --esmfold2-env ENV     conda env for ESMFold2 (default: binder-eval-esmfold2)
#   --esmfold2-model V     ESMFold2 checkpoint: full | fast (default: full)
#   --skip-soluprot        skip SoluProt solubility screen (default: auto-detect binder-eval-soluprot env)
#   --soluprot-env ENV     conda env for SoluProt (default: binder-eval-soluprot)
#   --soluprot-threshold N pass threshold for soluprot_score (default: 0.5; paper value)
#   --skip-tmprot          skip TmProt melting-temperature screen (default: auto-detect binder-eval-tmprot env)
#   --tmprot-env ENV       conda env for TmProt (default: binder-eval-tmprot)
#   --tmprot-threshold N   Tm (°C) at or above which a design is flagged thermostable
#                          (default: 60.0). Advisory only -- never drops or re-ranks.
#   --soluprot-filter      REMOVED 2026-09-28 -- now exits 1. SoluProt is a label, not a
#                          filter: measured against our own experimental results on two
#                          targets, dropping at the 0.5 threshold discarded several of
#                          the tightest binders, and no threshold above 0.0 met Part Z's
#                          recall gate. The score reaches the report either way.
#   --concurrent           run the refold engines SIMULTANEOUSLY instead of one after
#                          another, with staggered starts. Requires the CUDA MPS ceiling
#                          (tools/gpu_mem_guard.sh) and refuses to run without it, because
#                          concurrency without a hard per-client cap is exactly what took
#                          a unified-memory host down. Per-engine output goes to $OUTPUT/refold_<engine>.log.
#   --stagger N            seconds between concurrent engine starts (default: 30). The
#                          measured peak is the simultaneous COLD START -- all engines
#                          preallocating at once -- not steady state.
#   --gpu-cap-boltz2 N     per-engine GPU ceiling, e.g. 24G (default: 24G)
#   --gpu-cap-af3 N        default: 12G
#   --gpu-cap-protenix N   default: 24G (env BINDERSCOUT_GPU_CAP_PROTENIX). A PyTorch ceiling, set above
#                          the measured peak of about 20.4-20.8 GiB card-wide on the ~780-token complexes
#   --gpu-cap-esmfold2 N   default: 24G
#   --no-gpu-guard         do NOT apply the MPS ceiling (unsafe on unified memory)
#   --primary-engine ENG   primary ranking engine: boltz | af3 | esmfold2 | protenix (default: boltz).
#                          af3 / protenix are valid only when that engine holds the second slot
#   --min-engines N        how many independent engines must have refolded a design for it
#                          to be eligible for the ranking (default 3 = all of Boltz-2 / AF3 /
#                          ESMFold2; floor 2). Designs below the gate are ranked LAST, not
#                          dropped. On a host without AF3 — which usually means the gated
#                          weights were never placed, NOT a GPU limit; AF3 fits a 24 GB card
#                          in our size regime — only two engines run and the default gate
#                          fails EVERY design, so this script says so up front and names the flag.
#                          The gate is never lowered automatically: that would make two
#                          operators with the same designs produce different rankings
#                          depending on what happens to be installed.
#   --epitope-residues L   intended hotspot residues (e.g. '15,18,232,263' or 'A15,A18'). Computes
#                          epitope_match_fraction INLINE in the report from each design's refolded
#                          structure (selectivity signal for multi-pocket targets, e.g. ApoE4). Cheap.
#   --with-affinity        opt-in: after the report, run the |dG/dSASA| affinity ranking (Rosetta
#                          InterfaceAnalyzer, in the BindCraft env) on the top-20 structures, then
#                          re-generate the report with the affinity_energy_density column. Off by default.
#   --bindcraft-env ENV    conda env with PyRosetta for --with-affinity (default: BindCraft)
#   --monomer-dir DIR      opt-in: directory of binder-ALONE refolded structures (named by binder_id).
#                          Runs the context-dependent-fold check vs the in-complex structures and
#                          re-generates the report with the fold_robust column. Off by default.
#   --tool-root DIR        search DIR for each tool's OWN native CSV (metrics +
#                          sequence + rank) and pass what is found to the report
#                          as --tool-csv. Repeatable.
#   --resume               resume interrupted run

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

# A miss is not fatal HERE (--help and argument errors need no conda); it is reported per engine
# and then fatally, further down, once the arguments are known to be valid.
bs_source_conda "${_BINDERSCOUT_DIR}" || true

# aarch64/Blackwell: PyTorch CUDA compilation target.
#
# `export JAX_PLATFORMS=cpu` used to live here (added 2026-04-07 in 3cd03c5 as an
# aarch64 "platform guard", copied from PXDesign where JAX-on-sm_121 genuinely
# failed at the time).  It was WRONG for the Evaluator and silently broke it for
# ~4.5 months: JAX_PLATFORMS=cpu hides the GPU from every JAX child, so
#   * Boltz-2 ran on CPU -- correct numbers, ~2.7x slower, and it says nothing;
#   * AF3 died on EVERY binder with "Unknown backend: 'gpu' requested, but no
#     platforms that are instances of gpu are present", wrote empty rows, and
#     still exited 0 -- silently removing a whole engine from consensus_iptm_mean
#     and from the >=3-engine gate.
# Measured 2026-08-20 on a GB10: with it unset both engines report ['gpu'] and fold
# correctly (AF3 iptm 0.8900, Boltz-2 17.2 GiB on-GPU).  Do not re-add it.
# A machine that genuinely cannot run JAX on GPU can still export it externally;
# evaluate.sh inherits the environment.
if [[ "$(uname -m)" == "aarch64" ]]; then
    export TORCH_CUDA_ARCH_LIST="12.0"
fi

# Step logs must read chronologically. Every step below runs its real work in a
# child env via `conda run`, and Python block-buffers stdout when it is not a
# terminal while stderr stays unbuffered -- so a child's traceback arrived BEFORE
# the child's own "[filter-soluprot] loaded 3 sequence(s)" header, and the log
# read as if the step crashed before it started. Set once here rather than at
# fifteen call sites, and before any of them run.
export PYTHONUNBUFFERED=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MOSAIC_VENV_FILE="$SCRIPT_DIR/envs/mosaic_venv_path"

SEQUENCES=""
TARGET_SEQ=""
OUTPUT=""
ALLOW_NO_MSA=${BINDERSCOUT_ALLOW_NO_MSA:-0}
SKIP_BOLTZ2=0
SKIP_AF3=0
AF3_ENV="binder-eval-af3"
# The second slot of the panel: AF3 (default) or Protenix. SECOND_FLAG is what the operator asked for
# ("" = decide below); SECOND_ENGINE is what the run uses once that is decided. Never both.
SECOND_FLAG=""
SECOND_ENGINE="af3"
SKIP_SECOND=0
SKIP_PROTENIX=1          # cleared only when Protenix holds the slot and is not skipped
PROTENIX_ENV="binder-eval-protenix"
# What the installer's --tool protenix leaves behind: <checkout>/weights/protenix/checkpoint/<model>.pt,
# exactly this many bytes. A different size is a truncated or foreign file, refused up front.
PROTENIX_MODEL="protenix_base_default_v1.0.0"
PROTENIX_CKPT_BYTES=1475950125
PROTENIX_WEIGHTS_DIR="${_BINDERSCOUT_DIR}/weights/protenix"
SKIP_ESMFOLD2=0
ESMFOLD2_ENV="binder-eval-esmfold2"
ESMFOLD2_MODEL="full"
SKIP_SOLUPROT=0
SOLUPROT_ENV="binder-eval-soluprot"
SOLUPROT_THRESHOLD=0.5
# TmProt: sequence-only melting-temperature screen. Deliberately has NO filter
# mode -- and since 2026-09-28 neither has SoluProt. Tm predictors are out of
# domain on hyperstable de novo miniproteins, so the column is advisory and must
# never drop a design.
SKIP_TMPROT=0
TMPROT_ENV="binder-eval-tmprot"
TMPROT_THRESHOLD=60.0
PRIMARY_ENGINE="boltz"
CONCURRENT=0
STAGGER=${BINDERSCOUT_STAGGER_S:-30}
GPU_CAP_BOLTZ2=${BINDERSCOUT_GPU_CAP_BOLTZ2:-24G}
GPU_CAP_AF3=${BINDERSCOUT_GPU_CAP_AF3:-12G}
# Protenix: a NON-DEFAULT setting relative to AF3's 12G. A PyTorch ceiling (it does not preallocate),
# set above the measured peak of ~20.4 GiB card-wide on a 779-token complex, so it never binds.
GPU_CAP_PROTENIX=${BINDERSCOUT_GPU_CAP_PROTENIX:-24G}
GPU_CAP_ESMFOLD2=${BINDERSCOUT_GPU_CAP_ESMFOLD2:-24G}
USE_GPU_GUARD=1
MIN_ENGINES=""          # empty = let binder-compare apply its own default (3)
EPITOPE_RESIDUES=""
WITH_AFFINITY=0
BINDCRAFT_ENV="BindCraft"
MONOMER_DIR=""
RESUME=0
# Directories to search for each tool's OWN native CSV (metrics + sequence +
# rank). Whatever is found is handed to the report as --tool-csv, so the report
# can show what a tool said about its own designs beside the refold numbers.
TOOL_ROOTS=()

# --- parse arguments -------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --sequences)      SEQUENCES="$2";    shift 2 ;;
        --target-seq)     TARGET_SEQ="$2";   shift 2 ;;
        --output|-o)      OUTPUT="$2";       shift 2 ;;
        --allow-no-msa)   ALLOW_NO_MSA=1;    shift ;;
        --skip-boltz2)    SKIP_BOLTZ2=1;     shift ;;
        --skip-af3)       SKIP_AF3=1;        shift ;;
        --af3-env)        AF3_ENV="$2";      shift 2 ;;
        --second-engine)
            SECOND_FLAG="${2:-}"
            case "$SECOND_FLAG" in
                af3|protenix) ;;
                *) echo "Error: --second-engine must be one of: af3, protenix (got '$SECOND_FLAG')" >&2; exit 2 ;;
            esac
            shift 2 ;;
        --protenix-env)   PROTENIX_ENV="$2"; shift 2 ;;
        --skip-second)    SKIP_SECOND=1;     shift ;;
        --skip-esmfold2)  SKIP_ESMFOLD2=1;   shift ;;
        --esmfold2-env)   ESMFOLD2_ENV="$2"; shift 2 ;;
        --esmfold2-model) ESMFOLD2_MODEL="$2"; shift 2 ;;
        --skip-soluprot)     SKIP_SOLUPROT=1;          shift ;;
        --soluprot-env)      SOLUPROT_ENV="$2";        shift 2 ;;
        --soluprot-threshold) SOLUPROT_THRESHOLD="$2"; shift 2 ;;
        --soluprot-filter)
            # REMOVED 2026-09-28. SoluProt is a label, not a filter. Measured against our
            # own experimental results on two targets, this flag at its own default
            # threshold discarded several of the tightest measured binders and lost
            # designs from the full run's top-10; no threshold above 0.0 met Part Z's
            # recall gate. Refused rather than silently ignored -- a caller who scripted
            # it must find out, instead of quietly receiving different data.
            echo "Error: --soluprot-filter has been removed. SoluProt is a label, not a filter." >&2
            echo "       A pre-refold drop is unrecoverable, and measured on two targets it" >&2
            echo "       discarded several of the tightest binders. Remove the flag: the score" >&2
            echo "       still reaches the report as native_soluprot_score either way." >&2
            exit 1
            ;;
        --skip-tmprot)       SKIP_TMPROT=1;            shift ;;
        --tmprot-env)        TMPROT_ENV="$2";          shift 2 ;;
        --tmprot-threshold)  TMPROT_THRESHOLD="$2";    shift 2 ;;
        --concurrent)         CONCURRENT=1;              shift ;;
        --stagger)            STAGGER="$2";              shift 2 ;;
        --gpu-cap-boltz2)     GPU_CAP_BOLTZ2="$2";       shift 2 ;;
        --gpu-cap-af3)        GPU_CAP_AF3="$2";          shift 2 ;;
        --gpu-cap-protenix)   GPU_CAP_PROTENIX="$2";     shift 2 ;;
        --gpu-cap-esmfold2)   GPU_CAP_ESMFOLD2="$2";     shift 2 ;;
        --no-gpu-guard)       USE_GPU_GUARD=0;           shift ;;
        --primary-engine)
            PRIMARY_ENGINE="$2"
            case "$PRIMARY_ENGINE" in
                boltz|af3|esmfold2|protenix) ;;
                *) echo "Error: --primary-engine must be one of: boltz, af3, esmfold2, protenix (got '$PRIMARY_ENGINE')" >&2; exit 1 ;;
            esac
            shift 2 ;;
        --min-engines)
            MIN_ENGINES="$2"
            [[ "$MIN_ENGINES" =~ ^[0-9]+$ ]] || {
                echo "Error: --min-engines takes an integer (got '$MIN_ENGINES')" >&2; exit 1; }
            (( MIN_ENGINES >= 2 )) || {
                echo "Error: --min-engines floor is 2 — a cross-engine consensus needs at least two engines." >&2
                exit 1; }
            shift 2 ;;
        --epitope-residues) EPITOPE_RESIDUES="$2"; shift 2 ;;
        --with-affinity)    WITH_AFFINITY=1;        shift ;;
        --bindcraft-env)    BINDCRAFT_ENV="$2";     shift 2 ;;
        --monomer-dir)      MONOMER_DIR="$2";       shift 2 ;;
        --tool-root)      TOOL_ROOTS+=("$2"); shift 2 ;;
        --resume)         RESUME=1;          shift ;;
        -h|--help)
            sed -n '2,/^set /p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# --- validate ---------------------------------------------------------------
[[ -z "$SEQUENCES" ]]  && { echo "Error: --sequences required"; exit 1; }
[[ -z "$TARGET_SEQ" ]] && { echo "Error: --target-seq required"; exit 1; }
[[ -z "$OUTPUT" ]]     && { echo "Error: --output required"; exit 1; }
[[ -f "$SEQUENCES" ]]  || { echo "Error: sequences file not found: $SEQUENCES"; exit 1; }

# --- locate Mosaic venv (written by install.sh) ----------------------------
# Resolved AFTER argument parsing, and only when Boltz-2 will actually run. It used to
# be resolved at the top, unconditionally, so `evaluate.sh --help` could not print the
# help without a Mosaic install, and an AF3 + ESMFold2 evaluation (`--skip-boltz2`) was
# refused on a host that legitimately has no Mosaic.
if [[ $SKIP_BOLTZ2 -eq 0 ]]; then
    if [[ -f "$MOSAIC_VENV_FILE" ]]; then
        MOSAIC_VENV="$(cat "$MOSAIC_VENV_FILE")"
    else
        echo "Error: Mosaic venv path not found — Boltz-2 refolding runs in the Mosaic venv." >&2
        echo "       Run 'binderscout install --tool mosaic', or pass --skip-boltz2." >&2
        exit 1
    fi
    [[ -f "$MOSAIC_VENV/bin/binder-compare" ]] || {
        echo "Error: binder-compare not found in $MOSAIC_VENV. Run bash install.sh again," >&2
        echo "       or pass --skip-boltz2 to evaluate without Boltz-2." >&2
        exit 1
    }
fi

mkdir -p "$OUTPUT"
SEQUENCES="$(realpath "$SEQUENCES")"
OUTPUT="$(realpath "$OUTPUT")"

echo "=== BinderScout Evaluator ==="
echo "Sequences : $SEQUENCES"
echo "Output    : $OUTPUT"
echo ""

# _env_missing_reason <env>: prints why <env> cannot be used and succeeds; fails (prints nothing)
# when it can. "No conda" is its own answer: it used to read as "env not found", which blamed the
# install of every optional engine for what is a failure to find conda itself.
_env_missing_reason() {
    if ! command -v conda >/dev/null 2>&1; then
        echo "conda not found"
        return 0
    fi
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "$1"; then
        echo "conda env '$1' not found"
        return 0
    fi
    return 1
}

# Every optional engine / screen skipped for want of an env, with the reason, for one summary.
_SKIPPED=()

# Per-engine result CSVs. Set HERE, ahead of the second-slot decision, so that decision and the
# engine count / report below all read the same variables. An engine that is skipped but already
# has its CSV on disk still counts toward the gate.
BOLTZ2_CSV="$OUTPUT/boltz2_results.csv"
AF3_CSV="$OUTPUT/af3_results.csv"
PROTENIX_CSV="$OUTPUT/protenix_results.csv"
ESMFOLD2_CSV="$OUTPUT/esmfold2_results.csv"

# Counts rows that carry a SCORE, not rows.  The distinction is the whole guard:
# ESMFold2 writes a full-length row with every score blank when a design OOMs, so
# `tail -n +2 | wc -l` -- which this was -- counted 50 blanks as 50 successes and
# printed "ok -- 50 new row(s)" over an engine that produced nothing.  A blank row is
# not a neutral absence either: it drops that design below the >=3-engine gate, which
# in metrics.csv is indistinguishable from three engines disliking it.
#
# `iptm` is the right column because it is what consensus_iptm_mean averages -- the
# exact quantity whose absence demotes the design -- and all three engines emit it
# under that name.  Done in awk rather than by field index: the engines' CSVs have
# different column orders, so a hard-coded $7 would silently read the wrong column.
csv_rows () {
    if [[ ! -f "$1" ]]; then echo 0; return; fi
    awk -F',' '
        NR == 1 { for (i = 1; i <= NF; i++) if ($i == "iptm") c = i; next }
        c && $c != "" { n++ }
        END { print n + 0 }
    ' "$1"
}

# --- the second slot ---------------------------------------------------------
# The panel has exactly one second engine, AF3 or Protenix, and it is decided HERE, once, before
# anything is detected. An explicit --second-engine wins and is never swapped for the other engine.
# With no flag AF3 keeps the slot unless it turns out to be unusable (see the fallback below).
# --skip-af3 still means "skip the AF3 slot"; --skip-second skips whichever engine holds it.
_AUTO_SECOND=0
if [[ -n "$SECOND_FLAG" ]]; then
    SECOND_ENGINE="$SECOND_FLAG"
elif [[ $SKIP_AF3 -eq 0 && $SKIP_SECOND -eq 0 ]]; then
    _AUTO_SECOND=1
fi
if [[ "$SECOND_ENGINE" == "protenix" ]]; then
    SKIP_AF3=1                                   # AF3 is not in this panel: no detection, no notes
    [[ $SKIP_SECOND -eq 1 ]] || SKIP_PROTENIX=0
elif [[ $SKIP_SECOND -eq 1 ]]; then
    SKIP_AF3=1
fi

# Auto-detect AF3 availability unless user skipped it
if [[ $SKIP_AF3 -eq 0 ]]; then
    if _why="$(_env_missing_reason "${AF3_ENV}")"; then
        echo "[note] ${_why} — AF3 refolding will be skipped."
        _SKIPPED+=("AF3: ${_why}")
        echo "        (install with 'binderscout install --tool af3'; runs on 24 GB GPUs — see Evaluator/envs/binder-eval-af3.yml)"
        echo ""
        SKIP_AF3=1
    fi
fi

# The env is not enough: AF3's weights are gated, so the installer can neither bundle nor
# fetch them -- it only PRINTS where to put them, at the end of a long install. Detecting the
# env but not the weights meant a pool refolded through Boltz-2 and ESMFold2 for hours and
# only then died in the AF3 step on FileNotFoundError. Resolve them here instead, in the order
# refold_af3.py's _resolve_model_dir uses ($AF3_MODEL_DIR when it is a directory -- taken
# as-is, so an EMPTY one is a failure there too -- then the default directories, each only
# when non-empty), and drop AF3 NOW, by name, rather than in hour 3.
_af3_weights_dir () {   # prints the models directory refold_af3.py will use; fails if it has none
    local cand
    if [[ -n "${AF3_MODEL_DIR:-}" && -d "${AF3_MODEL_DIR}" ]]; then
        [[ -n "$(ls -A "${AF3_MODEL_DIR}" 2>/dev/null)" ]] || return 1
        echo "${AF3_MODEL_DIR}"; return 0
    fi
    for cand in "${HOME}/.alphafold3/models" "${HOME}/af3_models" /opt/alphafold3/models; do
        if [[ -d "${cand}" && -n "$(ls -A "${cand}" 2>/dev/null)" ]]; then
            echo "${cand}"; return 0
        fi
    done
    return 1
}

if [[ $SKIP_AF3 -eq 0 ]]; then
    if _af3_models="$(_af3_weights_dir)"; then
        echo "[note] AF3 weights found: ${_af3_models}"
        echo ""
    else
        echo "[note] '${AF3_ENV}' is installed but no AF3 weights were found — AF3 refolding will be skipped."
        _SKIPPED+=("AF3: no AF3 weights found (env '${AF3_ENV}' is installed)")
        echo "        Searched: \$AF3_MODEL_DIR, ~/.alphafold3/models, ~/af3_models, /opt/alphafold3/models"
        if [[ -n "${AF3_MODEL_DIR:-}" && -d "${AF3_MODEL_DIR}" ]]; then
            echo "        AF3_MODEL_DIR is set to ${AF3_MODEL_DIR} but that directory is empty;"
            echo "        refold_af3.py would use it as-is, so the defaults are not tried."
        fi
        echo "        The weights are gated and are NOT shipped with this repo: request access from the"
        echo "        AlphaFold 3 project (https://github.com/google-deepmind/alphafold3), place them in one of"
        echo "        the paths above, or export AF3_MODEL_DIR=/path/to/models, and re-run."
        echo "        Skipping now rather than failing after the Boltz-2 / ESMFold2 refolds."
        echo ""
        SKIP_AF3=1
    fi
fi

# Protenix: usable means its conda env exists AND the one checkpoint the installer fetched is
# there at exactly its published size (a size check, as the installer's own). Prints why not and
# succeeds when it is NOT usable; fails (prints nothing) when it is.
_protenix_unusable_reason () {
    local ckpt="${PROTENIX_WEIGHTS_DIR}/checkpoint/${PROTENIX_MODEL}.pt" size _why
    if _why="$(_env_missing_reason "${PROTENIX_ENV}")"; then
        echo "${_why}"
        return 0
    fi
    if [[ ! -f "${ckpt}" ]]; then
        echo "no Protenix weights found (env '${PROTENIX_ENV}' is installed)"
        return 0
    fi
    size="$(stat -Lc %s "${ckpt}" 2>/dev/null || echo 0)"
    if [[ "${size}" != "${PROTENIX_CKPT_BYTES}" ]]; then
        echo "Protenix checkpoint is ${size} bytes, expected ${PROTENIX_CKPT_BYTES} (env '${PROTENIX_ENV}' is installed)"
        return 0
    fi
    return 1
}

_PANEL_NOTE="panel Boltz-2 + Protenix + ESMFold2; scores from different panels are not on one scale."
if [[ "$SECOND_ENGINE" == "protenix" && $SKIP_PROTENIX -eq 0 ]]; then
    # Explicit --second-engine protenix: used if it can run, else skipped BY NAME -- never swapped.
    if _why="$(_protenix_unusable_reason)"; then
        echo "[note] ${_why} — Protenix refolding will be skipped."
        _SKIPPED+=("Protenix: ${_why}")
        echo "        Expected the checkpoint at ${PROTENIX_WEIGHTS_DIR}/checkpoint/${PROTENIX_MODEL}.pt (${PROTENIX_CKPT_BYTES} bytes)."
        echo "        (install with 'binderscout install --tool protenix'; opt-in, no AF3 weights needed)"
        echo ""
        SKIP_PROTENIX=1
    else
        echo "[note] second engine: Protenix (--second-engine protenix); ${_PANEL_NOTE}"
        echo ""
    fi
elif [[ $_AUTO_SECOND -eq 1 && $SKIP_AF3 -eq 1 ]]; then
    # No flag, and the AF3 detection above just dropped AF3 (env or weights). Order, never both:
    #   2. an af3_results.csv with scored rows already in the output dir keeps the slot with AF3: nothing runs, and the
    #      CSV is reported exactly as before this engine existed (a pool refolded elsewhere, or an AF3
    #      env that is absent here, must not silently change the panel);
    #   3. else Protenix, when it is fully usable OR its protenix_results.csv already has scored rows;
    #   4. else nothing new is said and the slot is skipped by name as before.
    # "Present" means SCORED rows (csv_rows counts a non-empty iptm): a header-only or all-blank CSV
    # is not results, so it neither keeps the slot on AF3 nor blocks a usable Protenix.
    if (( $(csv_rows "$AF3_CSV") > 0 )); then
        :   # slot stays AF3; SKIP_AF3 stays 1, the CSV still counts toward the gate and reaches the report
    elif ! _protenix_unusable_reason >/dev/null; then
        SECOND_ENGINE="protenix"
        SKIP_PROTENIX=0
        echo "[note] second engine: Protenix (AF3 not available); ${_PANEL_NOTE}"
        echo ""
    elif (( $(csv_rows "$PROTENIX_CSV") > 0 )); then
        SECOND_ENGINE="protenix"   # nothing runs: the existing CSV is reported
        echo "[note] second engine: Protenix (AF3 not available; existing protenix_results.csv reported, nothing refolded); ${_PANEL_NOTE}"
        echo ""
    fi
fi

# The primary engine must be one of THIS panel: af3 only while AF3 holds the slot, protenix only
# while Protenix does. Refused rather than reinterpreted -- the panel is what the ranking means.
if [[ "$PRIMARY_ENGINE" == "af3" && "$SECOND_ENGINE" != "af3" ]] \
    || [[ "$PRIMARY_ENGINE" == "protenix" && "$SECOND_ENGINE" != "protenix" ]]; then
    echo "Error: --primary-engine ${PRIMARY_ENGINE} is not in this panel: the second slot holds ${SECOND_ENGINE}" >&2
    echo "       (panel: Boltz-2 + ${SECOND_ENGINE} + ESMFold2). Choose boltz, esmfold2 or ${SECOND_ENGINE}," >&2
    echo "       or pass --second-engine ${PRIMARY_ENGINE}." >&2
    exit 2
fi

# Auto-detect ESMFold2 availability unless user skipped it
if [[ $SKIP_ESMFOLD2 -eq 0 ]]; then
    if _why="$(_env_missing_reason "${ESMFOLD2_ENV}")"; then
        echo "[note] ${_why} — ESMFold2 refolding will be skipped."
        _SKIPPED+=("ESMFold2: ${_why}")
        echo "        (install with: binderscout install --tool esmfold2; see Evaluator/envs/binder-eval-esmfold2.yml)"
        echo ""
        SKIP_ESMFOLD2=1
    fi
fi

# Auto-detect SoluProt availability unless user skipped it
if [[ $SKIP_SOLUPROT -eq 0 ]]; then
    if _why="$(_env_missing_reason "${SOLUPROT_ENV}")"; then
        echo "[note] ${_why} — SoluProt solubility screen will be skipped."
        _SKIPPED+=("SoluProt: ${_why}")
        echo "        (install with: binderscout install --tool soluprot — ranking is unaffected)"
        echo ""
        SKIP_SOLUPROT=1
    fi
fi

# The env name is necessary and not sufficient. SoluProt cannot score without
# USEARCH, and a `--tool all` install that failed at the USEARCH build leaves the
# env standing -- so the name-only check above passed, the screen ran, and the
# missing binary surfaced mid-evaluation as a twelve-line Python traceback plus a
# red `ERROR conda.cli.main_run`. The handling underneath was already right (the
# run continues, says so, and says refolding is unaffected) but a scientist reads
# a traceback as a broken run. AF3 gets a tidy one-line [note] for the same
# condition; so should this.
#
# Mirrors soluprot_runner._resolve_usearch's search order exactly, so a screen
# that WOULD work is never skipped here.
find_usearch() {
    local dir="${SOLUPROT_HOME:-${SCRIPT_DIR}/tools/soluprot}" arch
    arch="$(uname -m)"
    if [[ -n "${SOLUPROT_USEARCH:-}" && -x "${SOLUPROT_USEARCH}" ]]; then
        echo "${SOLUPROT_USEARCH}"; return 0
    fi
    local cand
    for cand in "${dir}/usearch.${arch}" "${dir}/usearch"; do
        [[ -x "${cand}" ]] && { echo "${cand}"; return 0; }
    done
    command -v usearch 2>/dev/null && return 0
    return 1
}

if [[ $SKIP_SOLUPROT -eq 0 ]] && ! find_usearch >/dev/null 2>&1; then
    echo "[note] USEARCH not found — SoluProt solubility screen will be skipped."
    echo "        SoluProt needs it for the identity feature and cannot score without it."
    echo "        (build it with: binderscout install --tool soluprot — ranking is unaffected)"
    echo ""
    SKIP_SOLUPROT=1
fi

# Auto-detect TmProt availability unless the user skipped it
if [[ $SKIP_TMPROT -eq 0 ]]; then
    if _why="$(_env_missing_reason "${TMPROT_ENV}")"; then
        echo "[note] ${_why} — TmProt melting-temperature screen will be skipped."
        _SKIPPED+=("TmProt: ${_why}")
        echo "        (install with: binderscout install --tool tmprot — ranking is unaffected)"
        echo ""
        SKIP_TMPROT=1
    fi
fi

# And the same gap for TmProt, which has no equivalent on master at all. Its
# binary is resolved INSIDE the child env (tmprot_runner._resolve_tmprot_bin:
# $TMPROT_BIN, else `tmprot` on that env's PATH), so an env that exists without
# the console script raises RuntimeError mid-evaluation -- the identical shape to
# the SoluProt traceback above. Ask the env once, here, where the answer costs
# one `conda run` instead of a step's worth of confusion.
if [[ $SKIP_TMPROT -eq 0 ]]; then
    if ! conda run -n "${TMPROT_ENV}" bash -c \
            'command -v "${TMPROT_BIN:-tmprot}" >/dev/null 2>&1' >/dev/null 2>&1; then
        echo "[note] the 'tmprot' command is not available in '${TMPROT_ENV}' — Tm screen will be skipped."
        echo "        (re-install with: binderscout install --tool tmprot — ranking is unaffected)"
        echo ""
        SKIP_TMPROT=1
    fi
fi

# Name every optional engine skipped for want of an env, with the reason. The [note] lines above
# are easy to miss in a long log, and a skipped engine changes what the ranking means.
if (( ${#_SKIPPED[@]} )); then
    for _s in "${_SKIPPED[@]}"; do
        echo "[skipped] ${_s}"
    done
    echo ""
fi

# Nothing below runs without conda (every step is a `conda run -n binder-eval ...`).
if ! command -v conda >/dev/null 2>&1; then
    echo "Error: conda not found (looked at \$BINDERSCOUT_CONDA, ${_BINDERSCOUT_DIR}/conda, \$CONDA_EXE, \$CONDA_PREFIX, PATH and the usual install locations)." >&2
    echo "       Install it with 'binderscout install --tool evaluator', or export BINDERSCOUT_CONDA=<its base directory>." >&2
    exit 1
fi

# --- Cross-engine gate vs. the engines that will actually run ---------------
# The ranking gates on how many INDEPENDENT engines refolded each design (default 3).
# AF3 is opt-in because its weights are DeepMind-gated, not because it is large:
# measured (docs/data/gpu_benchmark_2026-09-18/) it is the CHEAPEST engine here,
# 2.3-5.2 GB flat from 150 to 900 tokens. Boltz-2 is the memory-dominant one
# (44 GB at 600 tokens, 140 GB at 900), and ESMFold2 has a ~14 GB floor already
# at 150 tokens. So on most hosts only Boltz-2 + ESMFold2 run and
# every design fails a gate of 3 — ranked last, with an empty top of the list. The
# report warns after the fact; by then the GPU time is already spent, so say it here.
# Deliberately NOT auto-lowered: the gate is part of what the ranking means, and
# silently deriving it from the local install would make two operators with the same
# designs produce different rankings.
# Arithmetic ASSIGNMENT, not `(( n++ ))`: post-increment evaluates to the OLD value, so
# the first increment from 0 returns 0 — false — and `set -e` kills the script here.
# Per-engine result CSVs. Defined here, before the engine count below reads them, because
# an engine that is skipped but already has its CSV on disk still counts toward the gate.
# (BOLTZ2_CSV, AF3_CSV, PROTENIX_CSV, ESMFOLD2_CSV are set above the second-slot block, which reads them.)

# What matters for the gate is how many engines the REPORT will have, not how many run
# this invocation: a skipped engine whose CSV is already on disk still counts.  Counting
# only the running ones made a top-up run warn that every design would fail the gate when
# all three engines were in fact present.
_N_ENGINES=0
# "Its CSV is on disk" means SCORED rows (csv_rows keys on the `iptm` column all four engines write):
# a header-only or all-blank CSV is not an engine's results, so it is neither counted here nor, below,
# passed to the report. Counting the file hid the "gate defaults to 3" warning behind an empty CSV.
(( SKIP_BOLTZ2   == 0 )) || (( $(csv_rows "$BOLTZ2_CSV") > 0 )) && _N_ENGINES=$(( _N_ENGINES + 1 ))
if [[ "$SECOND_ENGINE" == "protenix" ]]; then
    (( SKIP_PROTENIX == 0 )) || (( $(csv_rows "$PROTENIX_CSV") > 0 )) && _N_ENGINES=$(( _N_ENGINES + 1 ))
else
    (( SKIP_AF3      == 0 )) || (( $(csv_rows "$AF3_CSV") > 0 )) && _N_ENGINES=$(( _N_ENGINES + 1 ))
fi
(( SKIP_ESMFOLD2 == 0 )) || (( $(csv_rows "$ESMFOLD2_CSV") > 0 )) && _N_ENGINES=$(( _N_ENGINES + 1 ))
if [[ -z "$MIN_ENGINES" ]] && (( _N_ENGINES < 3 )); then
    echo "[warn] ${_N_ENGINES} refold engine(s) will reach the report, but the cross-engine gate defaults to 3."
    if [[ "$SECOND_ENGINE" == "protenix" && $SKIP_PROTENIX -eq 1 ]] && (( $(csv_rows "$PROTENIX_CSV") == 0 )); then
        echo "       The second slot is Protenix and it is not running (no $(basename "$PROTENIX_CSV") either)."
    fi
    echo "       Every design will fail the gate and be ranked last, leaving no ranked shortlist."
    if (( _N_ENGINES >= 2 )); then
        echo "       To rank on the engines you have, re-run with:  --min-engines ${_N_ENGINES}"
    else
        echo "       A cross-engine ranking needs at least 2 engines; install another refold"
        echo "       engine (binderscout install --tool esmfold2) before trusting the ranking."
    fi
    echo ""
elif [[ -n "$MIN_ENGINES" ]] && (( _N_ENGINES < MIN_ENGINES )); then
    echo "[warn] --min-engines ${MIN_ENGINES} was requested but only ${_N_ENGINES} engine(s) will run —"
    echo "       every design will fail the gate."
    echo ""
fi

# --- Step 0: Normalise sequences to FASTA ----------------------------------
FASTA="$OUTPUT/sequences.fasta"
# The generated run_evaluate.sh passes --sequences "$OUTPUT/sequences.fasta", i.e. $SEQUENCES and
# $FASTA are the SAME file. Parse into a temporary file and move it into place, so the input is
# never read and written at once and a failed parse leaves the original untouched.
normalise_sequences () {   # $1=input  $2=output FASTA
    local tmp="$2.parse.$$"
    if ! conda run -n binder-eval binder-compare parse-seqs --input "$1" --output "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    mv -f "$tmp" "$2"
}
echo "[step 0] Parsing sequences → $FASTA"
normalise_sequences "$SEQUENCES" "$FASTA"
SEQUENCES="$FASTA"

# --- Step 1: Boltz-2 refolding ---------------------------------------------
SOLUPROT_CSV="$OUTPUT/soluprot_results.csv"
TMPROT_CSV="$OUTPUT/tmprot_results.csv"
TMPROT_OK=0
SOLUPROT_OK=1   # cleared if the optional screen fails; see Step 0.5

# Step counter: 1 (report) + 1 per engine not skipped + 1 if TmProt ran.
# (SoluProt and TmProt each print a step line and are each counted below.)
N_STEPS=1  # report
[[ $SKIP_TMPROT -eq 0 ]] && (( N_STEPS++ ))
if [[ $CONCURRENT -eq 1 ]]; then
    (( N_STEPS++ ))            # the engines run as a single concurrent step
else
    [[ $SKIP_BOLTZ2 -eq 0 ]]   && (( N_STEPS++ ))
    [[ $SKIP_AF3 -eq 0 ]]      && (( N_STEPS++ ))
    [[ $SKIP_PROTENIX -eq 0 ]] && (( N_STEPS++ ))
    [[ $SKIP_ESMFOLD2 -eq 0 ]] && (( N_STEPS++ ))
fi
[[ $SKIP_SOLUPROT -eq 0 ]] && (( N_STEPS++ ))
STEP=1

# --- Step 0.5: SoluProt solubility screen (optional, runs before refolding) ─
# Runs before the refold engines because it is cheap and CPU-only, so its column is
# already on every design by the time the report is written. It NEVER drops a design --
# the score is a label (see the --soluprot-filter note in the usage block above).
if [[ $SKIP_SOLUPROT -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] SoluProt screen     (soluprot env: ${SOLUPROT_ENV}, threshold: ${SOLUPROT_THRESHOLD})..."
    # binder-compare runs in binder-eval (py3.10); SoluProt's soluprot.py runs in
    # the py3.7 ${SOLUPROT_ENV} via $SOLUPROT_PYTHON. The two envs are mutually
    # exclusive — SoluProt needs scikit-learn 0.20.x / py3.7, binder-comparison
    # needs py3.10+ — so we cannot run binder-compare inside ${SOLUPROT_ENV}.
    # Guarded, and with its stderr kept: under `set -e` a bare assignment from a failing
    # command substitution exits the whole script, so a half-built ${SOLUPROT_ENV} (which
    # the name-only auto-detect above cannot see) killed the evaluation right after the
    # step header printed and before any refold engine ran -- silently, because the
    # error went to /dev/null. An empty SOLUPROT_PYTHON is fine: soluprot_runner.py
    # treats it as unset and falls back, and the guarded call below catches the rest.
    if ! SOLUPROT_PYTHON="$(conda run -n "${SOLUPROT_ENV}" python -c 'import sys; print(sys.executable)')"; then
        SOLUPROT_PYTHON=""
        echo "[soluprot] WARNING: cannot resolve python in ${SOLUPROT_ENV} — trying the runner's fallback." >&2
    fi
    export SOLUPROT_PYTHON
    # SoluProt is an OPTIONAL pre-screen, so a failure must not take the whole
    # evaluation down with it (it did: a missing USEARCH binary aborted the run
    # before any refold engine started).  There is no longer any exception: the
    # screen only labels, so continuing without it cannot change which designs
    # get refolded.
    if conda run -n binder-eval binder-compare filter-soluprot \
            --sequences "$SEQUENCES" \
            -o          "$SOLUPROT_CSV" \
            --threshold "$SOLUPROT_THRESHOLD"; then
        SOLUPROT_OK=1
    else
        SOLUPROT_OK=0
        echo "[soluprot] WARNING: screen failed — continuing WITHOUT the solubility" >&2
        echo "[soluprot]          column. Refolding is unaffected. See the error above." >&2
    fi
    (( STEP++ ))
fi

# --- Step 0.6: TmProt melting-temperature screen ---------------------------
# MUST stay below the initialisation block. It reads STEP, N_STEPS and TMPROT_CSV
# and sets TMPROT_OK, all of which that block owns. It used to sit ~90 lines
# ABOVE it, so on any host where the binder-eval-tmprot env exists (auto-detected,
# so no flag needed) `set -u` killed the entire evaluation with
# "STEP: unbound variable" before step 0 and before any refold engine ran -- and
# even past that, TMPROT_OK was reset to 0 underneath it, so the report could
# never have received --tmprot-results. Fixed 2026-09-29.
#
# Sequence-only, no GPU, and ADVISORY ONLY. Like SoluProt it is a label and there
# must be no filter mode: Tm predictors are trained on natural proteins
# and are out of domain on the hyperstable de novo miniproteins this pipeline
# produces (2.0 assessment item D1 -- "proceed as a screen, never a ranking
# term"). The column lands in the report; it never drops a design and never
# enters rank_designs().
#
# binder-compare is installed inside ${TMPROT_ENV}, so this runs there directly
# rather than shelling out the way SoluProt has to.
if [[ $SKIP_TMPROT -eq 0 ]]; then
    echo "[step ${STEP}/${N_STEPS}] TmProt screen       (env: ${TMPROT_ENV}, thermostable >= ${TMPROT_THRESHOLD} C)..."
    if conda run -n "${TMPROT_ENV}" binder-compare screen-tmprot \
            --sequences "$SEQUENCES" \
            -o          "$TMPROT_CSV" \
            --threshold "$TMPROT_THRESHOLD"; then
        TMPROT_OK=1
    else
        TMPROT_OK=0
        # Advisory screen: never take the evaluation down with it. Nothing about
        # the refold pool changes when this fails -- only a report column goes
        # missing. Same for SoluProt above, since 2026-09-28.
        echo "[tmprot] WARNING: screen failed - continuing WITHOUT the Tm column." >&2
    fi
    STEP=$(( STEP + 1 ))
    echo ""
fi


# --- Step 0.9: pre-warm the shared target MSA ──────────────────────────────
# Fetch ONCE, before any engine loads a model, so all three read the same cached
# a3m. Each engine also enforces this itself, so correctness does not depend on
# this step -- but without it a cold-cache failure surfaces only after the first
# engine has loaded its weights, which on AF3 is minutes of GPU time.
if [[ $SKIP_BOLTZ2 -eq 0 || $SKIP_AF3 -eq 0 || $SKIP_PROTENIX -eq 0 || $SKIP_ESMFOLD2 -eq 0 ]]; then
    echo "[msa] Pre-warming shared target MSA cache..."
    if conda run -n binder-eval python -m binder_comparison.refolding.target_msa \
            --target-seq "$TARGET_SEQ" >/dev/null 2>&1; then
        echo "[msa] Target MSA ready — all engines will read the same cached a3m."
    elif [[ $ALLOW_NO_MSA -eq 1 ]]; then
        echo "[msa] WARNING: could not obtain the target MSA; --allow-no-msa given, so engines"
        echo "[msa]          will fold the target single-sequence. Their scores are NOT directly"
        echo "[msa]          comparable to an MSA run, and this is recorded in target_msa_mode.json."
        export BINDERSCOUT_ALLOW_NO_MSA=1
    else
        echo "Error: could not obtain the target MSA, and engines would otherwise disagree on" >&2
        echo "       whether they used one. The MSA drives target fold confidence, so an" >&2
        echo "       MSA-less engine is systematically penalised and silently drags" >&2
        echo "       consensus_iptm_mean down." >&2
        echo "" >&2
        echo "  Pre-warm once (also works for copying to an air-gapped node):" >&2
        echo "    conda run -n binder-eval python -m binder_comparison.refolding.target_msa \\" >&2
        echo "        --target-seq '<TARGET_SEQ>'" >&2
        echo "" >&2
        echo "  Or proceed single-sequence on every engine (recorded in the report):" >&2
        echo "    $0 --allow-no-msa ...   (or BINDERSCOUT_ALLOW_NO_MSA=1)" >&2
        exit 2
    fi
fi

# --- GPU memory ceiling ----------------------------------------------------
# On unified-memory hosts (GB10 / DGX Spark) the GPU pool IS system RAM:
# cudaMemGetInfo total == SC_PHYS_PAGES == 121.7 GiB. An engine sizing itself as a
# fraction of "device total" therefore reserves a fraction of the WHOLE MACHINE and
# starves the kernel -- that is what hard-rebooted a GB10 host on 2026-08-18.
#
# Each engine also computes its own absolute-GiB fraction
# (binder_comparison.refolding.memory_policy), but that is COOPERATIVE. The hard
# ceiling is a CUDA MPS per-client limit; cgroups do not contain NVIDIA allocations
# on driver 580.x (measured).
GUARD="$SCRIPT_DIR/../tools/gpu_mem_guard.sh"
MPS_ACTIVE=0
MPS_WE_STARTED=0

gpu_guard_up () {
    [[ $USE_GPU_GUARD -eq 1 ]] || { echo "[gpu-guard] disabled by --no-gpu-guard"; return 1; }
    [[ -x "$GUARD" ]] || { echo "[gpu-guard] $GUARD not executable — cooperative caps only" >&2; return 1; }
    if "$GUARD" is-up 2>/dev/null; then
        MPS_ACTIVE=1; echo "[gpu-guard] MPS already running — reusing it"; return 0
    fi
    if "$GUARD" start "$GPU_CAP_BOLTZ2" >/dev/null 2>&1 && "$GUARD" is-up 2>/dev/null; then
        MPS_ACTIVE=1; MPS_WE_STARTED=1
        echo "[gpu-guard] MPS started (fallback cap $GPU_CAP_BOLTZ2; each engine sets its own)"
        return 0
    fi
    echo "[gpu-guard] WARNING: could not start MPS — no hard memory ceiling this run." >&2
    return 1
}
gpu_guard_down () { if [[ $MPS_WE_STARTED -eq 1 ]]; then "$GUARD" stop >/dev/null 2>&1 || true; fi; }
# EXIT alone is not enough: a SIGTERM (timeout, Ctrl-C, a scheduler) can leave the MPS
# daemon running and holding machine-wide state. Re-raise as an exit so EXIT fires.
trap gpu_guard_down EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Emit the per-client cap as an env assignment, or nothing when MPS is not active.
cap_env () { if [[ $MPS_ACTIVE -eq 1 ]]; then printf 'CUDA_MPS_PINNED_DEVICE_MEM_LIMIT=0=%s' "$1"; fi; }

gpu_guard_up || true

# --- engine definitions (one place; sequential and concurrent both use these) --
# shellcheck disable=SC2046  # cap_env deliberately expands to 0 or 1 words
engine_boltz2 () {
    local f=""; [[ $RESUME -eq 1 ]] && f="--resume"
    # --output-dir is NOT optional here, even though refold-boltz2 defaults it.
    # Its default is CWD-relative ./refold_boltz2, so without this every run
    # shares one directory keyed on where evaluate.sh happened to be invoked
    # from -- and --resume then reads THAT directory's accumulated
    # refold_designs.csv. Measured on a GB10 2026-10-04: a fresh 20-design run
    # resumed against 86 unrelated completed binders, folded nothing, and
    # published 260 rows from previous runs as its result. csv_rows() counts
    # non-empty iptm, so the guard reported "ok -- 260 new row(s)" over it.
    # AF3 and ESMFold2 already scope their output dirs this way.
    env $(cap_env "$GPU_CAP_BOLTZ2") "$MOSAIC_VENV/bin/binder-compare" refold-boltz2 \
        --sequences "$SEQUENCES" --target-seq "$TARGET_SEQ" -o "$BOLTZ2_CSV" \
        --output-dir "$OUTPUT/refold_boltz2" $f
}
# shellcheck disable=SC2046
engine_af3 () {
    local f=""; [[ $RESUME -eq 1 ]] && f="--resume"
    env $(cap_env "$GPU_CAP_AF3") conda run -n "${AF3_ENV}" binder-compare refold-af3 \
        --sequences "$SEQUENCES" --target-seq "$TARGET_SEQ" -o "$AF3_CSV" \
        --output-dir "$OUTPUT/refold_af3" $f
}
# shellcheck disable=SC2046
engine_protenix () {
    local f=""; [[ $RESUME -eq 1 ]] && f="--resume"
    # No kernel option is passed on purpose: refold-protenix forces the torch kernels itself (R5) and
    # refuses any attempt to set them. It must run INSIDE the Protenix env, hence `conda run -n`.
    env $(cap_env "$GPU_CAP_PROTENIX") conda run -n "${PROTENIX_ENV}" binder-compare refold-protenix \
        --sequences "$SEQUENCES" --target-seq "$TARGET_SEQ" -o "$PROTENIX_CSV" \
        --output-dir "$OUTPUT/refold_protenix" --model-dir "$PROTENIX_WEIGHTS_DIR" $f
}
# The second slot: one function the launch paths call, whichever engine holds it.
engine_second () {
    if [[ "$SECOND_ENGINE" == "protenix" ]]; then engine_protenix; else engine_af3; fi
}
# shellcheck disable=SC2046
engine_esmfold2 () {
    local f=""; [[ $RESUME -eq 1 ]] && f="--resume"
    env $(cap_env "$GPU_CAP_ESMFOLD2") conda run -n "${ESMFOLD2_ENV}" binder-compare refold-esmfold2 \
        --sequences "$SEQUENCES" --target-seq "$TARGET_SEQ" -o "$ESMFOLD2_CSV" \
        --output-dir "$OUTPUT/refold_esmfold2" --model "${ESMFOLD2_MODEL}" $f
}

# --- engine result guards ---------------------------------------------------
# 2026-09-16 ESMFold2 died on a cluster node with a TypeError from an unpinned model
# revision, wrote 0 rows, and evaluate.sh printed REFOLD_DONE and exited 0 -- an
# entire engine contributing nothing to a >=3-engine gate, invisibly. An engine
# that exits 0 and writes nothing is the same failure wearing a success code
# (cf. the AF3 empty-rows incident of 2026-08-21), so rc alone is not enough:
# the CSV must actually gain rows.
# (csv_rows is defined above the second-slot block, which needs it.)

# A row delta is not evidence the POOL was refolded. A refold that resumes off a stale CSV
# shared with earlier pools gains hundreds of rows, refolds none of this pool, and exits 0;
# the delta alone then read "ok -- 1003 new row(s)" while every design of the pool was
# missing from that engine and nothing could clear the cross-engine gate. So count the pool
# sequences the CSV actually carries, scored: `sequence` is the column every engine writes
# and the one the report's merge joins on, and a row with a blank `iptm` is not a refold
# (see csv_rows above). Columns are found by name -- the engines' CSVs differ in order.
pool_coverage () {   # $1=engine csv  $2=sequences fasta  [$3=target]  -> count of pool seqs scored in it
    [[ -f "$1" && -f "$2" ]] || { echo 0; return; }
    # $3, when given, is the run's target: a row folded against ANOTHER target is not coverage. --resume
    # keys on the binder sequence only, so re-running into the same output directory with a different
    # --target-seq would otherwise find every design "complete" and report the old target's scores.
    # A CSV without a target_sequence column cannot be checked and still counts.
    local tgt="${3//[[:space:]]/}"
    awk -v FS=, -v tgt="$tgt" '
        NR == FNR {
            if (FNR == 1) { for (i = 1; i <= NF; i++) { if ($i == "sequence") col = i; if ($i == "iptm") sc = i; if ($i == "target_sequence") tc = i }; next }
            if (col && sc) {
                v = $col; gsub(/[ \t\r]/, "", v)
                ok = 1
                if (tgt != "" && tc) { tv = $tc; gsub(/[ \t\r]/, "", tv); ok = (toupper(tv) == toupper(tgt)) }
                if (v != "" && $sc != "" && ok) seen[toupper(v)] = 1
            }
            next
        }
        # `cur` accumulates one (possibly wrapped) FASTA record. It must not share a name
        # with anything in the CSV pass above: awk variables are global, so a leftover
        # value counted the last CSV row as a pool hit.
        /^>/ { if (cur != "" && toupper(cur) in seen) n++; cur = ""; next }
        { t = $0; gsub(/[ \t\r]/, "", t); cur = cur t }
        END { if (cur != "" && toupper(cur) in seen) n++; print n + 0 }
    ' "$1" "$2"
}

fasta_count () { if [[ -f "$1" ]]; then grep -c '^>' "$1"; else echo 0; fi; }

engine_csv () {
    case "$1" in
        boltz2)   echo "$BOLTZ2_CSV" ;;
        af3)      echo "$AF3_CSV" ;;
        protenix) echo "$PROTENIX_CSV" ;;
        esmfold2) echo "$ESMFOLD2_CSV" ;;
        *)        echo "" ;;
    esac
}

# $1=label  $2=csv  $3=rows before  $4=rc
check_engine_rows () {
    local name=$1 csv=$2 before=$3 rc=$4 after covered pool
    after=$(csv_rows "$csv")
    if [[ $rc -ne 0 ]]; then
        echo "Error: $name refolding failed (rc=$rc). Refusing to report a partial pool." >&2
        return 1
    fi
    if [[ "$after" -le "$before" ]]; then
        # --resume on a finished run skips every design and exits 0 having written nothing. That
        # is success if the CSV already carries a scored row for EVERY pool design; it is only an
        # error when the pool is not covered (a stalled engine, a blank CSV, another pool's rows).
        covered=$(pool_coverage "$csv" "$SEQUENCES" "${TARGET_SEQ:-}")
        pool=$(fasta_count "$SEQUENCES")
        if [[ "$pool" -gt 0 && "$covered" -ge "$pool" ]]; then
            echo "    [$name] ok -- already complete: $covered/$pool pool design(s) scored in $csv, no new rows needed"
            return 0
        fi
        echo "Error: $name exited 0 but wrote no new SCORED rows to $csv ($before -> $after)." >&2
        echo "       (rows folded against a DIFFERENT target than this run's --target-seq do not count as coverage.)" >&2
        echo "       Counted on a non-empty iptm, so a file full of blank rows counts as zero." >&2
        echo "       A missing engine silently breaks the cross-engine gate -- aborting." >&2
        return 1
    fi
    covered=$(pool_coverage "$csv" "$SEQUENCES" "${TARGET_SEQ:-}")
    pool=$(fasta_count "$SEQUENCES")
    if [[ "$covered" -eq 0 ]]; then
        echo "Error: $name wrote $((after - before)) new SCORED row(s) to $csv, but NONE of them is a" >&2
        echo "       design in $SEQUENCES ($pool in the pool)." >&2
        echo "       Rows from another pool cannot rank this one. Likely a stale CSV or" >&2
        echo "       structure directory being resumed off -- aborting." >&2
        return 1
    fi
    if [[ "$covered" -lt "$pool" ]]; then
        echo "    [$name] WARNING -- covers $covered/$pool pool design(s); the rest will fail" >&2
        echo "               the cross-engine gate." >&2
    fi
    echo "    [$name] ok -- $covered/$pool pool design(s), $((after - before)) new row(s)"
    return 0
}

# Sequential wrapper. `"$fn"; rc=$?` would abort under `set -e` before the
# message could be printed, so the call is guarded by an if.
run_engine_checked () {   # $1=label  $2=fn  $3=csv
    local name=$1 fn=$2 csv=$3 before rc
    before=$(csv_rows "$csv")
    if "$fn"; then rc=0; else rc=$?; fi
    check_engine_rows "$name" "$csv" "$before" "$rc" || exit 1
}

if [[ $SKIP_BOLTZ2 -eq 1 && ! -f "$BOLTZ2_CSV" ]]; then
    echo "Error: --skip-boltz2 given but $BOLTZ2_CSV not found"; exit 1
fi

if [[ $CONCURRENT -eq 1 ]]; then
    # Concurrency without a hard per-client ceiling is precisely the configuration
    # that took this box down. Refuse rather than warn.
    if [[ $MPS_ACTIVE -ne 1 ]]; then
        echo "Error: --concurrent requires the CUDA MPS ceiling, which is not active." >&2
        echo "       Fix the guard ($GUARD verify) or drop --concurrent." >&2
        exit 2
    fi
    if [[ "$SECOND_ENGINE" == "protenix" ]]; then GPU_CAP_SECOND="$GPU_CAP_PROTENIX"; else GPU_CAP_SECOND="$GPU_CAP_AF3"; fi
    echo "[step ${STEP}/${N_STEPS}] Refolding — ${STAGGER}s staggered starts, caps ${GPU_CAP_BOLTZ2}/${GPU_CAP_SECOND}/${GPU_CAP_ESMFOLD2}"
    # Stagger exists because the measured peak is the simultaneous COLD START -- all
    # engines preallocating at once -- not steady state. On 2026-08-20 a simultaneous
    # launch peaked at 56.2 GiB and logged one NVRM NV_ERR_NO_MEMORY; 40 s later usage
    # had fallen to 37.9 GiB. Serialising the startup costs nothing, because the
    # engines do not finish together anyway.
    E_PIDS=(); E_NAMES=(); E_BEFORE=(); DELAY=0
    launch_engine () {
        local name=$1 fn=$2
        local log="$OUTPUT/refold_${name}.log"
        E_BEFORE+=("$(csv_rows "$(engine_csv "$name")")")
        ( sleep "$DELAY"; "$fn" ) > "$log" 2>&1 &
        E_PIDS+=("$!"); E_NAMES+=("$name")
        echo "    [$name] queued at +${DELAY}s → $log"
        DELAY=$(( DELAY + STAGGER ))
    }
    [[ $SKIP_BOLTZ2 -eq 0 ]]   && launch_engine boltz2   engine_boltz2
    # SKIP_AF3 -eq 0 implies the slot is af3 (SKIP_AF3 is forced to 1 for a protenix slot), so
    # engine_second here is engine_af3; the same holds for the protenix line and the sequential steps.
    [[ $SKIP_AF3 -eq 0 ]]      && launch_engine af3      engine_second
    [[ $SKIP_PROTENIX -eq 0 ]] && launch_engine protenix engine_second
    [[ $SKIP_ESMFOLD2 -eq 0 ]] && launch_engine esmfold2 engine_esmfold2

    ENGINE_FAIL=0
    for i in "${!E_PIDS[@]}"; do
        if wait "${E_PIDS[$i]}"; then rc=0; else rc=$?; fi
        if ! check_engine_rows "${E_NAMES[$i]}" \
                "$(engine_csv "${E_NAMES[$i]}")" "${E_BEFORE[$i]}" "$rc"; then
            echo "    [${E_NAMES[$i]}] last 15 lines:" >&2
            tail -15 "$OUTPUT/refold_${E_NAMES[$i]}.log" | sed 's/^/      /' >&2
            ENGINE_FAIL=1
        fi
    done
    [[ $ENGINE_FAIL -eq 0 ]] || { echo "Error: at least one refold engine failed." >&2; exit 1; }
    (( STEP++ ))
else
    if [[ $SKIP_BOLTZ2 -eq 1 ]]; then
        # No step prefix and no increment: N_STEPS does not count a skipped engine, so
        # numbering one produced "[step 2/1]" for the report. AF3 and ESMFold2 below
        # print nothing when skipped; this branch keeps its message because "using the
        # existing CSV" is worth saying, but it is a note, not a step.
        echo "  Boltz-2 refolding — skipped (using existing $BOLTZ2_CSV)"
    else
        echo "[step ${STEP}/${N_STEPS}] Boltz-2 refolding  (Mosaic venv, cap ${GPU_CAP_BOLTZ2})..."
        run_engine_checked "Boltz-2" engine_boltz2 "$BOLTZ2_CSV"
        (( STEP++ ))
    fi

    # (the slot invariant noted at the concurrent launch holds here too: SKIP_AF3 -eq 0 means af3)
    if [[ $SKIP_AF3 -eq 0 ]]; then
        echo "[step ${STEP}/${N_STEPS}] AF3 refolding       (conda env: ${AF3_ENV}, cap ${GPU_CAP_AF3})..."
        run_engine_checked "AF3" engine_second "$AF3_CSV"
        (( STEP++ ))
    fi

    if [[ $SKIP_PROTENIX -eq 0 ]]; then
        echo "[step ${STEP}/${N_STEPS}] Protenix refolding  (conda env: ${PROTENIX_ENV}, cap ${GPU_CAP_PROTENIX})..."
        run_engine_checked "Protenix" engine_second "$PROTENIX_CSV"
        (( STEP++ ))
    fi

    if [[ $SKIP_ESMFOLD2 -eq 0 ]]; then
        echo "[step ${STEP}/${N_STEPS}] ESMFold2 refolding  (conda env: ${ESMFOLD2_ENV}, cap ${GPU_CAP_ESMFOLD2})..."
        run_engine_checked "ESMFold2" engine_esmfold2 "$ESMFOLD2_CSV"
        (( STEP++ ))
    fi
fi

# --- Report ----------------------------------------------------------------
echo "[step ${STEP}/${N_STEPS}] Generating report   (binder-eval)..."
REPORT_ARGS=()
if (( SKIP_BOLTZ2 == 0 )) || (( $(csv_rows "$BOLTZ2_CSV") > 0 )); then
    REPORT_ARGS+=(--boltz2-results "$BOLTZ2_CSV")
fi
REPORT_ARGS+=(
    --sequences      "$SEQUENCES"
    -o               "$OUTPUT/report"
)
# Skipping an engine means "do not RUN it", never "discard results it already has".
# Boltz-2 has always been passed unconditionally, but AF3 and ESMFold2 were gated on
# their skip flag, so a top-up run — re-running one engine over a directory where the
# others already succeeded — silently dropped those engines from the report and every
# design failed the >=3-engine gate. That is the same silent-demotion failure the
# ESMC-6B bug caused: a design must not be demoted for a bookkeeping reason and have
# that read as a quality judgement. Include any engine whose CSV is present.
# The second slot holds ONE engine. The AF3 slot is passed exactly as ever (--af3-results, no
# --second-engine); the Protenix slot is named, so the report records the right panel. A CSV left in
# the output directory by the engine that does NOT hold the slot is never passed -- columns of the
# other engine are never averaged in (R3) -- and the operator is told.
if [[ "$SECOND_ENGINE" == "protenix" ]]; then
    REPORT_ARGS+=(--second-engine protenix)
    if (( $(csv_rows "$PROTENIX_CSV") > 0 )); then
        REPORT_ARGS+=(--second-results "$PROTENIX_CSV")
    fi
    if [[ -f "$AF3_CSV" ]]; then
        echo "[note] ignoring $AF3_CSV: the second slot holds Protenix in this run."
    fi
else
    if (( $(csv_rows "$AF3_CSV") > 0 )); then
        REPORT_ARGS+=(--af3-results "$AF3_CSV")
    fi
    if [[ -f "$PROTENIX_CSV" ]]; then
        echo "[note] ignoring $PROTENIX_CSV: the second slot holds AF3 in this run."
    fi
fi
if (( $(csv_rows "$ESMFOLD2_CSV") > 0 )); then
    REPORT_ARGS+=(--esmfold2-results "$ESMFOLD2_CSV")
fi
if [[ $SKIP_SOLUPROT -eq 0 && $SOLUPROT_OK -eq 1 && -f "$SOLUPROT_CSV" ]]; then
    REPORT_ARGS+=(--soluprot-results "$SOLUPROT_CSV")
fi
if [[ $SKIP_TMPROT -eq 0 && $TMPROT_OK -eq 1 && -f "$TMPROT_CSV" ]]; then
    REPORT_ARGS+=(--tmprot-results "$TMPROT_CSV")
fi
# Each tool's OWN native CSV, auto-discovered under --tool-root. discover_tool_csvs.py
# knows the output layout of all eight tools and prints ready-made flags, one token
# per line ("--tool-csv" then "name=path"). Without this the report has only the
# refold-derived numbers, and a tool's own metrics and rank never appear.
if (( ${#TOOL_ROOTS[@]} )); then
    _discover="$SCRIPT_DIR/scripts/discover_tool_csvs.py"
    if [[ -f "$_discover" ]]; then
        _n_tool_csv=0
        while IFS= read -r _line; do
            [[ -n "$_line" ]] || continue
            REPORT_ARGS+=("$_line")
            [[ "$_line" == "--tool-csv" ]] || _n_tool_csv=$((_n_tool_csv + 1))
        done < <(conda run -n binder-eval python "$_discover" "${TOOL_ROOTS[@]}" 2>/dev/null)
        echo "  native tool CSVs discovered: ${_n_tool_csv}"
    else
        echo "  [note] discover_tool_csvs.py not found at $_discover — no native tool CSVs attached."
    fi
fi
# RFD3 and RFD4-Proteina are diffusion models that emit NO quality score of their
# own, so their native blocks would otherwise be ordered by mpnn_sequence_recovery
# (RFD3 -- a sequence proxy with no binding signal) or by nothing at all (RFD4
# writes structures and no table, and its metrics block is disabled at generation).
# Rank them instead by the Boltz-2 fold-back, which is the field-standard recipe
# (diffusion gives geometry, the fold-back gives the rank) and costs NO extra GPU
# here: it re-reads the boltz2 results this run already produced. --only-tool is
# load-bearing: the report treats a --tool-csv file as that tool's whole ranked
# list, so an unfiltered selection would file every tool's designs under one name.
# Appended after discovery so it wins.
if (( $(csv_rows "$BOLTZ2_CSV") > 0 )); then
    for _diffusion_tool in rfd3 rfd4; do
        grep -q "source=$_diffusion_tool" "$SEQUENCES" 2>/dev/null || continue
        _diffusion_rank="$OUTPUT/${_diffusion_tool}_native_rank.csv"
        if conda run -n binder-eval binder-compare prefilter \
            --boltz2-results "$BOLTZ2_CSV" --sequences "$SEQUENCES" \
            --tool "$_diffusion_tool" --only-tool "$_diffusion_tool" \
            --metric ipsae_min -o "$_diffusion_rank" >/dev/null 2>&1; then
            REPORT_ARGS+=(--tool-csv "$_diffusion_tool=$_diffusion_rank")
            echo "  ${_diffusion_tool} native rank from the Boltz-2 fold-back → $(basename "$_diffusion_rank")"
        else
            echo "  [note] ${_diffusion_tool} fold-back ranking failed — its native block falls back to no ordering."
        fi
    done
fi
REPORT_ARGS+=(--primary-engine "$PRIMARY_ENGINE")
if [[ -n "$MIN_ENGINES" ]]; then
    REPORT_ARGS+=(--min-engines "$MIN_ENGINES")
fi
# Inline epitope match (selectivity) — cheap, no extra pass or GPU.
if [[ -n "$EPITOPE_RESIDUES" ]]; then
    REPORT_ARGS+=(--epitope-residues "$EPITOPE_RESIDUES")
fi
conda run -n binder-eval binder-compare report "${REPORT_ARGS[@]}"

# --- Advisory post-steps (opt-in): affinity (Rosetta) + monomer fold check ----
# These need the report's structures + metrics.csv, so they run AFTER pass 1 and
# trigger a second report pass that threads their columns in. Both are advisory
# (never reorder/drop) and off by default.
STRUCT_DIR="$OUTPUT/report/top20_structures"
# Binder chain + Rosetta interface spec depend on the primary engine's chain layout
# (Boltz-2 = binder chain A; AF3/ESMFold2/Protenix = binder chain B).
if [[ "$PRIMARY_ENGINE" == "boltz" ]]; then
    BINDER_CHAIN="A"; ROSETTA_IFACE="A_B"
else
    BINDER_CHAIN="B"; ROSETTA_IFACE="B_A"
fi
EXTRA_REPORT_ARGS=()

if [[ $WITH_AFFINITY -eq 1 ]]; then
    if ! conda env list 2>/dev/null | awk '{print $1}' | grep -qx "${BINDCRAFT_ENV}"; then
        echo "[note] --with-affinity requested but conda env '${BINDCRAFT_ENV}' not found — skipping affinity."
    elif [[ ! -d "$STRUCT_DIR" ]]; then
        echo "[note] --with-affinity: no structures at $STRUCT_DIR — skipping affinity."
    else
        echo "[affinity] Rosetta |dG/dSASA| ranking on top-20 (env: ${BINDCRAFT_ENV}, interface ${ROSETTA_IFACE})…"
        # interface_energy.py keys designs by the structure stem; strip the report's
        # rank-prefix so design_id == binder_id and the affinity join lands.
        AFF_STRUCT_DIR="$OUTPUT/affinity_structures"
        rm -rf "$AFF_STRUCT_DIR"; mkdir -p "$AFF_STRUCT_DIR"
        for f in "$STRUCT_DIR"/rank*_*.pdb "$STRUCT_DIR"/rank*_*.cif; do
            [[ -e "$f" ]] || continue
            base="$(basename "$f")"; stem="${base#rank}"; stem="${stem#*_}"  # drop 'rank\d+_'
            cp "$f" "$AFF_STRUCT_DIR/$stem"
        done
        if conda run -n binder-eval binder-compare affinity \
                --metrics       "$OUTPUT/report/metrics.csv" \
                --structures-dir "$AFF_STRUCT_DIR" \
                --run-rosetta --interface "$ROSETTA_IFACE" --bindcraft-env "$BINDCRAFT_ENV" \
                --energy-out    "$OUTPUT/interface_energy.csv" \
                -o              "$OUTPUT/affinity.csv"; then
            EXTRA_REPORT_ARGS+=(--affinity-results "$OUTPUT/affinity.csv")
        else
            echo "[note] affinity step failed — report will render without the affinity column."
        fi
    fi
fi

if [[ -n "$MONOMER_DIR" ]]; then
    if [[ ! -d "$MONOMER_DIR" ]]; then
        echo "[note] --monomer-dir '$MONOMER_DIR' not a directory — skipping monomer check."
    elif [[ ! -d "$STRUCT_DIR" ]]; then
        echo "[note] --monomer-dir: no in-complex structures at $STRUCT_DIR — skipping monomer check."
    else
        echo "[monomer] context-dependent-fold check (complex vs alone; binder chain ${BINDER_CHAIN})…"
        # Match the monomer files by binder_id: rename complex structures to <binder_id>.pdb.
        CX_DIR="$OUTPUT/monomer_complex_structures"
        rm -rf "$CX_DIR"; mkdir -p "$CX_DIR"
        for f in "$STRUCT_DIR"/rank*_*.pdb; do
            [[ -e "$f" ]] || continue
            base="$(basename "$f")"; stem="${base#rank}"; stem="${stem#*_}"
            cp "$f" "$CX_DIR/$stem"
        done
        if conda run -n binder-eval binder-compare monomer \
                --complex-dir "$CX_DIR" \
                --monomer-dir "$MONOMER_DIR" \
                --binder-chain "$BINDER_CHAIN" \
                -o            "$OUTPUT/monomer_validation.csv"; then
            EXTRA_REPORT_ARGS+=(--monomer-results "$OUTPUT/monomer_validation.csv")
        else
            echo "[note] monomer step found no comparable pairs — report will render without fold_robust."
        fi
    fi
fi

if [[ ${#EXTRA_REPORT_ARGS[@]} -gt 0 ]]; then
    echo "[report] Re-generating report with advisory panels: ${EXTRA_REPORT_ARGS[*]}"
    conda run -n binder-eval binder-compare report "${REPORT_ARGS[@]}" "${EXTRA_REPORT_ARGS[@]}"
fi

echo ""
echo "=== Done ==="
echo "Report : $OUTPUT/report/report.html"
echo "Metrics: $OUTPUT/report/metrics.csv"
