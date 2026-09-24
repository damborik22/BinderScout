#!/bin/bash
# BinderScout Installer
# Installs BindCraft, BoltzGen, Mosaic, PXDesign, Proteina-Complexa,
# Protein-Hunter, RFD3, and/or the Evaluator. AF3 and ESMFold2 are opt-in
# (--tool af3 / --tool esmfold2).
#
# Usage:
#   bash install/install.sh [--tool bindcraft|boltzgen|mosaic|evaluator|pxdesign|proteina-complexa|protein-hunter|rfd3|af3|esmfold2|all] [--cuda VERSION] [--skip-examples] [--yes] [--force]
#   binderscout install [same options]
#
# With no --tool flag, an interactive menu lets you choose which tools to install.

# ─── Constants ────────────────────────────────────────────────────────────────
# BINDERSCOUT_DIR is the repo root (one level above install/).
BINDERSCOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHORTCUTS_DIR="${BINDERSCOUT_DIR}/bin"
LOCAL_CONDA_DIR="${BINDERSCOUT_DIR}/conda"
LOG_FILE="${BINDERSCOUT_DIR}/install.log"

BINDCRAFT_DIR="${BINDERSCOUT_DIR}/BindCraft"
BOLTZGEN_DIR="${BINDERSCOUT_DIR}/BoltzGen"
MOSAIC_DIR="${BINDERSCOUT_DIR}/Mosaic"
EVALUATOR_DIR="${BINDERSCOUT_DIR}/Evaluator"

# Pinned commits for reproducible installs (x86_64 clones only; aarch64 uses bundled)
BINDCRAFT_COMMIT="7cd4ace"
BOLTZGEN_COMMIT="da0f092"
MOSAIC_COMMIT="82593a8"

PXDESIGN_REPO="https://github.com/bytedance/PXDesign.git"
PXDESIGN_COMMIT="HEAD"
PXDESIGN_DIR="${BINDERSCOUT_DIR}/PXDesign"
PROTEINA_COMPLEXA_REPO="https://github.com/NVIDIA-Digital-Bio/proteina-complexa.git"
PROTEINA_COMPLEXA_COMMIT="HEAD"
PROTEINA_COMPLEXA_DIR="${BINDERSCOUT_DIR}/Proteina-Complexa"
PROTEIN_HUNTER_REPO="https://github.com/yehlincho/Protein-Hunter.git"
PROTEIN_HUNTER_COMMIT="d4bd9515882c2aa81e97f3d3bf7f42247a9fe80c"
PROTEIN_HUNTER_DIR="${BINDERSCOUT_DIR}/Protein-Hunter"
# RFD3 / Foundry (Baker lab's RFdiffusion3, BSD-3, commercial-use OK).
# Installed from PyPI as rc-foundry — no clone needed. Variables kept for
# documentation + uninstall (FOUNDRY_DIR is cleaned on uninstall if present).
# shellcheck disable=SC2034
FOUNDRY_REPO="https://github.com/RosettaCommons/foundry.git"
FOUNDRY_COMMIT="v0.1.9"
FOUNDRY_DIR="${BINDERSCOUT_DIR}/Foundry"
FOUNDRY_WEIGHTS_DIR="${BINDERSCOUT_DIR}/weights/foundry"
# AlphaFold 3 (DeepMind, Evaluator refolding). NOT a real PyPI package — the
# "alphafold3" name on PyPI is an unrelated stub (v0.0.x). Installed from the
# official repo (pinned); refold_af3.py resolves run_alphafold.py at ${AF3_DIR}
# by default (or $AF3_REPO_DIR). alphafold3/ is gitignored.
AF3_REPO="https://github.com/google-deepmind/alphafold3"
TMPROT_REPO="https://github.com/loschmidt/TmProt.git"
# Upstream publishes no release tags and has no main/master branch -- its only
# ref is `tmprot-development`. This pins a commit on that branch; re-check when
# upstream tags a version.
TMPROT_BRANCH="tmprot-development"
TMPROT_COMMIT="02d4c12b39ffae8a6cde64a401210390ea9cb23f"
TMPROT_DIR="${BINDERSCOUT_DIR}/TmProt"
AF3_COMMIT="fd39d2c5dcaadfc7333c3466951b27563fa7d6fa"  # v3.0.3.dev, compatible with the v3.0.2 weights
AF3_DIR="${BINDERSCOUT_DIR}/alphafold3"

# BindCraft 2 (Pacesa Lab). Public since 2026-09-16, but source-available under
# its own licence (BindCraft2 Source-Available, hosting-restricted), not this
# repo's MIT, so nothing of it is committed here and BindCraft2/ stays
# gitignored — the same posture as the AF3 weights. --bc2-source still takes a
# .zip or a directory for an air-gapped machine or a pre-release copy.
# It installs EDITABLE into a .venv beside its own checkout, so that directory
# is permanent: moving or deleting it breaks the `bindcraft` command.
BINDCRAFT2_DIR="${BINDERSCOUT_DIR}/BindCraft2"
BINDCRAFT2_REPO="https://github.com/PacesaLab/BindCraft2.git"
BINDCRAFT2_SOURCE="${BINDCRAFT2_SOURCE:-$BINDCRAFT2_REPO}"   # --bc2-source, env, or upstream
BINDCRAFT2_COMMIT="${BINDCRAFT2_COMMIT:-v1.0.1}"   # only consulted for a git source

CONDA_CMD=""          # set by detect_conda: full path to mamba (preferred) or conda
ARCH="$(uname -m)"   # x86_64 or aarch64 (e.g. DGX Spark / Grace-Hopper)

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── Defaults ─────────────────────────────────────────────────────────────────
CUDA_VERSION="12.4"
SKIP_EXAMPLES=false
AUTO_YES=false
SKIP_PREFLIGHT=false
FORCE=false      # --force: allow --yes to accept DESTRUCTIVE prompts (reclone / env re-create)
UNINSTALL_MODE=false
VERIFY_ONLY=false        # --verify: audit what is on disk, install nothing
REPAIR_MODE=false        # --repair: audit, then re-install only what is broken
TOOL_SPECIFIED=false
TOOL_ALL=false         # --tool all was given; uninstall widens this to every optional add-on   # set to true when --tool is passed on CLI
STANDALONE="auto"      # auto | true | false — controls local Miniforge install

# Per-tool install flags (set by arg parsing or interactive menu)
DO_BINDCRAFT=false
DO_BINDCRAFT2=false      # opt-in: needs --bc2-source (or $BINDCRAFT2_SOURCE); skipped, not failed, under --tool all
DO_BOLTZGEN=false
DO_MOSAIC=false
DO_EVALUATOR=false
DO_PXDESIGN=false
DO_PROTEINA_COMPLEXA=false
DO_PROTEIN_HUNTER=false
DO_RFD3=false
DO_AF3=false            # opt-in via --tool af3 (runs on 24 GB GPUs; gated weights not bundled)
DO_ESMFOLD2=false       # default refold engine (included in --tool all; lightweight, no gated weights)
DO_SOLUPROT=false       # in --tool all (sequence-only E. coli solubility screen; needs a C/C++ toolchain for the USEARCH v12 source build)
DO_TMPROT=false         # opt-in: sequence-only melting-temperature screen (GPL-3.0, not redistributed)

# The one list. Every per-tool loop derives from this, in install order.
#
# There used to be five hardcoded tool lists that had drifted apart:
# print_tool_status carried 6 entries, select_tools_interactive 8, `--tool all`
# 11 and the dispatch and uninstall blocks 12. Only the 11 was deliberate (AF3
# is opt-in). The 8 was the damaging one: a user who ran the interactive menu
# could not select ESMFold2 at all, and ESMFold2 is the DEFAULT refold engine —
# so a menu-driven install produced an evaluator that could not satisfy its own
# default 3-engine gate, and only said so at report time.
#
# Format: DO_ flag | display name | install function | menu default | description
#
# The menu default matters: ESMFold2 is ON because it is the DEFAULT refold
# engine. AF3 is OFF because its weights are gated by DeepMind, and BindCraft 2
# is OFF because its licence is hosting-restricted -- both are deliberate
# opt-ins, not omissions.
TOOL_REGISTRY=(
    "DO_BINDCRAFT|BindCraft|install_bindcraft|true|Binder design via AlphaFold2 (conda, Python 3.10)"
    "DO_BINDCRAFT2|BindCraft 2|install_bindcraft2|false|AF2 hallucination rewritten for JAX, no PyRosetta (uv venv; source-available licence)"
    "DO_BOLTZGEN|BoltzGen|install_boltzgen|true|Structure generation with Boltz-1 (conda, Python 3.12, ~6 GB download)"
    "DO_MOSAIC|Mosaic|install_mosaic|true|JAX-based protein design with Marimo notebooks (uv venv)"
    "DO_EVALUATOR|Evaluator|install_evaluator|true|Evaluate binders: refold, ranked report (requires Mosaic)"
    "DO_RFD3|RFD3|install_rfd3|true|RFD3 / foundry -- all-atom diffusion for protein + ligand + NA binders (conda)"
    "DO_PXDESIGN|PXDesign|install_pxdesign|false|Protenix-based de novo binder design (conda)"
    "DO_PROTEINA_COMPLEXA|Proteina-Complexa|install_proteina_complexa|false|NVIDIA flow matching + test-time compute binder design (uv venv)"
    "DO_PROTEIN_HUNTER|Protein-Hunter|install_protein_hunter|false|Boltz/Chai hallucination: protein/cyclic/ligand/DNA/RNA binders (conda)"
    "DO_AF3|AF3|install_af3|false|AlphaFold 3 refold engine -- needs gated weights from DeepMind (conda)"
    "DO_ESMFOLD2|ESMFold2|install_esmfold2|true|DEFAULT refold engine -- the cross-engine gate needs 3 engines (conda)"
    "DO_SOLUPROT|SoluProt|install_soluprot|false|Sequence-only E. coli solubility screen, pre-refold (conda, Python 3.7)"
    "DO_TMPROT|TmProt|install_tmprot|false|Sequence-only melting-temperature screen, advisory only (conda; GPL-3.0, not redistributed)"
)

# Note: legacy RFAA support was removed entirely (see CHANGELOG).
# Use RFD3 (--tool rfd3) for all-atom diffusion-based binder design.

# ─── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tool)
            TOOL_SPECIFIED=true
            case "${2,,}" in
                all)
                    TOOL_ALL=true
                    DO_BINDCRAFT=true; DO_BOLTZGEN=true; DO_MOSAIC=true; DO_EVALUATOR=true; DO_PXDESIGN=true
                    DO_PROTEINA_COMPLEXA=true; DO_PROTEIN_HUNTER=true; DO_RFD3=true; DO_ESMFOLD2=true
                    # Attempted, but skipped with a warning when no source was
                    # supplied -- see the dispatch block.
                    DO_BINDCRAFT2=true
                    # SoluProt is a first-class part of the pipeline: it screens the
                    # pool BEFORE any GPU refolding, so leaving it out of `all` means
                    # the documented full install cannot run the documented workflow.
                    # Costs a Python 3.7 env and a USEARCH source build (needs a
                    # C/C++ toolchain) -- see the preflight footprint table.
                    DO_SOLUPROT=true ;;
                bindcraft)
                    DO_BINDCRAFT=true ;;
                bindcraft2|bc2)
                    DO_BINDCRAFT2=true ;;
                boltzgen)
                    DO_BOLTZGEN=true ;;
                mosaic)
                    DO_MOSAIC=true ;;
                evaluator)
                    DO_EVALUATOR=true ;;
                rfd3|foundry)
                    DO_RFD3=true ;;
                pxdesign)
                    DO_PXDESIGN=true ;;
                proteina-complexa|proteina_complexa|complexa)
                    DO_PROTEINA_COMPLEXA=true ;;
                protein-hunter|protein_hunter|phunter)
                    DO_PROTEIN_HUNTER=true ;;
                af3|alphafold3|alphafold)
                    DO_AF3=true ;;
                esmfold2|esm|esmfold)
                    DO_ESMFOLD2=true ;;
                tmprot|tm|thermostability)
                    DO_TMPROT=true
                    ;;
                soluprot|solu|solubility)
                    DO_SOLUPROT=true ;;
                *)
                    echo -e "${RED}Invalid --tool value: $2. Must be one of: all, bindcraft, bindcraft2, boltzgen, mosaic, evaluator, rfd3, pxdesign, proteina-complexa, protein-hunter, af3, esmfold2, soluprot${RESET}"
                    exit 1
                    ;;
            esac
            shift 2
            ;;
        --cuda)
            CUDA_VERSION="$2"
            shift 2
            ;;
        --bc2-source)
            # Overrides the upstream default: a .zip, a directory, or another
            # git URL. BINDCRAFT2_SOURCE in the environment does the same.
            BINDCRAFT2_SOURCE="$2"
            shift 2
            ;;
        --skip-examples)
            SKIP_EXAMPLES=true
            shift
            ;;
        --yes|-y)
            AUTO_YES=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --skip-preflight)
            SKIP_PREFLIGHT=true
            shift
            ;;
        --verify)
            VERIFY_ONLY=true
            shift
            ;;
        --repair)
            REPAIR_MODE=true
            shift
            ;;
        --standalone)
            STANDALONE=true
            shift
            ;;
        --system-conda)
            STANDALONE=false
            shift
            ;;
        --uninstall)
            UNINSTALL_MODE=true
            shift
            ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--tool TOOL] [--cuda VERSION] [--skip-examples] [--yes] [--force]
       $0 --uninstall --tool <tool|all> [--yes]

  --tool        Which tool(s) to install (or uninstall). Omit for interactive selection.
                  all                  current-generation tools: bindcraft, boltzgen,
                                       mosaic, evaluator, pxdesign, proteina-complexa,
                                       protein-hunter, rfd3, esmfold2 (default refold
                                       engine) and soluprot (pre-refold screen).
                                       bindcraft2 is attempted too, and skipped with
                                       a warning when no --bc2-source is given.
                  bindcraft|boltzgen|mosaic|evaluator|pxdesign|proteina-complexa|protein-hunter|rfd3
                                       install one current-generation tool
                  bindcraft2|bc2       BindCraft 2 — the eighth design tool. Cloned
                                       from https://github.com/PacesaLab/BindCraft2
                                       at v1.0.1; override with --bc2-source (a .zip,
                                       a directory, or another git URL). Installs
                                       editable into BindCraft2/.venv, which makes
                                       that directory permanent. Reuses the AF2
                                       parameters already on the machine instead of
                                       downloading another 5.3 GB.
                  af3                  AlphaFold 3 v3.0.2 refolder — opt-in only;
                                       runs on 24 GB GPUs for ~200-400-token
                                       complexes (~4.4 GB peak, measured);
                                       needs gated AF3 weights you obtain from
                                       https://github.com/google-deepmind/alphafold3
                  esmfold2             ESMFold2 refolder — default (in --tool all);
                                       lightweight refold engine, no gated weights
                  soluprot             SoluProt 1.0 solubility screen — also in
                                       --tool all; sequence-only, no GPU, no refolding.
                                       x86 and aarch64. Builds open-source USEARCH v12
                                       (rcedgar/usearch12, GPLv3) and scikit-learn
                                       0.20.4 from source, so a C/C++ toolchain is
                                       required. Uses the shipped --no_tmhmm model, so
                                       no TMHMM registration and no drive5.com download.
  --cuda        CUDA version for conda package resolution (default: 12.4).
                Not passed to BindCraft 2, which reads the driver itself and picks
                its own CUDA wheels; override that with BINDCRAFT2_ACCELERATOR.
  --bc2-source  Where BindCraft 2's source is: a .zip, an unpacked directory, or a
                git URL. Equivalent to exporting BINDCRAFT2_SOURCE. Optional —
                defaults to https://github.com/PacesaLab/BindCraft2 at v1.0.1.
  --skip-examples
                Do not prompt to run bundled examples after install.
  --yes, -y     Auto-confirm SAFE prompts (proceed?, run the example?) — for
                non-interactive / CI runs. Destructive prompts (re-clone a tool
                repo, re-create a conda env, remove the local Miniforge3) are
                auto-answered NO, so a repeat install keeps existing files and
                downloaded weights. Pair with --force to replace them.
  --skip-preflight  Skip the disk/GPU/network checks run before downloading.
  --verify      Check what is actually on disk for the selected tools and exit.
                Verifies the artifact each tool needs to RUN (weights, env,
                venv) rather than that its entry point exists: an rfd3 CLI that
                answers while its weights dir is empty is not an install.
                Exits non-zero if anything is unusable. Installs nothing.
  --repair      Same audit, then re-install only the tools that failed it, and
                verify again. Use after a network drop or a partial run; it is
                far cheaper than --force, which rebuilds everything including
                ~4 GB of AF2 weights.
  --force       Let --yes accept the destructive prompts too. Re-clones tool
                repos and re-creates conda envs, DELETING what is there —
                including BindCraft/params/*.npz (~4 GB of AF2 weights).
  --standalone  Force local Miniforge3 install into BinderScout/conda/ (server-friendly).
                All envs and shortcuts stay inside the project directory.
  --system-conda
                Use existing system conda (skip local Miniforge install).
  --uninstall   Remove conda envs, venvs, and shortcuts for selected tool(s).
                Never removes runs/, configs, or log files.
EOF
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${RESET}"
            echo "Run '$0 --help' for usage."
            exit 1
            ;;
    esac
done

# ─── Logging setup ────────────────────────────────────────────────────────────
mkdir -p "${BINDERSCOUT_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

# ─── Helper Functions ─────────────────────────────────────────────────────────

print_step() {
    echo ""
    echo -e "${CYAN}${BOLD}▶ $1${RESET}"
}

print_ok() {
    echo -e "${GREEN}✓ $1${RESET}"
}

print_warn() {
    echo -e "${YELLOW}⚠ $1${RESET}"
}

print_fail() {
    echo -e "${RED}✗ $1${RESET}"
}

# run_logged [--retries N] <label> <command...>
# Runs a verbose command showing only a spinner on the terminal.
# All output is written to LOG_FILE only. On failure the last 30 lines
# are printed to the terminal for diagnosis.
# Optional --retries N retries the command up to N times with linear backoff.
run_logged() {
    local retries=1
    if [[ "$1" == "--retries" ]]; then
        retries="$2"; shift 2
    fi
    local label="$1"
    shift
    local tmpfile
    tmpfile=$(mktemp)

    # Check once whether /dev/tty is usable (not available in non-TTY containers)
    local has_tty=false
    { true >/dev/tty; } 2>/dev/null && has_tty=true

    local rc=0
    for attempt in $(seq 1 "${retries}"); do
        # shellcheck disable=SC2188
        > "${tmpfile}"   # truncate on each attempt
        "$@" >> "${tmpfile}" 2>&1 &
        local pid=$!

        local frames='/-\|'
        local i=0
        if [[ "${has_tty}" == true ]]; then
            while kill -0 "${pid}" 2>/dev/null; do
                printf "\r  ${CYAN}%s${RESET}  %s" "${frames:$((i % 4)):1}" "${label}" >/dev/tty
                sleep 0.15
                (( i++ ))
            done
            printf "\r\033[K" >/dev/tty   # clear spinner line
        fi
        wait "${pid}"
        rc=$?

        if [[ ${rc} -eq 0 ]]; then break; fi
        if [[ ${attempt} -lt ${retries} ]]; then
            print_warn "${label} — attempt ${attempt}/${retries} failed, retrying..."
            sleep $((attempt * 2))
        fi
    done

    cat "${tmpfile}" >> "${LOG_FILE}" 2>/dev/null

    if [[ ${rc} -eq 0 ]]; then
        rm -f "${tmpfile}"
        print_ok "${label}"
    else
        echo -e "${RED}  Last output:${RESET}"
        tail -30 "${tmpfile}" | sed 's/^/  /'
        rm -f "${tmpfile}"
        print_fail "${label}"
    fi
    return ${rc}
}

# _confirm_interactive <prompt>
# The shared read loop. Default (bare Enter) is NO for every prompt in this script.
_confirm_interactive() {
    local prompt="${1:-Are you sure?}"
    while true; do
        read -rp "$(echo -e "${YELLOW}${prompt} [y/N]: ${RESET}")" answer
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no|"") return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

# confirm <prompt>
# For SAFE prompts (proceed?, run the example?). --yes auto-accepts.
# Returns 0 (yes) or 1 (no).
confirm() {
    local prompt="${1:-Are you sure?}"
    if [[ "${AUTO_YES}" == true ]]; then
        echo -e "${YELLOW}${prompt} [y/N]: ${RESET}y (auto-yes)"
        return 0
    fi
    _confirm_interactive "$prompt"
}

# confirm_destructive <prompt>
# For prompts that DELETE existing work (re-clone a tool repo, re-create a conda env,
# remove the local Miniforge3). --yes must NOT accept these: `--tool all --yes` is both
# the documented non-interactive install AND the documented repair step, so auto-yes
# turned a repeat run into `rm -rf BindCraft/` — including params/*.npz, ~4 GB of AF2
# weights that Proteina-Complexa symlinks against. It also inverted the prompt's own
# displayed default of [y/N]. --force opts in explicitly.
confirm_destructive() {
    local prompt="${1:-Are you sure?}"
    if [[ "${FORCE}" == true ]]; then
        echo -e "${YELLOW}${prompt} [y/N]: ${RESET}y (--force)"
        return 0
    fi
    if [[ "${AUTO_YES}" == true ]]; then
        echo -e "${YELLOW}${prompt} [y/N]: ${RESET}n (auto-yes keeps existing files; use --force to replace)"
        return 1
    fi
    _confirm_interactive "$prompt"
}

# smoke_test <label> <command...>
# Runs a command; prints OK or FAIL. Returns the exit code.
smoke_test() {
    local label="$1"
    shift
    print_step "Smoke test: ${label}"
    if "$@"; then
        print_ok "Smoke test passed: ${label}"
        return 0
    else
        print_fail "Smoke test FAILED: ${label}"
        return 1
    fi
}

# _stage_bindcraft2_source
# Populates ${BINDCRAFT2_DIR} from ${BINDCRAFT2_SOURCE}, which may be a .zip, a
# directory, or a git URL. Returns 0 when the directory holds a BindCraft 2
# checkout and 1 when it does not — the caller decides whether that is fatal
# (an explicit --tool bindcraft2) or a skip (--tool all on a machine that was
# never given the source).
#
# Idempotent: an already-staged checkout is left alone, so re-running the
# installer never re-extracts over a working .venv. Use --force to replace.
_stage_bindcraft2_source() {
    if [[ -f "${BINDCRAFT2_DIR}/pyproject.toml" && -d "${BINDCRAFT2_DIR}/bindcraft" ]]; then
        if [[ "${FORCE}" != true ]]; then
            print_ok "BindCraft 2 source already staged at ${BINDCRAFT2_DIR}"
            return 0
        fi
        confirm_destructive "Replace the existing BindCraft 2 source at ${BINDCRAFT2_DIR}?" || return 0
        rm -rf "${BINDCRAFT2_DIR}"
    fi

    if [[ -z "${BINDCRAFT2_SOURCE}" ]]; then
        print_fail "BindCraft 2 source is empty — BINDCRAFT2_SOURCE was set to nothing."
        echo "    Leave it unset to clone upstream, or point it at a copy:"
        echo ""
        echo "      binderscout install --tool bindcraft2 --bc2-source /path/to/BindCraft2.zip"
        echo "      binderscout install --tool bindcraft2 --bc2-source /path/to/BindCraft2/"
        echo ""
        return 1
    fi

    print_step "Staging BindCraft 2 source from ${BINDCRAFT2_SOURCE}"
    local staging
    staging="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '${staging}'" RETURN

    case "${BINDCRAFT2_SOURCE}" in
        *.git|git@*|https://*|http://*)
            command -v git >/dev/null 2>&1 || { print_fail "git not found; cannot clone ${BINDCRAFT2_SOURCE}"; return 1; }
            run_logged "Cloning BindCraft 2" \
                git clone --quiet "${BINDCRAFT2_SOURCE}" "${staging}/src" || return 1
            if [[ "${BINDCRAFT2_COMMIT}" != "HEAD" ]]; then
                run_logged "Pinning BindCraft 2 to ${BINDCRAFT2_COMMIT}" \
                    git -C "${staging}/src" checkout --quiet "${BINDCRAFT2_COMMIT}" || return 1
            fi
            ;;
        *.zip)
            [[ -f "${BINDCRAFT2_SOURCE}" ]] || { print_fail "No such file: ${BINDCRAFT2_SOURCE}"; return 1; }
            command -v unzip >/dev/null 2>&1 || { print_fail "unzip not found; install it or pass an unpacked directory"; return 1; }
            mkdir -p "${staging}/src"
            run_logged "Extracting BindCraft 2" \
                unzip -q -o "${BINDCRAFT2_SOURCE}" -d "${staging}/src" || return 1
            ;;
        *)
            [[ -d "${BINDCRAFT2_SOURCE}" ]] || { print_fail "Not a file or directory: ${BINDCRAFT2_SOURCE}"; return 1; }
            mkdir -p "${staging}/src"
            cp -a "${BINDCRAFT2_SOURCE}/." "${staging}/src/" || return 1
            ;;
    esac

    # A zip made on macOS carries a resource-fork sibling for every file and a
    # top-level wrapper directory; neither is part of the source.
    rm -rf "${staging}/src/__MACOSX"
    find "${staging}/src" -name '.DS_Store' -delete 2>/dev/null || true

    # Find the checkout root: either the staging dir itself or a single wrapper
    # directory inside it. Identify it by content, not by name, so a zip that
    # unpacks to BC2/ or bindcraft-2/ works as well as BindCraft2/.
    local root=""
    if [[ -f "${staging}/src/pyproject.toml" && -d "${staging}/src/bindcraft" ]]; then
        root="${staging}/src"
    else
        local candidate
        while IFS= read -r candidate; do
            if [[ -f "${candidate}/pyproject.toml" && -d "${candidate}/bindcraft" ]]; then
                root="${candidate}"
                break
            fi
        done < <(find "${staging}/src" -mindepth 1 -maxdepth 1 -type d)
    fi

    if [[ -z "${root}" ]]; then
        print_fail "That source does not look like BindCraft 2"
        echo "    Expected a directory containing pyproject.toml and bindcraft/, found:"
        find "${staging}/src" -mindepth 1 -maxdepth 1 -printf '      %f\n' 2>/dev/null | head -10
        return 1
    fi

    # Refuse a look-alike rather than build a .venv against the wrong package:
    # the same repository name is used by BindCraft 1, whose pyproject differs.
    if ! grep -q '^name *= *"bindcraft"' "${root}/pyproject.toml" 2>/dev/null; then
        print_fail "${root}/pyproject.toml does not declare the 'bindcraft' package"
        return 1
    fi

    mkdir -p "$(dirname "${BINDCRAFT2_DIR}")"
    rm -rf "${BINDCRAFT2_DIR}"
    mv "${root}" "${BINDCRAFT2_DIR}" || { print_fail "Could not move the source into ${BINDCRAFT2_DIR}"; return 1; }

    print_ok "BindCraft 2 source staged at ${BINDCRAFT2_DIR}"
    return 0
}

# env_exists <name>
# Returns 0 if conda env exists in OUR conda, 1 otherwise.
# Uses filesystem check (not conda registry) to avoid stale entries
# from unwritable system conda installations.
# The interpreter shortcuts are generated against.
#
# detect_conda PREFERS mamba for solving, which is right -- it is far faster.
# But `mamba run` has no --live-stream, and every generated shortcut uses it, so
# each one died on any argument with "exec: --: invalid option" -- including the
# exact usage printed in its own banner. Dropping the flag is not free either:
# without it `conda run` buffers all output until the command exits, which is
# unusable for a design run that prints progress for hours.
#
# Miniforge ships conda alongside mamba, so shortcuts use conda and keep
# streaming. Falls back to CONDA_CMD if no conda sits beside it.
shortcut_conda() {
    local sibling
    sibling="$(dirname "${CONDA_CMD}")/conda"
    if [[ -x "${sibling}" ]]; then printf '%s' "${sibling}"; else printf '%s' "${CONDA_CMD}"; fi
}

env_exists() {
    [[ -d "${CONDA_BASE}/envs/$1" ]]
}

# ensure_conda_in_path
ensure_conda_in_path() {
    export PATH="${CONDA_BASE}/bin:${PATH}"
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
}

# _write_local_condarc <conda_dir>
# Writes/updates .condarc to pin envs + pkgs locally while preserving channels.
_write_local_condarc() {
    local conda_dir="$1"
    local condarc="${conda_dir}/.condarc"
    if grep -q "envs_dirs" "${condarc}" 2>/dev/null; then
        return 0  # already configured
    fi
    # Append to (not overwrite) existing .condarc so Miniforge's default channels survive
    cat >> "${condarc}" <<RCEOF

# BinderScout standalone: pin envs + pkgs locally
envs_dirs:
  - ${conda_dir}/envs
pkgs_dirs:
  - ${conda_dir}/pkgs
RCEOF
}

# install_local_conda
# Downloads and installs Miniforge3 into LOCAL_CONDA_DIR (BinderScout/conda/).
# Idempotent — skips if already installed.
install_local_conda() {
    if [[ -d "${LOCAL_CONDA_DIR}" && -x "${LOCAL_CONDA_DIR}/bin/conda" ]]; then
        print_ok "Local Miniforge3 already installed at ${LOCAL_CONDA_DIR}"
        CONDA_BASE="${LOCAL_CONDA_DIR}"
        if [[ -x "${LOCAL_CONDA_DIR}/bin/mamba" ]]; then
            CONDA_CMD="${LOCAL_CONDA_DIR}/bin/mamba"
        else
            CONDA_CMD="${LOCAL_CONDA_DIR}/bin/conda"
        fi
        # Ensure .condarc pins envs/pkgs locally (may be missing from older installs)
        _write_local_condarc "${LOCAL_CONDA_DIR}"
        return 0
    fi

    print_step "Installing local Miniforge3 into ${LOCAL_CONDA_DIR}"

    local installer_url
    if [[ "${ARCH}" == "aarch64" ]]; then
        installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh"
    else
        installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
    fi

    local installer_path
    installer_path="$(mktemp /tmp/miniforge3-XXXXXXXX.sh)"

    run_logged --retries 3 "Downloading Miniforge3 (~80 MB)" \
        curl -fSL -o "${installer_path}" "${installer_url}" \
        || { print_fail "Failed to download Miniforge3"; rm -f "${installer_path}"; return 1; }

    # Batch mode (-b): no prompts, no license question, no PATH modification
    run_logged "Installing Miniforge3 (batch mode)" \
        bash "${installer_path}" -b -p "${LOCAL_CONDA_DIR}" \
        || { print_fail "Miniforge3 installation failed"; rm -f "${installer_path}"; return 1; }

    rm -f "${installer_path}"

    CONDA_BASE="${LOCAL_CONDA_DIR}"
    if [[ -x "${LOCAL_CONDA_DIR}/bin/mamba" ]]; then
        CONDA_CMD="${LOCAL_CONDA_DIR}/bin/mamba"
    else
        CONDA_CMD="${LOCAL_CONDA_DIR}/bin/conda"
    fi

    _write_local_condarc "${LOCAL_CONDA_DIR}"

    # ocl-icd-system (pulled by BindCraft's jaxlib) needs binutils in base env
    "${CONDA_CMD}" install -n base -y -c conda-forge binutils_linux-64 --quiet 2>/dev/null \
        || print_warn "Could not install binutils_linux-64 in base (non-fatal)"

    print_ok "Miniforge3 installed at ${LOCAL_CONDA_DIR}"
}

# detect_conda
# Finds conda/mamba and sets CONDA_BASE + CONDA_CMD.
# Priority: local conda → system conda (if writable) → auto-install local.
detect_conda() {
    # shellcheck disable=SC2034
    local base cmd

    # Helper: try a specific binary on PATH
    _try_cmd() {
        local bin="$1"
        if command -v "${bin}" &>/dev/null; then
            base=$(${bin} info --base 2>/dev/null | awk '/\// {print $NF}' | tail -1) && [[ -n "${base}" ]] && {
                CONDA_BASE="${base}"
                CONDA_CMD="$(command -v "${bin}")"
                return 0
            }
        fi
        return 1
    }

    # 1. Check for local (standalone) conda first
    if [[ -x "${LOCAL_CONDA_DIR}/bin/conda" ]]; then
        CONDA_BASE="${LOCAL_CONDA_DIR}"
        if [[ -x "${LOCAL_CONDA_DIR}/bin/mamba" ]]; then
            CONDA_CMD="${LOCAL_CONDA_DIR}/bin/mamba"
        else
            CONDA_CMD="${LOCAL_CONDA_DIR}/bin/conda"
        fi
        return 0
    fi

    # 2. If --standalone was explicitly requested, install local conda now
    if [[ "${STANDALONE}" == "true" ]]; then
        install_local_conda
        return $?
    fi

    # 3. Try system conda/mamba on PATH
    _try_cmd mamba && { _check_system_conda_writable && return 0; }
    _try_cmd conda && { _check_system_conda_writable && return 0; }

    # 4. Probe common install locations
    for candidate in \
        "$HOME/miniforge3" \
        "$HOME/mambaforge" \
        "$HOME/miniconda3" \
        "$HOME/anaconda3" \
        "$HOME/conda" \
        "/opt/conda" \
        "/opt/miniforge3" \
        "/opt/miniconda3" \
        "/opt/anaconda3"; do
        [[ -f "${candidate}/etc/profile.d/conda.sh" ]] || continue
        CONDA_BASE="${candidate}"
        if [[ -x "${candidate}/bin/mamba" ]]; then
            CONDA_CMD="${candidate}/bin/mamba"
        else
            CONDA_CMD="${candidate}/bin/conda"
        fi
        _check_system_conda_writable && return 0
    done

    # 5. No usable conda found — install locally if allowed
    if [[ "${STANDALONE}" != "false" ]]; then
        print_warn "No writable conda found — installing local Miniforge3"
        install_local_conda
        return $?
    fi

    print_fail "Could not find a writable conda installation."
    print_fail "Use --standalone to install Miniforge3 locally into ${LOCAL_CONDA_DIR}"
    return 1
}

# _check_system_conda_writable
# Returns 0 if the current CONDA_BASE envs dir is writable, or if --system-conda was forced.
# In auto mode, returns 1 (triggering fallback to local install) if not writable.
_check_system_conda_writable() {
    # --system-conda: trust the user, skip writability check
    if [[ "${STANDALONE}" == "false" ]]; then
        return 0
    fi

    local envs_dir="${CONDA_BASE}/envs"
    if [[ -d "${envs_dir}" && -w "${envs_dir}" ]]; then
        return 0
    fi

    # Try creating the envs dir (some conda installs start without it)
    if mkdir -p "${envs_dir}" 2>/dev/null && [[ -w "${envs_dir}" ]]; then
        return 0
    fi

    # Not writable — in auto mode, this triggers local install
    print_warn "System conda at ${CONDA_BASE} — envs directory not writable"
    return 1
}

# ─── Install Status Checks ────────────────────────────────────────────────────

is_bindcraft_installed() {
    [[ -d "${BINDCRAFT_DIR}" ]] && env_exists BindCraft
}

is_boltzgen_installed() {
    [[ -d "${BOLTZGEN_DIR}" ]] && env_exists BoltzGen
}

is_mosaic_installed() {
    [[ -d "${MOSAIC_DIR}" ]] && [[ -d "${MOSAIC_DIR}/.venv" ]]
}

is_evaluator_installed() {
    [[ -d "${EVALUATOR_DIR}" ]] && [[ -f "${EVALUATOR_DIR}/envs/mosaic_venv_path" ]]
}

is_pxdesign_installed() {
    [[ -d "${PXDESIGN_DIR}" ]] && env_exists binderscout_pxdesign
}

is_protein_hunter_installed() {
    [[ -d "${PROTEIN_HUNTER_DIR}" ]] && env_exists binderscout_protein_hunter
}

is_rfd3_installed() {
    env_exists binderscout_rfd3
}

is_bindcraft2_installed() {
    # The checkout IS the installation (editable install), so both halves must
    # be present: a staged source with no venv is a half-finished install.
    [[ -d "${BINDCRAFT2_DIR}" ]] && [[ -x "${BINDCRAFT2_DIR}/.venv/bin/bindcraft" ]]
}

is_proteina_complexa_installed() {
    [[ -d "${PROTEINA_COMPLEXA_DIR}" ]] && [[ -d "${PROTEINA_COMPLEXA_DIR}/.venv" ]]
}

# print_tool_status
# Shows installed/not-installed for each tool.
print_tool_status() {
    echo ""
    echo -e "${BOLD}=== Installed Tools ===${RESET}"
    # Driven by TOOL_REGISTRY, and reporting USABLE rather than merely present.
    # The old version hardcoded six names, so Protein-Hunter, RFD3, BindCraft 2,
    # AF3, ESMFold2 and SoluProt never appeared under a heading that claims to
    # list installed tools -- and detectors for three of them already existed
    # and were simply never called.
    local spec tool flag fn
    for spec in "${TOOL_REGISTRY[@]}"; do
        IFS='|' read -r flag tool fn _dflt _desc <<< "${spec}"
        if verify_tool "${tool}" 2>/dev/null; then
            printf "  %b  %-20s  %s\n" "${GREEN}✓${RESET}" "${tool}" "installed"
        else
            printf "  %b  %-20s  %s\n" "${RED}✗${RESET}" "${tool}" "not installed"
        fi
    done
    echo ""
}

# ─── Interactive Tool Selection ───────────────────────────────────────────────
# Called when no --tool flag was supplied. Displays a toggle menu; sets
# DO_BINDCRAFT / DO_BOLTZGEN / DO_MOSAIC based on user choices.

select_tools_interactive() {
    # Driven entirely by TOOL_REGISTRY. This used to be thirteen hardcoded
    # places all fixed at eight entries -- the sel_* scalars, three parallel
    # arrays, a literal `for i in 0 1 2 3 4 5 6 7`, one case arm per tool, the
    # select-all and select-none lines, the empty-selection guard, the DO_*
    # handoff and the confirmation echo. Adding a tool meant editing all
    # thirteen in sync, which is why four tools were never added: BindCraft 2,
    # AF3, SoluProt and -- the damaging one -- ESMFold2, the DEFAULT refold
    # engine. A menu-driven install therefore produced an evaluator that could
    # not satisfy its own default three-engine gate.
    local -a m_flag=() m_name=() m_desc=() m_sel=() m_state=()
    local spec flag name fn dflt desc
    for spec in "${TOOL_REGISTRY[@]}"; do
        IFS='|' read -r flag name fn dflt desc <<< "${spec}"
        m_flag+=("${flag}"); m_name+=("${name}"); m_desc+=("${desc}"); m_sel+=("${dflt}")
    done
    local n=${#m_flag[@]}

    # Probe install state ONCE -- the menu re-prints on every keystroke, and
    # verify_tool starts a python interpreter per tool.
    local i
    for (( i = 0; i < n; i++ )); do
        if verify_tool "${m_name[$i]}" 2>/dev/null; then
            m_state+=("${GREEN}installed${RESET}")
        else
            m_state+=("${YELLOW}not installed${RESET}")
        fi
    done

    _print_menu() {
        echo ""
        echo -e "${BOLD}${CYAN}  Select tools to install${RESET}"
        echo -e "  Type a number to toggle selection, then press Enter when done."
        echo ""
        local j box
        for (( j = 0; j < n; j++ )); do
            if [[ "${m_sel[$j]}" == true ]]; then box="${GREEN}[x]${RESET}"; else box="${RED}[ ]${RESET}"; fi
            printf "    %2d)  %b  ${BOLD}%-20s${RESET}  %-35b  %s\n" \
                $((j+1)) "${box}" "${m_name[$j]}" "${m_state[$j]}" "${m_desc[$j]}"
        done
        echo ""
        echo -e "  ${YELLOW}a${RESET}) Select all   ${YELLOW}n${RESET}) Select none   ${YELLOW}Enter${RESET} to confirm"
        echo ""
    }

    local choice j any
    while true; do
        _print_menu
        if ! read -rp "  > " choice; then
            # stdin is closed. Every further read returns immediately with an
            # empty choice, so the "no tools selected" branch below would
            # `continue` into an infinite loop -- which it did: piping
            # `n` then EOF spun this menu forever, printing the same line.
            # A human at a TTY never meets this; a script or CI job does.
            any=false
            for (( j = 0; j < n; j++ )); do [[ "${m_sel[$j]}" == true ]] && any=true; done
            if [[ "${any}" == true ]]; then
                echo ""
                print_warn "stdin closed -- proceeding with the tools selected above."
                break
            fi
            echo ""
            print_fail "stdin closed with no tools selected -- nothing to install."
            echo -e "  Pass ${BOLD}--tool <name>${RESET} (or ${BOLD}--tool all${RESET}) for a non-interactive install."
            return 1
        fi
        case "${choice,,}" in
            a) for (( j = 0; j < n; j++ )); do m_sel[$j]=true;  done ;;
            n) for (( j = 0; j < n; j++ )); do m_sel[$j]=false; done ;;
            "")
                any=false
                for (( j = 0; j < n; j++ )); do [[ "${m_sel[$j]}" == true ]] && any=true; done
                if [[ "${any}" == false ]]; then
                    echo -e "  ${RED}No tools selected. Select at least one.${RESET}"
                    continue
                fi
                break
                ;;
            *)
                if [[ "${choice}" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= n )); then
                    j=$((choice - 1))
                    [[ "${m_sel[$j]}" == true ]] && m_sel[$j]=false || m_sel[$j]=true
                else
                    echo -e "  ${RED}Invalid input. Enter 1-${n}, a, n, or press Enter.${RESET}"
                fi
                ;;
        esac
    done

    for (( i = 0; i < n; i++ )); do
        printf -v "${m_flag[$i]}" '%s' "${m_sel[$i]}"
    done

    echo ""
    echo -e "  ${BOLD}Installing:${RESET}"
    for (( i = 0; i < n; i++ )); do
        [[ "${m_sel[$i]}" == true ]] && echo -e "    ${GREEN}✓${RESET} ${m_name[$i]}"
    done

    # Explicit, and load-bearing. Without it the function's exit status is that
    # of the last `[[ ... ]] && echo`, which is 1 whenever the LAST tool in the
    # registry is unselected -- the default, since SoluProt is opt-in. The old
    # menu had the same shape and it never mattered, because nobody checked the
    # return. Adding `select_tools_interactive || exit 1` at the call site (to
    # honour the EOF refusal below) turned that latent quirk into "the
    # interactive installer always exits 1 and installs nothing".
    return 0
}

# ─── BindCraft ────────────────────────────────────────────────────────────────

# Rewrite Colab-style /content/... paths in all settings_target/*.json files
# to proper local paths under BINDCRAFT_DIR.
_fix_target_settings() {
    local settings_dir="${BINDCRAFT_DIR}/settings_target"
    [[ -d "${settings_dir}" ]] || return 0

    local count=0
    for f in "${settings_dir}"/*.json; do
        [[ -f "$f" ]] || continue
        # /content/drive/My Drive/BindCraft/<target>/ → <BINDCRAFT_DIR>/output/<target>/
        sed -i "s|/content/drive/My Drive/BindCraft/|${BINDCRAFT_DIR}/output/|g" "$f"
        # /content/bindcraft/ → <BINDCRAFT_DIR>/
        sed -i "s|/content/bindcraft/|${BINDCRAFT_DIR}/|g" "$f"
        (( count++ ))
    done
    print_ok "Patched Colab paths in ${count} target settings file(s)"

    # Reduce example design count and max binder length for a quick smoke run
    local pdl1="${settings_dir}/PDL1.json"
    if [[ -f "${pdl1}" ]]; then
        sed -i 's|"number_of_final_designs":.*|"number_of_final_designs": 1|' "${pdl1}"
        sed -i 's|"lengths":.*|"lengths": [65, 100],|' "${pdl1}"
        print_ok "PDL1 example: number_of_final_designs=1, max binder length=100"
    fi
}

install_bindcraft() {
    print_step "Installing BindCraft"
    ensure_conda_in_path
    # Ensure our conda is found first by BindCraft's own installer
    # (it calls `conda info --base` which must return our conda)
    export PATH="${CONDA_BASE}/bin:${PATH}"

    # Clone
    print_step "Cloning BindCraft repository"
    if [[ -d "${BINDCRAFT_DIR}" ]]; then
        print_warn "Directory ${BINDCRAFT_DIR} already exists."
        if confirm_destructive "Remove and reclone?"; then
            rm -rf "${BINDCRAFT_DIR}" || { print_fail "Failed to remove ${BINDCRAFT_DIR}"; return 1; }
        else
            print_warn "Skipping reclone; using existing directory."
        fi
    fi
    if [[ ! -d "${BINDCRAFT_DIR}" ]]; then
        run_logged --retries 3 "Cloning BindCraft" \
            git clone --depth 50 https://github.com/martinpacesa/BindCraft "${BINDCRAFT_DIR}" \
            || { print_fail "Failed to clone BindCraft"; return 1; }
        git -C "${BINDCRAFT_DIR}" checkout "${BINDCRAFT_COMMIT}" --quiet \
            || print_warn "Could not pin BindCraft to ${BINDCRAFT_COMMIT} — using latest"
    fi

    # Fix Colab paths in target settings
    _fix_target_settings

    # Remove existing conda env if present
    if env_exists BindCraft; then
        print_warn "Conda environment 'BindCraft' already exists."
        if confirm_destructive "Remove and recreate the BindCraft conda environment?"; then
            run_logged "Removing existing BindCraft conda env" \
                "${CONDA_CMD}" env remove -n BindCraft -y \
                || return 1
        else
            print_warn "Keeping existing BindCraft conda env; skipping install script."
        fi
    fi

    # Delegate to BindCraft's own installer
    if ! env_exists BindCraft; then
        print_step "Running BindCraft install script (conda env + AlphaFold2 weights)"
        print_warn "This will take 45-90 min — full output in install.log"
        run_logged --retries 3 "Installing BindCraft (conda packages + AlphaFold2 weights)" \
            bash -c "export PATH='${CONDA_BASE}/bin:${PATH}'; cd '${BINDCRAFT_DIR}' && bash install_bindcraft.sh --cuda '${CUDA_VERSION}' --pkg_manager conda" \
            || { print_fail "BindCraft install script failed"; return 1; }
    fi

    # Smoke test
    smoke_test "colabdesign import" \
        "${CONDA_CMD}" run -n BindCraft \
        python -c "from colabdesign import mk_af_model; print('OK')" \
        || return 1

    # Example
    if [[ "${SKIP_EXAMPLES}" == false ]]; then
        print_step "BindCraft example run"
        print_warn "The example will run BindCraft on PDL1 target (may take a very long time)."
        if confirm "Run the BindCraft PDL1 example?"; then
            (
                cd "${BINDCRAFT_DIR}" || exit 1
                XLA_PYTHON_CLIENT_PREALLOCATE=false \
                "${CONDA_CMD}" run -n BindCraft \
                    python -u ./bindcraft.py \
                    --settings './settings_target/PDL1.json' \
                    --filters './settings_filters/default_filters.json' \
                    --advanced './settings_advanced/default_4stage_multimer.json'
            ) && { print_ok "BindCraft example completed"; } \
              || { print_fail "BindCraft example failed — installation is still OK"; FAILED_EXAMPLES+=("BindCraft"); }
        else
            print_warn "Skipped BindCraft example."
        fi
    fi

    # Shortcut
    print_step "Installing bindcraft shortcut"
    _write_bindcraft_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/bindcraft"

    print_ok "BindCraft installation complete"
}

_write_bindcraft_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    # Write path variables first (expanded at install time), then static body
    {
        echo "#!/bin/bash"
        echo "# BindCraft shortcut — activates the BindCraft conda environment"
        echo "# and opens an interactive shell in the BindCraft directory."
        echo ""
        echo "BINDCRAFT_DIR=\"${BINDCRAFT_DIR}\""
        echo "CONDA_BASE=\"${CONDA_BASE}\""
    } > "${SHORTCUTS_DIR}/bindcraft"
    cat >> "${SHORTCUTS_DIR}/bindcraft" << 'EOF'

source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate BindCraft
cd "${BINDCRAFT_DIR}"

echo "BindCraft environment activated."
echo "Working directory: ${BINDCRAFT_DIR}"
echo "To run BindCraft:"
echo "  python -u ./bindcraft.py --settings './settings_target/<target>.json' \\"
echo "    --filters './settings_filters/default_filters.json' \\"
echo "    --advanced './settings_advanced/default_4stage_multimer.json'"
echo ""

exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/bindcraft"
}

# ─── BoltzGen ─────────────────────────────────────────────────────────────────

# Fix bare open().write() → context-managed writes in BoltzGen's writer.py.
# Prevents ResourceWarning: unclosed file handles.
_patch_boltzgen() {
    local writer="${BOLTZGEN_DIR}/src/boltzgen/task/predict/writer.py"
    [[ -f "${writer}" ]] || return 0
    python3 - "${writer}" << 'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    src = f.read()
original = src

# Single-line: open(args).write(content)
def fix_single(m):
    ind, args, body = m.group(1), m.group(2), m.group(3)
    return f"{ind}with open({args}) as _f:\n{ind}    _f.write({body})"
src = re.sub(
    r'^( +)open\((.+?)\)\.write\((.+)\)$',
    fix_single, src, flags=re.MULTILINE)

# Multi-line: open(args).write(\n...\nINDENT)
def fix_multi(m):
    ind, args, body = m.group(1), m.group(2), m.group(3)
    body = "\n".join("    " + l for l in body.split("\n"))
    return f"{ind}with open({args}) as _f:\n{ind}    _f.write(\n{body}\n{ind}    )"
src = re.sub(
    r'^( +)open\((.+?)\)\.write\(\n([\s\S]+?)\n\1\)',
    fix_multi, src, flags=re.MULTILINE)

if src != original:
    with open(path, "w") as f:
        f.write(src)
    print("Patched writer.py: fixed unclosed file handles")
else:
    print("writer.py: already patched")
PYEOF
}

install_boltzgen() {
    print_step "Installing BoltzGen"
    ensure_conda_in_path

    # Clone
    print_step "Cloning BoltzGen repository"
    if [[ -d "${BOLTZGEN_DIR}" ]]; then
        print_warn "Directory ${BOLTZGEN_DIR} already exists."
        if confirm_destructive "Remove and reclone?"; then
            rm -rf "${BOLTZGEN_DIR}" || { print_fail "Failed to remove ${BOLTZGEN_DIR}"; return 1; }
        else
            print_warn "Skipping reclone; using existing directory."
        fi
    fi
    if [[ ! -d "${BOLTZGEN_DIR}" ]]; then
        run_logged --retries 3 "Cloning BoltzGen" \
            git clone --depth 50 https://github.com/HannesStark/boltzgen "${BOLTZGEN_DIR}" \
            || { print_fail "Failed to clone BoltzGen"; return 1; }
        git -C "${BOLTZGEN_DIR}" checkout "${BOLTZGEN_COMMIT}" --quiet \
            || print_warn "Could not pin BoltzGen to ${BOLTZGEN_COMMIT} — using latest"
    fi

    # Patch known issues in BoltzGen source
    _patch_boltzgen

    # Conda environment
    print_step "Creating BoltzGen conda environment (Python 3.12)"
    if env_exists BoltzGen; then
        print_warn "Conda environment 'BoltzGen' already exists."
        if confirm_destructive "Remove and recreate the BoltzGen conda environment?"; then
            run_logged "Removing existing BoltzGen conda env" \
                "${CONDA_CMD}" env remove -n BoltzGen -y \
                || return 1
        else
            print_warn "Keeping existing BoltzGen conda env."
        fi
    fi
    if ! env_exists BoltzGen; then
        run_logged "Creating BoltzGen conda env (Python 3.12)" \
            "${CONDA_CMD}" create -n BoltzGen python=3.12 -y \
            || { print_fail "Failed to create BoltzGen conda env"; return 1; }
    fi

    # Install gcc — required by Triton to JIT-compile CUDA kernels at runtime
    run_logged "Installing gcc into BoltzGen env (required by Triton)" \
        "${CONDA_CMD}" install -n BoltzGen -c conda-forge gcc -y \
        || { print_fail "Failed to install gcc into BoltzGen env"; return 1; }

    # Install packages
        # NOTE: plain PyPI torch is CPU-ONLY on Linux aarch64. This branch is
        # unreachable now (the arch guard above exits first) and is kept only so
        # the override path does something defined. Use install_aarch.sh.
    print_step "Installing PyTorch and BoltzGen"
    if [[ "${ARCH}" == "aarch64" ]]; then
        run_logged "Installing PyTorch (aarch64, from PyPI)" \
            "${CONDA_CMD}" run -n BoltzGen \
            pip install torch==2.5.1 \
            || { print_fail "Failed to install PyTorch"; return 1; }
    else
        run_logged "Installing PyTorch cu121 (x86_64)" \
            "${CONDA_CMD}" run -n BoltzGen \
            pip install torch==2.5.1+cu121 --index-url https://download.pytorch.org/whl/cu121 \
            || { print_fail "Failed to install PyTorch"; return 1; }
    fi
    run_logged "Installing BoltzGen package" \
        "${CONDA_CMD}" run -n BoltzGen \
        pip install -e "${BOLTZGEN_DIR}" \
        || { print_fail "Failed to install BoltzGen package"; return 1; }

    # Smoke test
    smoke_test "boltzgen --help" \
        "${CONDA_CMD}" run -n BoltzGen boltzgen --help \
        || return 1

    # Example
    if [[ "${SKIP_EXAMPLES}" == false ]]; then
        print_step "BoltzGen example run"
        print_warn "The example downloads ~6 GB of model weights on first run."
        if confirm "Run the BoltzGen example (2 designs of 1g13)?"; then
            print_warn "First run downloads ~6 GB of model weights — this will take a while."
            (
                cd "${BOLTZGEN_DIR}" || exit 1
                "${CONDA_CMD}" run -n BoltzGen \
                    boltzgen run example/vanilla_protein/1g13prot.yaml \
                    --output output/test_run \
                    --protocol protein-anything \
                    --num_designs 2
            ) && { print_ok "BoltzGen example completed"; } \
              || { print_fail "BoltzGen example failed — installation is still OK"; FAILED_EXAMPLES+=("BoltzGen"); }
        else
            print_warn "Skipped BoltzGen example."
        fi
    fi

    # Shortcut
    print_step "Installing boltzgen shortcut"
    _write_boltzgen_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/boltzgen"

    print_ok "BoltzGen installation complete"
}

_write_boltzgen_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BoltzGen shortcut — activates the BoltzGen conda environment"
        echo "# and opens an interactive shell in the BoltzGen directory."
        echo ""
        echo "BOLTZGEN_DIR=\"${BOLTZGEN_DIR}\""
        echo "CONDA_BASE=\"${CONDA_BASE}\""
    } > "${SHORTCUTS_DIR}/boltzgen"
    cat >> "${SHORTCUTS_DIR}/boltzgen" << 'EOF'

source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate BoltzGen
cd "${BOLTZGEN_DIR}"

echo "BoltzGen environment activated."
echo "Working directory: ${BOLTZGEN_DIR}"
echo "To run BoltzGen:"
echo "  boltzgen run <config.yaml> --output <output_dir> --protocol protein-anything --num_designs 2"
echo ""

exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/boltzgen"
}

# ─── Mosaic ───────────────────────────────────────────────────────────────────

install_mosaic() {
    print_step "Installing Mosaic"

    # Clone
    print_step "Cloning Mosaic repository"
    if [[ -d "${MOSAIC_DIR}" ]]; then
        print_warn "Directory ${MOSAIC_DIR} already exists."
        if confirm_destructive "Remove and reclone?"; then
            rm -rf "${MOSAIC_DIR}" || { print_fail "Failed to remove ${MOSAIC_DIR}"; return 1; }
        else
            print_warn "Skipping reclone; using existing directory."
        fi
    fi
    if [[ ! -d "${MOSAIC_DIR}" ]]; then
        run_logged --retries 3 "Cloning Mosaic" \
            git clone --depth 50 https://github.com/escalante-bio/mosaic "${MOSAIC_DIR}" \
            || { print_fail "Failed to clone Mosaic"; return 1; }
        git -C "${MOSAIC_DIR}" checkout "${MOSAIC_COMMIT}" --quiet \
            || print_warn "Could not pin Mosaic to ${MOSAIC_COMMIT} — using latest"
    fi

    # Ensure uv is available
    print_step "Checking for uv package manager"
    if ! command -v uv &>/dev/null; then
        print_warn "uv not found — installing via official installer"
        curl -LsSf https://astral.sh/uv/install.sh | sh \
            || { print_fail "Failed to install uv"; return 1; }
        export PATH="${HOME}/.local/bin:${PATH}"
        # Add to .bashrc if not already there
        if ! grep -q '.local/bin' "${HOME}/.bashrc" 2>/dev/null; then
            echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "${HOME}/.bashrc"
            print_ok "Added ~/.local/bin to PATH in ~/.bashrc"
        fi
    fi
    if ! command -v uv &>/dev/null; then
        print_fail "uv still not found after install; check PATH"
        return 1
    fi
    print_ok "uv is available: $(command -v uv)"

    # Offline-MSA support: upstream Mosaic lacks TargetChain.msa_path, which our
    # Boltz-2 refolds AND the hallucination template rely on to feed a cached
    # target .a3m on air-gapped nodes. Re-apply our source patch after clone
    # (idempotent — skipped if already present). The old grpcio-tools override is
    # obsolete: upstream removed override-dependencies at this pin (uv sync resolves).
    local msa_patch="${BINDERSCOUT_DIR}/install/patches/mosaic-offline-msa.patch"
    if [[ -f "${msa_patch}" ]] && ! grep -q "msa_path" "${MOSAIC_DIR}/src/mosaic/structure_prediction.py" 2>/dev/null; then
        git -C "${MOSAIC_DIR}" apply "${msa_patch}" \
            && print_ok "Applied offline-MSA patch (TargetChain.msa_path)" \
            || print_warn "Offline-MSA patch failed to apply — offline target MSA disabled"
    fi

    # Create virtual environment with JAX CUDA support
    print_step "Running uv sync --group jax-cuda (creates .venv/ inside Mosaic/)"
    run_logged "Setting up Mosaic venv (uv sync --group jax-cuda)" \
        bash -c "cd '${MOSAIC_DIR}' && uv sync --group jax-cuda" \
        || { print_fail "uv sync failed for Mosaic"; return 1; }

    # Smoke test
    smoke_test "import mosaic" \
        "${MOSAIC_DIR}/.venv/bin/python" -c "import mosaic; print('OK')" \
        || return 1

    # Example
    if [[ "${SKIP_EXAMPLES}" == false ]]; then
        print_step "Mosaic example"
        print_warn "The example opens an interactive Marimo notebook in your browser."
        if confirm "Open the Mosaic example notebook?"; then
            cd "${MOSAIC_DIR}" || return 1
            "${MOSAIC_DIR}/.venv/bin/marimo" edit examples/example_notebook.py &
            local marimo_pid=$!
            print_ok "Marimo running (PID ${marimo_pid}) — open the URL shown above in your browser"
            echo ""
            if [[ "${AUTO_YES}" == true ]]; then
                sleep 5
            else
                read -rp "$(echo -e "${YELLOW}  Press Enter to stop Marimo and continue the installer...${RESET}")"
            fi
            kill "${marimo_pid}" 2>/dev/null && print_ok "Marimo stopped" || print_warn "Marimo already exited"
            cd - > /dev/null || true
        else
            print_warn "Skipped Mosaic example."
        fi
    fi

    # Copy BinderScout custom examples into Mosaic
    local src_examples="${BINDERSCOUT_DIR}/binderscout_examples"
    local dst_examples="${MOSAIC_DIR}/examples/binderscout_examples"
    if [[ -d "${src_examples}" ]]; then
        mkdir -p "${dst_examples}"
        cp -r "${src_examples}/." "${dst_examples}/"
        # Remove the placeholder if it's the only file
        rm -f "${dst_examples}/.gitkeep"
        local count
        count=$(find "${dst_examples}" -maxdepth 1 -type f | wc -l)
        if [[ "${count}" -gt 0 ]]; then
            print_ok "Copied ${count} custom example(s) to ${dst_examples}"
        else
            print_ok "binderscout_examples/ ready at ${dst_examples} (add your scripts there)"
        fi
    fi

    # Shortcut
    print_step "Installing mosaic shortcut"
    _write_mosaic_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/mosaic"

    print_ok "Mosaic installation complete"
}

_write_mosaic_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# Mosaic shortcut — activates the Mosaic uv virtual environment"
        echo "# and opens an interactive shell in the Mosaic directory."
        echo ""
        echo "MOSAIC_DIR=\"${MOSAIC_DIR}\""
    } > "${SHORTCUTS_DIR}/mosaic"
    cat >> "${SHORTCUTS_DIR}/mosaic" << 'EOF'

source "${MOSAIC_DIR}/.venv/bin/activate"
cd "${MOSAIC_DIR}"

echo "Mosaic environment activated."
echo "Working directory: ${MOSAIC_DIR}"
echo "To open the example notebook:"
echo "  marimo edit examples/example_notebook.py"
echo ""

exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/mosaic"
}

# ─── Evaluator ────────────────────────────────────────────────────────────────

install_evaluator() {
    print_step "Installing Evaluator"
    ensure_conda_in_path

    # Mosaic must be installed first — we use its venv for Boltz-2
    if ! is_mosaic_installed; then
        print_fail "Mosaic must be installed before the Evaluator (provides the Boltz-2 venv)."
        print_warn "Run: bash install.sh --tool mosaic"
        return 1
    fi
    MOSAIC_VENV="${MOSAIC_DIR}/.venv"
    print_ok "Mosaic venv found: ${MOSAIC_VENV}"

    # Evaluator is bundled in the monorepo — verify the directory exists
    if [[ ! -d "${EVALUATOR_DIR}" ]]; then
        print_fail "Evaluator directory not found at ${EVALUATOR_DIR}"
        print_warn "It should be bundled in the repository. Try re-cloning BinderScout."
        return 1
    fi
    print_ok "Evaluator directory: ${EVALUATOR_DIR}"

    # Install binder-compare into Mosaic venv (Boltz-2 step)
    print_step "Installing binder-compare into Mosaic venv"
    run_logged "pip install binder-compare into Mosaic venv" \
        uv pip install --python "${MOSAIC_VENV}/bin/python" -q -e "${EVALUATOR_DIR}[boltz2]" \
        || { print_fail "Failed to install binder-compare into Mosaic venv"; return 1; }

    # ESM2 pseudolikelihood expressibility prior for Mosaic hallucination.
    # fair-esm loads the weights via torch (already present); the PLL runs in
    # JAX/esm2quinox. Non-fatal — the design template guards a missing ESM2.
    print_step "Installing fair-esm (ESM2 expressibility prior) into Mosaic venv"
    run_logged "pip install fair-esm into Mosaic venv" \
        uv pip install --python "${MOSAIC_VENV}/bin/python" -q fair-esm \
        || print_warn "fair-esm install failed — Mosaic will run without the ESM2 prior"
    # Pre-cache the ESM2-150M weights (~566 MB) so offline compute nodes need no
    # download at design time (cached under ~/.cache/torch/hub/checkpoints). Non-fatal.
    run_logged --retries 3 "pre-fetch ESM2-150M weights" \
        "${MOSAIC_VENV}/bin/python" -c "import esm; esm.pretrained.esm2_t30_150M_UR50D()" \
        || print_warn "ESM2-150M weight prefetch failed — provision it offline or design runs without the prior"

    # DO NOT force a CUDA build of PyTorch into this venv. Mosaic's engine is JAX (jax-cuda),
    # and the campaign's Boltz-2 refold (`binder-compare refold-boltz2`) is JAX as well — both
    # use the GPU via jax-cuda. A CUDA torch wheel hard-pins `nvidia-cudnn-cu12==9.7.x`, but
    # jaxlib (>=0.10) requires `nvidia-cudnn-cu12>=9.8`, so installing CUDA torch SILENTLY BREAKS
    # JAX here ("RET_CHECK failure ... dnn_support != nullptr"). The transitive CPU torch wheel
    # (via boltz) is correct and harmless. If a torch-based `boltz predict` on GPU is ever needed
    # (e.g. homodimers, which refold-boltz2 skips), put it in a SEPARATE env — never this one.

    # Save the venv path so evaluate.sh can find it
    mkdir -p "${EVALUATOR_DIR}/envs"
    echo "${MOSAIC_VENV}" > "${EVALUATOR_DIR}/envs/mosaic_venv_path"
    print_ok "Mosaic venv path saved → ${EVALUATOR_DIR}/envs/mosaic_venv_path"

    # binder-eval conda env (parse-seqs + report — lightweight, no ML)
    print_step "Creating binder-eval conda environment (Python 3.10)"
    if env_exists binder-eval; then
        print_warn "Conda environment 'binder-eval' already exists — skipping creation."
    else
        run_logged "Creating binder-eval conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval.yml" -y \
            || { print_fail "Failed to create binder-eval conda env"; return 1; }
    fi
    run_logged "Installing binder-compare into binder-eval" \
        "${CONDA_CMD}" run -n binder-eval pip install -q -e "${EVALUATOR_DIR}[report]" \
        || { print_fail "Failed to install binder-compare into binder-eval"; return 1; }

    # (AF2 and Protenix refolding have both been removed; the binder-eval-af2
    #  env is no longer created. The 2nd/3rd engines are AF3 (--tool af3) and
    #  ESMFold2 (--tool esmfold2), each in its own env.)

    # Smoke test
    smoke_test "binder-compare --help" \
        "${CONDA_CMD}" run -n binder-eval binder-compare --help \
        || return 1

    # Shortcut
    print_step "Installing evaluate shortcut"
    _write_evaluator_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/evaluate"

    print_ok "Evaluator installation complete"
}

_write_evaluator_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BinderScout Evaluator shortcut — launches the interactive evaluation wizard."
        echo ""
        echo "EVALUATOR_DIR=\"${EVALUATOR_DIR}\""
    } > "${SHORTCUTS_DIR}/evaluate"
    cat >> "${SHORTCUTS_DIR}/evaluate" << 'EOF'

exec bash "${EVALUATOR_DIR}/run.sh"
EOF
    chmod +x "${SHORTCUTS_DIR}/evaluate"
}

# ─── PXDesign ────────────────────────────────────────────────────────────────

install_pxdesign() {
    print_step "Installing PXDesign"

    # Clone PXDesign
    if [[ -d "${PXDESIGN_DIR}" ]]; then
        print_ok "PXDesign already cloned at ${PXDESIGN_DIR}"
    else
        run_logged "Cloning PXDesign" \
            git clone "${PXDESIGN_REPO}" "${PXDESIGN_DIR}" \
            || { print_fail "Failed to clone PXDesign"; return 1; }
        if [[ "${PXDESIGN_COMMIT}" != "HEAD" ]]; then
            run_logged "Pinning PXDesign to ${PXDESIGN_COMMIT}" \
                bash -c "cd '${PXDESIGN_DIR}' && git checkout '${PXDESIGN_COMMIT}'" \
                || print_warn "Failed to checkout pinned commit"
        fi
    fi

    # Create conda env (gcc for Triton JIT, cuda-nvcc for deepspeed CUDA_HOME)
    #
    # env_exists guard: everything after this point is network-bound (Protenix,
    # PXDesignBench, ColabDesign, deepspeed, CUTLASS clone, weight downloads), so a
    # dropped connection mid-install is the common failure. Without the guard the
    # operator's natural `--tool pxdesign` re-run aborted here instead of resuming,
    # making this ~25-step function the only non-resumable installer path. Same
    # pattern the binder-eval-esmfold2 env already uses. Use --force to rebuild.
    print_step "Creating binderscout_pxdesign conda environment"
    if env_exists binderscout_pxdesign; then
        if [[ "${FORCE}" == true ]]; then
            run_logged "Removing existing binderscout_pxdesign env (--force)" \
                "${CONDA_CMD}" env remove -n binderscout_pxdesign -y \
                || { print_fail "Failed to remove binderscout_pxdesign env"; return 1; }
        else
            print_warn "Conda environment 'binderscout_pxdesign' already exists — reusing it."
            print_warn "  The remaining steps are idempotent; pass --force to rebuild from scratch."
        fi
    fi
    if ! env_exists binderscout_pxdesign; then
        run_logged "Creating binderscout_pxdesign env" \
            "${CONDA_CMD}" create -n binderscout_pxdesign -y python=3.11 \
                "pytorch>=2.2" "pytorch-cuda=12.4" "gcc_linux-64<14" "gxx_linux-64<14" "cuda-nvcc=12.4" "cuda-cudart-dev=12.4" \
                -c pytorch -c nvidia -c conda-forge \
            || { print_fail "Failed to create binderscout_pxdesign env"; return 1; }
    fi

    # Install PXDesign
    run_logged "Installing PXDesign (pip)" \
        "${CONDA_CMD}" run -n binderscout_pxdesign pip install -q -e "${PXDESIGN_DIR}" \
        || { print_fail "Failed to install PXDesign"; return 1; }

    # Install Protenix (PXDesign-specific fork) and PXDesignBench
    run_logged "Installing Protenix (PXDesign fork)" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install --no-cache-dir "git+https://github.com/bytedance/Protenix.git@v0.5.0+pxd" \
        || print_warn "Protenix install failed — PXDesign may not work"

    run_logged "Installing PXDesignBench" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install --no-cache-dir "git+https://github.com/bytedance/PXDesignBench.git@v0.1.2" --no-deps \
        || print_warn "PXDesignBench install failed — PXDesign may not work"

    # PXDesign setup.py has install_requires commented out; install deps from requirements.txt
    if [[ -f "${PXDESIGN_DIR}/requirements.txt" ]]; then
        run_logged "Installing PXDesign requirements" \
            "${CONDA_CMD}" run -n binderscout_pxdesign pip install -q -r "${PXDESIGN_DIR}/requirements.txt" \
            || print_warn "Some PXDesign deps failed — may need manual install"
    fi
    # click is needed by pxdesign CLI but not in requirements.txt
    run_logged "Installing PXDesign CLI deps" \
        "${CONDA_CMD}" run -n binderscout_pxdesign pip install -q click \
        || print_warn "Failed to install click — pxdesign CLI may not work"

    # requirements.txt pins torch==2.3.1 (CPU-only from PyPI); reinstall with CUDA
    run_logged "Reinstalling PyTorch with CUDA ${CUDA_VERSION}" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install torch --force-reinstall --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" \
        || print_warn "PyTorch CUDA reinstall failed — GPU may not work"

    # ColabDesign from GitHub (PyPI version 1.1.1 too old, missing 'weights' param)
    run_logged "Installing ColabDesign from GitHub" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install --no-cache-dir "git+https://github.com/sokrypton/ColabDesign.git" \
        || print_warn "ColabDesign install failed — AF2 eval may not work"

    # Upgrade deepspeed for PyTorch 2.x compatibility
    run_logged "Upgrading deepspeed" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install -q "deepspeed>=0.18" \
        || print_warn "deepspeed upgrade failed"

    # Pin dm-haiku + JAX with CUDA12 plugin so AF2 (ColabDesign) runs on GPU.
    # Without [cuda12], pip pulls the CPU-only jaxlib wheel and AF2 evaluation
    # falls back to CPU (~23 min/eval vs ~30 s on a 3090).
    # nvidia-cuda-nvcc-cu12 is also pinned to 12.4.x because the latest 12.9.x
    # ships as a namespace package (no __init__.py) which breaks JAX's
    # _try_cuda_nvcc_import — pathlib.Path(cuda_nvcc.__file__).parent fails
    # on __file__ == None.
    # haiku 0.0.12 is the last version to support jax.core.JaxprEqn.
    run_logged "Pinning dm-haiku and JAX (with CUDA12)" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install -q "dm-haiku==0.0.12" "jax[cuda12]==0.4.35" \
        "nvidia-cuda-nvcc-cu12==12.4.131" \
        || print_warn "dm-haiku/JAX pin failed"

    # ── Post-install patches for known upstream issues ──────────────────────
    print_step "Applying PXDesign compatibility patches"

    # Patch: configs_infer.py num_workers (default 16 causes dataloader deadlock)
    if [[ -f "${PXDESIGN_DIR}/pxdesign/configs/configs_infer.py" ]]; then
        sed -i 's/"num_workers": 16/"num_workers": 0/' \
            "${PXDESIGN_DIR}/pxdesign/configs/configs_infer.py" 2>/dev/null && \
            print_ok "Patched configs_infer.py: num_workers=0"
    fi

    # Patch: pxdbench NumpyEncoder (numpy float32 not JSON serializable)
    run_logged "Patching pxdbench JSON serialization" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python << 'PATCHEOF'
import importlib.util, pathlib
spec = importlib.util.find_spec('pxdbench')
if not spec or not spec.submodule_search_locations:
    print('pxdbench not found — skipping'); exit(0)
base = pathlib.Path(spec.submodule_search_locations[0])
ENC = ('\n\nclass _NumpyEncoder(json.JSONEncoder):\n'
    '    def default(self, obj):\n'
    '        if isinstance(obj, (np.floating,)):\n'
    '            return float(obj)\n'
    '        if isinstance(obj, (np.integer,)):\n'
    '            return int(obj)\n'
    '        if isinstance(obj, np.ndarray):\n'
    '            return obj.tolist()\n'
    '        return super().default(obj)\n')
for fn in ['tools/af2/main_af2_complex.py', 'tools/af2/main_af2_monomer.py']:
    fp = base / fn
    if not fp.exists(): continue
    t = fp.read_text()
    if '_NumpyEncoder' in t: print(f'Already patched: {fn}'); continue
    m = 'from colabdesign import clear_mem, mk_afdesign_model'
    if m in t: t = t.replace(m, m + ENC)
    t = t.replace('json.dump(stats, f)', 'json.dump(stats, f, cls=_NumpyEncoder)')
    t = t.replace('json.dump(results, f)', 'json.dump(results, f, cls=_NumpyEncoder)')
    fp.write_text(t); print(f'Patched: {fn}')
PATCHEOF

    # Patch: MPNN subprocess writes error JSON on failure (prevents JSONDecodeError)
    run_logged "Patching pxdbench MPNN error handling" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python << 'MPNNEOF'
import importlib.util, pathlib
spec = importlib.util.find_spec('pxdbench')
if not spec or not spec.submodule_search_locations:
    print('pxdbench not found — skipping'); exit(0)
base = pathlib.Path(spec.submodule_search_locations[0])
# Patch main_mpnn.py: write error JSON on exception
mpnn = base / 'tools/protmpnn/main_mpnn.py'
if mpnn.exists():
    t = mpnn.read_text()
    old = '        traceback.print_exc()\n        exit(1)'
    new = ('        traceback.print_exc()\n'
           '        with open(args.output, "w") as f:\n'
           '            json.dump({"error": True, "message": str(e)}, f)\n'
           '        exit(1)')
    if old in t and 'error' not in t.split('traceback.print_exc')[1][:100]:
        t = t.replace(old, new); mpnn.write_text(t); print('Patched main_mpnn.py')
    else: print('main_mpnn.py already patched or different format')
# Patch base.py: handle JSONDecodeError
bp = base / 'tools/base.py'
if bp.exists():
    t = bp.read_text()
    if 'JSONDecodeError' not in t:
        old_base = '                return json.load(f)\n\n        except Exception as e:'
        new_base = ('                result = json.load(f)\n'
                    '            if isinstance(result, dict) and result.get("error"):\n'
                    '                raise RuntimeError(f"Subprocess failed: {result.get(\'message\', \'unknown\')}")\n'
                    '            return result\n\n'
                    '        except json.JSONDecodeError:\n'
                    '            raise RuntimeError(f"Subprocess {self.script_path} produced empty output")\n'
                    '        except Exception as e:')
        if old_base in t:
            t = t.replace(old_base, new_base); bp.write_text(t); print('Patched base.py')
        else: print('base.py format differs — manual patch may be needed')
    else: print('base.py already patched')
MPNNEOF

    # Patch: Make ProtenixFilter import lazy in pxdbench (prevents CUDA JIT in MPNN subprocess)
    run_logged "Patching pxdbench lazy ProtenixFilter import" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python << 'LAZYEOF'
import importlib.util, pathlib
spec = importlib.util.find_spec('pxdbench')
if not spec or not spec.submodule_search_locations:
    print('pxdbench not found — skipping'); exit(0)
init = pathlib.Path(spec.submodule_search_locations[0]) / 'tools/__init__.py'
if not init.exists():
    print('tools/__init__.py not found'); exit(0)
t = init.read_text()
if 'try:' in t:
    print('Already patched'); exit(0)
new = ('from .registry import register\n\n'
       'try:\n'
       '    from .ptx.ptx import ProtenixFilter\n'
       '    register("public", ProtenixFilter)\n'
       'except Exception:\n'
       '    pass\n')
init.write_text(new)
print('Patched tools/__init__.py: lazy ProtenixFilter import')
LAZYEOF

    # Patch: Make protenix LayerNorm CUDA JIT optional (falls back to torch.nn.functional)
    run_logged "Patching protenix LayerNorm fallback" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python << 'LNEOF'
import importlib.util, pathlib
spec = importlib.util.find_spec('protenix')
if not spec or not spec.submodule_search_locations:
    print('protenix not found — skipping'); exit(0)
ln = pathlib.Path(spec.submodule_search_locations[0]) / 'model/layer_norm/layer_norm.py'
if not ln.exists():
    print('layer_norm.py not found'); exit(0)
t = ln.read_text()
if 'fastfold_layer_norm_cuda = None' in t:
    print('Already patched'); exit(0)
# Replace the try block that hard-fails on CUDA JIT with a soft fallback
old = 'try:\n    fastfold_layer_norm_cuda = importlib.import_module("fastfold_layer_norm_cuda")\nexcept ImportError:'
if old not in t:
    # Alternative: wrap entire JIT block in soft try/except
    t = t.replace(
        'fastfold_layer_norm_cuda = importlib.import_module("fastfold_layer_norm_cuda")',
        'fastfold_layer_norm_cuda = None\ntry:\n    fastfold_layer_norm_cuda = importlib.import_module("fastfold_layer_norm_cuda")\nexcept ImportError:'
    )
# Ensure forward() has the torch.nn.functional fallback
if 'torch.nn.functional.layer_norm' not in t:
    old_fwd = '    def forward(self, input):\n        return FusedLayerNormAffineFunction.apply('
    new_fwd = ('    def forward(self, input):\n'
               '        if fastfold_layer_norm_cuda is None:\n'
               '            return torch.nn.functional.layer_norm(\n'
               '                input, self.normalized_shape, self.weight, self.bias, self.eps\n'
               '            )\n'
               '        return FusedLayerNormAffineFunction.apply(')
    t = t.replace(old_fwd, new_fwd)
ln.write_text(t)
print('Patched layer_norm.py: CUDA JIT fallback to torch.nn.functional')
LNEOF

    # Install cusparse headers for CUDA JIT (optional but avoids build warnings)
    run_logged "Installing libcusparse-dev for CUDA headers" \
        "${CONDA_CMD}" install -n binderscout_pxdesign -c "nvidia/label/cuda-${CUDA_VERSION}.0" \
        libcusparse-dev -y \
        || print_warn "libcusparse-dev install failed — CUDA JIT will use fallback"

    # Download weights if script exists
    if [[ -f "${PXDESIGN_DIR}/download_tool_weights.sh" ]]; then
        run_logged --retries 3 "Downloading PXDesign weights" \
            bash -c "cd '${PXDESIGN_DIR}' && bash download_tool_weights.sh" \
            || print_warn "PXDesign weights download failed — download manually later"
    else
        print_warn "No download_tool_weights.sh found — download PXDesign weights manually"
    fi

    # Smoke test
    smoke_test "PXDesign import check" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python -c "import torch; print('PXDesign env OK')" \
        || return 1

    # ── Conda env activate.d hook for CUDA-header CPATH + CUTLASS_PATH ──────
    #
    # Protenix's `fastfold_layer_norm_cuda` extension and DeepSpeed4Science's
    # `DS4Sci_EvoformerAttention` kernel are both JIT-compiled at first import.
    # The conda env already installs `cuda-cudart-dev` and pip-side `nvidia-*`
    # wheels, but those put their headers under non-standard paths:
    #   - $CONDA_PREFIX/targets/x86_64-linux/include/        (cuda-cudart-dev)
    #   - $CONDA_PREFIX/lib/python3.11/site-packages/nvidia/<lib>/include/  (pip nvidia-*)
    # The JIT build only searches $CONDA_PREFIX/include by default, so it
    # fails on cuda_runtime_api.h, cublas_v2.h, cusolverDn.h, etc.
    #
    # DS4Sci EvoformerAttention additionally needs NVIDIA CUTLASS v3.5.1
    # headers (header-only library at ~/cutlass).
    #
    # This activate.d hook sets CPATH (preserving existing) and CUTLASS_PATH
    # whenever the env is activated, with CONDA_BACKUP_ for clean deactivation.
    # Permanent fix for the protenix+DS4Sci JIT trap that bit the ApoE4
    # BinderScout / PXDesign-BM4 campaign 2026-05-27 / 2026-05-28.
    print_step "Setting up CUDA-header CPATH + CUTLASS_PATH activate.d hook"

    # Clone CUTLASS v3.5.1 (header-only, ~150 MB) if not already present.
    local CUTLASS_DIR="${HOME}/cutlass"
    if [[ -d "${CUTLASS_DIR}/include/cutlass" ]]; then
        print_ok "CUTLASS already present at ${CUTLASS_DIR}"
    else
        run_logged "Cloning NVIDIA CUTLASS v3.5.1 (header-only)" \
            git clone --depth 1 --branch v3.5.1 \
            https://github.com/NVIDIA/cutlass.git "${CUTLASS_DIR}" \
            || print_warn "CUTLASS clone failed — DS4Sci_EvoformerAttention JIT will not work"
    fi

    # Resolve the conda env prefix so we can write activate.d/deactivate.d.
    local PXD_ENV_PREFIX
    PXD_ENV_PREFIX=$("${CONDA_CMD}" run -n binderscout_pxdesign printenv CONDA_PREFIX 2>/dev/null)
    if [[ -z "${PXD_ENV_PREFIX}" || ! -d "${PXD_ENV_PREFIX}" ]]; then
        print_warn "Could not resolve binderscout_pxdesign CONDA_PREFIX — skipping activate.d hook"
    else
        mkdir -p "${PXD_ENV_PREFIX}/etc/conda/activate.d" \
                 "${PXD_ENV_PREFIX}/etc/conda/deactivate.d"

        cat > "${PXD_ENV_PREFIX}/etc/conda/activate.d/binderscout_pxd_headers.sh" << 'ACTEOF'
# BinderScout: expose CUDA + nvidia-* headers + CUTLASS to JIT builds.
# Written by install/install.sh (install_pxdesign). Permanent fix for the
# protenix fastfold_layer_norm_cuda + DS4Sci_EvoformerAttention JIT-compile traps
# documented in the ApoE4 BinderScout campaign (2026-05-27/28).
if [ -n "${CPATH:-}" ]; then
    export CONDA_BACKUP_CPATH="${CPATH}"
fi
_BM_NVIDIA_INC_ROOT="${CONDA_PREFIX}/lib/python3.11/site-packages/nvidia"
_BM_CPATH_PARTS="${CONDA_PREFIX}/targets/x86_64-linux/include"
for _bm_sub in cublas cuda_cupti cuda_nvcc cuda_nvrtc cuda_runtime cudnn cufft curand cusolver cusparse nccl nvjitlink nvtx; do
    if [ -d "${_BM_NVIDIA_INC_ROOT}/${_bm_sub}/include" ]; then
        _BM_CPATH_PARTS="${_BM_CPATH_PARTS}:${_BM_NVIDIA_INC_ROOT}/${_bm_sub}/include"
    fi
done
export CPATH="${_BM_CPATH_PARTS}${CPATH:+:${CPATH}}"
unset _BM_NVIDIA_INC_ROOT _BM_CPATH_PARTS _bm_sub

if [ -n "${CUTLASS_PATH:-}" ]; then
    export CONDA_BACKUP_CUTLASS_PATH="${CUTLASS_PATH}"
fi
if [ -d "${HOME}/cutlass/include/cutlass" ]; then
    export CUTLASS_PATH="${HOME}/cutlass"
fi
ACTEOF

        cat > "${PXD_ENV_PREFIX}/etc/conda/deactivate.d/binderscout_pxd_headers.sh" << 'DEACTEOF'
# BinderScout: restore CPATH / CUTLASS_PATH on deactivation.
if [ -n "${CONDA_BACKUP_CPATH:-}" ]; then
    export CPATH="${CONDA_BACKUP_CPATH}"
    unset CONDA_BACKUP_CPATH
else
    unset CPATH
fi
if [ -n "${CONDA_BACKUP_CUTLASS_PATH:-}" ]; then
    export CUTLASS_PATH="${CONDA_BACKUP_CUTLASS_PATH}"
    unset CONDA_BACKUP_CUTLASS_PATH
else
    unset CUTLASS_PATH
fi
DEACTEOF
        print_ok "Wrote activate.d/deactivate.d hooks (CPATH + CUTLASS_PATH)"
    fi

    # ── Create missing unversioned dev .so symlinks ─────────────────────────
    #
    # conda-forge's `libcurand`, `libcusolver`, `libcufft`, etc. ship only the
    # versioned shared objects (libcurand.so.10, libcurand.so.10.3.5.147). The
    # dev symlink `libcurand.so` (which the linker `-lcurand` looks for) is in
    # the matching `lib*-dev` packages which the env does not currently pull
    # in. Without it, DeepSpeed4Science evoformer_attn JIT-link fails with
    # `ld: cannot find -lcurand`. Create the unversioned symlinks for every
    # lib*.so.<MAJOR> in $CONDA_PREFIX/lib.
    # Permanent fix for the linker trap that bit the ApoE4 BinderScout
    # campaign 2026-05-28 (DS4Sci evoformer_attn JIT-link).
    if [[ -n "${PXD_ENV_PREFIX:-}" && -d "${PXD_ENV_PREFIX}/lib" ]]; then
        print_step "Creating missing unversioned .so dev symlinks in env lib/"
        local _bm_so_created=0
        local _so _base _name _unver
        shopt -s nullglob
        for _so in "${PXD_ENV_PREFIX}"/lib/lib*.so.*; do
            [[ -L "$_so" || -f "$_so" ]] || continue
            _base=$(basename "$_so")
            # Only single .so.<digits> segments (libfoo.so.10), NOT libfoo.so.10.3.5.147.
            case "$_base" in
                *.so.[0-9]|*.so.[0-9][0-9]|*.so.[0-9][0-9][0-9]) ;;
                *) continue ;;
            esac
            _name=${_base%.so.*}
            _unver="${PXD_ENV_PREFIX}/lib/${_name}.so"
            if [[ ! -e "$_unver" ]]; then
                ln -s "$_base" "$_unver"
                _bm_so_created=$((_bm_so_created + 1))
            fi
        done
        shopt -u nullglob
        print_ok "Created ${_bm_so_created} unversioned .so dev symlinks"
    fi

    # Smoke test: confirm both JIT kernels can be loaded under the env.
    # This catches missing CUTLASS or missing CUDA headers at install time
    # instead of 5 h into a sweep.
    run_logged "PXDesign JIT-kernel smoke test (protenix layer_norm + DS4Sci EvoformerAttention)" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python - << 'JITEOF'
import sys
try:
    import protenix  # triggers fastfold_layer_norm_cuda JIT compile
    import torch
    from deepspeed.ops.deepspeed4science import DS4Sci_EvoformerAttention
    # DS4Sci_EvoformerAttention asserts seq_len > 16; use 32.
    B, N, S, H, D = 1, 4, 32, 4, 8
    q = torch.randn(B, N, S, H, D, device="cuda", dtype=torch.bfloat16)
    k = q.clone(); v = q.clone()
    b0 = torch.zeros(B, N, 1, 1, S, device="cuda", dtype=torch.bfloat16)
    b1 = torch.zeros(B, 1, H, S, S, device="cuda", dtype=torch.bfloat16)
    _ = DS4Sci_EvoformerAttention(q, k, v, [b0, b1])
    print("JIT smoke OK: protenix import + DS4Sci EvoformerAttention compiled and ran.")
except Exception as e:
    print(f"JIT smoke FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    raise
JITEOF
    # Soft-fail: print_warn if smoke fails (installer still completes; user
    # can rerun PXDesign installation after fixing the underlying issue).

    # Shortcut
    mkdir -p "${SHORTCUTS_DIR}"
    cat > "${SHORTCUTS_DIR}/pxdesign" << PXDEOF
#!/bin/bash
# BinderScout PXDesign shortcut
exec ${CONDA_CMD} run -n binderscout_pxdesign bash
PXDEOF
    chmod +x "${SHORTCUTS_DIR}/pxdesign"

    print_ok "PXDesign installation complete"
}

# ─── Proteina-Complexa ────────────────────────────────────────────────────────

# Reuse weights already downloaded by other BinderScout tools (symlinks).
_link_complexa_shared_weights() {
    local cm="${PROTEINA_COMPLEXA_DIR}/community_models"

    # AF2 weights from BindCraft
    if [[ -d "${BINDCRAFT_DIR}/params" ]] && [[ ! -e "${cm}/ckpts/AF2" ]]; then
        mkdir -p "${cm}/ckpts"
        ln -sfn "${BINDCRAFT_DIR}/params" "${cm}/ckpts/AF2"
        print_ok "AF2 weights → BindCraft/params (symlink)"
    elif [[ -d "${BINDERSCOUT_DIR}/bindcraft-tools/af2_params" ]] && [[ ! -e "${cm}/ckpts/AF2" ]]; then
        mkdir -p "${cm}/ckpts"
        ln -sfn "${BINDERSCOUT_DIR}/bindcraft-tools/af2_params" "${cm}/ckpts/AF2"
        print_ok "AF2 weights → bindcraft-tools/af2_params (symlink)"
    fi

    # ProteinMPNN ca_model_weights + vanilla_model_weights from PXDesign
    if [[ -d "${PXDESIGN_DIR}/tool_weights/mpnn/ca_model_weights" ]] && [[ ! -e "${cm}/ProteinMPNN/ca_model_weights" ]]; then
        ln -sfn "${PXDESIGN_DIR}/tool_weights/mpnn/ca_model_weights" "${cm}/ProteinMPNN/ca_model_weights"
        ln -sfn "${PXDESIGN_DIR}/tool_weights/mpnn/vanilla_model_weights" "${cm}/ProteinMPNN/vanilla_model_weights"
        print_ok "ProteinMPNN weights → PXDesign/tool_weights/mpnn (symlink)"
    fi

}

# Install foldseek and mmseqs2 static binaries into Complexa's venv.
_install_complexa_tools() {
    local venv_bin="${PROTEINA_COMPLEXA_DIR}/.venv/bin"

    # Foldseek
    if [[ ! -x "${venv_bin}/foldseek" ]]; then
        print_step "Installing foldseek"
        local tmp_dir
        tmp_dir="$(mktemp -d)"
        if curl -fsSL "https://mmseqs.com/foldseek/foldseek-linux-avx2.tar.gz" \
                | tar xz -C "${tmp_dir}" 2>/dev/null; then
            cp "${tmp_dir}/foldseek/bin/foldseek" "${venv_bin}/foldseek"
            chmod +x "${venv_bin}/foldseek"
            print_ok "foldseek installed → ${venv_bin}/foldseek"
        else
            print_warn "foldseek download failed — install manually"
        fi
        rm -rf "${tmp_dir}"
    else
        print_ok "foldseek already installed"
    fi

    # MMseqs2
    if [[ ! -x "${venv_bin}/mmseqs" ]]; then
        print_step "Installing mmseqs2"
        local tmp_dir
        tmp_dir="$(mktemp -d)"
        if curl -fsSL "https://mmseqs.com/latest/mmseqs-linux-avx2.tar.gz" \
                | tar xz -C "${tmp_dir}" 2>/dev/null; then
            cp "${tmp_dir}/mmseqs/bin/mmseqs" "${venv_bin}/mmseqs"
            chmod +x "${venv_bin}/mmseqs"
            print_ok "mmseqs installed → ${venv_bin}/mmseqs"
        else
            print_warn "mmseqs download failed — install manually"
        fi
        rm -rf "${tmp_dir}"
    else
        print_ok "mmseqs already installed"
    fi
}

# Write a complete .env file with correct local paths.
_write_complexa_env() {
    print_step "Configuring Proteina-Complexa .env"
    local env_file="${PROTEINA_COMPLEXA_DIR}/.env"

    # PC expects AF2 weights at community_models/ckpts/AF2/ (populated by
    # _link_complexa_shared_weights earlier via symlink to BindCraft/params).
    local af2_dir="${PROTEINA_COMPLEXA_DIR}/community_models/ckpts/AF2"
    if [[ ! -d "${af2_dir}" || -z "$(ls -A "${af2_dir}" 2>/dev/null)" ]]; then
        if [[ -d "${BINDCRAFT_DIR}/params" ]]; then
            af2_dir="${BINDCRAFT_DIR}/params"
        elif [[ -d "${BINDERSCOUT_DIR}/bindcraft-tools/af2_params" ]]; then
            af2_dir="${BINDERSCOUT_DIR}/bindcraft-tools/af2_params"
        fi
    fi

    cat > "${env_file}" <<ENVEOF
# BinderScout-generated .env for Proteina-Complexa
LOCAL_CODE_PATH=${PROTEINA_COMPLEXA_DIR}
LOCAL_DATA_PATH=${PROTEINA_COMPLEXA_DIR}/data
LOCAL_CACHE_DIR=\${LOCAL_CODE_PATH}/.cache
LOCAL_CHECKPOINT_PATH=${PROTEINA_COMPLEXA_DIR}/ckpts
LOGURU_LEVEL=INFO
USE_V2_COMPLEXA_ARCH=False
COMMUNITY_MODELS_PATH=\${LOCAL_CODE_PATH}/community_models
ESM_DIR=\${COMMUNITY_MODELS_PATH}/ckpts/ESM2
AF2_DIR=${af2_dir}
RF3_DIR=\${COMMUNITY_MODELS_PATH}/ckpts/RF3
RF3_CKPT_PATH=\${RF3_DIR}/rf3_foundry_01_24_latest_remapped.ckpt
UV_VENV=\${LOCAL_CODE_PATH}/.venv
FOLDSEEK_EXEC=\${UV_VENV}/bin/foldseek
RF3_EXEC_PATH=\${UV_VENV}/bin/rf3
SC_EXEC=\${LOCAL_CODE_PATH}/env/docker/internal/sc
MMSEQS_EXEC=\${UV_VENV}/bin/mmseqs
DSSP_EXEC=\${LOCAL_CODE_PATH}/env/docker/internal/dssp
TMOL_PATH=\${UV_VENV}/lib/python3.12/site-packages/tmol
DATA_PATH=\${LOCAL_DATA_PATH}
CKPT_PATH=\${LOCAL_CHECKPOINT_PATH}
WANDB_API_KEY=
WANDB_ENTITY=
HF_TOKEN=
ENVEOF
    mkdir -p "${PROTEINA_COMPLEXA_DIR}/data"
    print_ok "Wrote .env with local paths"
    if [[ -n "${af2_dir}" ]]; then
        print_ok "AF2_DIR=${af2_dir}"
    else
        print_warn "AF2 weights not found — install BindCraft first, or set AF2_DIR in .env"
    fi
}

install_proteina_complexa() {
    print_step "Installing Proteina-Complexa"

    # Clone
    print_step "Cloning Proteina-Complexa repository"
    if [[ -d "${PROTEINA_COMPLEXA_DIR}" ]]; then
        print_warn "Directory ${PROTEINA_COMPLEXA_DIR} already exists."
        if confirm_destructive "Remove and reclone?"; then
            rm -rf "${PROTEINA_COMPLEXA_DIR}" || { print_fail "Failed to remove ${PROTEINA_COMPLEXA_DIR}"; return 1; }
        else
            print_warn "Skipping reclone; using existing directory."
        fi
    fi
    if [[ ! -d "${PROTEINA_COMPLEXA_DIR}" ]]; then
        run_logged --retries 3 "Cloning Proteina-Complexa" \
            git clone --depth 50 "${PROTEINA_COMPLEXA_REPO}" "${PROTEINA_COMPLEXA_DIR}" \
            || { print_fail "Failed to clone Proteina-Complexa"; return 1; }
        if [[ "${PROTEINA_COMPLEXA_COMMIT}" != "HEAD" ]]; then
            git -C "${PROTEINA_COMPLEXA_DIR}" checkout "${PROTEINA_COMPLEXA_COMMIT}" --quiet \
                || print_warn "Could not pin Proteina-Complexa to ${PROTEINA_COMPLEXA_COMMIT} — using latest"
        fi
    fi

    # Ensure uv is available (same logic as Mosaic)
    print_step "Checking for uv package manager"
    if ! command -v uv &>/dev/null; then
        print_warn "uv not found — installing via official installer"
        curl -LsSf https://astral.sh/uv/install.sh | sh \
            || { print_fail "Failed to install uv"; return 1; }
        export PATH="${HOME}/.local/bin:${PATH}"
        if ! grep -q '.local/bin' "${HOME}/.bashrc" 2>/dev/null; then
            echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "${HOME}/.bashrc"
            print_ok "Added ~/.local/bin to PATH in ~/.bashrc"
        fi
    fi
    if ! command -v uv &>/dev/null; then
        print_fail "uv still not found after install; check PATH"
        return 1
    fi
    print_ok "uv is available: $(command -v uv)"

    # Build uv venv using upstream build script
    print_step "Building Proteina-Complexa uv environment"

    # Ensure a C compiler is available (cpdb-protein needs one).
    # Prefer system gcc; fall back to conda's cross-compiler with CC/CXX.
    if ! command -v x86_64-linux-gnu-gcc &>/dev/null && ! command -v gcc &>/dev/null; then
        local _conda_gcc
        _conda_gcc="$(command -v x86_64-conda-linux-gnu-gcc 2>/dev/null || true)"
        local _conda_gxx
        _conda_gxx="$(command -v x86_64-conda-linux-gnu-g++ 2>/dev/null || true)"
        if [[ -n "${_conda_gcc}" ]]; then
            export CC="${_conda_gcc}"
            export CXX="${_conda_gxx:-${_conda_gcc}}"
            print_ok "Using conda C compiler: ${CC}"
        else
            print_warn "No C compiler found — cpdb-protein may fail to build."
            print_warn "Install gcc: sudo apt-get install build-essential  OR  conda install -c conda-forge gcc_linux-64"
        fi
    fi

    # Ensure uv has a managed Python with C headers (system python3 often
    # lacks python3-dev).  UV_PYTHON_PREFERENCE=only-managed makes uv pick
    # its own standalone build that bundles Python.h.
    if ! /usr/bin/test -f /usr/include/python3.12/Python.h 2>/dev/null; then
        "${HOME}/.local/bin/uv" python install 3.12 2>/dev/null || true
        export UV_PYTHON_PREFERENCE="only-managed"
        print_ok "Using uv-managed Python 3.12 (system python3-dev not found)"
    fi

    if [[ -f "${PROTEINA_COMPLEXA_DIR}/env/build_uv_env.sh" ]]; then
        run_logged "Building uv venv (env/build_uv_env.sh)" \
            bash -c "cd '${PROTEINA_COMPLEXA_DIR}' && bash env/build_uv_env.sh" \
            || { print_fail "uv env build failed for Proteina-Complexa"; return 1; }
    else
        # Fallback: create venv manually if build script not present
        print_warn "No env/build_uv_env.sh found — creating venv with uv sync"
        run_logged "Setting up Proteina-Complexa venv (uv sync)" \
            bash -c "cd '${PROTEINA_COMPLEXA_DIR}' && uv sync" \
            || { print_fail "uv sync failed for Proteina-Complexa"; return 1; }
    fi

    # Initialize and download checkpoints
    print_step "Initializing Proteina-Complexa"
    if [[ -x "${PROTEINA_COMPLEXA_DIR}/.venv/bin/complexa" ]]; then
        # Generate .env file (must run from project root where .env_example lives)
        run_logged "Running complexa init" \
            bash -c "cd '${PROTEINA_COMPLEXA_DIR}' && .venv/bin/complexa init" \
            || print_warn "complexa init failed — .env may need manual setup"

        # Download ALL models (Complexa + community models).
        # Activate the venv first: `complexa download` shells out to
        # `python script_utils/download/download_esm_model.py`, which
        # picks the venv's transformers only when `.venv/bin` is on PATH.
        # shellcheck disable=SC1091
        print_step "Downloading Proteina-Complexa checkpoints & community models"
        run_logged --retries 2 "Downloading all models (complexa download --everything)" \
            bash -c "cd '${PROTEINA_COMPLEXA_DIR}' && source .venv/bin/activate && complexa download --everything" \
            || print_warn "Model download failed — download manually with: source .venv/bin/activate && complexa download --everything"
    else
        print_warn "complexa CLI not found in .venv — skipping init/download"
    fi

    # Reuse existing weights from other BinderScout tools via symlinks
    _link_complexa_shared_weights

    # Install foldseek & mmseqs2 (static binaries, no root needed)
    _install_complexa_tools

    # Configure .env with correct local paths
    _write_complexa_env

    # Smoke test
    smoke_test "Proteina-Complexa import check" \
        "${PROTEINA_COMPLEXA_DIR}/.venv/bin/python" -c "import proteinfoundation; print('OK')" \
        || return 1

    # Shortcut
    print_step "Installing proteina-complexa shortcut"
    _write_proteina_complexa_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/complexa"

    print_ok "Proteina-Complexa installation complete"
}

_write_proteina_complexa_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# Proteina-Complexa shortcut — activates the uv virtual environment"
        echo "# and opens an interactive shell in the Proteina-Complexa directory."
        echo ""
        echo "PROTEINA_COMPLEXA_DIR=\"${PROTEINA_COMPLEXA_DIR}\""
    } > "${SHORTCUTS_DIR}/complexa"
    cat >> "${SHORTCUTS_DIR}/complexa" << 'EOF'

source "${PROTEINA_COMPLEXA_DIR}/.venv/bin/activate"
cd "${PROTEINA_COMPLEXA_DIR}"

echo "Proteina-Complexa environment activated."
echo "Working directory: ${PROTEINA_COMPLEXA_DIR}"
echo "To run binder design:"
echo "  complexa design configs/search_binder_local_pipeline.yaml ++run_name=test"
echo ""

exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/complexa"
}

# ─── RFD3 / Foundry (RosettaCommons) ─────────────────────────────────────────
# Butcher et al. 2025. BSD-3-Clause. PyPI: `rc-foundry`.
# — no DGL, no SE3-Transformer, works on aarch64 / DGX Spark. Weights live
# under BinderScout/weights/foundry.

# ─── BindCraft 2 ──────────────────────────────────────────────────────────────

# _bindcraft2_af2_params
# Echoes the first usable AlphaFold 2 parameter directory, or nothing.
#
# BindCraft 2 wants to download 5.3 GB of AF2 parameters on first install. We
# almost always already have them, so this resolves an existing cache instead.
# It matters more than convenience: BindCraft 2's own selfcheck EXITS 1 (it does
# not warn) when --no-weights was passed and no parameters can be found, and
# BindCraft 1 -- the usual source of ${BINDERSCOUT_DIR}/BindCraft/params -- cannot
# be installed on aarch64 at all. Without a fallback chain the Spark install
# would fail on a machine that has the files sitting in another directory.
_bindcraft2_af2_params() {
    local candidate
    for candidate in \
        "${BINDCRAFT2_AF2_PARAMS:-}" \
        "${BINDERSCOUT_DIR}/BindCraft/params" \
        "${HOME}/Documents/OLD/BinderScout/bindcraft-tools/af2_params" \
        "${HOME}/bindcraft-tools/af2_params"
    do
        [[ -n "${candidate}" && -d "${candidate}" ]] || continue
        # Require one real checkpoint rather than just a directory: an
        # interrupted download leaves the folder present and empty, which would
        # otherwise be reported as a cache hit and fail much later.
        if compgen -G "${candidate}/*multimer_v3.npz" > /dev/null \
           || compgen -G "${candidate}/params/*multimer_v3.npz" > /dev/null; then
            echo "${candidate}"
            return 0
        fi
    done
    return 1
}

install_bindcraft2() {
    print_step "Installing BindCraft 2"

    _stage_bindcraft2_source || return 1

    # Build the venv ourselves rather than letting BindCraft 2's install.sh do
    # it. Left alone, that script installs into whatever environment is already
    # active whenever CONDA_PREFIX or VIRTUAL_ENV is set -- and this installer
    # activates conda for almost everything -- which would put jax>=0.11 into an
    # unrelated env and leave no .venv for the configurator to detect. Creating
    # it here also removes its conda fallback path, so BindCraft2/.venv/bin/python
    # is the one detection marker everything else can rely on.
    print_step "Checking for uv package manager"
    if ! command -v uv &>/dev/null; then
        print_warn "uv not found — installing via official installer"
        curl -LsSf https://astral.sh/uv/install.sh | sh \
            || { print_fail "Failed to install uv"; return 1; }
        export PATH="${HOME}/.local/bin:${PATH}"
        if ! grep -q '.local/bin' "${HOME}/.bashrc" 2>/dev/null; then
            echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "${HOME}/.bashrc"
            print_ok "Added ~/.local/bin to PATH in ~/.bashrc"
        fi
    fi
    command -v uv &>/dev/null || { print_fail "uv still not found after install; check PATH"; return 1; }
    print_ok "uv is available: $(command -v uv)"

    if [[ -x "${BINDCRAFT2_DIR}/.venv/bin/python" ]]; then
        print_ok "BindCraft 2 venv already exists — skipping creation"
    else
        # BindCraft 2 needs >=3.12; uv fetches an interpreter when the machine
        # has none that new, which is the usual case on an older login node.
        run_logged "Creating BindCraft 2 venv (Python >=3.12)" \
            uv venv --seed --python ">=3.12" "${BINDCRAFT2_DIR}/.venv" \
            || { print_fail "Failed to create ${BINDCRAFT2_DIR}/.venv"; return 1; }
    fi

    local af2_params
    if af2_params="$(_bindcraft2_af2_params)"; then
        print_ok "Reusing AlphaFold 2 parameters at ${af2_params}"
    else
        af2_params=""
        print_warn "No AlphaFold 2 parameter cache found — BindCraft 2 will download ~5.3 GB"
    fi

    # The accelerator argument is deliberately omitted unless asked for.
    # BindCraft 2 reads the driver's CUDA version itself and already downgrades
    # to cuda12 for any card below compute capability 7.5. Deriving it from our
    # ${CUDA_VERSION} would be wrong -- that is a pip wheel-index version, not a
    # driver version -- and passing it explicitly bypasses that downgrade.
    local bc2_args=()
    [[ -n "${BINDCRAFT2_ACCELERATOR:-}" ]] && bc2_args+=("${BINDCRAFT2_ACCELERATOR}")
    [[ -n "${af2_params}" ]] && bc2_args+=("--no-weights")

    run_logged "Installing BindCraft 2" \
        env -u CONDA_PREFIX -u VIRTUAL_ENV \
            BINDCRAFT_PYTHON="${BINDCRAFT2_DIR}/.venv/bin/python" \
            BINDCRAFT_AF2_PARAMS="${af2_params}" \
            bash -c "cd '${BINDCRAFT2_DIR}' && bash install.sh ${bc2_args[*]}" \
        || { print_fail "BindCraft 2 install failed — see ${LOG_FILE}"; return 1; }

    smoke_test "BindCraft 2 CLI" \
        "${BINDCRAFT2_DIR}/.venv/bin/bindcraft" --help \
        || { print_fail "BindCraft 2 CLI did not run"; return 1; }

    # A CPU-only JAX is an installation a hundred times slower than the person
    # running it expects, with nothing afterwards to say so. Fail on x86, where
    # the GPU wheels are well trodden; warn on aarch64, where sm_121 support is
    # exactly the open question the first Spark campaign exists to answer.
    print_step "Smoke test: BindCraft 2 sees the GPU"
    local backend
    if backend="$("${BINDCRAFT2_DIR}/.venv/bin/python" -c 'import jax; print(jax.default_backend())' 2>/dev/null)"; then
        if [[ "${backend}" == "gpu" ]]; then
            print_ok "Smoke test passed: jax backend is gpu"
        elif ! nvidia-smi -L >/dev/null 2>&1; then
            # This host has no usable GPU at all, so jax reporting cpu is the
            # correct answer, not a broken install. Normal on a cluster login
            # node: the install is staged on a shared filesystem and the
            # campaign runs on an allocated GPU node. Failing here made every
            # Clara install exit non-zero while being perfectly good.
            print_warn "jax reports '${backend}': no GPU visible on this host (normal on a login node)."
            print_warn "  The install is fine; verify the backend inside a GPU allocation before a campaign."
        elif [[ "${ARCH}" == "aarch64" ]]; then
            print_warn "jax fell back to '${backend}' on aarch64 — BindCraft 2 is unvalidated here; a campaign would run on the CPU"
        else
            print_fail "jax fell back to '${backend}' — a campaign would run on the CPU"
            return 1
        fi
    else
        print_warn "jax did not start here (normal on a login node); check inside your allocation"
    fi

    _write_bindcraft2_shortcut

    print_ok "BindCraft 2 installation complete"
    print_ok "  Usage: bindcraft2 design campaign.json"
}

_write_bindcraft2_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BindCraft 2 shortcut — runs 'bindcraft ...' from its own venv."
        echo "# With no args: opens an interactive shell with the venv active."
        echo ""
        echo "BINDCRAFT2_DIR=\"${BINDCRAFT2_DIR}\""
        echo "BINDCRAFT2_AF2_PARAMS=\"$(_bindcraft2_af2_params || true)\""
    } > "${SHORTCUTS_DIR}/bindcraft2"
    cat >> "${SHORTCUTS_DIR}/bindcraft2" << 'EOF'

# Point BindCraft 2 at the parameters we already have, so it neither downloads
# 5.3 GB nor refuses to start. An EMPTY value would count as a value and fail,
# so the variable is exported only when it resolved to something.
if [[ -n "${BINDCRAFT2_AF2_PARAMS}" ]]; then
    export BINDCRAFT_AF2_PARAMS="${BINDCRAFT2_AF2_PARAMS}"
fi

# JAX_COMPILATION_CACHE_DIR is deliberately NOT set: BindCraft 2 keys its own
# cache per GPU model under ~/.cache/bindcraft/compile_cache/<card>, and setting
# this variable overrides that keying wholesale. An executable is not portable
# across cards, so the per-card layout is the one that works.

if [[ $# -eq 0 ]]; then
    echo "BindCraft 2 (${BINDCRAFT2_DIR})"
    echo "Examples:"
    echo "  bindcraft2 design campaign.json"
    echo "  bindcraft2 design --list-modalities"
    exec "${BINDCRAFT2_DIR}/.venv/bin/python" -c 'import subprocess,sys,os; os.execvp("bash",["bash"])'
fi

exec "${BINDCRAFT2_DIR}/.venv/bin/bindcraft" "$@"
EOF
    chmod +x "${SHORTCUTS_DIR}/bindcraft2"
}

install_rfd3() {
    print_step "Installing RFD3 (foundry)"

    # Conda env: Py 3.12 + PyTorch 2.2+ (CUDA 12.x)
    if env_exists binderscout_rfd3; then
        print_warn "Conda environment 'binderscout_rfd3' already exists — skipping creation."
    else
        run_logged "Creating binderscout_rfd3 env" \
            "${CONDA_CMD}" create -n binderscout_rfd3 -y python=3.12 pip \
            -c conda-forge \
            || { print_fail "Failed to create binderscout_rfd3 env"; return 1; }
    fi

    # PyTorch (CUDA 12.1 wheels — works for 12.1–12.8 host drivers)
    run_logged "Installing PyTorch (CUDA 12.1)" \
        "${CONDA_CMD}" run -n binderscout_rfd3 \
        pip install -q "torch>=2.2" "torchvision" "torchaudio" --index-url https://download.pytorch.org/whl/cu121 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # foundry + rfd3 extra (PyPI package name is `rc-foundry`)
    run_logged "Installing rc-foundry[rfd3] ${FOUNDRY_COMMIT}" \
        "${CONDA_CMD}" run -n binderscout_rfd3 \
        pip install -q "rc-foundry[rfd3]==0.1.9" \
        || { print_fail "Failed to install rc-foundry"; return 1; }

    # Also install MPNN extra for post-diffusion sequence design (ProteinMPNN + LigandMPNN)
    run_logged "Installing rc-foundry[mpnn]" \
        "${CONDA_CMD}" run -n binderscout_rfd3 \
        pip install -q "rc-foundry[mpnn]==0.1.9" \
        || print_warn "rc-foundry[mpnn] install failed — MPNN redesign step may not work"

    # Download RFD3 weights to a shared location inside BinderScout
    mkdir -p "${FOUNDRY_WEIGHTS_DIR}"
    if [[ -n "$(ls -A "${FOUNDRY_WEIGHTS_DIR}" 2>/dev/null)" ]]; then
        print_ok "Foundry weights dir already populated at ${FOUNDRY_WEIGHTS_DIR}"
    else
        run_logged --retries 3 "Downloading RFD3 weights (~few GB)" \
            "${CONDA_CMD}" run -n binderscout_rfd3 \
            foundry install rfd3 --checkpoint-dir "${FOUNDRY_WEIGHTS_DIR}" \
            || print_warn "RFD3 weight download failed — retry: conda run -n binderscout_rfd3 foundry install rfd3 --checkpoint-dir ${FOUNDRY_WEIGHTS_DIR}"
    fi

    # Smoke test: rfd3 CLI help
    smoke_test "RFD3 CLI check" \
        "${CONDA_CMD}" run -n binderscout_rfd3 rfd3 --help \
        || print_warn "rfd3 CLI smoke test failed — env may need foundry weights first"

    # Shortcut
    _write_rfd3_shortcut

    print_ok "RFD3 installation complete"
    print_ok "  Usage: rfd3 design out_dir=./run inputs=config.yaml"
}

_write_rfd3_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# RFD3 shortcut — runs 'rfd3 design ...' in the binderscout_rfd3 env."
        echo "# With no args: opens an interactive env shell."
        echo ""
        echo "CONDA_CMD=\"$(shortcut_conda)\""
        echo "FOUNDRY_WEIGHTS_DIR=\"${FOUNDRY_WEIGHTS_DIR}\""
    } > "${SHORTCUTS_DIR}/rfd3"
    cat >> "${SHORTCUTS_DIR}/rfd3" << 'EOF'

# Surface the weights dir for the foundry checkpoint registry.
# (The registry reads FOUNDRY_CHECKPOINT_DIRS / FOUNDRY_CHECKPOINTS_DIR; the
# singular form FOUNDRY_CHECKPOINT_DIR is silently ignored.)
export FOUNDRY_CHECKPOINT_DIRS="${FOUNDRY_WEIGHTS_DIR}"

if [[ $# -eq 0 ]]; then
    echo "RFD3 environment (binderscout_rfd3). Weights: ${FOUNDRY_WEIGHTS_DIR}"
    echo "Examples:"
    echo "  rfd3 design out_dir=./run inputs=examples/ppi.yaml"
    echo "  foundry list-installed"
    exec "${CONDA_CMD}" run --live-stream -n binderscout_rfd3 bash
fi

exec "${CONDA_CMD}" run --live-stream -n binderscout_rfd3 rfd3 "$@"
EOF
    chmod +x "${SHORTCUTS_DIR}/rfd3"
}

# ─── Protein-Hunter ──────────────────────────────────────────────────────────
# Cho et al. (2025) bioRxiv 10.1101/2025.10.10.681530 — Boltz-2/Chai-1 structure
# hallucination for protein / cyclic-peptide / small-molecule / DNA / RNA binders.
# Upstream: github.com/yehlincho/Protein-Hunter

install_protein_hunter() {
    print_step "Installing Protein-Hunter"

    # Clone at pinned commit
    if [[ -d "${PROTEIN_HUNTER_DIR}" ]]; then
        print_ok "Protein-Hunter already cloned at ${PROTEIN_HUNTER_DIR}"
    else
        run_logged "Cloning Protein-Hunter" \
            git clone --depth 50 "${PROTEIN_HUNTER_REPO}" "${PROTEIN_HUNTER_DIR}" \
            || { print_fail "Failed to clone Protein-Hunter"; return 1; }
        git -C "${PROTEIN_HUNTER_DIR}" checkout "${PROTEIN_HUNTER_COMMIT}" --quiet \
            || print_warn "Could not pin Protein-Hunter to ${PROTEIN_HUNTER_COMMIT} — using latest"
    fi

    # Conda env (Python 3.10 — matches upstream setup.sh)
    if env_exists binderscout_protein_hunter; then
        print_warn "Conda environment 'binderscout_protein_hunter' already exists — skipping creation."
    else
        print_step "Creating binderscout_protein_hunter conda environment (Python 3.10)"
        run_logged "Creating binderscout_protein_hunter env" \
            "${CONDA_CMD}" create -n binderscout_protein_hunter -y python=3.10 pip \
            -c conda-forge \
            || { print_fail "Failed to create binderscout_protein_hunter env"; return 1; }
    fi

    # Install PyTorch (matches upstream setup.sh expectations: torch>=2.2 with CUDA)
    run_logged "Installing PyTorch (CUDA 12.1)" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter \
        pip install -q "torch>=2.2" "torchvision" "torchaudio" --index-url https://download.pytorch.org/whl/cu121 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # Install vendored Boltz_PH + upstream deps
    run_logged "Installing Protein-Hunter Python deps" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter bash -c \
        "cd '${PROTEIN_HUNTER_DIR}' && pip install -q -e './boltz_ph' && pip install -q matplotlib seaborn prody py3Dmol pyyaml ml_collections biopython modelcif jaxtyping pandera logmd==0.1.45 pyrosetta-installer" \
        || print_warn "Some Protein-Hunter deps failed — may need manual follow-up"

    # PyRosetta (required by boltz_ph.design at import time)
    # pyrosetta_installer >=0.1.2 renamed download_pyrosetta -> install_pyrosetta.
    run_logged "Installing PyRosetta" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter python -c \
        "from pyrosetta_installer import install_pyrosetta; install_pyrosetta(serialization=True, skip_if_installed=True)" \
        || print_warn "PyRosetta install failed — Protein-Hunter design will not work until this is fixed"

    # Install chai-lab (from sokrypton fork pinned by Protein-Hunter upstream)
    run_logged "Installing Chai-1 (sokrypton fork)" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter \
        pip install -q "git+https://github.com/sokrypton/chai-lab.git" \
        || print_warn "chai-lab install failed — only the Boltz-2 edition of Protein-Hunter will work"

    # Protein-Hunter vendors LigandMPNN source in-repo and downloads weights into model_params/.
    local ph_mpnn_dir="${PROTEIN_HUNTER_DIR}/LigandMPNN/model_params"
    if [[ ! -d "${ph_mpnn_dir}" ]] && [[ -f "${PROTEIN_HUNTER_DIR}/LigandMPNN/get_model_params.sh" ]]; then
        run_logged --retries 3 "Downloading LigandMPNN weights (Protein-Hunter)" \
            bash -c "cd '${PROTEIN_HUNTER_DIR}/LigandMPNN' && bash get_model_params.sh ./model_params" \
            || print_warn "LigandMPNN weights download failed — download manually"
    fi

    # Boltz-2 weight cache (~/.boltz) — shared with Mosaic if Mosaic populates it first.
    # Protein-Hunter pulls Boltz-2 weights on first run; we don't pre-download here.

    # Smoke test: import boltz_ph package
    smoke_test "Protein-Hunter import check" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter bash -c \
        "cd '${PROTEIN_HUNTER_DIR}' && python -c 'import boltz; print(\"boltz_ph import OK\")'" \
        || print_warn "Protein-Hunter import failed — env may still work after first-use weight download"

    # Shortcut
    _write_protein_hunter_shortcut

    print_ok "Protein-Hunter installation complete"
    print_ok "  Usage: protein-hunter  (opens env shell)"
    print_ok "         python boltz_ph/design.py --protein_seqs TARGET --num_designs N --name JOBNAME  (direct)"
}

_write_protein_hunter_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# Protein-Hunter shortcut — activates binderscout_protein_hunter conda env"
        echo "# and opens an interactive shell in the Protein-Hunter directory."
        echo ""
        echo "PROTEIN_HUNTER_DIR=\"${PROTEIN_HUNTER_DIR}\""
        echo "CONDA_CMD=\"$(shortcut_conda)\""
    } > "${SHORTCUTS_DIR}/protein-hunter"
    cat >> "${SHORTCUTS_DIR}/protein-hunter" << 'EOF'

cd "${PROTEIN_HUNTER_DIR}"

echo "Protein-Hunter environment (binderscout_protein_hunter) activated."
echo "Working directory: ${PROTEIN_HUNTER_DIR}"
echo "Minimal protein binder run:"
echo "  python boltz_ph/design.py --num_designs 50 --num_cycles 7 \\"
echo "      --protein_seqs <TARGET_AA> --msa_mode mmseqs --gpu_id 0 \\"
echo "      --name JOBNAME --min_protein_length 90 --max_protein_length 150 \\"
echo "      --high_iptm_threshold 0.7 --percent_X 80"
echo ""
echo "Modalities (flags on design.py):"
echo "  --cyclic                  cyclic peptide binder"
echo "  --ligand_ccd CCD          small-molecule binder (CCD code)"
echo "  --ligand_smiles 'SMILES'  small-molecule binder (SMILES)"
echo "  --nucleic_seq SEQ --nucleic_type dna|rna    DNA / RNA binder"
echo ""

exec "${CONDA_CMD}" run --live-stream -n binderscout_protein_hunter bash
EOF
    chmod +x "${SHORTCUTS_DIR}/protein-hunter"
}

# ─── AlphaFold 3 (refolder, opt-in) ─────────────────────────────────────────

install_af3() {
    print_step "Installing AlphaFold 3 v3.0.2 refolder (binder-eval-af3 env)"
    ensure_conda_in_path

    # Soft VRAM check — installer doesn't have to run on the same host the eval will use,
    # so we only warn (a head node may have no GPU at all).
    local gpu_mem_mib=""
    if command -v nvidia-smi >/dev/null 2>&1; then
        gpu_mem_mib="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')"
    fi
    # NOTE: this used to warn below 100 GiB and claim AF3 would OOM on a 24 GB
    # card. That was wrong — measured 2026-08-14 on an RTX 3090, a 258-token
    # binder:target complex peaks at 4,430 MiB (20/20 designs clean). The old
    # ">=100 GB" figure came from reading preallocated pool size as the working
    # set. Warn only where the *working set* is genuinely at risk.
    if [[ -n "${gpu_mem_mib}" && "${gpu_mem_mib}" -lt 8000 ]]; then
        print_warn "Detected GPU has ${gpu_mem_mib} MiB memory (<8 GiB)."
        print_warn "  AF3 needs ~4.4 GB for a ~260-token complex, more for larger ones."
        print_warn "  Install will proceed — lower AF3_XLA_MEM_FRACTION if refold-af3 OOMs."
    fi

    # Evaluator dir must exist (bundled in monorepo)
    if [[ ! -d "${EVALUATOR_DIR}" ]]; then
        print_fail "Evaluator directory not found at ${EVALUATOR_DIR}"
        print_warn "It should be bundled in the repository. Try re-cloning BinderScout."
        return 1
    fi
    if [[ ! -f "${EVALUATOR_DIR}/envs/binder-eval-af3.yml" ]]; then
        print_fail "Env spec not found at ${EVALUATOR_DIR}/envs/binder-eval-af3.yml"
        return 1
    fi

    # Create binder-eval-af3 conda env (Python 3.12, see env yml)
    print_step "Creating binder-eval-af3 conda environment (Python 3.12)"
    if env_exists binder-eval-af3; then
        print_warn "Conda environment 'binder-eval-af3' already exists — skipping creation."
    else
        run_logged "Creating binder-eval-af3 conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval-af3.yml" -y \
            || { print_fail "Failed to create binder-eval-af3 conda env"; return 1; }
    fi

    # Install AlphaFold 3 from source. The "alphafold3" PyPI package is an unrelated
    # stub (v0.0.x) — the genuine DeepMind AF3 ships only via its repo (source build)
    # or Docker. Recipe (verified on Clara H200, 2026-07-15):
    #   clone (pinned) -> pip install (pulls jax==0.9.1 + gemmi + deps, builds C++)
    #   -> build_data (generates the CCD chemical_component_sets.pickle AF3 needs).
    if [[ -d "${AF3_DIR}/.git" ]]; then
        print_warn "alphafold3 repo already present at ${AF3_DIR} — fetching + re-pinning to ${AF3_COMMIT}."
        run_logged "Re-pinning alphafold3 to ${AF3_COMMIT}" \
            bash -c "cd '${AF3_DIR}' && git fetch --quiet origin && git checkout '${AF3_COMMIT}'" \
            || { print_fail "Failed to checkout alphafold3 ${AF3_COMMIT}"; return 1; }
    elif [[ -e "${AF3_DIR}" ]]; then
        print_fail "${AF3_DIR} exists but is not a git repo — remove it and retry."; return 1
    else
        run_logged "Cloning alphafold3" \
            git clone "${AF3_REPO}" "${AF3_DIR}" \
            || { print_fail "Failed to clone alphafold3 (network / GitHub access?)"; return 1; }
        run_logged "Pinning alphafold3 to ${AF3_COMMIT}" \
            bash -c "cd '${AF3_DIR}' && git checkout '${AF3_COMMIT}'" \
            || { print_fail "Failed to checkout alphafold3 ${AF3_COMMIT}"; return 1; }
    fi

    run_logged "Building + installing AlphaFold 3 from source (jax 0.9.1 + gemmi)" \
        "${CONDA_CMD}" run -n binder-eval-af3 pip install -q "${AF3_DIR}" gemmi \
        || { print_fail "Failed to build/install AlphaFold 3 (jax 0.9.1 + C++ build)"; return 1; }

    run_logged "Building AF3 chemical-component data (build_data)" \
        "${CONDA_CMD}" run -n binder-eval-af3 build_data \
        || { print_fail "Failed to run AF3 build_data (CCD pickle)"; return 1; }

    # Install binder-compare into the env so 'binder-compare refold-af3' works
    run_logged "Installing binder-compare into binder-eval-af3" \
        "${CONDA_CMD}" run -n binder-eval-af3 pip install -q -e "${EVALUATOR_DIR}[report]" \
        || { print_fail "Failed to install binder-compare into binder-eval-af3"; return 1; }

    # Smoke test — verify the REAL AF3 actually imports (the old --help-only test
    # passed even against the broken PyPI stub, which imports nothing) and that
    # run_alphafold.py is present.
    smoke_test "AF3 producer imports (alphafold3 + jax)" \
        "${CONDA_CMD}" run -n binder-eval-af3 python -c "import alphafold3, jax" \
        || { print_fail "AF3 producer import failed — install did not build the real AF3"; return 1; }
    [[ -f "${AF3_DIR}/run_alphafold.py" ]] \
        || { print_fail "AF3 install incomplete: ${AF3_DIR}/run_alphafold.py missing"; return 1; }
    smoke_test "binder-compare refold-af3 --help" \
        "${CONDA_CMD}" run -n binder-eval-af3 binder-compare refold-af3 --help \
        || return 1

    # Shortcut
    print_step "Installing af3 shortcut"
    _write_af3_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/af3"

    # Weights — NOT bundled; user obtains from Google DeepMind themselves.
    echo ""
    print_warn "AF3 model weights are NOT bundled with this installer."
    print_warn "  Request access:  https://github.com/google-deepmind/alphafold3"
    print_warn "  Place at:        ~/.alphafold3/models/"
    print_warn "  Or set:          export AF3_MODEL_DIR=/your/path/to/models"
    echo ""

    print_ok "AF3 refolder installation complete"
}

_write_af3_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BinderScout AF3 shortcut — runs 'binder-compare refold-af3 ...' in the"
        echo "# binder-eval-af3 env. With no args: opens an interactive env shell."
        echo ""
        echo "CONDA_CMD=\"$(shortcut_conda)\""
    } > "${SHORTCUTS_DIR}/af3"
    cat >> "${SHORTCUTS_DIR}/af3" << 'AF3EOF'

if [ "$#" -eq 0 ]; then
    echo "AF3 env (binder-eval-af3) activated."
    echo "Usage:"
    echo "  binder-compare refold-af3 --sequences seqs.fasta --target-seq SEQ -o af3.csv"
    echo "  (AF3 weights expected at ~/.alphafold3/models/ or \$AF3_MODEL_DIR)"
    echo ""
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-af3 bash
else
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-af3 binder-compare refold-af3 "$@"
fi
AF3EOF
    chmod +x "${SHORTCUTS_DIR}/af3"
}

# ─── ESMFold2 (refolder, opt-in) ────────────────────────────────────────────

install_esmfold2() {
    print_step "Installing ESMFold2 refolder (binder-eval-esmfold2 env)"
    ensure_conda_in_path

    # Evaluator dir must exist (bundled in monorepo)
    if [[ ! -d "${EVALUATOR_DIR}" ]]; then
        print_fail "Evaluator directory not found at ${EVALUATOR_DIR}"
        print_warn "It should be bundled in the repository. Try re-cloning BinderScout."
        return 1
    fi
    if [[ ! -f "${EVALUATOR_DIR}/envs/binder-eval-esmfold2.yml" ]]; then
        print_fail "Env spec not found at ${EVALUATOR_DIR}/envs/binder-eval-esmfold2.yml"
        return 1
    fi

    # Create binder-eval-esmfold2 conda env
    print_step "Creating binder-eval-esmfold2 conda environment"
    if env_exists binder-eval-esmfold2; then
        print_warn "Conda environment 'binder-eval-esmfold2' already exists — skipping creation."
    else
        run_logged "Creating binder-eval-esmfold2 conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval-esmfold2.yml" -y \
            || { print_fail "Failed to create binder-eval-esmfold2 conda env"; return 1; }
    fi

    # Install the ESMFold2 runtime deps (canonical list lives in the env yml header).
    # NOTE: there is NO `esmfold` PyPI package. The runtime is transformers' ESMFold2Model
    # + biohub's `esm` SDK (ESMFold2InputBuilder + the ProteinInput/StructurePredictionInput
    # dataclasses) + gemmi for CIF→PDB. refold_esmfold2.py imports exactly these.
    local _torch_index="https://download.pytorch.org/whl/cu124"
    [[ "$(uname -m)" == "aarch64" ]] && _torch_index="https://download.pytorch.org/whl/cu130"
    run_logged "Installing torch (${_torch_index##*/}) into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 pip install -q --index-url "$_torch_index" torch \
        || { print_fail "Failed to install torch into binder-eval-esmfold2"; return 1; }
    run_logged "Installing transformers + gemmi + safetensors into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 pip install -q 'transformers>=4.50' gemmi safetensors \
        || { print_fail "Failed to install transformers/gemmi/safetensors into binder-eval-esmfold2"; return 1; }
    # biohub/esm: ESMFold2InputBuilder + chain dataclasses. Pinned commit per the HF model
    # card (no PyPI release yet). If this 404s/changes upstream, update the ref in the yml header too.
    #
    # --no-deps is load-bearing, not an optimisation. Biohub/esm itself resolves
    # fine, but its pyproject depends on git+https://github.com/biohub/transformers,
    # which now returns 404 -- so pip hands the clone to git, git prompts for a
    # username, finds no TTY, and the whole install dies with
    # "could not read Username for 'https://github.com'". That took out the
    # DEFAULT refold engine on 2026-09-23. The step immediately above already
    # installs transformers, gemmi and safetensors from PyPI, so nothing is lost
    # by declining to resolve that dependency tree; verify_tool() checks that
    # `import esm` works afterwards.
    run_logged --retries 3 "Installing biohub esm SDK into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 pip install -q --no-deps 'esm @ git+https://github.com/Biohub/esm.git@c94ed8d' \
        || { print_fail "Failed to install biohub esm SDK (check network / git access)"; return 1; }

    # Install binder-compare into the env so 'binder-compare refold-esmfold2' works
    run_logged "Installing binder-compare into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 pip install -q -e "${EVALUATOR_DIR}[report]" \
        || { print_fail "Failed to install binder-compare into binder-eval-esmfold2"; return 1; }

    # Smoke test — just the CLI parses (no weights needed for --help)
    smoke_test "binder-compare refold-esmfold2 --help" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 binder-compare refold-esmfold2 --help \
        || return 1

    # Shortcut
    print_step "Installing esmfold2 shortcut"
    _write_esmfold2_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/esmfold2"

    echo ""
    print_ok "ESMFold2 weights are open-source and download on first use via the HuggingFace cache."
    print_ok "  Default model: ${BOLD}full${RESET} (biohub/ESMFold2, MSA-capable, more accurate; ~3-5 GB)"
    print_ok "  Switch via:    --esmfold2-model fast  (single-sequence, speed-optimized; ~1 GB)"
    echo ""

    print_ok "ESMFold2 refolder installation complete"
}

_write_esmfold2_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BinderScout ESMFold2 shortcut — runs 'binder-compare refold-esmfold2 ...' in the"
        echo "# binder-eval-esmfold2 env. With no args: opens an interactive env shell."
        echo ""
        echo "CONDA_CMD=\"$(shortcut_conda)\""
    } > "${SHORTCUTS_DIR}/esmfold2"
    cat >> "${SHORTCUTS_DIR}/esmfold2" << 'ESMFOLD2EOF'

if [ "$#" -eq 0 ]; then
    echo "ESMFold2 env (binder-eval-esmfold2) activated."
    echo "Usage:"
    echo "  binder-compare refold-esmfold2 --sequences seqs.fasta --target-seq SEQ -o esmfold2.csv"
    echo "  (Default model: fast; switch via --esmfold2-model full)"
    echo ""
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-esmfold2 bash
else
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-esmfold2 binder-compare refold-esmfold2 "$@"
fi
ESMFOLD2EOF
    chmod +x "${SHORTCUTS_DIR}/esmfold2"
}

# ─── SoluProt (sequence-only solubility screen, opt-in) ───────────────────────

# Where SoluProt's distribution lands. Kept inside Evaluator/tools/ so the
# Python runner's default _resolve_scripts_path() finds it without env vars.
SOLUPROT_DIR="${EVALUATOR_DIR}/tools/soluprot"
SOLUPROT_ZIP_URL="https://loschmidt.chemi.muni.cz/soluprot/?page=download&f=soluprot.zip"
USEARCH12_REPO="https://github.com/rcedgar/usearch12"

# Resolve the USEARCH binary the same way soluprot_runner._resolve_usearch does
# ($SOLUPROT_USEARCH, then <dir>/usearch.<arch>, then <dir>/usearch, then PATH),
# so what the installer validates is what the runner will actually execute.
# Echoes the path and returns 0, or returns 1 if none is usable.
_resolve_usearch() {
    local cand
    for cand in "${SOLUPROT_USEARCH:-}" \
                "${SOLUPROT_DIR}/usearch.$(uname -m)" \
                "${SOLUPROT_DIR}/usearch"; do
        if [[ -n "${cand}" && -x "${cand}" ]]; then
            echo "${cand}"
            return 0
        fi
    done
    if command -v usearch >/dev/null 2>&1; then
        command -v usearch
        return 0
    fi
    return 1
}

# Verify the resolved binary can actually START. `-x` only checks the mode bit,
# which passes for a wrong-architecture or missing-libstdc++ binary -- and the
# bioconda usearch 12.0_beta build is known to crash at startup on aarch64. We
# do not assume any particular CLI, so ANY ordinary exit status counts as
# success; only a failure to exec (126/127) or a fatal signal (>=128) fails.
_check_usearch_runs() {
    local bin="$1" rc=0
    print_step "Checking USEARCH runs: ${bin}"
    "${bin}" --version >/dev/null 2>&1 || rc=$?
    if (( rc == 126 || rc == 127 || rc >= 128 )); then
        print_fail "USEARCH at ${bin} could not be executed (exit ${rc})."
        print_warn "  Usually a wrong-architecture binary or a missing shared library."
        print_warn "  Check with: file '${bin}' && ldd '${bin}'"
        print_warn "  Then delete it and re-run --tool soluprot to rebuild from source."
        return 1
    fi
    print_ok "USEARCH executes"
    return 0
}

# Compile open-source USEARCH v12 for SoluProt's E. coli identity feature.
# Built here rather than committed: USEARCH v12 is GPLv3, and shipping the
# binary in this MIT-licensed repository put a copyleft redistribution
# obligation on every clone. x86_64 is usearch12's native platform, so this is
# the same source build install_aarch.sh has always used, minus the aarch64
# workarounds. The old proprietary drive5 32-bit build is NOT a substitute --
# it is academic-use-only, which is stricter than what it would replace.
_build_usearch_v12() {
    print_step "Building open-source USEARCH v12 for the identity feature"
    local t
    for t in git make g++ gcc; do
        if ! command -v "${t}" >/dev/null 2>&1; then
            print_warn "USEARCH build needs git + make + gcc/g++ (missing: ${t})."
            print_warn "  Install a toolchain and re-run, or place a 'usearch.x86_64' binary at"
            print_warn "  ${SOLUPROT_DIR}/usearch.x86_64 (or 'usearch' on PATH)."
            return 1
        fi
    done
    local src_dir="${SOLUPROT_DIR}/usearch12-src"
    rm -rf "${src_dir}"
    run_logged "Cloning ${USEARCH12_REPO}" \
        git clone --depth 1 "${USEARCH12_REPO}" "${src_dir}" \
        || { print_warn "git clone of ${USEARCH12_REPO} failed"; return 1; }
    # The generated Makefile hardcodes 'ccache g++'; override CC/CXX. Static
    # link is preferred so the binary does not depend on this host's libstdc++;
    # fall back to dynamic where static libs are unavailable.
    if ! run_logged "Compiling usearch12 (static)" \
        make -C "${src_dir}/src" -j"$(nproc)" CC=gcc CXX=g++; then
        print_warn "Static build failed; retrying without -static"
        # NB: the Makefile appends '-static' to LDFLAGS, and a command-line
        # LDFLAGS= override does NOT win against that '+=' -- so strip it from
        # the Makefile directly, then re-link (objects are already built).
        sed -i 's/[[:space:]]*-static//g' "${src_dir}/src/Makefile"
        run_logged "Compiling usearch12 (dynamic)" \
            make -C "${src_dir}/src" -j"$(nproc)" CC=gcc CXX=g++ \
            || { print_warn "USEARCH v12 build failed"; return 1; }
    fi
    if [[ -x "${src_dir}/bin/usearch12" ]]; then
        cp "${src_dir}/bin/usearch12" "${SOLUPROT_DIR}/usearch.x86_64"
        chmod +x "${SOLUPROT_DIR}/usearch.x86_64"
        rm -rf "${src_dir}"
        print_ok "USEARCH v12 built -> ${SOLUPROT_DIR}/usearch.x86_64"
        return 0
    fi
    print_warn "USEARCH v12 binary not found after build (${src_dir}/bin/usearch12)"
    return 1
}


install_tmprot() {
    print_step "Installing TmProt 1.0 melting-temperature screen (binder-eval-tmprot env)"

    # TmProt is GPL-3.0 and this repository is MIT, so it is cloned and installed
    # editable rather than vendored -- the same posture the GPLv3 USEARCH
    # binaries were moved to. The ESM2-LoRA production weights ship inside the
    # tmprot-1.0 package, so there is no gated download and no weights step.
    if [[ ! -f "${EVALUATOR_DIR}/envs/binder-eval-tmprot.yml" ]]; then
        print_fail "Env spec not found at ${EVALUATOR_DIR}/envs/binder-eval-tmprot.yml"
        return 1
    fi

    if env_exists binder-eval-tmprot; then
        print_warn "Conda environment 'binder-eval-tmprot' already exists -- reusing it."
    else
        run_logged --retries 3 "Creating binder-eval-tmprot conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval-tmprot.yml" -y \
            || { print_fail "Failed to create binder-eval-tmprot env"; return 1; }
    fi

    if [[ -d "${TMPROT_DIR}/.git" ]]; then
        print_warn "TmProt repo already present at ${TMPROT_DIR} -- fetching + re-pinning to ${TMPROT_COMMIT}."
        run_logged --retries 3 "Re-pinning TmProt to ${TMPROT_COMMIT}" \
            bash -c "cd '${TMPROT_DIR}' && git fetch --quiet origin && git checkout --quiet '${TMPROT_COMMIT}'" \
            || { print_fail "Failed to check out TmProt ${TMPROT_COMMIT}"; return 1; }
    elif [[ -e "${TMPROT_DIR}" ]]; then
        print_fail "${TMPROT_DIR} exists but is not a git repo -- remove it and retry."; return 1
    else
        # Upstream has no main/master branch, so the branch must be named.
        run_logged --retries 3 "Cloning TmProt (${TMPROT_BRANCH})" \
            git clone --quiet --branch "${TMPROT_BRANCH}" "${TMPROT_REPO}" "${TMPROT_DIR}" \
            || { print_fail "Failed to clone ${TMPROT_REPO}"; return 1; }
        run_logged "Pinning TmProt to ${TMPROT_COMMIT}" \
            bash -c "cd '${TMPROT_DIR}' && git checkout --quiet '${TMPROT_COMMIT}'" \
            || { print_fail "Failed to check out TmProt ${TMPROT_COMMIT}"; return 1; }
    fi

    # The standalone CLI package, which is what carries the bundled model.
    local _pkg="${TMPROT_DIR}/tmprot-1.0"
    [[ -d "${_pkg}" ]] || _pkg="${TMPROT_DIR}"
    run_logged --retries 2 "Installing TmProt (editable) into binder-eval-tmprot" \
        "${CONDA_CMD}" run -n binder-eval-tmprot pip install -q -e "${_pkg}" \
        || { print_fail "Failed to install TmProt from ${_pkg}"; return 1; }

    # binder-compare inside the env so `screen-tmprot` runs there directly.
    run_logged --retries 2 "Installing binder-compare into binder-eval-tmprot" \
        "${CONDA_CMD}" run -n binder-eval-tmprot pip install -q -e "${EVALUATOR_DIR}" \
        || { print_fail "Failed to install binder-compare into binder-eval-tmprot"; return 1; }

    # Verify the thing the screen actually needs: that tmprot imports and its
    # console script exists. An entry point that merely answers --help is not
    # evidence of an install -- see verify_tool().
    smoke_test "TmProt import check" \
        "${CONDA_CMD}" run -n binder-eval-tmprot python -c "import tmprot" \
        || return 1

    cat > "${SHORTCUTS_DIR}/tmprot" <<TMPROTEOF
#!/usr/bin/env bash
# BinderScout shortcut: TmProt melting-temperature screen.
# With args -> binder-compare screen-tmprot; without -> a shell in the env.
set -euo pipefail
if [[ \$# -eq 0 ]]; then
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-tmprot bash
else
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-tmprot binder-compare screen-tmprot "\$@"
fi
TMPROTEOF
    chmod +x "${SHORTCUTS_DIR}/tmprot"
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/tmprot"

    print_ok "TmProt installation complete"
    print_warn "TmProt is a SCREEN, not a ranking term: native_tmprot_tm is advisory."
    print_warn "  Tm predictors are trained on natural proteins and are out of domain on"
    print_warn "  hyperstable de novo miniproteins. Use it to flag, never to rank or drop."
    return 0
}

install_soluprot() {
    print_step "Installing SoluProt 1.0 solubility screen (binder-eval-soluprot env)"
    ensure_conda_in_path

    # This is the x86_64 installer. SoluProt IS supported on aarch64, but via the
    # aarch64 installer (it builds scikit-learn 0.20.4 + USEARCH v12 from source
    # and patches biopython — the pinned x86 env below has no aarch64 conda
    # builds). Redirect rather than attempting a doomed conda solve here.
    if [[ "${ARCH}" == "aarch64" ]]; then
        print_fail "This is the x86_64 installer. On aarch64, install SoluProt with:"
        print_warn "    bash install/install_aarch.sh --tool soluprot"
        print_warn "  (It source-builds scikit-learn 0.20.4 + USEARCH v12 and uses the --no_tmhmm model.)"
        return 1
    fi

    if [[ ! -d "${EVALUATOR_DIR}" ]]; then
        print_fail "Evaluator directory not found at ${EVALUATOR_DIR}"
        return 1
    fi
    if [[ ! -f "${EVALUATOR_DIR}/envs/binder-eval-soluprot.yml" ]]; then
        print_fail "Env spec not found at ${EVALUATOR_DIR}/envs/binder-eval-soluprot.yml"
        return 1
    fi

    # 1. Create the conda env (Python 3.7 + pinned old sklearn — slow first time).
    print_step "Creating binder-eval-soluprot conda environment (Python 3.7)"
    if env_exists binder-eval-soluprot; then
        print_warn "Conda environment 'binder-eval-soluprot' already exists — skipping creation."
    else
        run_logged "Creating binder-eval-soluprot conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval-soluprot.yml" -y \
            || { print_fail "Failed to create binder-eval-soluprot conda env"; return 1; }
    fi

    # 2. Fetch and unpack SoluProt's distribution.
    mkdir -p "${SOLUPROT_DIR}"
    local zip_path="${SOLUPROT_DIR}/soluprot.zip"
    if [[ -f "${SOLUPROT_DIR}/soluprot.py" ]] \
        || [[ -f "${SOLUPROT_DIR}/predict_solubility.py" ]] \
        || [[ -f "${SOLUPROT_DIR}/predict.py" ]]; then
        print_ok "SoluProt distribution already present at ${SOLUPROT_DIR}"
    else
        print_step "Downloading SoluProt 1.0 from ${SOLUPROT_ZIP_URL}"
        if ! run_logged --retries 3 "Downloading soluprot.zip" \
            curl -fsSL -o "${zip_path}" "${SOLUPROT_ZIP_URL}"; then
            print_fail "Failed to download SoluProt from Loschmidt Lab."
            print_warn "  Manual download:  https://loschmidt.chemi.muni.cz/soluprot/?page=download"
            print_warn "  Unpack into:      ${SOLUPROT_DIR}"
            return 1
        fi
        if ! run_logged "Unpacking soluprot.zip" \
            unzip -q -o "${zip_path}" -d "${SOLUPROT_DIR}"; then
            print_fail "Failed to unpack soluprot.zip — is 'unzip' installed?"
            return 1
        fi
        # Move any single nested directory up so soluprot.py is at the top.
        local nested
        nested="$(find "${SOLUPROT_DIR}" -mindepth 1 -maxdepth 1 -type d | head -1)"
        if [[ -n "${nested}" ]] && [[ -f "${nested}/soluprot.py" || -f "${nested}/predict_solubility.py" ]]; then
            mv "${nested}"/* "${SOLUPROT_DIR}/"
            rmdir "${nested}" 2>/dev/null || true
        fi
        rm -f "${zip_path}"
    fi

    # 2b. Patch SoluProt's USEARCH command. The shipped soluprot.py calls
    # `usearch -search_global ...`, but the canonical (and only documented)
    # USEARCH command is `usearch_global`; the `-search_global` spelling is
    # rejected by open-source USEARCH v12 and is not a documented option in any
    # version. Idempotent — only rewrites if the old spelling is present.
    local _solu_py="${SOLUPROT_DIR}/soluprot.py"
    if [[ -f "${_solu_py}" ]] && grep -q "'-search_global'" "${_solu_py}"; then
        sed -i "s/'-search_global'/'-usearch_global'/g" "${_solu_py}"
        print_ok "Patched soluprot.py: USEARCH command -search_global -> -usearch_global"
    fi

    # 3. Check TMHMM. We cannot redistribute it; the user gets a registration URL.
    if [[ ! -x "${SOLUPROT_DIR}/tmhmm-2.0/bin/tmhmm" ]] \
        && ! command -v tmhmm >/dev/null 2>&1; then
        echo ""
        print_warn "TMHMM 2.0 is not installed. SoluProt needs it for transmembrane features."
        print_warn "  Request access:  https://services.healthtech.dtu.dk/services/TMHMM-2.0/"
        print_warn "  Unpack to:       ${SOLUPROT_DIR}/tmhmm-2.0/"
        print_warn "  Or add to PATH:  the runner finds 'tmhmm' on PATH as a fallback."
        echo ""
    fi

    # 4. Build USEARCH v12 for the identity feature. SoluProt cannot score
    #    without it, and it fails SILENTLY: soluprot.py catches UsearchInvalidPath,
    #    prints to stderr and returns, so the process exits 0 having written no
    #    output CSV. A missing binary is therefore a hard install failure -- the
    #    --help smoke test below would NOT catch it (argparse exits before the
    #    USEARCH path runs).
    if _resolve_usearch >/dev/null; then
        print_ok "USEARCH binary present ($(_resolve_usearch))"
    else
        _build_usearch_v12 || true
        if ! _resolve_usearch >/dev/null; then
            print_fail "USEARCH is required for SoluProt's identity feature and could not be built."
            print_warn "  Install a C/C++ toolchain (git make g++) and re-run, or place a 'usearch.x86_64'"
            print_warn "  binary at ${SOLUPROT_DIR}/usearch.x86_64 (or on PATH), then re-run --tool soluprot."
            print_warn "  Source: ${USEARCH12_REPO} (GPLv3). Do NOT substitute the drive5 32-bit build --"
            print_warn "  it is academic-use-only and is not the version SoluProt is patched for."
            return 1
        fi
    fi
    _check_usearch_runs "$(_resolve_usearch)" || return 1

    # 5. binder-compare runs in the 'binder-eval' env (Python 3.10+), NOT here.
    # binder-comparison is requires-python>=3.10 (numpy>=1.24 / pandas>=2.0), so
    # it cannot be installed into this Python 3.7 SoluProt env; the soluprot
    # runner shells out to this env's interpreter via $SOLUPROT_PYTHON.
    if ! env_exists binder-eval; then
        print_warn "The 'binder-eval' env is not installed — SoluProt scoring runs binder-compare from there."
        print_warn "  Install it with: binderscout install --tool evaluator   (or --tool all)"
    fi

    # 6. Smoke test: SoluProt's own entry script imports cleanly in this env.
    smoke_test "soluprot.py --help" \
        "${CONDA_CMD}" run -n binder-eval-soluprot python "${SOLUPROT_DIR}/soluprot.py" --help \
        || return 1

    # 7. Shortcut
    print_step "Installing soluprot shortcut"
    _write_soluprot_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/soluprot"

    echo ""
    print_ok "SoluProt distribution at ${SOLUPROT_DIR}"
    print_ok "  Citation:    Hon et al. 2021, Bioinformatics 37(1):23-28"
    print_ok "  License:     free for academic; commercial via Enantis (enantis@enantis.com)"
    print_ok "  Threshold:   0.5 (paper default; consider tuning for binder-length sequences)"
    echo ""

    print_ok "SoluProt solubility screen installation complete"
}

_write_soluprot_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BinderScout SoluProt shortcut — runs 'binder-compare filter-soluprot ...' in the"
        echo "# binder-eval env (Python 3.10+), shelling out to the Python 3.7 binder-eval-soluprot"
        echo "# env for SoluProt itself. With no args: opens a shell in the SoluProt env."
        echo ""
        echo "CONDA_CMD=\"$(shortcut_conda)\""
        echo "export SOLUPROT_HOME=\"${SOLUPROT_DIR}\""
    } > "${SHORTCUTS_DIR}/soluprot"
    cat >> "${SHORTCUTS_DIR}/soluprot" << 'SOLUPROTEOF'
SOLUPROT_PYTHON="$("${CONDA_CMD}" run -n binder-eval-soluprot python -c 'import sys; print(sys.executable)' 2>/dev/null)"
export SOLUPROT_PYTHON

if [ "$#" -eq 0 ]; then
    echo "SoluProt: binder-compare runs in 'binder-eval'; soluprot.py runs in 'binder-eval-soluprot'."
    echo "Usage:"
    echo "  soluprot --sequences seqs.fasta -o soluprot.csv [--threshold 0.5]"
    echo "  (Default threshold: 0.5 -- the SoluProt paper value.)"
    echo ""
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-soluprot bash
else
    exec "${CONDA_CMD}" run --live-stream -n binder-eval binder-compare filter-soluprot "$@"
fi
SOLUPROTEOF
    chmod +x "${SHORTCUTS_DIR}/soluprot"
}

# ─── Uninstall ─────────────────────────────────────────────────────────────────

uninstall_tool() {
    local tool="${1,,}"
    case "${tool}" in
        bindcraft)
            print_step "Uninstalling BindCraft"
            env_exists BindCraft && run_logged "Removing BindCraft conda env" \
                "${CONDA_CMD}" env remove -n BindCraft -y
            rm -f "${SHORTCUTS_DIR}/bindcraft"
            # x86_64: cloned dir can be removed (not bundled)
            if [[ -d "${BINDCRAFT_DIR}" ]]; then
                rm -rf "${BINDCRAFT_DIR}"
                print_ok "Removed ${BINDCRAFT_DIR}"
            fi
            print_ok "BindCraft uninstalled"
            ;;
        boltzgen)
            print_step "Uninstalling BoltzGen"
            env_exists BoltzGen && run_logged "Removing BoltzGen conda env" \
                "${CONDA_CMD}" env remove -n BoltzGen -y
            rm -f "${SHORTCUTS_DIR}/boltzgen"
            # x86_64: cloned dir can be removed (not bundled)
            if [[ -d "${BOLTZGEN_DIR}" ]]; then
                rm -rf "${BOLTZGEN_DIR}"
                print_ok "Removed ${BOLTZGEN_DIR}"
            fi
            print_ok "BoltzGen uninstalled"
            ;;
        mosaic)
            print_step "Uninstalling Mosaic"
            if [[ -d "${MOSAIC_DIR}/.venv" ]]; then
                rm -rf "${MOSAIC_DIR}/.venv"
                print_ok "Removed Mosaic .venv"
            fi
            rm -f "${SHORTCUTS_DIR}/mosaic"
            # x86_64: cloned dir can be removed (not bundled)
            if [[ -d "${MOSAIC_DIR}" ]]; then
                rm -rf "${MOSAIC_DIR}"
                print_ok "Removed ${MOSAIC_DIR}"
            fi
            print_ok "Mosaic uninstalled"
            ;;
        evaluator)
            print_step "Uninstalling Evaluator"
            env_exists binder-eval && run_logged "Removing binder-eval conda env" \
                "${CONDA_CMD}" env remove -n binder-eval -y
            # Legacy binder-eval-af2 env (from pre-refactor installs): remove if present
            env_exists binder-eval-af2 && run_logged "Removing legacy binder-eval-af2 conda env" \
                "${CONDA_CMD}" env remove -n binder-eval-af2 -y
            rm -f "${EVALUATOR_DIR}/envs/mosaic_venv_path"
            rm -f "${SHORTCUTS_DIR}/evaluate"
            print_ok "Evaluator uninstalled"
            ;;
        pxdesign)
            print_step "Uninstalling PXDesign"
            env_exists binderscout_pxdesign && run_logged "Removing binderscout_pxdesign conda env" \
                "${CONDA_CMD}" env remove -n binderscout_pxdesign -y
            rm -f "${SHORTCUTS_DIR}/pxdesign"
            [[ -d "${PXDESIGN_DIR}" ]] && { rm -rf "${PXDESIGN_DIR}"; print_ok "Removed ${PXDESIGN_DIR}"; }
            # CUTLASS v3.5.1 headers (~150 MB) cloned by install_pxdesign for the
            # DS4Sci EvoformerAttention JIT — nothing else uses them.
            [[ -d "${HOME}/cutlass" ]] && { rm -rf "${HOME}/cutlass"; print_ok "Removed ${HOME}/cutlass"; }
            print_ok "PXDesign uninstalled"
            ;;
        proteina-complexa|proteina_complexa|complexa)
            print_step "Uninstalling Proteina-Complexa"
            if [[ -d "${PROTEINA_COMPLEXA_DIR}/.venv" ]]; then
                rm -rf "${PROTEINA_COMPLEXA_DIR}/.venv"
                print_ok "Removed Proteina-Complexa .venv"
            fi
            rm -f "${SHORTCUTS_DIR}/complexa"
            [[ -d "${PROTEINA_COMPLEXA_DIR}" ]] && { rm -rf "${PROTEINA_COMPLEXA_DIR}"; print_ok "Removed ${PROTEINA_COMPLEXA_DIR}"; }
            print_ok "Proteina-Complexa uninstalled"
            ;;
        protein-hunter|protein_hunter|phunter)
            print_step "Uninstalling Protein-Hunter"
            env_exists binderscout_protein_hunter && run_logged "Removing binderscout_protein_hunter env" \
                "${CONDA_CMD}" env remove -n binderscout_protein_hunter -y
            rm -f "${SHORTCUTS_DIR}/protein-hunter"
            [[ -d "${PROTEIN_HUNTER_DIR}" ]] && { rm -rf "${PROTEIN_HUNTER_DIR}"; print_ok "Removed ${PROTEIN_HUNTER_DIR}"; }
            print_ok "Protein-Hunter uninstalled"
            ;;
        rfd3|foundry)
            print_step "Uninstalling RFD3"
            env_exists binderscout_rfd3 && run_logged "Removing binderscout_rfd3 env" \
                "${CONDA_CMD}" env remove -n binderscout_rfd3 -y
            rm -f "${SHORTCUTS_DIR}/rfd3"
            [[ -d "${FOUNDRY_WEIGHTS_DIR}" ]] && { rm -rf "${FOUNDRY_WEIGHTS_DIR}"; print_ok "Removed ${FOUNDRY_WEIGHTS_DIR}"; }
            [[ -d "${FOUNDRY_DIR}" ]] && { rm -rf "${FOUNDRY_DIR}"; print_ok "Removed ${FOUNDRY_DIR}"; }
            print_ok "RFD3 uninstalled"
            ;;
        bindcraft2|bc2)
            print_step "Uninstalling BindCraft 2"
            rm -f "${SHORTCUTS_DIR}/bindcraft2"
            # The venv lives inside the checkout (BindCraft 2 installs editable),
            # so removing the directory removes the environment with it.
            if [[ -d "${BINDCRAFT2_DIR}" ]]; then
                rm -rf "${BINDCRAFT2_DIR}"
                print_ok "Removed ${BINDCRAFT2_DIR}"
            fi
            # Left in place deliberately: ~/.cache/bindcraft holds the XLA compile
            # cache and, on a machine that had no AF2 parameters of its own, the
            # 5.3 GB download. Both are expensive to recreate and are shared with
            # any other BindCraft 2 checkout, so they are reported, not deleted.
            if [[ -d "${HOME}/.cache/bindcraft" ]]; then
                print_warn "Left in place: ${HOME}/.cache/bindcraft ($(du -sh "${HOME}/.cache/bindcraft" 2>/dev/null | cut -f1)) — compile cache and any downloaded AF2 parameters"
            fi
            print_ok "BindCraft 2 uninstalled"
            ;;
        af3|alphafold3|alphafold)
            print_step "Uninstalling AlphaFold 3 refolder"
            env_exists binder-eval-af3 && run_logged "Removing binder-eval-af3 conda env" \
                "${CONDA_CMD}" env remove -n binder-eval-af3 -y
            rm -f "${SHORTCUTS_DIR}/af3"
            [[ -d "${AF3_DIR}" ]] && { rm -rf "${AF3_DIR}"; print_ok "Removed ${AF3_DIR}"; }
            print_warn "AF3 model weights (if any) at ~/.alphafold3/models or \$AF3_MODEL_DIR were NOT removed."
            print_ok "AF3 refolder uninstalled"
            ;;
        esmfold2|esm|esmfold)
            print_step "Uninstalling ESMFold2 refolder"
            env_exists binder-eval-esmfold2 && run_logged "Removing binder-eval-esmfold2 conda env" \
                "${CONDA_CMD}" env remove -n binder-eval-esmfold2 -y
            rm -f "${SHORTCUTS_DIR}/esmfold2"
            print_ok "ESMFold2 refolder uninstalled"
            ;;
        soluprot|solu|solubility)
            print_step "Uninstalling SoluProt solubility screen"
            env_exists binder-eval-soluprot && run_logged "Removing binder-eval-soluprot conda env" \
                "${CONDA_CMD}" env remove -n binder-eval-soluprot -y
            rm -f "${SHORTCUTS_DIR}/soluprot"
            local _solu_dir="${EVALUATOR_DIR}/tools/soluprot"
            if [[ -d "${_solu_dir}" ]]; then
                rm -rf "${_solu_dir}"
                print_ok "Removed ${_solu_dir} (script, TMHMM, USEARCH)"
            fi
            print_ok "SoluProt solubility screen uninstalled"
            ;;
        *)
            print_fail "Unknown tool: ${tool}"
            return 1
            ;;
    esac
}

# ─── Main ─────────────────────────────────────────────────────────────────────

# ── Post-install verification ────────────────────────────────────────────────
# A tool counts as installed when the artifact it needs to RUN is on disk — not
# when its entry point exists.
#
# This exists because both halves of that distinction bit us in one run
# (2026-09-23, docs/INVESTIGATION_install_bare_box_2026-09-23.md):
#
#   * RFD3's smoke test ran `rfd3 --help`, which passed while
#     weights/foundry/ was EMPTY — a transient DNS failure had killed
#     `foundry install rfd3` and the campaign would have died at first use.
#   * Proteina-Complexa printed "installation complete" with no Complexa
#     checkpoint at all, because `complexa download --everything` died on a
#     torchaudio ABI mismatch and that step was not fatal.
#
# Both install functions end on print_ok, which returns 0, so neither ever
# reached failed_tools. The exit status was honest about the array; the array
# was wrong.
#
# VERIFY_REASON carries the explanation for the caller to print.
VERIFY_REASON=""

# Run python inside a conda env from a neutral CWD. Running from the repo root
# lets a cloned SOURCE directory shadow the installed package: `import
# alphafold3` succeeded against ./alphafold3/ with __file__ = None while the
# wheel build had in fact failed. A verifier that can be fooled that way is
# worse than none, because it reports green.
_env_python_ok() {
    local env="$1" code="$2"
    env_exists "${env}" || return 1
    ( cd / && "${CONDA_BASE}/envs/${env}/bin/python" -c "${code}" ) >/dev/null 2>&1
}

_count_glob() {
    # shellcheck disable=SC2012  # count only; names are not parsed
    ls "$@" 2>/dev/null | wc -l
}

verify_tool() {
    local tool="$1"
    VERIFY_REASON=""
    case "${tool,,}" in
        bindcraft)
            (( $(_count_glob "${BINDCRAFT_DIR}"/params/*.npz) >= 5 )) \
                || VERIFY_REASON="no AF2 .npz parameters under ${BINDCRAFT_DIR}/params" ;;
        "bindcraft 2"|bindcraft2)
            [[ -x "${BINDCRAFT2_DIR}/.venv/bin/python" ]] \
                || VERIFY_REASON="no venv at ${BINDCRAFT2_DIR}/.venv" ;;
        boltzgen)
            _env_python_ok BoltzGen "import torch" \
                || VERIFY_REASON="torch does not import in the BoltzGen env" ;;
        mosaic)
            [[ -x "${MOSAIC_DIR}/.venv/bin/python" ]] \
                || VERIFY_REASON="no venv at ${MOSAIC_DIR}/.venv" ;;
        evaluator)
            _env_python_ok binder-eval "import binder_comparison" \
                || VERIFY_REASON="binder_comparison does not import in binder-eval" ;;
        rfd3)
            # The check that RFD3's own smoke test was missing.
            (( $(_count_glob "${FOUNDRY_WEIGHTS_DIR}"/*.ckpt) >= 1 )) \
                || VERIFY_REASON="no .ckpt in ${FOUNDRY_WEIGHTS_DIR} — run: foundry install rfd3" ;;
        pxdesign)
            _env_python_ok binderscout_pxdesign "import torch" \
                || VERIFY_REASON="torch does not import in binderscout_pxdesign" ;;
        proteina-complexa)
            if [[ ! -x "${PROTEINA_COMPLEXA_DIR}/.venv/bin/python" ]]; then
                VERIFY_REASON="no venv at ${PROTEINA_COMPLEXA_DIR}/.venv"
            elif (( $(_count_glob "${PROTEINA_COMPLEXA_DIR}"/ckpts/*.ckpt) < 1 )); then
                VERIFY_REASON="no .ckpt in ${PROTEINA_COMPLEXA_DIR}/ckpts — run: complexa download --everything"
            fi ;;
        protein-hunter)
            _env_python_ok binderscout_protein_hunter "import pyrosetta" \
                || VERIFY_REASON="pyrosetta does not import in binderscout_protein_hunter" ;;
        af3)
            # __file__ is None for a namespace-package shadow, so assert it.
            _env_python_ok binder-eval-af3 \
                "import alphafold3, sys; sys.exit(0 if alphafold3.__file__ else 1)" \
                || VERIFY_REASON="alphafold3 not installed in binder-eval-af3 (wheel build failed?)" ;;
        esmfold2)
            _env_python_ok binder-eval-esmfold2 "import esm" \
                || VERIFY_REASON="the esm SDK does not import in binder-eval-esmfold2" ;;
        tmprot)
            _env_python_ok binder-eval-tmprot "import tmprot" \
                || VERIFY_REASON="tmprot does not import in binder-eval-tmprot" ;;
        soluprot)
            if ! env_exists binder-eval-soluprot; then
                VERIFY_REASON="binder-eval-soluprot env missing"
            elif [[ -z "$(_resolve_usearch)" ]]; then
                VERIFY_REASON="no USEARCH binary for the identity feature"
            fi ;;
        *)  VERIFY_REASON="no verifier for '${tool}'"; return 1 ;;
    esac
    [[ -z "${VERIFY_REASON}" ]]
}

# Verify every selected tool. Appends broken ones to the named array.
# Returns 1 if anything is broken, so callers can gate on it.
verify_selected_tools() {
    # The nameref parameter must not share a name with any caller's variable or
    # bash refuses with "circular name reference" and silently leaves the array
    # empty -- which looked exactly like "nothing was broken".
    local -n __vst_out="$1"
    local any=false
    echo ""
    echo -e "${BOLD}=== Verifying installed tools ===${RESET}"
    local spec tool flag fn
    for spec in "${TOOL_REGISTRY[@]}"; do
        IFS='|' read -r flag tool fn _dflt _desc <<< "${spec}"
        [[ "${!flag}" == true ]] || continue
        if verify_tool "${tool}"; then
            printf "  %b  %-20s %s\n" "${GREEN}✓${RESET}" "${tool}" "usable"
        else
            printf "  %b  %-20s %s\n" "${RED}✗${RESET}" "${tool}" "${VERIFY_REASON}"
            __vst_out+=("${tool}")
            any=true
        fi
    done
    [[ "${any}" == false ]]
}

# Re-install only the tools that failed verification, then verify again.
# Far cheaper than --force, which rebuilds everything including ~4 GB of AF2
# weights; the common case is one tool that lost a download to a network blip.
repair_tools() {
    local -n __rt_todo="$1"   # see the nameref note in verify_selected_tools
    local spec tool flag fn repaired=()
    echo ""
    echo -e "${BOLD}=== Repairing ${#__rt_todo[@]} tool(s) ===${RESET}"
    for spec in "${TOOL_REGISTRY[@]}"; do
        IFS='|' read -r flag tool fn _dflt _desc <<< "${spec}"
        local wanted=false t
        for t in "${__rt_todo[@]}"; do [[ "${t}" == "${tool}" ]] && wanted=true; done
        [[ "${wanted}" == true ]] || continue
        echo -e "\n${BOLD}Repairing ${tool}${RESET}"
        if "${fn}"; then repaired+=("${tool}"); else print_warn "${tool}: repair attempt failed"; fi
    done
    (( ${#repaired[@]} )) && print_ok "Re-ran: ${repaired[*]}"
    return 0
}

# preflight
# Cheap sanity checks BEFORE the installer starts downloading tens of GB. Without
# this, a host with too little free space failed an hour in with an opaque tar/pip
# error deep inside install.log, leaving half-built envs behind. Advisory by
# default for GPU/network (an install can legitimately precede the driver, or run
# behind a proxy); only disk space aborts, and --skip-preflight bypasses all of it.
preflight() {
    [[ "${SKIP_PREFLIGHT}" == true ]] && return 0
    print_step "Preflight checks"

    # Rough per-tool download+install footprints, GB. Deliberate over-estimates.
    local need=0
    [[ "${DO_BINDCRAFT}" == true ]]         && need=$(( need + 8 ))   # AF2 params ~4 GB + env
    [[ "${DO_BOLTZGEN}"  == true ]]         && need=$(( need + 10 ))  # Boltz-1 weights ~6 GB + env
    [[ "${DO_MOSAIC}"    == true ]]         && need=$(( need + 8 ))   # JAX/CUDA venv + Boltz-2 cache
    [[ "${DO_EVALUATOR}" == true ]]         && need=$(( need + 2 ))
    [[ "${DO_PXDESIGN}"  == true ]]         && need=$(( need + 12 ))  # torch + CUTLASS + weights
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && need=$(( need + 8 ))
    [[ "${DO_PROTEIN_HUNTER}" == true ]]    && need=$(( need + 8 ))   # vendored Boltz-2 + Chai-1
    [[ "${DO_RFD3}"      == true ]]         && need=$(( need + 6 ))   # rfd3_latest.ckpt ~2.5 GB
    [[ "${DO_BINDCRAFT2}" == true ]]        && need=$(( need + 12 ))  # jax+cuda wheels; AF2 params reused, not re-downloaded
    [[ "${DO_AF3}"       == true ]]         && need=$(( need + 6 ))
    [[ "${DO_ESMFOLD2}"  == true ]]         && need=$(( need + 6 ))
    [[ "${DO_SOLUPROT}"  == true ]]         && need=$(( need + 2 ))
    [[ "${CONDA_BASE}" == "${LOCAL_CONDA_DIR}" ]] && need=$(( need + 1 ))

    local avail
    avail="$(df -BG --output=avail "${BINDERSCOUT_DIR}" 2>/dev/null | tail -1 | tr -dc '0-9')"
    if [[ -z "${avail}" ]]; then
        print_warn "Could not determine free space on ${BINDERSCOUT_DIR} — skipping the disk check."
    elif (( avail < need )); then
        print_fail "Not enough free space: ${avail} GB available, ~${need} GB needed for the selected tools."
        print_warn "  Free some space, install fewer tools, or re-run with --skip-preflight to override."
        return 1
    else
        print_ok "Disk: ${avail} GB free, ~${need} GB needed"
    fi

    if command -v nvidia-smi &>/dev/null; then
        local _gpu
        _gpu="$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
        [[ -n "${_gpu}" ]] && print_ok "GPU: ${_gpu}" || print_warn "nvidia-smi present but reported no GPU."
    else
        print_warn "nvidia-smi not found — install will proceed, but the tools need an NVIDIA GPU to run."
    fi

    if command -v curl &>/dev/null; then
        if curl -fsS --max-time 10 -o /dev/null https://pypi.org/simple/ 2>/dev/null; then
            print_ok "Network: pypi.org reachable"
        else
            print_warn "Could not reach pypi.org in 10 s — downloads may fail (proxy? offline?)."
        fi
    fi
    return 0
}

main() {
    echo ""
    echo -e "${BOLD}=== BinderScout Installer — $(date) ===${RESET}"
    echo -e "CUDA: ${CUDA_VERSION} | Arch: ${ARCH} | Standalone: ${STANDALONE} | Skip examples: ${SKIP_EXAMPLES}"

    detect_conda || exit 1
    local _conda_name _conda_ver
    _conda_name="$(basename "${CONDA_CMD}")"
    _conda_ver="$("${CONDA_CMD}" --version 2>/dev/null | awk '{print $2}')"
    print_ok "${_conda_name} ${_conda_ver} at: ${CONDA_BASE}"
    if [[ "${CONDA_BASE}" == "${LOCAL_CONDA_DIR}" ]]; then
        print_ok "Standalone mode — all environments local to ${BINDERSCOUT_DIR}"
    fi

    # REFUSE on aarch64 rather than warn. This script is x86-shaped throughout —
    # it pins cu121 wheel indexes that have no aarch64 build, and its BoltzGen arm
    # installs plain PyPI torch, which on aarch64 is CPU-only. A warning is not
    # enough protection: running `--tool all` here once replaced a working
    # torch 2.10.0+cu130 in the BoltzGen env with CPU torch 2.5.1, silently, while
    # printing "BoltzGen installation complete". Four other tools failed outright
    # on cu121, and only SoluProt's arm refused properly — that guard is now
    # hoisted to the top, where it protects every tool instead of one.
    #
    # `binderscout install` already routes aarch64 here correctly (binderscout.py);
    # this only catches a direct `bash install/install.sh` invocation.
    if [[ "${ARCH}" == "aarch64" ]]; then
        print_fail "install/install.sh is the x86_64 installer, and this machine is aarch64."
        echo ""
        echo "    Use the aarch64 installer instead:"
        echo "        bash install/install_aarch.sh <same arguments>"
        echo "    or let the dispatcher pick for you:"
        echo "        binderscout install <same arguments>"
        echo ""
        echo "    Override with BINDERSCOUT_ALLOW_X86_INSTALLER=1 if you truly mean to"
        echo "    run the x86 script here — it will degrade CUDA-enabled environments."
        [[ "${BINDERSCOUT_ALLOW_X86_INSTALLER:-}" == "1" ]] || exit 1
        print_warn "BINDERSCOUT_ALLOW_X86_INSTALLER=1 — continuing on aarch64 anyway."
    fi

    print_tool_status

    # Show interactive menu if no --tool was given
    if [[ "${TOOL_SPECIFIED}" == false ]]; then
        if [[ "${UNINSTALL_MODE}" == true ]]; then
            print_fail "--uninstall requires --tool <tool|all>"
            exit 1
        fi
        # Honour the return: the menu refuses when stdin closes with nothing
        # selected, and ignoring that let the run continue to a green summary
        # having installed no tools at all.
        select_tools_interactive || exit 1
    fi

    # --verify: report what is actually on disk and stop. Runs before preflight
    # because auditing needs no disk headroom and no network.
    if [[ "${VERIFY_ONLY}" == true ]]; then
        local _broken=()
        verify_selected_tools _broken && { echo ""; print_ok "All selected tools verified usable."; exit 0; }
        echo ""
        print_fail "Unusable: ${_broken[*]}"
        echo -e "  Re-run with ${BOLD}--repair${RESET} to re-install just these."
        exit 1
    fi

    # Preflight runs after tool selection (so the disk estimate matches the choice)
    # and before any download. Uninstall skips it — it frees space, not consumes it.
    if [[ "${UNINSTALL_MODE}" != true ]]; then
        preflight || exit 1
    fi

    # ── Repair mode ──────────────────────────────────────────────────────────
    if [[ "${REPAIR_MODE}" == true ]]; then
        local _broken=()
        if verify_selected_tools _broken; then
            echo ""; print_ok "Nothing to repair — all selected tools verified usable."; exit 0
        fi
        repair_tools _broken
        local _still=()
        if verify_selected_tools _still; then
            echo ""; print_ok "Repair complete — all selected tools verified usable."; exit 0
        fi
        echo ""
        print_fail "Still unusable after repair: ${_still[*]}"
        echo -e "  Full log: ${LOG_FILE}"
        exit 1
    fi

    # ── Uninstall mode ───────────────────────────────────────────────────────
    if [[ "${UNINSTALL_MODE}" == true ]]; then
        echo ""
        echo -e "${BOLD}=== Uninstall Mode ===${RESET}"
        echo -e "This removes conda envs, venvs, and shortcuts."
        echo -e "User data (runs/, configs, logs) is ${GREEN}preserved${RESET}."
        confirm "Proceed with uninstall?" || { echo "Aborted."; exit 0; }

        # `--tool all` means "everything installed" when uninstalling. The install-side
        # `all` still omits AF3 (gated weights), so without this its env — plus
        # alphafold3/ — survived an "uninstall everything" and the script still said
        # it was complete. SoluProt and ESMFold2 are in install-`all` now; they are
        # re-asserted here so an uninstall stays correct either way.
        if [[ "${TOOL_ALL}" == true ]]; then
            DO_AF3=true
            DO_ESMFOLD2=true
            DO_SOLUPROT=true
        fi

        local failed_uninstalls=()
        [[ "${DO_BINDCRAFT}" == true ]] && { uninstall_tool bindcraft  || failed_uninstalls+=("BindCraft"); }
        [[ "${DO_BOLTZGEN}"  == true ]] && { uninstall_tool boltzgen   || failed_uninstalls+=("BoltzGen");  }
        [[ "${DO_MOSAIC}"    == true ]] && { uninstall_tool mosaic     || failed_uninstalls+=("Mosaic");    }
        [[ "${DO_EVALUATOR}" == true ]] && { uninstall_tool evaluator  || failed_uninstalls+=("Evaluator"); }
        [[ "${DO_PXDESIGN}"  == true ]] && { uninstall_tool pxdesign  || failed_uninstalls+=("PXDesign"); }
        [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && { uninstall_tool proteina-complexa || failed_uninstalls+=("Proteina-Complexa"); }
        [[ "${DO_PROTEIN_HUNTER}" == true ]] && { uninstall_tool protein-hunter || failed_uninstalls+=("Protein-Hunter"); }
        [[ "${DO_RFD3}"      == true ]] && { uninstall_tool rfd3      || failed_uninstalls+=("RFD3"); }
        [[ "${DO_BINDCRAFT2}" == true ]] && { uninstall_tool bindcraft2 || failed_uninstalls+=("BindCraft 2"); }
        [[ "${DO_AF3}"       == true ]] && { uninstall_tool af3       || failed_uninstalls+=("AF3"); }
        [[ "${DO_ESMFOLD2}"  == true ]] && { uninstall_tool esmfold2  || failed_uninstalls+=("ESMFold2"); }
        [[ "${DO_SOLUPROT}"  == true ]] && { uninstall_tool soluprot  || failed_uninstalls+=("SoluProt"); }

        # Offer to remove local Miniforge when all tools are uninstalled
        if [[ "${DO_BINDCRAFT}" == true && "${DO_BOLTZGEN}" == true && \
              "${DO_MOSAIC}" == true && "${DO_EVALUATOR}" == true ]]; then
            if [[ -d "${LOCAL_CONDA_DIR}" ]]; then
                if confirm_destructive "Also remove local Miniforge3 installation (${LOCAL_CONDA_DIR})?"; then
                    rm -rf "${LOCAL_CONDA_DIR}"
                    print_ok "Removed local Miniforge3"
                fi
            fi
        fi

        echo ""
        if [[ ${#failed_uninstalls[@]} -eq 0 ]]; then
            print_ok "Uninstall complete."
        else
            print_fail "Failed to uninstall: ${failed_uninstalls[*]}"
        fi

        # Be explicit about what is still on disk. "Uninstall complete." used to be
        # printed while multi-GB artefacts remained, so a user reclaiming space had no
        # idea where it went. These are NOT removed automatically: runs/ is the user's
        # data, and editing ~/.bashrc on their behalf is not ours to do.
        echo ""
        print_warn "Left in place (remove by hand if you want the space back):"
        [[ -d "${BINDERSCOUT_DIR}/runs" ]] && print_warn "  ${BINDERSCOUT_DIR}/runs/        — your run directories and results"
        [[ -f "${LOG_FILE}" ]] && print_warn "  ${LOG_FILE}"
        [[ -d "${HOME}/.boltz" ]] && print_warn "  ${HOME}/.boltz/                — Boltz-2 weight cache (~4.5 GB)"
        [[ -d "${HOME}/.cache/binderscout" ]] && print_warn "  ${HOME}/.cache/binderscout/     — shared target-MSA cache"
        [[ -d "${HOME}/.cache/huggingface" ]] && print_warn "  ${HOME}/.cache/huggingface/    — ESMFold2 weights (shared with other tools)"
        grep -q "${SHORTCUTS_DIR}" "${HOME}/.bashrc" 2>/dev/null && \
            print_warn "  the PATH line for ${SHORTCUTS_DIR} in ~/.bashrc"
        [[ ${#failed_uninstalls[@]} -gt 0 ]] && exit 1 || exit 0
    fi

    # ── Install mode ─────────────────────────────────────────────────────────
    echo ""
    echo -e "Log file: ${LOG_FILE}"

    # Step counter for progress
    local step=0 total=0
    [[ "${DO_BINDCRAFT}" == true ]] && (( total++ ))
    [[ "${DO_BOLTZGEN}"  == true ]] && (( total++ ))
    [[ "${DO_MOSAIC}"    == true ]] && (( total++ ))
    [[ "${DO_EVALUATOR}" == true ]] && (( total++ ))
    [[ "${DO_PXDESIGN}"  == true ]] && (( total++ ))
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && (( total++ ))
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && (( total++ ))
    [[ "${DO_RFD3}"      == true ]] && (( total++ ))
    [[ "${DO_BINDCRAFT2}" == true ]] && (( total++ ))
    [[ "${DO_AF3}"       == true ]] && (( total++ ))
    [[ "${DO_ESMFOLD2}"  == true ]] && (( total++ ))
    [[ "${DO_SOLUPROT}"  == true ]] && (( total++ ))

    local failed_tools=()
    FAILED_EXAMPLES=()   # populated by install functions on example failure

    [[ "${DO_BINDCRAFT}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BindCraft${RESET}"; install_bindcraft || failed_tools+=("BindCraft"); }
    # BindCraft 2 is cloned from upstream like every other tool now that it is
    # public, so a failure here is a real failure -- no skip special case.
    [[ "${DO_BINDCRAFT2}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BindCraft 2${RESET}"; install_bindcraft2 || failed_tools+=("BindCraft 2"); }
    [[ "${DO_BOLTZGEN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BoltzGen${RESET}";  install_boltzgen  || failed_tools+=("BoltzGen");  }
    [[ "${DO_MOSAIC}"    == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Mosaic${RESET}";    install_mosaic    || failed_tools+=("Mosaic");    }
    [[ "${DO_EVALUATOR}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Evaluator${RESET}"; install_evaluator || failed_tools+=("Evaluator"); }
    [[ "${DO_RFD3}"      == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] RFD3${RESET}";      install_rfd3      || failed_tools+=("RFD3"); }
    [[ "${DO_PXDESIGN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] PXDesign${RESET}";  install_pxdesign  || failed_tools+=("PXDesign"); }
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Proteina-Complexa${RESET}"; install_proteina_complexa || failed_tools+=("Proteina-Complexa"); }
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Protein-Hunter${RESET}"; install_protein_hunter || failed_tools+=("Protein-Hunter"); }
    [[ "${DO_AF3}"       == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] AlphaFold 3${RESET}"; install_af3 || failed_tools+=("AF3"); }
    [[ "${DO_ESMFOLD2}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] ESMFold2${RESET}"; install_esmfold2 || failed_tools+=("ESMFold2"); }
    [[ "${DO_SOLUPROT}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] SoluProt 1.0${RESET}"; install_soluprot || failed_tools+=("SoluProt"); }
    [[ "${DO_TMPROT}"    == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] TmProt 1.0${RESET}"; install_tmprot || failed_tools+=("TmProt"); }

    # Verify before summarising. Without this a tool whose install function
    # ended on print_ok -- RFD3 with an empty weights dir, Proteina-Complexa
    # with no checkpoints -- is reported as installed and never reaches
    # failed_tools, so the exit status is honest about an array that is wrong.
    local _unusable=()
    if ! verify_selected_tools _unusable; then
        local _u
        for _u in "${_unusable[@]}"; do
            local _seen=false _f
            for _f in "${failed_tools[@]}"; do [[ "${_f}" == "${_u}" ]] && _seen=true; done
            [[ "${_seen}" == false ]] && failed_tools+=("${_u}")
        done
        echo ""
        print_warn "Re-run with ${BOLD}--repair${RESET} to re-install just the tools above."
    fi

    echo ""
    echo -e "${BOLD}=== Installation Summary ===${RESET}"

    # Installation results
    if [[ ${#failed_tools[@]} -eq 0 ]]; then
        print_ok "All selected tools installed successfully."
    else
        print_fail "The following tools failed to install: ${failed_tools[*]}"
    fi

    # Example results (separate from installation)
    if [[ ${#FAILED_EXAMPLES[@]} -gt 0 ]]; then
        print_warn "Examples failed (tools themselves are usable): ${FAILED_EXAMPLES[*]}"
        echo -e "  Check the log for details: ${LOG_FILE}"
    fi

    # Shortcuts and PATH instructions
    echo ""
    echo -e "Shortcuts available in ${SHORTCUTS_DIR}:"
    [[ "${DO_BINDCRAFT}" == true ]] && echo -e "  ${GREEN}bindcraft${RESET}  — open BindCraft shell"
    [[ "${DO_BOLTZGEN}"  == true ]] && echo -e "  ${GREEN}boltzgen${RESET}   — open BoltzGen shell"
    [[ "${DO_MOSAIC}"    == true ]] && echo -e "  ${GREEN}mosaic${RESET}     — open Mosaic shell"
    [[ "${DO_EVALUATOR}" == true ]] && echo -e "  ${GREEN}evaluate${RESET}   — launch evaluation wizard"
    [[ "${DO_RFD3}"      == true ]] && echo -e "  ${GREEN}rfd3${RESET}       — run RFD3 design / open env shell"
    [[ "${DO_BINDCRAFT2}" == true && -x "${SHORTCUTS_DIR}/bindcraft2" ]] && echo -e "  ${GREEN}bindcraft2${RESET} — run BindCraft 2 design / open env shell"
    [[ "${DO_PXDESIGN}"  == true ]] && echo -e "  ${GREEN}pxdesign${RESET}   — open PXDesign shell"
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && echo -e "  ${GREEN}complexa${RESET}   — open Proteina-Complexa shell"
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && echo -e "  ${GREEN}protein-hunter${RESET} — open Protein-Hunter shell"
    # Add shortcuts dir to PATH in .bashrc (idempotent)
    local path_line="export PATH=\"${SHORTCUTS_DIR}:\$PATH\""
    if ! grep -qF "${SHORTCUTS_DIR}" "${HOME}/.bashrc" 2>/dev/null; then
        echo "" >> "${HOME}/.bashrc"
        echo "# BinderScout shortcuts" >> "${HOME}/.bashrc"
        echo "${path_line}" >> "${HOME}/.bashrc"
        print_ok "Added ${SHORTCUTS_DIR} to PATH in ~/.bashrc"
    else
        print_ok "${SHORTCUTS_DIR} already in ~/.bashrc"
    fi
    export PATH="${SHORTCUTS_DIR}:${PATH}"
    echo ""
    echo -e "Full log: ${LOG_FILE}"

    [[ ${#failed_tools[@]} -gt 0 ]] && exit 1 || exit 0
}

main
