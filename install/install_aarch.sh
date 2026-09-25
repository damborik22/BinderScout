#!/bin/bash
# BinderScout Installer — DGX Spark (aarch64) Edition
# Platform: NVIDIA DGX Spark (GB10 Blackwell), aarch64, CUDA 13.0, Ubuntu 24.04
#
# BindCraft, BoltzGen, and Mosaic are cloned from upstream on first install
# (same as x86_64). Pre-cached resources (AF2 weights, ARM64 binaries) are
# read from TOOLS_DIR to avoid redundant downloads.
#
# Usage:
#   bash install/install_aarch.sh [--tool bindcraft|boltzgen|mosaic|evaluator|pxdesign|af3|esmfold2|all] [--tools-dir PATH] [--skip-examples]
#
# --tools-dir: path to pre-cached resources. Defaults to the sibling
#              Documents/OLD/BinderScout/bindcraft-tools directory.

# ─── Constants ────────────────────────────────────────────────────────────────
BINDERSCOUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHORTCUTS_DIR="${BINDERSCOUT_DIR}/bin"
LOCAL_CONDA_DIR="${BINDERSCOUT_DIR}/conda"
LOG_FILE="${BINDERSCOUT_DIR}/install_aarch.log"

BINDCRAFT_DIR="${BINDERSCOUT_DIR}/BindCraft"
BOLTZGEN_DIR="${BINDERSCOUT_DIR}/BoltzGen"
MOSAIC_DIR="${BINDERSCOUT_DIR}/Mosaic"
EVALUATOR_DIR="${BINDERSCOUT_DIR}/Evaluator"
FOUNDRY_WEIGHTS_DIR="${BINDERSCOUT_DIR}/weights/foundry"
# AlphaFold 3 (DeepMind, Evaluator refolding). NOT a real PyPI package — the
# "alphafold3" PyPI name is an unrelated stub. Installed from the official repo
# (pinned); refold_af3.py resolves run_alphafold.py at ${AF3_DIR}. alphafold3/ gitignored.
AF3_REPO="https://github.com/google-deepmind/alphafold3"
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

PROTEINA_COMPLEXA_REPO="${PROTEINA_COMPLEXA_REPO:-https://github.com/NVIDIA-Digital-Bio/proteina-complexa.git}"
PROTEINA_COMPLEXA_COMMIT="${PROTEINA_COMPLEXA_COMMIT:-HEAD}"
PROTEINA_COMPLEXA_DIR="${BINDERSCOUT_DIR}/Proteina-Complexa"

# aarch64: VALIDATED on GB10/sm_121 — jax-cuda13 0.11.1 takes the GPU, biotraj
# (the only source build in the tree) compiles, and a campaign runs to completion
# with the two guard settings run_bindcraft2.sh injects. Out of --tool all for
# throughput, not capability: ~7.4 min/trajectory here vs ~90 s on a GH200.

# Pinned commits for reproducible installs (same as x86_64)
BINDCRAFT_COMMIT="7cd4ace"
BOLTZGEN_COMMIT="da0f092"
MOSAIC_COMMIT="82593a8"

PXDESIGN_REPO="https://github.com/bytedance/PXDesign.git"
PXDESIGN_COMMIT="HEAD"
PXDESIGN_DIR="${BINDERSCOUT_DIR}/PXDesign"
PROTEIN_HUNTER_REPO="https://github.com/yehlincho/Protein-Hunter.git"
PROTEIN_HUNTER_COMMIT="d4bd9515882c2aa81e97f3d3bf7f42247a9fe80c"
PROTEIN_HUNTER_DIR="${BINDERSCOUT_DIR}/Protein-Hunter"

ARCH="$(uname -m)"     # expected: aarch64
CUDA_VERSION="13.0"    # DGX Spark GB10 (Blackwell, sm_121)
FOUNDRY_VERSION="0.1.9"   # rc-foundry release pinned for RFD3 (matches install.sh)

# Pre-cached resources: two levels up → Documents/OLD/BinderScout/bindcraft-tools
_default_tools="$(cd "${BINDERSCOUT_DIR}" && cd ../../Documents/OLD/BinderScout/bindcraft-tools 2>/dev/null && pwd || true)"
TOOLS_DIR="${_default_tools}"

CONDA_CMD=""          # set by detect_conda: full path to mamba (preferred) or conda

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── Defaults ─────────────────────────────────────────────────────────────────
SKIP_EXAMPLES=false
AUTO_YES=false
SKIP_PREFLIGHT=false
FORCE=false      # --force: allow --yes to accept DESTRUCTIVE prompts (reclone / env re-create)
UNINSTALL_MODE=false
TOOL_SPECIFIED=false
TOOL_ALL=false         # --tool all was given; uninstall widens this to every optional add-on   # set to true when --tool is passed on CLI
STANDALONE="auto"      # auto | true | false — controls local Miniforge install

# Per-tool install flags (set by arg parsing or interactive menu)
DO_BINDCRAFT=false
DO_BOLTZGEN=false
DO_MOSAIC=false
DO_EVALUATOR=false
DO_PXDESIGN=false
DO_AF3=false            # opt-in via --tool af3 (gated weights; not in --tool all)
DO_BINDCRAFT2=false     # opt-in via --tool bindcraft2 + --bc2-source (see the note above)
DO_PROTEIN_HUNTER=false # opt-in via --tool protein-hunter. PyRosetta comes from the graylab
                        # conda channel -- the same aarch64 build install_bindcraft() already
                        # uses here -- not from the pip wheel, which has no aarch64 build and
                        # whose installer hard-aborts on this architecture. UNVALIDATED on
                        # aarch64 hardware, so it is kept out of --tool all.
DO_RFD3=false           # opt-in via --tool rfd3. Should work (pip-only, no DGL) but is
                        # UNVALIDATED on aarch64 hardware, so it is kept out of --tool all.
DO_PROTEINA_COMPLEXA=false  # opt-in via --tool proteina-complexa. Deprecated here until
                        # 2026-09-26: the original reason ("no CUDA jaxlib for aarch64") was
                        # disproved, and the real blocker -- jax 0.4.x cannot compile an
                        # AF2-class graph for sm_121 -- is fixed by jax 0.6.2, which BindCraft 1
                        # already uses on this hardware. UNVALIDATED end to end, so not in
                        # --tool all: the throughput question that drove the deprecation
                        # (3300 AF2 calls per replicate) is only answerable by running it.
DO_ESMFOLD2=false       # in --tool all (default refold engine) (lightweight 4th refold engine; no gated weights)
DO_SOLUPROT=false       # in --tool all (sequence-only E. coli solubility screen; source-builds scikit-learn 0.20.4 + USEARCH v12, uses the --no_tmhmm model)

# ─── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tool)
            TOOL_SPECIFIED=true
            case "${2,,}" in
                all)
                    TOOL_ALL=true
                    # ESMFold2 is the DEFAULT refold engine, so `all` must include it —
                    # otherwise evaluate.sh skips it and consensus_iptm is built from
                    # fewer engines than the two-stage ranking assumes.
                    DO_BINDCRAFT=true; DO_BOLTZGEN=true; DO_MOSAIC=true; DO_EVALUATOR=true; DO_PXDESIGN=true
                    DO_ESMFOLD2=true      # RFD3 is opt-in here: --tool rfd3 (see the note on DO_RFD3)
                    # SoluProt screens the pool BEFORE any GPU refolding, so a full
                    # install without it cannot run the documented workflow. On this
                    # platform it also source-builds scikit-learn 0.20.4 and USEARCH
                    # v12, so `all` now requires a C/C++ toolchain.
                    DO_SOLUPROT=true ;;
                bindcraft)
                    DO_BINDCRAFT=true ;;
                boltzgen)
                    DO_BOLTZGEN=true ;;
                mosaic)
                    DO_MOSAIC=true ;;
                evaluator)
                    DO_EVALUATOR=true ;;
                pxdesign)
                    DO_PXDESIGN=true ;;
                bindcraft2|bc2)
                    DO_BINDCRAFT2=true ;;
                rfd3|foundry)
                    DO_RFD3=true ;;
                protein-hunter|protein_hunter|phunter)
                    DO_PROTEIN_HUNTER=true ;;
                proteina-complexa|proteina_complexa|complexa)
                    # The 2026-07-29 deprecation reason ("no CUDA jaxlib for aarch64") was
                    # disproved on 09-18; the real blocker was that jax 0.4.x cannot compile an
                    # AF2-class graph for sm_121. That is fixed twice over on this hardware now
                    # (BindCraft 1 on jax[cuda12]==0.6.2, BindCraft 2 on jax-cuda13 0.11.1), and
                    # PC's AF2 reward is the same ColabDesign, so it inherits the fix.
                    # Opt-in, NOT in --tool all: unvalidated end to end here.
                    DO_PROTEINA_COMPLEXA=true ;;
                af3|alphafold3|alphafold)
                    DO_AF3=true ;;
                esmfold2|esm|esmfold)
                    DO_ESMFOLD2=true ;;
                soluprot|solu|solubility)
                    DO_SOLUPROT=true ;;
                *)
                    echo -e "${RED}Invalid --tool value: $2. Must be one of: all, bindcraft, bindcraft2, boltzgen, mosaic, evaluator, pxdesign, protein-hunter, rfd3, af3, esmfold2, soluprot${RESET}"
                    exit 1
                    ;;
            esac
            shift 2
            ;;
        --tools-dir)
            TOOLS_DIR="$2"
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
Usage: $0 [--tool TOOL] [--tools-dir PATH] [--cuda VERSION] [--skip-examples] [--yes] [--force]
       $0 --uninstall --tool <tool|all> [--yes]

DGX Spark (aarch64) edition. CUDA ${CUDA_VERSION}. Tools are cloned from upstream on first install.

  --tool        Which tool(s) to install (or uninstall). Omit for interactive selection.
                  all                  bindcraft, boltzgen, mosaic, evaluator, pxdesign,
                                       esmfold2 (the default refold engine)
                  bindcraft|boltzgen|mosaic|evaluator|pxdesign
                                       install one tool
                  bindcraft2|bc2       BindCraft 2 — the eighth design tool, and the only
                                       AF2-hallucination designer that runs on this
                                       platform (BindCraft 1 needs PyRosetta and conda
                                       jaxlib, neither of which exists for aarch64).
                                       VALIDATED on GB10/sm_121, but kept out of
                                       --tool all on throughput: ~7.4 min/trajectory
                                       here against ~90 s on a GH200, so run
                                       production campaigns on x86. Not a public
                                       download — pass the copy you were given with
                                       --bc2-source (a .zip, a directory, or a git URL
                                       once upstream opens).
                  protein-hunter       Protein-Hunter — opt-in on aarch64, and NEWLY enabled:
                                       this platform used to refuse it outright, on the
                                       incorrect grounds that PyRosetta has no aarch64 build.
                                       It does — the graylab conda channel ships the same
                                       serialization flavour BindCraft already uses here, and
                                       that is what this installs instead of the pip wheel.
                                       Chai-1 is skipped (the Boltz-2 edition does not use
                                       it). UNVALIDATED on aarch64 hardware, so not in
                                       --tool all. gemmi builds from source: needs a
                                       C/C++ toolchain.
                  rfd3                 RFD3 / foundry — opt-in on aarch64. Pure pip (no DGL),
                                       so it should work, but it is UNVALIDATED on aarch64
                                       hardware and is therefore not in --tool all.
                  af3                  AlphaFold 3 v3.0.2 refolder — opt-in only;
                                       gated AF3 weights you obtain from
                                       https://github.com/google-deepmind/alphafold3
                  esmfold2             ESMFold2 refolder — opt-in only;
                                       lightweight 4th refold engine, no gated weights
                  soluprot             SoluProt solubility screen — opt-in. aarch64
                                       enabled: builds scikit-learn 0.20.4 + USEARCH
                                       v12 from source, patches biopython, uses the
                                       --no_tmhmm model (TMHMM/USEARCH x86 binaries
                                       are not used). Needs a C/C++ toolchain.
  --bc2-source  Where BindCraft 2's source is: a .zip, an unpacked directory, or a
                git URL. Equivalent to exporting BINDCRAFT2_SOURCE. Optional —
                defaults to https://github.com/PacesaLab/BindCraft2 at v1.0.1.
  --tools-dir   Path to pre-cached resources (AF2 weights, ARM64 binaries).
                Default: <repo>/../../OLD/BinderScout/bindcraft-tools
  --cuda        CUDA version (default: 13.0). Only 13.0 has been tested on DGX Spark (GB10).
  --skip-examples
                Do not prompt to run bundled examples after install.
  --yes, -y     Auto-confirm SAFE prompts (proceed?, run the example?) — for
                non-interactive / CI runs. Destructive prompts (re-clone a tool
                repo, re-create a conda env, remove the local Miniforge3) are
                auto-answered NO, so a repeat install keeps existing files and
                downloaded weights. Pair with --force to replace them.
  --skip-preflight  Skip the disk/GPU/network checks run before downloading.
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

# ─── CUDA version warning ─────────────────────────────────────────────────────
if [[ "${CUDA_VERSION}" != "13.0" ]]; then
    echo -e "\033[1;33m⚠ CUDA ${CUDA_VERSION} selected — only 13.0 has been tested on DGX Spark (GB10).\033[0m"
    echo -e "\033[1;33m⚠ PyTorch cu130 wheels and JAX CUDA plugin may not work with other CUDA versions.\033[0m"
fi

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

# ─── Platform Checks ──────────────────────────────────────────────────────────

check_arch() {
    if [[ "${ARCH}" != "aarch64" ]]; then
        print_warn "Expected aarch64 (DGX Spark) but detected: ${ARCH}"
        confirm "Continue anyway? ARM64 binaries and settings may not match." || exit 1
    else
        print_ok "Architecture: ${ARCH} — DGX Spark compatible"
    fi
}

check_tools_dir() {
    if [[ -n "${TOOLS_DIR}" && -d "${TOOLS_DIR}" ]]; then
        print_ok "Pre-cached tools directory: ${TOOLS_DIR}"
    else
        print_warn "Pre-cached tools directory not found: '${TOOLS_DIR}'"
        print_warn "  AF2 weights will be downloaded from Google (~3 GB)."
        print_warn "  Specify --tools-dir to use local cache."
        TOOLS_DIR=""
    fi
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

# print_tool_status
# Shows installed/not-installed for each tool.
print_tool_status() {
    echo ""
    echo -e "${BOLD}=== Installed Tools ===${RESET}"
    local _status _icon
    for _tool in BindCraft BoltzGen Mosaic Evaluator PXDesign; do
        if "is_${_tool,,}_installed" 2>/dev/null; then
            _icon="${GREEN}✓${RESET}"; _status="installed"
        else
            _icon="${RED}✗${RESET}"; _status="not installed"
        fi
        printf "  %b  %-12s  %s\n" "${_icon}" "${_tool}" "${_status}"
    done
    echo ""
}

# ─── Interactive Tool Selection ───────────────────────────────────────────────
# Called when no --tool flag was supplied. Displays a toggle menu; sets
# DO_BINDCRAFT / DO_BOLTZGEN / DO_MOSAIC based on user choices.

select_tools_interactive() {
    # Default: all selected
    local sel_bc=true
    local sel_bg=true
    local sel_mo=true
    local sel_ev=true
    local sel_pxd=false

    local tools=("BindCraft" "BoltzGen" "Mosaic" "Evaluator" "PXDesign")
    local descs=(
        "Binder design via AlphaFold2 (conda, Python 3.10)"
        "Structure generation with Boltz-1 (conda, Python 3.12)"
        "JAX-based protein design with Marimo notebooks (uv venv)"
        "Evaluate binders: refold with Boltz-2 (+ AF3, ESMFold2 if installed), ranked report (requires Mosaic)"
        "Protenix-based de novo binder design (conda)"
    )

    # Check current install state once (avoid repeated conda calls in the loop)
    local inst_bc inst_bg inst_mo inst_ev inst_pxd
    is_bindcraft_installed && inst_bc="${GREEN}installed${RESET}" || inst_bc="${YELLOW}not installed${RESET}"
    is_boltzgen_installed  && inst_bg="${GREEN}installed${RESET}" || inst_bg="${YELLOW}not installed${RESET}"
    is_mosaic_installed    && inst_mo="${GREEN}installed${RESET}" || inst_mo="${YELLOW}not installed${RESET}"
    is_evaluator_installed && inst_ev="${GREEN}installed${RESET}" || inst_ev="${YELLOW}not installed${RESET}"
    is_pxdesign_installed  && inst_pxd="${GREEN}installed${RESET}" || inst_pxd="${YELLOW}not installed${RESET}"
    local inst_states=("$inst_bc" "$inst_bg" "$inst_mo" "$inst_ev" "$inst_pxd")

    # Helper: print current state
    _print_menu() {
        echo ""
        echo -e "${BOLD}${CYAN}  Select tools to install${RESET}"
        echo -e "  Type a number to toggle selection, then press Enter when done."
        echo ""
        local states=("$sel_bc" "$sel_bg" "$sel_mo" "$sel_ev" "$sel_pxd")
        for i in 0 1 2 3 4; do
            local box
            if [[ "${states[$i]}" == true ]]; then
                box="${GREEN}[x]${RESET}"
            else
                box="${RED}[ ]${RESET}"
            fi
            printf "    %d)  %b  ${BOLD}%-12s${RESET}  %-35b  %s\n" \
                $((i+1)) "$box" "${tools[$i]}" "${inst_states[$i]}" "${descs[$i]}"
        done
        echo ""
        echo -e "  ${YELLOW}a${RESET}) Select all   ${YELLOW}n${RESET}) Select none   ${YELLOW}Enter${RESET} to confirm"
        echo ""
    }

    while true; do
        _print_menu
        read -rp "  > " choice
        case "${choice,,}" in
            1) [[ "$sel_bc" == true ]] && sel_bc=false || sel_bc=true ;;
            2) [[ "$sel_bg" == true ]] && sel_bg=false || sel_bg=true ;;
            3) [[ "$sel_mo" == true ]] && sel_mo=false || sel_mo=true ;;
            4) [[ "$sel_ev" == true ]] && sel_ev=false || sel_ev=true ;;
            5) [[ "$sel_pxd" == true ]] && sel_pxd=false || sel_pxd=true ;;
            a) sel_bc=true;  sel_bg=true;  sel_mo=true;  sel_ev=true;  sel_pxd=true  ;;
            n) sel_bc=false; sel_bg=false; sel_mo=false; sel_ev=false; sel_pxd=false ;;
            "")
                # Confirm: at least one must be selected
                if [[ "$sel_bc" == false && "$sel_bg" == false && "$sel_mo" == false && "$sel_ev" == false && "$sel_pxd" == false ]]; then
                    echo -e "  ${RED}No tools selected. Select at least one.${RESET}"
                    continue
                fi
                break
                ;;
            *) echo -e "  ${RED}Invalid input. Enter 1–5, a, n, or press Enter.${RESET}" ;;
        esac
    done

    DO_BINDCRAFT="$sel_bc"
    DO_BOLTZGEN="$sel_bg"
    DO_MOSAIC="$sel_mo"
    DO_EVALUATOR="$sel_ev"
    DO_PXDESIGN="$sel_pxd"

    echo ""
    echo -e "  ${BOLD}Installing:${RESET}"
    [[ "$DO_BINDCRAFT" == true ]] && echo -e "    ${GREEN}✓${RESET} BindCraft"
    [[ "$DO_BOLTZGEN"  == true ]] && echo -e "    ${GREEN}✓${RESET} BoltzGen"
    [[ "$DO_MOSAIC"    == true ]] && echo -e "    ${GREEN}✓${RESET} Mosaic"
    [[ "$DO_EVALUATOR" == true ]] && echo -e "    ${GREEN}✓${RESET} Evaluator"
    [[ "$DO_PXDESIGN"  == true ]] && echo -e "    ${GREEN}✓${RESET} PXDesign"
    [[ "$DO_AF3"       == true ]] && echo -e "    ${YELLOW}✓ AlphaFold 3 (opt-in; weights required)${RESET}"
    [[ "$DO_RFD3"      == true ]] && echo -e "    ${GREEN}✓${RESET} RFD3 (opt-in; unvalidated on aarch64)"
    [[ "$DO_PROTEINA_COMPLEXA" == true ]] && echo -e "    ${GREEN}✓${RESET} Proteina-Complexa (opt-in; jax 0.6.2 GPU path, unvalidated end-to-end)"
    [[ "$DO_ESMFOLD2"  == true ]] && echo -e "    ${GREEN}✓${RESET} ESMFold2 (default refolder)"
    [[ "$DO_SOLUPROT"  == true ]] && echo -e "    ${GREEN}✓${RESET} SoluProt (opt-in solubility screen; aarch64 via source build)"
    echo ""

    confirm "Proceed with installation?" || { echo "Aborted."; exit 0; }
}

# ─── BindCraft helpers ────────────────────────────────────────────────────────

# Rewrite Colab-style /content/... paths in settings_target/*.json files.
_fix_target_settings() {
    local settings_dir="${BINDCRAFT_DIR}/settings_target"
    [[ -d "${settings_dir}" ]] || return 0
    local count=0
    for f in "${settings_dir}"/*.json; do
        [[ -f "$f" ]] || continue
        sed -i "s|/content/drive/My Drive/BindCraft/|${BINDCRAFT_DIR}/output/|g" "$f"
        sed -i "s|/content/bindcraft/|${BINDCRAFT_DIR}/|g" "$f"
        (( count++ ))
    done
    print_ok "Patched Colab paths in ${count} target settings file(s)"
    local pdl1="${settings_dir}/PDL1.json"
    if [[ -f "${pdl1}" ]]; then
        sed -i 's|"number_of_final_designs":.*|"number_of_final_designs": 1|' "${pdl1}"
        sed -i 's|"lengths":.*|"lengths": [65, 100],|' "${pdl1}"
        print_ok "PDL1 example: number_of_final_designs=1, max binder length=100"
    fi
}

# Copy pre-built ARM64 binaries into BindCraft/functions/.
# Priority: 1) bundled tools/aarch64/  2) TOOLS_DIR  3) system dssp as fallback
_install_bindcraft_binaries_aarch64() {
    local funcs_dir="${BINDCRAFT_DIR}/functions"
    mkdir -p "${funcs_dir}"

    local bundled_dir="${BINDERSCOUT_DIR}/tools/aarch64"

    # ── DAlphaBall ──────────────────────────────────────────────────────────
    local dab_src=""
    if [[ -f "${bundled_dir}/DAlphaBall.gcc" ]]; then
        dab_src="${bundled_dir}/DAlphaBall.gcc"
    elif [[ -n "${TOOLS_DIR}" && -f "${TOOLS_DIR}/DAlphaBall/src/DAlphaBall.gcc" ]]; then
        dab_src="${TOOLS_DIR}/DAlphaBall/src/DAlphaBall.gcc"
    fi

    if [[ -n "${dab_src}" ]]; then
        cp "${dab_src}" "${funcs_dir}/DAlphaBall.gcc" && chmod +x "${funcs_dir}/DAlphaBall.gcc"
        print_ok "Installed ARM64 DAlphaBall.gcc"
    else
        print_warn "DAlphaBall.gcc not found — surface scoring will be disabled in BindCraft"
    fi

    # ── dssp / mkdssp ────────────────────────────────────────────────────────
    local dssp_src=""
    if [[ -f "${bundled_dir}/dssp" ]]; then
        dssp_src="${bundled_dir}/dssp"
    elif [[ -n "${TOOLS_DIR}" && -f "${TOOLS_DIR}/dssp-2.3.0/mkdssp" ]]; then
        dssp_src="${TOOLS_DIR}/dssp-2.3.0/mkdssp"
    fi

    if [[ -n "${dssp_src}" ]]; then
        cp "${dssp_src}" "${funcs_dir}/dssp" && chmod +x "${funcs_dir}/dssp"
        print_ok "Installed ARM64 dssp"
    else
        _link_system_dssp "${funcs_dir}"
    fi
}

_link_system_dssp() {
    local funcs_dir="$1"
    if command -v mkdssp &>/dev/null; then
        ln -sf "$(command -v mkdssp)" "${funcs_dir}/dssp"
        print_ok "Linked system mkdssp → ${funcs_dir}/dssp"
    elif command -v dssp &>/dev/null; then
        ln -sf "$(command -v dssp)" "${funcs_dir}/dssp"
        print_ok "Linked system dssp → ${funcs_dir}/dssp"
    else
        print_warn "dssp/mkdssp not found — install via: sudo apt install dssp"
    fi
}

# Install AF2 weights: copy from TOOLS_DIR cache, or download as fallback.
_install_af2_params() {
    local params_dir="${BINDCRAFT_DIR}/params"
    mkdir -p "${params_dir}"

    if [[ -f "${params_dir}/params_model_5_ptm.npz" ]]; then
        print_ok "AF2 weights already present in ${params_dir}"; return 0
    fi

    if [[ -n "${TOOLS_DIR}" ]]; then
        # Layout: af2_params/params/*.npz
        local src="${TOOLS_DIR}/af2_params/params"
        if [[ -d "${src}" ]] && ls "${src}"/*.npz &>/dev/null; then
            print_step "Copying AF2 weights from pre-cached tools (no download)"
            run_logged "Copying AF2 weights" cp -r "${src}/." "${params_dir}/" \
                || { print_fail "Failed to copy AF2 weights"; return 1; }
            [[ -f "${params_dir}/params_model_5_ptm.npz" ]] \
                || { print_fail "AF2 weight copy incomplete"; return 1; }
            print_ok "AF2 weights installed from local cache"; return 0
        fi

        # Flat layout: af2_params/*.npz
        local src_flat="${TOOLS_DIR}/af2_params"
        if [[ -d "${src_flat}" ]] && ls "${src_flat}"/*.npz &>/dev/null; then
            run_logged "Copying AF2 weights (flat)" \
                bash -c "cp '${src_flat}'/*.npz '${params_dir}/'" \
                || { print_fail "Failed to copy AF2 weights"; return 1; }
            print_ok "AF2 weights installed from local cache"; return 0
        fi

        print_warn "AF2 weights not found in tools dir — will download"
    fi

    # Fallback: download (~3 GB)
    print_warn "Downloading AF2 weights from Google (~3 GB) — takes several minutes"
    local params_file="${params_dir}/alphafold_params_2022-12-06.tar"
    run_logged --retries 3 "Downloading AF2 weights" \
        wget -q -O "${params_file}" \
        "https://storage.googleapis.com/alphafold/alphafold_params_2022-12-06.tar" \
        || { print_fail "Failed to download AF2 weights"; return 1; }
    [[ -s "${params_file}" ]] || { print_fail "Downloaded file is empty"; return 1; }
    tar tf "${params_file}" >/dev/null 2>&1 || { print_fail "Corrupt download"; return 1; }
    tar -xf "${params_file}" -C "${params_dir}" \
        || { print_fail "Failed to extract AF2 weights"; return 1; }
    [[ -f "${params_dir}/params_model_5_ptm.npz" ]] \
        || { print_fail "Extraction incomplete"; return 1; }
    rm -f "${params_file}"
    print_ok "AF2 weights downloaded and extracted"
}

# Patch dssp_path, dalphaball_path, and af_params_dir in every advanced settings JSON.
# BindCraft ships these as empty strings; they must point to the actual binaries/params.
_fix_advanced_settings() {
    local advanced_dir="${BINDCRAFT_DIR}/settings_advanced"
    [[ -d "${advanced_dir}" ]] || return 0

    local dssp_bin="${BINDCRAFT_DIR}/functions/dssp"
    local dab_bin="${BINDCRAFT_DIR}/functions/DAlphaBall.gcc"
    local params_dir="${BINDCRAFT_DIR}/params"

    local count=0
    for f in "${advanced_dir}"/*.json; do
        [[ -f "$f" ]] || continue
        # Only write paths for binaries that actually exist
        if [[ -f "${dssp_bin}" ]]; then
            sed -i "s|\"dssp_path\": \"\"|\"dssp_path\": \"${dssp_bin}\"|g" "$f"
        fi
        if [[ -f "${dab_bin}" ]]; then
            sed -i "s|\"dalphaball_path\": \"\"|\"dalphaball_path\": \"${dab_bin}\"|g" "$f"
        fi
        (( count++ ))
    done
    print_ok "Patched dssp_path and dalphaball_path in ${count} advanced settings file(s)"
}

# ─── BindCraft ────────────────────────────────────────────────────────────────

install_bindcraft() {
    print_step "Installing BindCraft (aarch64 / CUDA ${CUDA_VERSION})"
    ensure_conda_in_path
    # Ensure our conda is found first by BindCraft's own installer
    export PATH="${CONDA_BASE}/bin:${PATH}"

    # Clone if missing (matches x86_64 installer behavior)
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

    _fix_target_settings
    _install_bindcraft_binaries_aarch64
    _install_af2_params || return 1
    _fix_advanced_settings

    # PyRosetta's pr.init() passes paths through shlex.split() then into
    # Rosetta's C++ option parser, which chokes on spaces even when the token
    # is correctly quoted. Work around by creating space-free symlinks.
    if [[ "${BINDCRAFT_DIR}" == *" "* ]]; then
        local _link_dir="/tmp/binderscout_bindcraft_bin"
        mkdir -p "${_link_dir}"
        local _dab="${BINDCRAFT_DIR}/functions/DAlphaBall.gcc"
        local _dssp="${BINDCRAFT_DIR}/functions/dssp"
        [[ -f "${_dab}" ]]  && ln -sf "${_dab}"  "${_link_dir}/DAlphaBall.gcc"
        [[ -f "${_dssp}" ]] && ln -sf "${_dssp}" "${_link_dir}/dssp"
        # Re-patch settings JSONs to use space-free symlink paths
        local _adv="${BINDCRAFT_DIR}/settings_advanced"
        if [[ -d "${_adv}" ]]; then
            for f in "${_adv}"/*.json; do
                [[ -f "$f" ]] || continue
                sed -i "s|${BINDCRAFT_DIR}/functions/DAlphaBall.gcc|${_link_dir}/DAlphaBall.gcc|g" "$f"
                sed -i "s|${BINDCRAFT_DIR}/functions/dssp|${_link_dir}/dssp|g" "$f"
            done
        fi
        print_ok "Created space-free symlinks in ${_link_dir} (PyRosetta workaround)"
    fi

    if env_exists BindCraft; then
        print_warn "Conda environment 'BindCraft' already exists."
        if confirm_destructive "Remove and recreate the BindCraft conda environment?"; then
            run_logged "Removing BindCraft conda env" \
                "${CONDA_CMD}" env remove -n BindCraft -y || return 1
        else
            print_warn "Keeping existing env — skipping package installation."
            # Still refresh the shortcut. It is generated (it carries the GB10
            # guard) and lives in a gitignored bin/, so this early return was the
            # one path by which re-running the installer could NOT repair a
            # wrapper -- exactly the repair an operator runs it for.
            _write_bindcraft_shortcut
            _bindcraft_smoke_test; return $?
        fi
    fi

    print_step "Creating BindCraft conda env (Python 3.10)"
    run_logged "Creating BindCraft conda env" \
        "${CONDA_CMD}" create --name BindCraft python=3.10 -y \
        || { print_fail "Failed to create BindCraft conda env"; return 1; }

    # ── Step 1: conda packages ────────────────────────────────────────────────
    # On aarch64, jaxlib CUDA conda packages don't exist — install only the
    # non-CUDA conda packages here. JAX + CUDA come from PyPI in step 2.
    # PyRosetta is available for aarch64 via the graylab conda channel.
    print_step "Installing conda packages (PyRosetta + scientific libs)"
    print_warn "This takes 20–40 min — full output in install_aarch.log"
    run_logged "Installing BindCraft conda packages" \
        "${CONDA_CMD}" install -n BindCraft \
            pip biopython matplotlib scipy seaborn pandas \
            dm-tree einops absl-py tqdm \
            pyrosetta \
            -c conda-forge \
            --channel https://conda.graylab.jhu.edu \
            -y \
        || { print_fail "Failed to install BindCraft conda packages"; return 1; }

    # ── Step 2: JAX with CUDA 12 plugins (PyPI — aarch64 wheels exist here) ──
    # jax-cuda12-plugin does NOT pull in cuDNN or the full CUDA runtime.
    # nvidia-cudnn-cu12 needs libcudart.so.12 + friends at dlopen time, so we
    # install the complete set of nvidia-cu12 runtime packages explicitly.
    # Pinned to 0.6.2, and the version is load-bearing on GB10 (sm_121).
    # jaxlib 0.4.34's bundled LLVM knows sm_20..sm_90a only.  Asked for sm_121 it
    # falls back to a subtarget with no bf16, and ColabDesign runs AF2 in bf16 by
    # default (colabdesign/af/model.py: use_bfloat16=True) -- so every AF2 graph
    # dies at compile time with:
    #     Unsupported conversion from bf16 to f16
    #     LLVM ERROR: Unsupported rounding mode for conversion.
    # 0.5.3 is NOT enough: it tops out at sm_120.  0.6.2 is the first jaxlib that
    # knows sm_121/sm_121a AND still ships a cp310 wheel (so the py3.10 env, and
    # its aarch64 conda PyRosetta, are unchanged).  It also still exposes the
    # deprecated jax.lib.xla_bridge.get_backend that ColabDesign's clear_mem()
    # calls, so ColabDesign needs no patch.
    # Measured on BM5 (GB10), 120aa target + 40aa binder, AF2 fwd+bwd:
    #   0.4.34 + bf16 disabled : 5.40 s/iter   (the only way to make 0.4.34 run)
    #   0.6.2  + bf16 enabled  : 2.39 s/iter   (2.3x faster, and half the memory)
    print_step "Installing JAX 0.6.2 with CUDA 12 plugins (PyPI)"
    run_logged "Installing JAX + CUDA 12 plugins" \
        "${CONDA_CMD}" run -n BindCraft \
        pip install \
            "numpy<2.0.0" \
            "jax[cuda12]==0.6.2" \
            "nvidia-cudnn-cu12" \
            "nvidia-cuda-runtime-cu12" \
            "nvidia-cublas-cu12" \
            "nvidia-cusolver-cu12" \
            "nvidia-cusparse-cu12" \
            "nvidia-cufft-cu12" \
            "nvidia-cuda-nvrtc-cu12" \
            "nvidia-nvjitlink-cu12" \
        || { print_fail "Failed to install JAX"; return 1; }

    # ── Step 3: ColabDesign and BindCraft Python dependencies ─────────────────
    print_step "Installing ColabDesign and dependencies"
    run_logged "Installing ColabDesign" \
        "${CONDA_CMD}" run -n BindCraft \
        pip install \
            "colabdesign @ git+https://github.com/sokrypton/ColabDesign.git" \
            "chex==0.1.90" \
            "dm-haiku==0.0.15" \
            "optax==0.2.5" \
            "ml-collections==1.1.0" \
            "immutabledict" \
            "joblib" \
            "py3dmol" \
            "fsspec" \
            "pdbfixer" \
        || { print_fail "Failed to install ColabDesign"; return 1; }

    run_logged "Cleaning conda cache" "${CONDA_CMD}" clean -a -y

    _bindcraft_smoke_test || return 1

    if [[ "${SKIP_EXAMPLES}" == false ]]; then
        print_step "BindCraft example run (PDL1)"
        if confirm "Run the BindCraft PDL1 example?"; then
            (
                cd "${BINDCRAFT_DIR}" || exit 1
                XLA_PYTHON_CLIENT_PREALLOCATE=false \
                "${CONDA_CMD}" run -n BindCraft \
                    python -u ./bindcraft.py \
                    --settings './settings_target/PDL1.json' \
                    --filters './settings_filters/default_filters.json' \
                    --advanced './settings_advanced/default_4stage_multimer.json'
            ) && print_ok "BindCraft example completed" \
              || { print_fail "BindCraft example failed — installation is still OK"; FAILED_EXAMPLES+=("BindCraft"); }
        else
            print_warn "Skipped BindCraft example."
        fi
    fi

    _write_bindcraft_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/bindcraft"
    print_ok "BindCraft installation complete"
}

_bindcraft_smoke_test() {
    smoke_test "colabdesign import" \
        "${CONDA_CMD}" run -n BindCraft \
        python -c "from colabdesign import mk_af_model; print('OK')" \
        || return 1
    smoke_test "JAX GPU matmul" \
        "${CONDA_CMD}" run -n BindCraft \
        python -c "import jax.numpy as jnp; print(jnp.dot(jnp.ones((2,2)), jnp.ones((2,2))))"
}

_write_bindcraft_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BindCraft shortcut — activates the BindCraft conda environment"
        echo "# and opens an interactive shell in the BindCraft directory."
        echo ""
        echo "BINDCRAFT_DIR=\"${BINDCRAFT_DIR}\""
        echo "CONDA_BASE=\"${CONDA_BASE}\""
        echo "BINDERSCOUT_DIR=\"${BINDERSCOUT_DIR}\""
    } > "${SHORTCUTS_DIR}/bindcraft"
    cat >> "${SHORTCUTS_DIR}/bindcraft" << 'EOF'

source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate BindCraft
cd "${BINDCRAFT_DIR}"

echo "BindCraft environment activated."
echo "Working directory: ${BINDCRAFT_DIR}"
echo "To run BindCraft:"
echo "  XLA_PYTHON_CLIENT_PREALLOCATE=false python -u ./bindcraft.py \\"
echo "    --settings './settings_target/<target>.json' \\"
echo "    --filters './settings_filters/default_filters.json' \\"
echo "    --advanced './settings_advanced/default_4stage_multimer.json'"
echo ""


# GB10 (DGX Spark): the GPU pool IS system RAM, so a framework's default
# "fraction of device memory" is a fraction of the whole machine. This wrapper
# opens an interactive shell, so it exports the ceilings with gb10_apply rather
# than wrapping a command in gpurun -- see tools/gb10-env.sh's header for why
# the two shapes differ. GENERATED: bin/ is gitignored, so a hand-applied guard
# lives on one disk and any reinstall silently reverts it.
if [[ -r "${BINDERSCOUT_DIR}/tools/gb10-env.sh" ]]; then
    # shellcheck disable=SC1091
    source "${BINDERSCOUT_DIR}/tools/gb10-env.sh"
    gb10_apply bindcraft
fi

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
    print_step "Installing BoltzGen (aarch64)"
    ensure_conda_in_path

    # Clone if missing (matches x86_64 installer behavior)
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

    if env_exists BoltzGen; then
        print_warn "Conda environment 'BoltzGen' already exists."
        if confirm_destructive "Remove and recreate the BoltzGen conda environment?"; then
            run_logged "Removing BoltzGen conda env" \
                "${CONDA_CMD}" env remove -n BoltzGen -y || return 1
        else
            print_warn "Keeping existing BoltzGen env."
        fi
    fi
    if ! env_exists BoltzGen; then
        run_logged "Creating BoltzGen conda env (Python 3.12)" \
            "${CONDA_CMD}" create -n BoltzGen python=3.12 -y \
            || { print_fail "Failed to create BoltzGen conda env"; return 1; }
    fi

    run_logged "Installing gcc into BoltzGen env (Triton dependency)" \
        "${CONDA_CMD}" install -n BoltzGen -c conda-forge gcc -y \
        || { print_fail "Failed to install gcc"; return 1; }

    # On aarch64 / DGX Spark (GB10), PyPI's default torch is CPU-only.
    # Use the cu130 wheel index (CUDA 13.0, Blackwell sm_121).
    # Note: PyTorch emits a UserWarning about cuda capability 12.1 (GB10) not
    # being in the native arch list — this is harmless. The cu130 build ships
    # compute_120 PTX which JIT-compiles to sm_121 at runtime.
    run_logged "Installing PyTorch (aarch64, CUDA 13.0)" \
        "${CONDA_CMD}" run -n BoltzGen \
        pip install "torch==2.10.0+cu130" --index-url https://download.pytorch.org/whl/cu130 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # On aarch64, gemmi==0.6.5 has no binary wheel and fails to build from source.
    # gemmi 0.7.4 ships manylinux_2_28_aarch64 wheels — relax the pin (idempotent).
    local boltzgen_toml="${BOLTZGEN_DIR}/pyproject.toml"
    if grep -q '"gemmi==0.6.5"' "${boltzgen_toml}"; then
        sed -i 's/"gemmi==0.6.5"/"gemmi>=0.6.5"/' "${boltzgen_toml}"
        print_ok "BoltzGen pyproject.toml: relaxed gemmi pin to >=0.6.5 (aarch64 binary wheel)"
    fi

    run_logged "Installing BoltzGen package" \
        "${CONDA_CMD}" run -n BoltzGen \
        pip install -e "${BOLTZGEN_DIR}" \
        || { print_fail "Failed to install BoltzGen package"; return 1; }

    # BoltzGen pulls cuequivariance-ops-cu12 which needs libnvrtc.so.12, but the
    # cu130 PyTorch ships CUDA 13 runtime only. Swap to the cu13 builds (same API).
    run_logged "Swapping cuequivariance-ops to cu13 (matching CUDA 13 runtime)" \
        "${CONDA_CMD}" run -n BoltzGen \
        pip install cuequivariance-ops-cu13 cuequivariance-ops-torch-cu13 --force-reinstall --no-deps \
        || print_warn "cuequivariance cu13 swap failed — kernels may fall back to Python"

    # PyTorch DataLoader with num_workers>=1 deadlocks on aarch64/DGX Spark
    # (futex_wait_queue in worker process). Setting the CLI default to 0 forces
    # single-process data loading, which completes design in ~24 s per structure.
    local _bg_cli="${BOLTZGEN_DIR}/src/boltzgen/cli/boltzgen.py"
    if [[ -f "${_bg_cli}" ]]; then
        sed -i '/"--num_workers"/,/default=/{s/default=1,/default=0,/}' "${_bg_cli}" \
            && print_ok "Patched boltzgen CLI: num_workers default 1 → 0 (aarch64 deadlock fix)" \
            || print_warn "Could not patch num_workers default"
    fi

    smoke_test "boltzgen --help" \
        "${CONDA_CMD}" run -n BoltzGen boltzgen --help || return 1
    smoke_test "PyTorch GPU matmul" \
        "${CONDA_CMD}" run -n BoltzGen \
        python -c "import torch; x=torch.randn(2,2,device='cuda'); print(x@x.T)" \
        || return 1

    if [[ "${SKIP_EXAMPLES}" == false ]]; then
        print_step "BoltzGen example run"
        print_warn "First run downloads ~6 GB of model weights."
        if confirm "Run the BoltzGen example (2 designs of 1g13)?"; then
            (
                cd "${BOLTZGEN_DIR}" || exit 1
                "${CONDA_CMD}" run -n BoltzGen \
                    boltzgen run example/vanilla_protein/1g13prot.yaml \
                    --output output/test_run \
                    --protocol protein-anything \
                    --num_designs 2
            ) && print_ok "BoltzGen example completed" \
              || { print_fail "BoltzGen example failed — installation is still OK"; FAILED_EXAMPLES+=("BoltzGen"); }
        else
            print_warn "Skipped BoltzGen example."
        fi
    fi

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
        echo "BINDERSCOUT_DIR=\"${BINDERSCOUT_DIR}\""
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


# GB10 (DGX Spark): the GPU pool IS system RAM, so a framework's default
# "fraction of device memory" is a fraction of the whole machine. This wrapper
# opens an interactive shell, so it exports the ceilings with gb10_apply rather
# than wrapping a command in gpurun -- see tools/gb10-env.sh's header for why
# the two shapes differ. GENERATED: bin/ is gitignored, so a hand-applied guard
# lives on one disk and any reinstall silently reverts it.
if [[ -r "${BINDERSCOUT_DIR}/tools/gb10-env.sh" ]]; then
    # shellcheck disable=SC1091
    source "${BINDERSCOUT_DIR}/tools/gb10-env.sh"
    gb10_apply boltzgen
fi

exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/boltzgen"
}

# ─── Mosaic ───────────────────────────────────────────────────────────────────

# Patch Mosaic/pyproject.toml for aarch64:
#   esmj has no aarch64 wheel — add the platform_machine exclusion.
# Safe to call on an already-patched file (idempotent).
_patch_mosaic_pyproject() {
    local toml="${MOSAIC_DIR}/pyproject.toml"
    [[ -f "${toml}" ]] || { print_warn "pyproject.toml not found at ${toml}"; return 0; }

    if grep -q '"esmj"' "${toml}" && ! grep -q 'platform_machine' "${toml}"; then
        sed -i 's|"esmj",|"esmj; platform_machine != '"'"'aarch64'"'"'",|' "${toml}"
        print_ok "Patched esmj: excluded on aarch64"
    else
        print_ok "Mosaic pyproject.toml: esmj already has aarch64 exclusion"
    fi

    # Mosaic 82593a8 pins required-environments to x86_64, which breaks uv
    # resolution on aarch64. Strip it so uv resolves for this platform.
    # UNTESTED on DGX Spark — verify uv sync resolves after this.
    if grep -q 'required-environments' "${toml}"; then
        sed -i '/required-environments = /d' "${toml}"
        print_ok "Removed required-environments x86_64 pin (aarch64 resolution)"
    fi
}

install_mosaic() {
    print_step "Installing Mosaic (aarch64 / CUDA ${CUDA_VERSION})"

    # Clone if missing (matches x86_64 installer behavior)
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
        print_fail "uv still not found after install; check PATH"; return 1
    fi
    print_ok "uv: $(command -v uv)"

    _patch_mosaic_pyproject

    # Offline-MSA support: re-apply TargetChain.msa_path patch (upstream lacks it;
    # our refolds + hallucination template need it). Idempotent.
    local msa_patch="${BINDERSCOUT_DIR}/install/patches/mosaic-offline-msa.patch"
    if [[ -f "${msa_patch}" ]] && ! grep -q "msa_path" "${MOSAIC_DIR}/src/mosaic/structure_prediction.py" 2>/dev/null; then
        git -C "${MOSAIC_DIR}" apply "${msa_patch}" \
            && print_ok "Applied offline-MSA patch (TargetChain.msa_path)" \
            || print_warn "Offline-MSA patch failed to apply — offline target MSA disabled"
    fi

    run_logged "Setting up Mosaic venv (uv sync --group jax-cuda)" \
        bash -c "cd '${MOSAIC_DIR}' && uv sync --group jax-cuda" \
        || { print_fail "uv sync failed for Mosaic"; return 1; }

    smoke_test "import mosaic" \
        "${MOSAIC_DIR}/.venv/bin/python" -c "import mosaic; print('OK')" || return 1

    if [[ "${SKIP_EXAMPLES}" == false ]]; then
        print_step "Mosaic example"
        if confirm "Open the Mosaic example notebook in Marimo?"; then
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

    # Copy BinderScout custom examples into Mosaic/examples/
    local src_examples="${BINDERSCOUT_DIR}/binderscout_examples"
    local dst_examples="${MOSAIC_DIR}/examples/binderscout_examples"
    if [[ -d "${src_examples}" ]]; then
        mkdir -p "${dst_examples}"
        cp -r "${src_examples}/." "${dst_examples}/" 2>/dev/null || true
        rm -f "${dst_examples}/.gitkeep" 2>/dev/null || true
        local count
        count=$(find "${dst_examples}" -maxdepth 1 -type f | wc -l)
        if [[ "${count}" -gt 0 ]]; then
            print_ok "Copied ${count} custom example(s) to ${dst_examples}"
        else
            print_ok "binderscout_examples/ ready at ${dst_examples} (add your Marimo scripts there)"
        fi
    fi

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
        echo "BINDERSCOUT_DIR=\"${BINDERSCOUT_DIR}\""
    } > "${SHORTCUTS_DIR}/mosaic"
    cat >> "${SHORTCUTS_DIR}/mosaic" << 'EOF'

source "${MOSAIC_DIR}/.venv/bin/activate"
cd "${MOSAIC_DIR}"

echo "Mosaic environment activated."
echo "Working directory: ${MOSAIC_DIR}"
echo "To open the example notebook:"
echo "  marimo edit examples/example_notebook.py"
echo ""


# GB10 (DGX Spark): the GPU pool IS system RAM, so a framework's default
# "fraction of device memory" is a fraction of the whole machine. This wrapper
# opens an interactive shell, so it exports the ceilings with gb10_apply rather
# than wrapping a command in gpurun -- see tools/gb10-env.sh's header for why
# the two shapes differ. GENERATED: bin/ is gitignored, so a hand-applied guard
# lives on one disk and any reinstall silently reverts it.
if [[ -r "${BINDERSCOUT_DIR}/tools/gb10-env.sh" ]]; then
    # shellcheck disable=SC1091
    source "${BINDERSCOUT_DIR}/tools/gb10-env.sh"
    gb10_apply mosaic
fi

exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/mosaic"
}

# ─── Evaluator ─────────────────────────────────────────────────────────────

install_evaluator() {
    print_step "Installing Evaluator"
    ensure_conda_in_path

    # Mosaic must be installed first — we use its venv for Boltz-2
    if ! is_mosaic_installed; then
        print_fail "Mosaic must be installed before the Evaluator (provides the Boltz-2 venv)."
        print_warn "Run: bash install_aarch.sh --tool mosaic"
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
    # fair-esm loads the weights via torch; the PLL runs in JAX/esm2quinox.
    # Non-fatal — the design template guards a missing ESM2 (fine on aarch64).
    print_step "Installing fair-esm (ESM2 expressibility prior) into Mosaic venv"
    run_logged "pip install fair-esm into Mosaic venv" \
        uv pip install --python "${MOSAIC_VENV}/bin/python" -q fair-esm \
        || print_warn "fair-esm install failed — Mosaic will run without the ESM2 prior"
    # Pre-cache the ESM2-150M weights (~566 MB) so offline compute nodes need no
    # download at design time (cached under ~/.cache/torch/hub/checkpoints). Non-fatal.
    run_logged "pre-fetch ESM2-150M weights" \
        "${MOSAIC_VENV}/bin/python" -c "import esm; esm.pretrained.esm2_t30_150M_UR50D()" \
        || print_warn "ESM2-150M weight prefetch failed — provision it offline or design runs without the prior"

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
    #  env is no longer created. AF3 is installed separately via `install_af3`,
    #  ESMFold2 via `install_esmfold2`.)

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

    # Create conda env (gcc needed for Triton JIT compilation used by deepspeed)
    #
    # env_exists guard so a re-run after a mid-install network failure resumes rather
    # than aborting here — every remaining step in this function is network-bound.
    # Mirrors install.sh. Use --force to rebuild from scratch.
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
                gcc_linux-aarch64 gxx_linux-aarch64 -c conda-forge \
            || { print_fail "Failed to create binderscout_pxdesign env"; return 1; }
    fi

    # aarch64: install PyTorch from PyPI with cu130 index (no conda pytorch-cuda for aarch64)
    run_logged "Installing PyTorch (aarch64, CUDA 13.0)" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install torch --index-url https://download.pytorch.org/whl/cu130 \
        || { print_fail "Failed to install PyTorch"; return 1; }

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
    run_logged "Reinstalling PyTorch with CUDA 13.0 (aarch64)" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install torch --force-reinstall --index-url https://download.pytorch.org/whl/cu130 \
        || print_warn "PyTorch CUDA reinstall failed — GPU may not work"

    # ColabDesign from GitHub (PyPI version 1.1.1 too old, missing 'weights' param)
    run_logged "Installing ColabDesign from GitHub" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install --no-cache-dir "git+https://github.com/sokrypton/ColabDesign.git" \
        || print_warn "ColabDesign install failed — AF2 eval may not work"

    # Pin JAX <=0.4.34 here (PXDesign's ColabDesign path; BindCraft itself now
    # uses 0.6.2 -- see the sm_121 note in install_bindcraft)
    run_logged "Pinning JAX for ColabDesign compatibility" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install -q "jax<=0.4.34" "jaxlib<=0.4.34" \
        || print_warn "JAX pin failed — AF2 eval may not work"

    # Upgrade deepspeed for PyTorch 2.10+ compatibility (torch.amp.custom_fwd changes)
    run_logged "Upgrading deepspeed" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install -q "deepspeed>=0.18" \
        || print_warn "deepspeed upgrade failed"

    # Pin dm-haiku + JAX (haiku 0.0.12 is last to support jax.core.JaxprEqn)
    run_logged "Pinning dm-haiku and JAX versions" \
        "${CONDA_CMD}" run -n binderscout_pxdesign \
        pip install -q "dm-haiku==0.0.12" "jax==0.4.35" "jaxlib==0.4.35" \
        || print_warn "dm-haiku/JAX pin failed"

    # ── Post-install patches for known upstream issues ──────────────────────
    print_step "Applying PXDesign compatibility patches (aarch64)"

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

    # Patch: pxdbench AF2 eval must not use bf16 on aarch64.
    # The AF2 eval runs under JAX_PLATFORMS=cpu here (the JAX CUDA backend is
    # unusable for this tool's pinned jax), and jaxlib's *AArch64* backend cannot
    # lower a bf16 convert under SVE.  ColabDesign defaults use_bfloat16=True, so
    # the eval subprocess aborts (SIGABRT) with
    #     LLVM ERROR: Cannot select: nxv4bf16 = AArch64ISD::UINT_TO_FP_MERGE_PASSTHRU
    # and pxdbench then reads the empty output file and dies on a JSONDecodeError
    # that says nothing about the real cause.  Bisected on BM5: bf16 on = abort,
    # bf16 off = AF2 completes on CPU in 89 s.  x86 is unaffected, so this patch
    # lives only in the aarch64 installer.
    run_logged "Patching pxdbench AF2 eval (no bf16 on aarch64)" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python << 'PATCHEOF'
import importlib.util, pathlib, re
spec = importlib.util.find_spec('pxdbench')
if not spec or not spec.submodule_search_locations:
    print('pxdbench not found - skipping'); raise SystemExit(0)
base = pathlib.Path(spec.submodule_search_locations[0]) / 'tools' / 'af2'
for fn in ('main_af2_complex.py', 'main_af2_monomer.py'):
    fp = base / fn
    if not fp.exists():
        print(f'{fn} not found - skipping'); continue
    t = fp.read_text()
    if 'use_bfloat16' in t:
        print(f'Already patched: {fn}'); continue
    t2, n = re.subn(r'(prediction_model = mk_afdesign_model\(\n)',
                    r'\1        use_bfloat16=False,\n', t, count=1)
    if not n:
        print(f'Anchor not found in {fn} - skipping'); continue
    fp.write_text(t2); print(f'Patched {fn} (use_bfloat16=False)')
PATCHEOF

    # Patch: protenix torch_ext_compile.py.  TWO independent fixes, and they are
    # applied independently on purpose -- an env patched by an older installer has
    # the arch fix but not the C++ one, and a single "already patched" guard would
    # skip the second one forever.
    #   1. arch: CUDA 13 dropped sm_70, and Blackwell needs sm_120.  sm_120 cubin
    #      runs on GB10's sm_121 (minor-version compatibility), so one gencode is
    #      enough -- verified by a fused-kernel run on this box.
    #   2. -std=c++17 -> c++20: torch >= 2.9 headers hard-error with
    #      "C++20 or later compatible compiler is required to use PyTorch", so the
    #      extension fails to build against the cu130 torch we install below.
    run_logged "Patching protenix CUDA arch (sm_120) + C++20" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python << 'PATCHEOF'
import importlib.util, pathlib, re
spec = importlib.util.find_spec('protenix')
if not spec or not spec.submodule_search_locations:
    print('protenix not found — skipping'); exit(0)
base = pathlib.Path(spec.submodule_search_locations[0])
fp = base / 'model' / 'layer_norm' / 'torch_ext_compile.py'
if not fp.exists():
    print(f'{fp} not found — skipping'); exit(0)
t = fp.read_text()
orig = t
# Set TORCH_CUDA_ARCH_LIST
if 'TORCH_CUDA_ARCH_LIST' not in t:
    t = t.replace(
        'def compile(name, sources, extra_include_paths, build_directory):',
        'def compile(name, sources, extra_include_paths, build_directory):\n'
        '    os.environ["TORCH_CUDA_ARCH_LIST"] = "12.0"'
    )
# Replace all gencode lines with sm_120 only
if 'compute_120' not in t:
    t = re.sub(
        r'(\s*"-gencode",\s*"arch=compute_\d+,code=sm_\d+",?\s*\n?)+',
        '            "-gencode",\n            "arch=compute_120,code=sm_120",\n',
        t
    )
# torch >= 2.9 requires C++20; protenix hardcodes c++17.
t = t.replace('"-std=c++17"', '"-std=c++20"')
if t == orig:
    print('Already patched'); exit(0)
fp.write_text(t)
# Stale objects were built against the old torch ABI -- drop them or the rebuild
# links against headers it no longer matches.
for stale in list(fp.parent.glob('*.so')) + list(fp.parent.glob('*.o')) + \
             list(fp.parent.glob('build.ninja')) + list(fp.parent.glob('.ninja_*')):
    stale.unlink()
print('Patched torch_ext_compile.py (sm_120 + C++20); cleared stale build artifacts')
PATCHEOF

    # Download weights if script exists
    if [[ -f "${PXDESIGN_DIR}/download_tool_weights.sh" ]]; then
        run_logged "Downloading PXDesign weights" \
            bash -c "cd '${PXDESIGN_DIR}' && bash download_tool_weights.sh" \
            || print_warn "PXDesign weights download failed — download manually later"
    else
        print_warn "No download_tool_weights.sh found — download PXDesign weights manually"
    fi

    # Smoke test
    smoke_test "PXDesign import check" \
        "${CONDA_CMD}" run -n binderscout_pxdesign python -c "import torch; print('PXDesign env OK')" \
        || return 1

    # Shortcut
    mkdir -p "${SHORTCUTS_DIR}"
    cat > "${SHORTCUTS_DIR}/pxdesign" << PXDEOF
#!/bin/bash
# BinderScout PXDesign shortcut
# GB10: export the framework ceilings before the shell starts. GENERATED --
# bin/ is gitignored, so a hand-applied guard lives on one disk and any
# reinstall reverts it. This heredoc is UNQUOTED, so paths expand here.
if [[ -r "${BINDERSCOUT_DIR}/tools/gb10-env.sh" ]]; then
    # shellcheck disable=SC1091
    source "${BINDERSCOUT_DIR}/tools/gb10-env.sh"
    gb10_apply pxdesign
fi
exec ${CONDA_CMD} run -n binderscout_pxdesign bash
PXDEOF
    chmod +x "${SHORTCUTS_DIR}/pxdesign"

    print_ok "PXDesign installation complete"
}

# ─── AlphaFold 3 (refolder, opt-in) ─────────────────────────────────────────

install_af3() {
    print_step "Installing AlphaFold 3 v3.0.2 refolder (binder-eval-af3 env)"
    ensure_conda_in_path

    # aarch64 hosts (DGX Spark / GH200) have enough unified memory by design,
    # but warn if we can read VRAM and it's surprisingly small (e.g. CPU-only build host).
    local gpu_mem_mib=""
    if command -v nvidia-smi >/dev/null 2>&1; then
        gpu_mem_mib="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')"
    fi
    # See install.sh: the old <100 GiB warning was preallocation misread as the
    # working set. Measured 4,430 MiB peak for a 258-token complex (RTX 3090).
    if [[ -n "${gpu_mem_mib}" && "${gpu_mem_mib}" -lt 8000 ]]; then
        print_warn "Detected GPU has ${gpu_mem_mib} MiB memory (<8 GiB)."
        print_warn "  AF3 needs ~4.4 GB for a ~260-token complex, more for larger ones."
        print_warn "  Install will proceed — lower AF3_XLA_MEM_FRACTION if refold-af3 OOMs."
    fi

    if [[ ! -d "${EVALUATOR_DIR}" ]]; then
        print_fail "Evaluator directory not found at ${EVALUATOR_DIR}"
        return 1
    fi
    if [[ ! -f "${EVALUATOR_DIR}/envs/binder-eval-af3.yml" ]]; then
        print_fail "Env spec not found at ${EVALUATOR_DIR}/envs/binder-eval-af3.yml"
        return 1
    fi

    print_step "Creating binder-eval-af3 conda environment (Python 3.12)"
    if env_exists binder-eval-af3; then
        print_warn "Conda environment 'binder-eval-af3' already exists — skipping creation."
    else
        run_logged "Creating binder-eval-af3 conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval-af3.yml" -y \
            || { print_fail "Failed to create binder-eval-af3 conda env"; return 1; }
    fi

    # Install AlphaFold 3 from source. The "alphafold3" PyPI package is an unrelated
    # stub — the genuine DeepMind AF3 ships only via its repo (source build). Same
    # recipe as install.sh; on aarch64 (GH200 / DGX Spark) pip resolves the aarch64
    # jax[cuda12] wheels. Clone (pinned) -> pip install (jax 0.9.1 + gemmi + C++) ->
    # build_data (CCD chemical_component_sets.pickle, required at import).
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
        || { print_fail "Failed to build/install AlphaFold 3 (jax 0.9.1 + C++ build; check aarch64 jax[cuda12] wheels)"; return 1; }

    run_logged "Building AF3 chemical-component data (build_data)" \
        "${CONDA_CMD}" run -n binder-eval-af3 build_data \
        || { print_fail "Failed to run AF3 build_data (CCD pickle)"; return 1; }

    run_logged "Installing binder-compare into binder-eval-af3" \
        "${CONDA_CMD}" run -n binder-eval-af3 pip install -q -e "${EVALUATOR_DIR}[report]" \
        || { print_fail "Failed to install binder-compare into binder-eval-af3"; return 1; }

    smoke_test "AF3 producer imports (alphafold3 + jax)" \
        "${CONDA_CMD}" run -n binder-eval-af3 python -c "import alphafold3, jax" \
        || { print_fail "AF3 producer import failed — install did not build the real AF3"; return 1; }
    [[ -f "${AF3_DIR}/run_alphafold.py" ]] \
        || { print_fail "AF3 install incomplete: ${AF3_DIR}/run_alphafold.py missing"; return 1; }
    smoke_test "binder-compare refold-af3 --help" \
        "${CONDA_CMD}" run -n binder-eval-af3 binder-compare refold-af3 --help \
        || return 1

    print_step "Installing af3 shortcut"
    _write_af3_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/af3"

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
        echo "CONDA_CMD=\"${CONDA_CMD}\""
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

    run_logged "Installing BindCraft 2 (this compiles biotraj on aarch64)" \
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
        echo "BINDERSCOUT_DIR=\"${BINDERSCOUT_DIR}\""
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

# GB10 (DGX Spark): the GPU pool IS system RAM, so every "fraction of device
# memory" knob is a fraction of the whole machine. JAX's default
# (preallocate=true, MEM_FRACTION=0.75) reserves 91.3 GiB at import -- that is
# the documented hard-reboot path, not an out-of-memory error. BindCraft 2 is
# JAX, so its budget is a RESERVATION, not a ceiling.
#
# This is generated, not hand-applied. The guard used to be edited into this
# file by hand, and a --force reinstall silently reverted it on 2026-09-22,
# leaving BindCraft 2 uncapped on the one box where that reboots the machine.
#
# Two shapes, per tools/gb10-env.sh's header: an interactive env-shell exports
# the framework ceilings with gb10_apply; a wrapper that execs a real job must
# go through gpurun, which is what joins MPS and gets a driver-enforced cap.
GB10_ENV="${BINDERSCOUT_DIR}/tools/gb10-env.sh"
GB10_GPURUN="${BINDERSCOUT_DIR}/tools/gpurun"

if [[ $# -eq 0 ]]; then
    echo "BindCraft 2 (${BINDCRAFT2_DIR})"
    echo "Examples:"
    echo "  bindcraft2 design campaign.json"
    echo "  bindcraft2 design --list-modalities"
    if [[ -r "${GB10_ENV}" ]]; then
        # shellcheck disable=SC1090
        source "${GB10_ENV}"
        gb10_apply bindcraft2
    fi
    exec "${BINDCRAFT2_DIR}/.venv/bin/python" -c 'import subprocess,sys,os; os.execvp("bash",["bash"])'
fi

if [[ -r "${GB10_ENV}" && -x "${GB10_GPURUN}" ]]; then
    # shellcheck disable=SC1090
    GB10_CAP="$(source "${GB10_ENV}"; gb10_budget bindcraft2)"
    if [[ "${GB10_CAP}" =~ ^[0-9]+$ ]]; then
        exec "${GB10_GPURUN}" --cap "${GB10_CAP}" --name bindcraft2 -- \
            "${BINDCRAFT2_DIR}/.venv/bin/bindcraft" "$@"
    fi
    echo "bindcraft2: WARNING -- no usable GB10 budget for bindcraft2; running uncapped." >&2
    echo "            Check tools/gb10-env.sh:gb10_budget." >&2
fi

exec "${BINDCRAFT2_DIR}/.venv/bin/bindcraft" "$@"
EOF
    chmod +x "${SHORTCUTS_DIR}/bindcraft2"
}

# ─── Protein-Hunter (aarch64) ─────────────────────────────────────────────────
# Ported from install.sh with four platform deltas. The one that matters is
# PyRosetta: upstream's `pyrosetta-installer` is a thin wheel downloader whose
# allow-list is ['ubuntu','mac','m1'], so on aarch64 it prints "Could not find
# PyRosetta wheel" and exits 1 -- and even patched it would 404, because the
# release mirror publishes no cxx11thread.serialization flavour for aarch64.
# The graylab CONDA channel does: pyrosetta 2023.11, py310, linux-aarch64,
# build tag PyRosetta4.conda.aarch64.cxx11thread.serialization -- the same
# package install_bindcraft() already uses on this platform, and the same
# serialization flavour PH asks the wheel installer for.
install_protein_hunter() {
    print_step "Installing Protein-Hunter (aarch64)"

    if [[ -d "${PROTEIN_HUNTER_DIR}" ]]; then
        print_ok "Protein-Hunter already cloned at ${PROTEIN_HUNTER_DIR}"
    else
        run_logged "Cloning Protein-Hunter" \
            git clone --depth 50 "${PROTEIN_HUNTER_REPO}" "${PROTEIN_HUNTER_DIR}" \
            || { print_fail "Failed to clone Protein-Hunter"; return 1; }
        git -C "${PROTEIN_HUNTER_DIR}" checkout "${PROTEIN_HUNTER_COMMIT}" --quiet \
            || print_warn "Could not pin Protein-Hunter to ${PROTEIN_HUNTER_COMMIT} — using latest"
    fi

    # PyRosetta goes in the ENV-CREATION solve, not afterwards. It depends on
    # zlib <1.3.0a0, which conda-forge's newer python-3.10 builds conflict with,
    # so adding it later drags python 3.10.21 back to 3.10.14 -- and every pip
    # package built against the first interpreter is then orphaned. numpy is
    # pinned <2 in the same solve: rosetta.so reaches numpy.core, which numpy 2
    # renamed, and boltz_ph pins numpy<2 anyway, so the two agree.
    if env_exists binderscout_protein_hunter; then
        print_warn "Conda environment 'binderscout_protein_hunter' already exists — skipping creation."
        print_warn "  If it predates this installer it may lack PyRosetta; the smoke test below will say."
    else
        print_step "Creating binderscout_protein_hunter conda environment (Python 3.10 + PyRosetta)"
        run_logged "Creating binderscout_protein_hunter env" \
            "${CONDA_CMD}" create -n binderscout_protein_hunter -y \
            python=3.10 pip "numpy<2" pyrosetta \
            -c conda-forge --channel https://conda.graylab.jhu.edu \
            || { print_fail "Failed to create binderscout_protein_hunter env with PyRosetta"; return 1; }
    fi

    # cu130, matching every other torch install on this platform (x86 uses cu121).
    run_logged "Installing PyTorch (CUDA 13.0)" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter \
        pip install -q "torch>=2.2" "torchvision" "torchaudio" --index-url https://download.pytorch.org/whl/cu130 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # pyrosetta-installer is deliberately absent from this list -- see the header.
    # gemmi 0.6.5 has no aarch64 wheel and builds from its sdist here; that is the
    # only source build in the set and it needs a C/C++ toolchain.
    run_logged "Installing Protein-Hunter Python deps (gemmi builds from source)" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter bash -c \
        "cd '${PROTEIN_HUNTER_DIR}' && pip install -q -e './boltz_ph' && pip install -q matplotlib seaborn prody py3Dmol pyyaml ml_collections biopython modelcif jaxtyping pandera logmd==0.1.45" \
        || print_warn "Some Protein-Hunter deps failed — may need manual follow-up"

    # Chai-1 is skipped on aarch64, and skipping costs nothing we use: the
    # Boltz-2 entrypoint (boltz_ph/design.py) never imports chai_lab -- only the
    # chai_ph/ backend does -- and install.sh already treats the step as
    # non-fatal on x86 for the same reason.
    print_warn "Skipping Chai-1 on aarch64 — the Boltz-2 edition does not use it."

    # DAlphaBall is invoked by a hardcoded in-repo path, so the ARM64 binary has
    # to be copied over the x86 one. Only --use_alphafold3_validation needs it.
    local ph_dab="${PROTEIN_HUNTER_DIR}/utils/DAlphaBall.gcc"
    if [[ -f "${BINDERSCOUT_DIR}/tools/aarch64/DAlphaBall.gcc" && -f "${ph_dab}" ]]; then
        [[ -f "${ph_dab}.x86.bak" ]] || cp "${ph_dab}" "${ph_dab}.x86.bak"
        cp "${BINDERSCOUT_DIR}/tools/aarch64/DAlphaBall.gcc" "${ph_dab}" \
            && chmod +x "${ph_dab}" \
            && print_ok "Installed ARM64 DAlphaBall (x86 original kept as .x86.bak)"
    else
        print_warn "No ARM64 DAlphaBall available — --use_alphafold3_validation will not work"
    fi

    local ph_mpnn_dir="${PROTEIN_HUNTER_DIR}/LigandMPNN/model_params"
    if [[ ! -d "${ph_mpnn_dir}" ]] && [[ -f "${PROTEIN_HUNTER_DIR}/LigandMPNN/get_model_params.sh" ]]; then
        run_logged "Downloading LigandMPNN weights (Protein-Hunter)" \
            bash -c "cd '${PROTEIN_HUNTER_DIR}/LigandMPNN' && bash get_model_params.sh ./model_params" \
            || print_warn "LigandMPNN weights download failed — download manually"
    fi

    # design.py aborts at startup with "CCD component ALA not found!" if mols/ is
    # absent, which reads like a bug rather than a missing cache. Mosaic populates
    # the same directory, so on a machine with Mosaic this usually passes already.
    if [[ ! -f "${HOME}/.boltz/mols/ALA.pkl" ]]; then
        print_warn "Boltz-2 cache incomplete (~/.boltz/mols/ALA.pkl missing). Bootstrap it with:"
        echo "    conda run -n binderscout_protein_hunter python -c \"from boltz.main import download_boltz2; from pathlib import Path; download_boltz2(cache=Path.home()/'.boltz')\""
    else
        print_ok "Boltz-2 cache present at ${HOME}/.boltz"
    fi

    # Two smoke tests, because the two halves fail independently: PyRosetta is
    # the platform risk, boltz the dependency risk.
    smoke_test "PyRosetta (aarch64 conda build)" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter python -c \
        "import pyrosetta; print(pyrosetta.version())" \
        || print_warn "PyRosetta import failed — Protein-Hunter design will not run"

    smoke_test "Protein-Hunter import check" \
        "${CONDA_CMD}" run -n binderscout_protein_hunter bash -c \
        "cd '${PROTEIN_HUNTER_DIR}' && python -c 'import boltz; print(\"boltz_ph import OK\")'" \
        || print_warn "Protein-Hunter import failed — env may still work after first-use weight download"

    _write_protein_hunter_shortcut

    print_ok "Protein-Hunter installation complete (aarch64 — UNVALIDATED, please report results)"
    print_ok "  Usage: protein-hunter  (opens env shell)"
    print_ok "         python boltz_ph/design.py --protein_seqs TARGET --num_designs N --name JOBNAME"
}

_write_protein_hunter_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# Protein-Hunter shortcut — activates binderscout_protein_hunter conda env"
        echo "# and opens an interactive shell in the Protein-Hunter directory."
        echo ""
        echo "PROTEIN_HUNTER_DIR=\"${PROTEIN_HUNTER_DIR}\""
        echo "CONDA_CMD=\"${CONDA_CMD}\""
        echo "BINDERSCOUT_DIR=\"${BINDERSCOUT_DIR}\""
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


# GB10 (DGX Spark): the GPU pool IS system RAM, so a framework's default
# "fraction of device memory" is a fraction of the whole machine. This wrapper
# opens an interactive shell, so it exports the ceilings with gb10_apply rather
# than wrapping a command in gpurun -- see tools/gb10-env.sh's header for why
# the two shapes differ. GENERATED: bin/ is gitignored, so a hand-applied guard
# lives on one disk and any reinstall silently reverts it.
if [[ -r "${BINDERSCOUT_DIR}/tools/gb10-env.sh" ]]; then
    # shellcheck disable=SC1091
    source "${BINDERSCOUT_DIR}/tools/gb10-env.sh"
    gb10_apply protein-hunter
fi

exec "${CONDA_CMD}" run --live-stream -n binderscout_protein_hunter bash
EOF
    chmod +x "${SHORTCUTS_DIR}/protein-hunter"
}

install_rfd3() {
    print_step "Installing RFD3 (foundry) — aarch64"
    ensure_conda_in_path

    # NOTE: UNVALIDATED on aarch64 hardware. RFD3 should port cleanly (pure pip, no
    # DGL / SE3-Transformer), which is why the docs claim aarch64 support — but the
    # aarch64 installer had no --tool rfd3 case at all, so that claim was untestable.
    # Kept out of `--tool all` until someone confirms it on a Spark / GH200.
    # Mirrors install.sh's install_rfd3(); the only difference is the CUDA wheel index.
    if env_exists binderscout_rfd3; then
        print_warn "Conda environment 'binderscout_rfd3' already exists — skipping creation."
    else
        run_logged "Creating binderscout_rfd3 env" \
            "${CONDA_CMD}" create -n binderscout_rfd3 -y python=3.12 pip \
            -c conda-forge \
            || { print_fail "Failed to create binderscout_rfd3 env"; return 1; }
    fi

    # cu130 wheels for Blackwell/GB10 (the x86 installer pins cu121).
    run_logged "Installing PyTorch (cu130, aarch64)" \
        "${CONDA_CMD}" run -n binderscout_rfd3 \
        pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    run_logged "Installing rc-foundry[rfd3]==${FOUNDRY_VERSION}" \
        "${CONDA_CMD}" run -n binderscout_rfd3 \
        pip install -q "rc-foundry[rfd3]==${FOUNDRY_VERSION}" \
        || { print_fail "Failed to install rc-foundry"; return 1; }

    run_logged "Installing rc-foundry[mpnn]==${FOUNDRY_VERSION}" \
        "${CONDA_CMD}" run -n binderscout_rfd3 \
        pip install -q "rc-foundry[mpnn]==${FOUNDRY_VERSION}" \
        || print_warn "rc-foundry[mpnn] install failed — MPNN redesign step may not work"

    mkdir -p "${FOUNDRY_WEIGHTS_DIR}"
    if [[ -n "$(ls -A "${FOUNDRY_WEIGHTS_DIR}" 2>/dev/null)" ]]; then
        print_ok "Foundry weights dir already populated at ${FOUNDRY_WEIGHTS_DIR}"
    else
        run_logged "Downloading RFD3 weights (~2.5 GB)" \
            "${CONDA_CMD}" run -n binderscout_rfd3 \
            foundry install rfd3 --checkpoint-dir "${FOUNDRY_WEIGHTS_DIR}" \
            || print_warn "RFD3 weight download failed — retry: conda run -n binderscout_rfd3 foundry install rfd3 --checkpoint-dir ${FOUNDRY_WEIGHTS_DIR}"
    fi

    # ProteinMPNN weights are NOT bundled with rfd3 (foundry install rfd3 fetches only
    # rfd3_latest.ckpt) — the MPNN sequence-design stage needs this ~7 MB file.
    run_logged "Downloading ProteinMPNN weights (~7 MB)" \
        "${CONDA_CMD}" run -n binderscout_rfd3 \
        foundry install proteinmpnn --checkpoint-dir "${FOUNDRY_WEIGHTS_DIR}" \
        || print_warn "ProteinMPNN weight download failed — 'mpnn' will not run until it is fetched"

    smoke_test "RFD3 CLI check" \
        "${CONDA_CMD}" run -n binderscout_rfd3 rfd3 --help \
        || print_warn "rfd3 CLI smoke test failed — env may need foundry weights first"

    _write_rfd3_shortcut

    print_ok "RFD3 installation complete (aarch64 — please report whether it works)"
    print_ok "  Usage: rfd3 design out_dir=./run inputs=config.yaml"
}


_write_rfd3_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# RFD3 shortcut — runs 'rfd3 design ...' in the binderscout_rfd3 env."
        echo "# With no args: opens an interactive env shell."
        echo ""
        echo "CONDA_CMD=\"${CONDA_CMD}\""
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

install_esmfold2() {
    print_step "Installing ESMFold2 refolder (binder-eval-esmfold2 env)"
    ensure_conda_in_path

    if [[ ! -d "${EVALUATOR_DIR}" ]]; then
        print_fail "Evaluator directory not found at ${EVALUATOR_DIR}"
        return 1
    fi
    if [[ ! -f "${EVALUATOR_DIR}/envs/binder-eval-esmfold2.yml" ]]; then
        print_fail "Env spec not found at ${EVALUATOR_DIR}/envs/binder-eval-esmfold2.yml"
        return 1
    fi

    print_step "Creating binder-eval-esmfold2 conda environment"
    if env_exists binder-eval-esmfold2; then
        print_warn "Conda environment 'binder-eval-esmfold2' already exists — skipping creation."
    else
        run_logged "Creating binder-eval-esmfold2 conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval-esmfold2.yml" -y \
            || { print_fail "Failed to create binder-eval-esmfold2 conda env"; return 1; }
    fi

    # NOTE: there is NO `esmfold` PyPI package — this used to pip install one, which
    # either hard-failed or produced an env with no torch, no transformers and no
    # biohub `esm`, so `binder-compare refold-esmfold2` died at import while the
    # --help-only smoke test below still passed. The runtime is transformers'
    # ESMFold2Model + biohub's `esm` SDK (ESMFold2InputBuilder + the ProteinInput /
    # StructurePredictionInput dataclasses) + gemmi for CIF->PDB. refold_esmfold2.py
    # imports exactly these. Kept in sync with install.sh's install_esmfold2().
    run_logged "Installing torch (cu130) into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 \
        pip install -q --index-url https://download.pytorch.org/whl/cu130 torch \
        || { print_fail "Failed to install torch into binder-eval-esmfold2"; return 1; }
    run_logged "Installing transformers + gemmi + safetensors into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 pip install -q 'transformers>=4.50' gemmi safetensors \
        || { print_fail "Failed to install transformers/gemmi/safetensors into binder-eval-esmfold2"; return 1; }
    # biohub/esm: pinned commit per the HuggingFace model card (no PyPI release yet).
    run_logged "Installing biohub esm SDK into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 \
        pip install -q 'esm @ git+https://github.com/Biohub/esm.git@c94ed8d' \
        || { print_fail "Failed to install biohub esm SDK (check network / git access)"; return 1; }

    run_logged "Installing binder-compare into binder-eval-esmfold2" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 pip install -q -e "${EVALUATOR_DIR}[report]" \
        || { print_fail "Failed to install binder-compare into binder-eval-esmfold2"; return 1; }

    smoke_test "binder-compare refold-esmfold2 --help" \
        "${CONDA_CMD}" run -n binder-eval-esmfold2 binder-compare refold-esmfold2 --help \
        || return 1

    print_step "Installing esmfold2 shortcut"
    _write_esmfold2_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/esmfold2"

    echo ""
    print_ok "ESMFold2 weights are open-source and download on first use via the HuggingFace cache."
    print_ok "  Default model: ${BOLD}fast${RESET} (~1 GB)"
    print_ok "  Switch via:    --esmfold2-model full  (larger, MSA-capable; ~3-5 GB)"
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
        echo "CONDA_CMD=\"${CONDA_CMD}\""
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

# ─── Uninstall ─────────────────────────────────────────────────────────────────

uninstall_tool() {
    local tool="${1,,}"
    case "${tool}" in
        bindcraft)
            print_step "Uninstalling BindCraft"
            env_exists BindCraft && run_logged "Removing BindCraft conda env" \
                "${CONDA_CMD}" env remove -n BindCraft -y
            rm -f "${SHORTCUTS_DIR}/bindcraft"
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
        rfd3|foundry)
            print_step "Uninstalling RFD3 (foundry)"
            env_exists binderscout_rfd3 && run_logged "Removing binderscout_rfd3 conda env" \
                "${CONDA_CMD}" env remove -n binderscout_rfd3 -y
            rm -f "${SHORTCUTS_DIR}/rfd3"
            [[ -d "${FOUNDRY_WEIGHTS_DIR}" ]] && { rm -rf "${FOUNDRY_WEIGHTS_DIR}"; print_ok "Removed ${FOUNDRY_WEIGHTS_DIR}"; }
            print_ok "RFD3 uninstalled"
            ;;
        protein-hunter|protein_hunter|phunter)
            print_step "Uninstalling Protein-Hunter"
            env_exists binderscout_protein_hunter && run_logged "Removing binderscout_protein_hunter env" \
                "${CONDA_CMD}" env remove -n binderscout_protein_hunter -y
            rm -f "${SHORTCUTS_DIR}/protein-hunter"
            [[ -d "${PROTEIN_HUNTER_DIR}" ]] && { rm -rf "${PROTEIN_HUNTER_DIR}"; print_ok "Removed ${PROTEIN_HUNTER_DIR}"; }
            print_ok "Protein-Hunter uninstalled"
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
                print_ok "Removed ${_solu_dir}"
            fi
            print_ok "SoluProt solubility screen uninstalled"
            ;;
        *)
            print_fail "Unknown tool: ${tool}"
            return 1
            ;;
    esac
}

# ─── SoluProt (sequence-only solubility screen) — aarch64 enabled ─────────────
#
# SoluProt's pinned environment is unsatisfiable on aarch64 and its external
# tools ship x86-only binaries; this installer works around all four blockers:
#   1. USEARCH (identity feature) — x86 binary, and vsearch can't substitute
#      (nucleotide-only). We compile open-source USEARCH v12 (rcedgar/usearch12,
#      GPLv3, portable C++11, no x86 intrinsics) from source.
#   2. TMHMM (3 of 96 features) — x86-only binary, no source. We use SoluProt's
#      shipped --no_tmhmm model (grad_clf_v1_tc_notmhmm.pkl, ~-0.5% accuracy).
#   3. scikit-learn 0.20.1 — no aarch64 build, and the model pickle won't
#      predict() under any aarch64-available sklearn (0.21/0.22 raise
#      'get_init_raw_predictions'). We pip-build scikit-learn 0.20.4 from source
#      (same minor series as the pickle; <0.23 so sklearn.externals.joblib still
#      imports).
#   4. biopython 1.74 — no aarch64 build; the oldest (1.78) removed Bio.Alphabet
#      that soluprot.py imports. We patch the SoluProt source.
# Validated on DGX Spark: end-to-end agreement r~0.96 / 90% pass-fail vs the x86
# reference output (the residual is the --no_tmhmm model swap).
SOLUPROT_DIR="${EVALUATOR_DIR}/tools/soluprot"
SOLUPROT_ZIP_URL="https://loschmidt.chemi.muni.cz/soluprot/?page=download&f=soluprot.zip"
USEARCH12_REPO="https://github.com/rcedgar/usearch12"

# Patch the downloaded SoluProt source for aarch64: biopython>=1.78 (removed
# Bio.Alphabet/IUPAC) and the USEARCH command spelling (usearch_global).
_patch_soluprot_source() {
    local patch_py
    patch_py="$(mktemp)"
    cat > "${patch_py}" <<'PYEOF'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])
AA = '"ACDEFGHIKLMNPQRSTVWY"'
changed = []
for f in root.rglob("*.py"):
    s = f.read_text(); o = s
    s = s.replace("from Bio.Alphabet.IUPAC import IUPACProtein\n", "")
    s = s.replace("from Bio.Alphabet import IUPAC\n", "")
    s = s.replace("IUPAC.protein.letters", AA)
    s = s.replace("IUPACProtein.letters", AA)
    s = re.sub(r"Seq\(([^,()]+),\s*IUPAC\.protein\)", r"Seq(\1)", s)
    s = s.replace("'-search_global'", "'-usearch_global'")
    if s != o:
        f.write_text(s); changed.append(f.name)
print("[soluprot-patch] " + ("patched: " + ", ".join(sorted(changed)) if changed else "nothing to patch"))
PYEOF
    run_logged "Patching SoluProt source (biopython>=1.78, usearch_global)" \
        "${CONDA_CMD}" run -n binder-eval-soluprot python "${patch_py}" "${SOLUPROT_DIR}"
    local rc=$?
    rm -f "${patch_py}"
    return $rc
}

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

# Compile open-source USEARCH v12 for the identity feature. The bioconda
# usearch 12.0_beta build crashes at startup on aarch64, so we build from
# source (clean on GB10/Grace-Hopper with gcc 13). TMHMM is sidestepped via
# the --no_tmhmm model, so no second binary is needed.
_build_usearch_v12() {
    print_step "Building open-source USEARCH v12 for the identity feature (aarch64)"
    local t
    for t in git make g++ gcc; do
        if ! command -v "${t}" >/dev/null 2>&1; then
            print_warn "USEARCH build needs git + make + gcc/g++ (missing: ${t})."
            print_warn "  Install a toolchain and re-run, or drop a 'usearch.aarch64' binary at ${SOLUPROT_DIR}/usearch.aarch64."
            return 1
        fi
    done
    local src_dir="${SOLUPROT_DIR}/usearch12-src"
    rm -rf "${src_dir}"
    run_logged "Cloning ${USEARCH12_REPO}" \
        git clone --depth 1 "${USEARCH12_REPO}" "${src_dir}" \
        || { print_warn "git clone of ${USEARCH12_REPO} failed"; return 1; }
    # The generated Makefile hardcodes 'ccache g++'; override CC/CXX. -march=native
    # is valid on aarch64 and the source carries no x86 intrinsics. Static link
    # works on Spark; fall back to dynamic if static libs are unavailable.
    if ! run_logged "Compiling usearch12 (static)" \
        make -C "${src_dir}/src" -j"$(nproc)" CC=gcc CXX=g++; then
        print_warn "Static build failed; retrying without -static"
        # NB: the Makefile appends '-static' to LDFLAGS, and a command-line
        # LDFLAGS= override does NOT win against that '+=' here — so strip it
        # from the Makefile directly, then re-link (objects are already built).
        sed -i 's/[[:space:]]*-static//g' "${src_dir}/src/Makefile"
        run_logged "Compiling usearch12 (dynamic)" \
            make -C "${src_dir}/src" -j"$(nproc)" CC=gcc CXX=g++ \
            || { print_warn "USEARCH v12 build failed"; return 1; }
    fi
    if [[ -x "${src_dir}/bin/usearch12" ]]; then
        cp "${src_dir}/bin/usearch12" "${SOLUPROT_DIR}/usearch.aarch64"
        chmod +x "${SOLUPROT_DIR}/usearch.aarch64"
        rm -rf "${src_dir}"
        print_ok "USEARCH v12 built → ${SOLUPROT_DIR}/usearch.aarch64"
        return 0
    fi
    print_warn "USEARCH v12 binary not found after build (${src_dir}/bin/usearch12)"
    return 1
}

install_proteina_complexa() {
    print_step "Installing Proteina-Complexa — aarch64 (GB10 / sm_121)"

    # WHY THIS EXISTS, AND WHAT IS AND IS NOT PROVEN.
    #
    # PC was deprecated here on 2026-07-29 with the reason "no CUDA jaxlib for
    # aarch64". That reason was disproved on 2026-09-18 (96a1f02): the CUDA
    # plugin does exist and gives `backend: gpu` on jax 0.4.29. The REAL blocker
    # was identified there instead -- jax 0.4.x cannot compile an AF2-class graph
    # for sm_121, aborting with `LLVM ERROR: Unsupported rounding mode for
    # conversion`.
    #
    # That blocker is now gone, twice over on this hardware: BindCraft 1 runs AF2
    # on the GPU here on jax[cuda12]==0.6.2 (9c29729), and BindCraft 2 runs on
    # jax-cuda13 0.11.1. PC's AF2 reward IS ColabDesign -- the same library -- so
    # it inherits the same fix. Hence jax 0.6.2 below instead of the jax[cpu]
    # 0.4.29 the manual Blackwell port used.
    #
    # NOT PROVEN: nobody has run this. It is assembled from the documented
    # five-blocker recipe plus the jax that works, and the smoke test at the end
    # is written to FAIL rather than flatter -- it runs a real AF2 forward pass,
    # because this repo has already once declared aarch64 support on the strength
    # of `jax reports gpu` plus a successful import, and been wrong.
    if ! command -v uv &>/dev/null && [[ ! -x "${HOME}/.local/bin/uv" ]]; then
        run_logged "Installing uv" bash -c "curl -fsSL https://astral.sh/uv/install.sh | sh" \
            || { print_fail "uv install failed"; return 1; }
    fi
    local UV="${HOME}/.local/bin/uv"
    command -v uv &>/dev/null && UV="$(command -v uv)"

    if [[ ! -d "${PROTEINA_COMPLEXA_DIR}" ]]; then
        run_logged "Cloning Proteina-Complexa" \
            git clone --depth 50 "${PROTEINA_COMPLEXA_REPO}" "${PROTEINA_COMPLEXA_DIR}" \
            || { print_fail "Clone failed"; return 1; }
        if [[ "${PROTEINA_COMPLEXA_COMMIT}" != "HEAD" ]]; then
            git -C "${PROTEINA_COMPLEXA_DIR}" checkout "${PROTEINA_COMPLEXA_COMMIT}" --quiet \
                || print_warn "Could not pin to ${PROTEINA_COMPLEXA_COMMIT} — using latest"
        fi
    fi

    # Upstream env/build_uv_env.sh is x86/cu126-pinned, so the venv is built here.
    run_logged "Creating uv venv (python 3.12)" \
        bash -c "cd '${PROTEINA_COMPLEXA_DIR}' && '${UV}' venv --python 3.12 .venv" \
        || { print_fail "uv venv failed"; return 1; }

    local PCPIP=("${UV}" pip install --python "${PROTEINA_COMPLEXA_DIR}/.venv/bin/python" -q)

    # Blocker 1: torch. cu126 has no aarch64 build; cu130 is what this box runs.
    run_logged "Installing PyTorch (cu130, aarch64)" \
        "${PCPIP[@]}" torch torchvision --index-url https://download.pytorch.org/whl/cu130 \
        || { print_fail "PyTorch install failed"; return 1; }

    run_logged "Installing Proteina-Complexa (editable)" \
        bash -c "cd '${PROTEINA_COMPLEXA_DIR}' && '${UV}' pip install --python .venv/bin/python -q -e ." \
        || { print_fail "PC editable install failed"; return 1; }

    # Blocker 2: torch_scatter has no aarch64 wheel and needs no compile here --
    # PC's only use is scatter_mean, which torch itself can do. A 2 KB shim beats
    # a source build of the whole package.
    local SHIM="${PROTEINA_COMPLEXA_DIR}/.venv/lib/python3.12/site-packages/torch_scatter.py"
    if [[ ! -f "${SHIM}" ]]; then
        cat > "${SHIM}" <<'SHIMPY'
"""Minimal torch_scatter stand-in — scatter_mean only.

Proteina-Complexa's sole torch_scatter reference is scatter_mean, and the real
package has no aarch64 wheel. torch's own scatter_add_ expresses it exactly, so
this avoids a source build of a CUDA extension for one function.
"""

import torch


def scatter_mean(src, index, dim=0, out=None, dim_size=None):
    if dim_size is None:
        dim_size = int(index.max()) + 1 if index.numel() else 0
    shape = list(src.shape)
    shape[dim] = dim_size
    total = torch.zeros(shape, dtype=src.dtype, device=src.device)
    count = torch.zeros(dim_size, dtype=src.dtype, device=src.device)
    idx = index
    while idx.dim() < src.dim():
        idx = idx.unsqueeze(-1)
    total.scatter_add_(dim, idx.expand_as(src), src)
    count.scatter_add_(0, index, torch.ones_like(index, dtype=src.dtype))
    count = count.clamp(min=1)
    while count.dim() < total.dim():
        count = count.unsqueeze(-1)
    result = total / count
    return result if out is None else out.copy_(result)
SHIMPY
        print_ok "torch_scatter shim written (scatter_mean only)"
    fi

    # Blocker 3, and the whole point of this function: the AF2 reward's JAX.
    # jax[cpu]==0.4.29 was the manual port's answer because 0.4.x cannot compile
    # AF2 for sm_121 at all. 0.6.2 can, and is the version BindCraft 1 uses here.
    run_logged "Installing jax[cuda12]==0.6.2 + colabdesign (AF2 reward)" \
        "${PCPIP[@]}" "jax[cuda12]==0.6.2" git+https://github.com/sokrypton/ColabDesign.git \
        || { print_fail "jax/colabdesign install failed"; return 1; }

    # Blocker 4/5 and the rest of the manual recipe.
    run_logged "Installing biotite 1.6.0 + graphein + atomworks" \
        "${PCPIP[@]}" "biotite==1.6.0" graphein atomworks \
        || print_warn "biotite/graphein/atomworks install failed — some PC paths may not import"

    # THE SMOKE TEST, and it is deliberately narrow.
    #
    # `jax.devices("gpu")` succeeding proves nothing -- that check plus a clean
    # import is exactly what made this repo claim BindCraft ran on aarch64 when it
    # did not. What actually failed on jax 0.4.x was XLA's LOWERING of a bf16
    # conversion for sm_121 ("Unsupported conversion from bf16 to f16" /
    # "Unsupported rounding mode for conversion"), and ColabDesign runs AF2 in
    # bf16 by default. So this compiles and runs a jitted bf16 graph, which
    # exercises that path without needing the ~4 GB of AF2 parameters.
    #
    # It does NOT prove a full AF2 pass, let alone throughput. Both remain to be
    # confirmed on the box -- see the closing note.
    print_step "Smoke test: compiling a jitted bf16 graph on this GPU"
    if "${PROTEINA_COMPLEXA_DIR}/.venv/bin/python" - <<'SMOKE'
import sys

import jax
import jax.numpy as jnp

print(f"  jax {jax.__version__} | backend {jax.default_backend()}")
if jax.default_backend() != "gpu":
    print("  FAIL: jax has no GPU backend", file=sys.stderr)
    sys.exit(1)
print(f"  device: {jax.devices()[0]}")


@jax.jit
def _bf16_graph(x):
    # A convert + matmul + reduction in bf16 -- the lowering that aborted on 0.4.x.
    y = x.astype(jnp.bfloat16)
    z = jnp.einsum("ij,jk->ik", y, y.T)
    return jax.nn.softmax(z.astype(jnp.float32), axis=-1).sum()

out = float(_bf16_graph(jnp.ones((128, 128), dtype=jnp.float32)))
print(f"  bf16 graph compiled and ran: {out:.3f}")

try:
    import colabdesign  # noqa: F401

    print("  colabdesign imports")
except Exception as exc:  # pragma: no cover
    print(f"  FAIL: colabdesign does not import: {exc}", file=sys.stderr)
    sys.exit(1)
SMOKE
    then
        print_ok "bf16 lowering works on this GPU — the jax 0.4.x blocker is gone"
    else
        print_fail "The bf16 graph FAILED to compile — the XLA/LLVM blocker is NOT resolved here."
        print_warn "Do NOT treat PC as operable. Capture the error and reopen docs/plans.md."
        return 1
    fi

    print_ok "Proteina-Complexa installed (aarch64) — UNVALIDATED end-to-end; run a short MCTS to confirm throughput"
}


install_soluprot() {
    print_step "Installing SoluProt 1.0 solubility screen (aarch64 — binder-eval-soluprot env)"
    ensure_conda_in_path

    if [[ ! -d "${EVALUATOR_DIR}" ]]; then
        print_fail "Evaluator directory not found at ${EVALUATOR_DIR}"
        return 1
    fi

    # 1. Create the env imperatively (the pinned soluprot_environment.yml is
    #    unsatisfiable on aarch64). scikit-learn 0.20.4 is built from source so
    #    the 0.20.1 model pickle predicts correctly; numpy is held at 1.17.5
    #    (build-compatible with that sklearn) across the runtime-dep install.
    # Treat the env as ready only if it imports the full SoluProt stack; an
    # interrupted earlier run can leave the env created but without sklearn /
    # biopython, which the bare env_exists check would wrongly skip past.
    if env_exists binder-eval-soluprot \
        && "${CONDA_CMD}" run -n binder-eval-soluprot python -c "import sklearn, Bio, pandas" >/dev/null 2>&1; then
        print_warn "Conda environment 'binder-eval-soluprot' already complete — skipping creation."
    else
        if env_exists binder-eval-soluprot; then
            print_warn "Existing 'binder-eval-soluprot' env is incomplete (interrupted install?) — rebuilding."
            run_logged "Removing incomplete binder-eval-soluprot env" \
                "${CONDA_CMD}" env remove -n binder-eval-soluprot -y || true
        fi
        print_step "Creating binder-eval-soluprot conda env (Python 3.7, aarch64 pins)"
        run_logged "Creating binder-eval-soluprot conda env" \
            "${CONDA_CMD}" create -n binder-eval-soluprot -y -c conda-forge \
            python=3.7 numpy=1.17.5 scipy cython joblib pip \
            || { print_fail "Failed to create binder-eval-soluprot conda env"; return 1; }
        run_logged "Building scikit-learn 0.20.4 from source (matches model pickle)" \
            "${CONDA_CMD}" run -n binder-eval-soluprot \
            pip install --no-build-isolation "scikit-learn==0.20.4" \
            || { print_fail "Failed to build scikit-learn 0.20.4 (needs a C/C++ toolchain)"; return 1; }
        run_logged "Installing SoluProt runtime deps (biopython 1.78, pandas<1.4, blast)" \
            "${CONDA_CMD}" install -n binder-eval-soluprot -y -c conda-forge -c bioconda \
            numpy=1.17.5 "pandas<1.4" biopython=1.78 tqdm blast \
            || { print_fail "Failed to install SoluProt runtime deps"; return 1; }
    fi

    # 2. Fetch and unpack SoluProt's distribution.
    mkdir -p "${SOLUPROT_DIR}"
    local zip_path="${SOLUPROT_DIR}/soluprot.zip"
    if [[ -f "${SOLUPROT_DIR}/soluprot.py" ]]; then
        print_ok "SoluProt distribution already present at ${SOLUPROT_DIR}"
    else
        print_step "Downloading SoluProt 1.0 from Loschmidt Lab"
        if ! run_logged "Downloading soluprot.zip" \
            curl -fsSL -o "${zip_path}" "${SOLUPROT_ZIP_URL}"; then
            print_fail "Failed to download SoluProt from Loschmidt Lab."
            print_warn "  Manual download: https://loschmidt.chemi.muni.cz/soluprot/?page=download"
            print_warn "  Unpack into:     ${SOLUPROT_DIR}"
            return 1
        fi
        if ! run_logged "Unpacking soluprot.zip" \
            unzip -q -o "${zip_path}" -d "${SOLUPROT_DIR}"; then
            print_fail "Failed to unpack soluprot.zip — is 'unzip' installed?"
            return 1
        fi
        local nested
        nested="$(find "${SOLUPROT_DIR}" -mindepth 1 -maxdepth 1 -type d | head -1)"
        if [[ -n "${nested}" ]] && [[ -f "${nested}/soluprot.py" ]]; then
            mv "${nested}"/* "${SOLUPROT_DIR}/"
            rmdir "${nested}" 2>/dev/null || true
        fi
        rm -f "${zip_path}"
    fi

    # 3. Patch SoluProt's source for biopython>=1.78 and the usearch_global
    #    command spelling.
    _patch_soluprot_source || { print_fail "Failed to patch SoluProt source for aarch64"; return 1; }

    # Sanity-check the bundle actually contains the model we use (the --help
    # smoke test below loads no model, so verify it here).
    if [[ ! -f "${SOLUPROT_DIR}/data/grad_clf_v1_tc_notmhmm.pkl" ]]; then
        print_fail "SoluProt model missing at ${SOLUPROT_DIR}/data/grad_clf_v1_tc_notmhmm.pkl — incomplete download?"
        return 1
    fi

    # 4. Build USEARCH v12 for the identity feature. SoluProt cannot score
    #    without it (it aborts on a USEARCH failure), so a missing binary is a
    #    hard install failure — the --help smoke test below would NOT catch it
    #    (argparse exits before the USEARCH path runs).
    if _resolve_usearch >/dev/null; then
        print_ok "USEARCH binary present ($(_resolve_usearch))"
    else
        _build_usearch_v12 || true
        if ! _resolve_usearch >/dev/null; then
            print_fail "USEARCH is required for SoluProt's identity feature and could not be built."
            print_warn "  Install a C/C++ toolchain (git make g++) and re-run, or place a 'usearch.aarch64'"
            print_warn "  binary at ${SOLUPROT_DIR}/usearch.aarch64 (or on PATH), then re-run --tool soluprot."
            print_warn "  Source: ${USEARCH12_REPO} (GPLv3)."
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
        print_warn "  Install it with: bash install/install_aarch.sh --tool evaluator   (or --tool all)"
    fi

    # 6. Smoke test: SoluProt's own (patched) entry script imports cleanly here.
    smoke_test "soluprot.py --help" \
        "${CONDA_CMD}" run -n binder-eval-soluprot python "${SOLUPROT_DIR}/soluprot.py" --help \
        || return 1

    # 7. Shortcut.
    print_step "Installing soluprot shortcut"
    _write_soluprot_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/soluprot"

    echo ""
    print_ok "SoluProt (aarch64) ready: scikit-learn 0.20.4 (source build), biopython 1.78 (patched), --no_tmhmm model"
    print_ok "  Citation:  Hon et al. 2021, Bioinformatics 37(1):23-28 | License: academic (commercial via Enantis)"
    print_ok "  USEARCH:   open-source v12 ${USEARCH12_REPO} (GPLv3) | Threshold: 0.5 (paper default)"
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
        echo "CONDA_CMD=\"${CONDA_CMD}\""
        echo "export SOLUPROT_HOME=\"${SOLUPROT_DIR}\""
    } > "${SHORTCUTS_DIR}/soluprot"
    cat >> "${SHORTCUTS_DIR}/soluprot" << 'SOLUPROTEOF'
SOLUPROT_PYTHON="$("${CONDA_CMD}" run -n binder-eval-soluprot python -c 'import sys; print(sys.executable)' 2>/dev/null)"
export SOLUPROT_PYTHON

if [[ $# -eq 0 ]]; then
    echo "SoluProt: binder-compare runs in 'binder-eval'; soluprot.py runs in 'binder-eval-soluprot'."
    echo "Usage:"
    echo "  soluprot --sequences seqs.fasta -o soluprot.csv [--threshold 0.5]"
    echo "  (aarch64: uses the --no_tmhmm model + open-source USEARCH v12 automatically.)"
    exec "${CONDA_CMD}" run --live-stream -n binder-eval-soluprot bash
fi
exec "${CONDA_CMD}" run --live-stream -n binder-eval binder-compare filter-soluprot "$@"
SOLUPROTEOF
    chmod +x "${SHORTCUTS_DIR}/soluprot"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

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
    [[ "${DO_BINDCRAFT2}" == true ]]        && need=$(( need + 12 ))  # jax+cuda wheels; AF2 params reused
    [[ "${DO_PROTEIN_HUNTER}" == true ]]    && need=$(( need + 14 ))  # torch + vendored Boltz-2 + PyRosetta (1.5 GB conda pkg)
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
    echo -e "${BOLD}=== BinderScout Installer — DGX Spark (aarch64) — $(date) ===${RESET}"
    echo -e "Platform: ${ARCH} | CUDA: ${CUDA_VERSION} | Standalone: ${STANDALONE}"

    check_arch
    detect_conda || exit 1
    local _name _ver
    _name="$(basename "${CONDA_CMD}")"; _ver="$("${CONDA_CMD}" --version 2>/dev/null | awk '{print $2}')"
    print_ok "${_name} ${_ver} at: ${CONDA_BASE}"
    if [[ "${CONDA_BASE}" == "${LOCAL_CONDA_DIR}" ]]; then
        print_ok "Standalone mode — all environments local to ${BINDERSCOUT_DIR}"
    fi
    check_tools_dir

    print_tool_status

    if [[ "${TOOL_SPECIFIED}" == false ]]; then
        if [[ "${UNINSTALL_MODE}" == true ]]; then
            print_fail "--uninstall requires --tool <tool|all>"
            exit 1
        fi
        select_tools_interactive
    fi

    # Preflight runs after tool selection (so the disk estimate matches the choice)
    # and before any download. Uninstall skips it — it frees space, not consumes it.
    if [[ "${UNINSTALL_MODE}" != true ]]; then
        preflight || exit 1
    fi

    # ── Uninstall mode ───────────────────────────────────────────────────────
    if [[ "${UNINSTALL_MODE}" == true ]]; then
        echo ""
        echo -e "${BOLD}=== Uninstall Mode ===${RESET}"
        echo -e "This removes conda envs, venvs, and shortcuts."
        echo -e "User data (runs/, configs, logs) is ${GREEN}preserved${RESET}."
        confirm "Proceed with uninstall?" || { echo "Aborted."; exit 0; }

        # `--tool all` means "everything installed" when uninstalling. The install-side
        # `all` deliberately omits AF3 (gated weights) and SoluProt (opt-in screen), so
        # without this their envs — plus alphafold3/ and Evaluator/tools/soluprot —
        # survived an "uninstall everything" and the script still said it was complete.
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
        # NOTE: RFD3 has no line here, so `--uninstall --tool all` leaves it on
        # disk on this platform. Pre-existing; flagged rather than fixed here.
        [[ "${DO_BINDCRAFT2}" == true ]] && { uninstall_tool bindcraft2 || failed_uninstalls+=("BindCraft 2"); }
        [[ "${DO_PROTEIN_HUNTER}" == true ]] && { uninstall_tool protein-hunter || failed_uninstalls+=("Protein-Hunter"); }
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
    [[ "${DO_RFD3}"      == true ]] && (( total++ ))
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && (( total++ ))
    [[ "${DO_BINDCRAFT2}" == true ]] && (( total++ ))
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && (( total++ ))
    [[ "${DO_AF3}"       == true ]] && (( total++ ))
    [[ "${DO_ESMFOLD2}"  == true ]] && (( total++ ))
    [[ "${DO_SOLUPROT}"  == true ]] && (( total++ ))

    local failed_tools=()
    FAILED_EXAMPLES=()   # populated by install functions on example failure

    [[ "${DO_BINDCRAFT}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BindCraft${RESET}"; install_bindcraft || failed_tools+=("BindCraft"); }
    [[ "${DO_BOLTZGEN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BoltzGen${RESET}";  install_boltzgen  || failed_tools+=("BoltzGen");  }
    [[ "${DO_MOSAIC}"    == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Mosaic${RESET}";    install_mosaic    || failed_tools+=("Mosaic");    }
    [[ "${DO_EVALUATOR}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Evaluator${RESET}"; install_evaluator || failed_tools+=("Evaluator"); }
    [[ "${DO_PXDESIGN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] PXDesign${RESET}";  install_pxdesign  || failed_tools+=("PXDesign"); }
    [[ "${DO_RFD3}"      == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] RFD3${RESET}"; install_rfd3 || failed_tools+=("RFD3"); }
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Proteina-Complexa${RESET}"; install_proteina_complexa || failed_tools+=("Proteina-Complexa"); }
    # Opt-in on this platform, so an unresolvable source is always a hard failure:
    # nothing reaches this line without an explicit --tool bindcraft2.
    [[ "${DO_BINDCRAFT2}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BindCraft 2${RESET}"; install_bindcraft2 || failed_tools+=("BindCraft 2"); }
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Protein-Hunter${RESET}"; install_protein_hunter || failed_tools+=("Protein-Hunter"); }
    [[ "${DO_AF3}"       == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] AlphaFold 3${RESET}"; install_af3 || failed_tools+=("AF3"); }
    [[ "${DO_ESMFOLD2}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] ESMFold2${RESET}"; install_esmfold2 || failed_tools+=("ESMFold2"); }
    [[ "${DO_SOLUPROT}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] SoluProt 1.0${RESET}"; install_soluprot || failed_tools+=("SoluProt"); }

    echo ""
    echo -e "${BOLD}=== Installation Summary ===${RESET}"

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
    [[ "${DO_PXDESIGN}"  == true ]] && echo -e "  ${GREEN}pxdesign${RESET}   — open PXDesign shell"
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
