#!/bin/bash
# BindMaster Installer — DGX Spark (aarch64) Edition
# Platform: NVIDIA DGX Spark (GB10 Blackwell), aarch64, CUDA 13.0, Ubuntu 24.04
#
# BindCraft, BoltzGen, and Mosaic are cloned from upstream on first install
# (same as x86_64). Pre-cached resources (AF2 weights, ARM64 binaries) are
# read from TOOLS_DIR to avoid redundant downloads.
#
# Usage:
#   bash install/install_aarch.sh [--tool bindcraft|boltzgen|mosaic|evaluator|rfaa|pxdesign|all] [--tools-dir PATH] [--skip-examples]
#
# --tools-dir: path to pre-cached resources. Defaults to the sibling
#              Documents/OLD/BindMaster/bindcraft-tools directory.

# ─── Constants ────────────────────────────────────────────────────────────────
BINDMASTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHORTCUTS_DIR="${BINDMASTER_DIR}/bin"
LOCAL_CONDA_DIR="${BINDMASTER_DIR}/conda"
LOG_FILE="${BINDMASTER_DIR}/install_aarch.log"

BINDCRAFT_DIR="${BINDMASTER_DIR}/BindCraft"
BOLTZGEN_DIR="${BINDMASTER_DIR}/BoltzGen"
MOSAIC_DIR="${BINDMASTER_DIR}/Mosaic"
EVALUATOR_DIR="${BINDMASTER_DIR}/Evaluator"

# Pinned commits for reproducible installs (same as x86_64)
BINDCRAFT_COMMIT="828fd9f"
BOLTZGEN_COMMIT="da0f092"
MOSAIC_COMMIT="dc9c4d7"

RFAA_REPO="https://github.com/baker-laboratory/rf_diffusion_all_atom.git"
RFAA_DIR="${BINDMASTER_DIR}/rf_diffusion_all_atom"
LIGANDMPNN_REPO="https://github.com/dauparas/LigandMPNN.git"
LIGANDMPNN_DIR="${BINDMASTER_DIR}/LigandMPNN"
PXDESIGN_REPO="https://github.com/bytedance/PXDesign.git"
PXDESIGN_COMMIT="HEAD"
PXDESIGN_DIR="${BINDMASTER_DIR}/PXDesign"

ARCH="$(uname -m)"     # expected: aarch64
CUDA_VERSION="13.0"    # DGX Spark GB10 (Blackwell, sm_121)

# Pre-cached resources: two levels up → Documents/OLD/BindMaster/bindcraft-tools
_default_tools="$(cd "${BINDMASTER_DIR}" && cd ../../Documents/OLD/BindMaster/bindcraft-tools 2>/dev/null && pwd || true)"
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
UNINSTALL_MODE=false
TOOL_SPECIFIED=false   # set to true when --tool is passed on CLI
STANDALONE="auto"      # auto | true | false — controls local Miniforge install

# Per-tool install flags (set by arg parsing or interactive menu)
DO_BINDCRAFT=false
DO_BOLTZGEN=false
DO_MOSAIC=false
DO_EVALUATOR=false
DO_RFAA=false
DO_PXDESIGN=false

# ─── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tool)
            TOOL_SPECIFIED=true
            case "${2,,}" in
                all)
                    DO_BINDCRAFT=true; DO_BOLTZGEN=true; DO_MOSAIC=true; DO_EVALUATOR=true; DO_RFAA=true; DO_PXDESIGN=true ;;
                bindcraft)
                    DO_BINDCRAFT=true ;;
                boltzgen)
                    DO_BOLTZGEN=true ;;
                mosaic)
                    DO_MOSAIC=true ;;
                evaluator)
                    DO_EVALUATOR=true ;;
                rfaa)
                    DO_RFAA=true ;;
                pxdesign)
                    DO_PXDESIGN=true ;;
                *)
                    echo -e "${RED}Invalid --tool value: $2. Must be one of: all, bindcraft, boltzgen, mosaic, evaluator, rfaa, pxdesign${RESET}"
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
        --skip-examples)
            SKIP_EXAMPLES=true
            shift
            ;;
        --yes|-y)
            AUTO_YES=true
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
Usage: $0 [--tool all|bindcraft|boltzgen|mosaic|evaluator|rfaa|pxdesign] [--tools-dir PATH] [--cuda VERSION] [--skip-examples] [--yes]
       $0 --uninstall --tool <tool|all> [--yes]

DGX Spark (aarch64) edition. CUDA ${CUDA_VERSION}. Tools are cloned from upstream on first install.

  --tool        Which tool(s) to install (or uninstall). Omit for interactive selection.
  --tools-dir   Path to pre-cached resources (AF2 weights, ARM64 binaries).
                Default: <repo>/../../OLD/BindMaster/bindcraft-tools
  --cuda        CUDA version (default: 13.0). Only 13.0 has been tested on DGX Spark (GB10).
  --skip-examples
                Do not prompt to run bundled examples after install.
  --yes, -y     Auto-confirm all prompts (useful for non-interactive/CI runs).
  --standalone  Force local Miniforge3 install into BindMaster/conda/ (server-friendly).
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
mkdir -p "${BINDMASTER_DIR}"
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

# confirm <prompt>
# Returns 0 (yes) or 1 (no).
confirm() {
    local prompt="${1:-Are you sure?}"
    if [[ "${AUTO_YES}" == true ]]; then
        echo -e "${YELLOW}${prompt} [y/N]: ${RESET}y (auto-yes)"
        return 0
    fi
    while true; do
        read -rp "$(echo -e "${YELLOW}${prompt} [y/N]: ${RESET}")" answer
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no|"") return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
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

# env_exists <name>
# Returns 0 if conda env exists, 1 otherwise.
env_exists() {
    "${CONDA_CMD}" env list | grep -qw "$1"
}

# ensure_conda_in_path
ensure_conda_in_path() {
    export PATH="${CONDA_BASE}/bin:${PATH}"
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
}

# install_local_conda
# Downloads and installs Miniforge3 into LOCAL_CONDA_DIR (BindMaster/conda/).
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

is_rfaa_installed() {
    [[ -d "${RFAA_DIR}" ]] && env_exists bindmaster_rfaa
}

is_pxdesign_installed() {
    [[ -d "${PXDESIGN_DIR}" ]] && env_exists bindmaster_pxdesign
}

# print_tool_status
# Shows installed/not-installed for each tool.
print_tool_status() {
    echo ""
    echo -e "${BOLD}=== Installed Tools ===${RESET}"
    local _status _icon
    for _tool in BindCraft BoltzGen Mosaic Evaluator RFAA PXDesign; do
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
    local sel_rfaa=false
    local sel_pxd=false

    local tools=("BindCraft" "BoltzGen" "Mosaic" "Evaluator" "RFAA" "PXDesign")
    local descs=(
        "Binder design via AlphaFold2 (conda, Python 3.10)"
        "Structure generation with Boltz-1 (conda, Python 3.12)"
        "JAX-based protein design with Marimo notebooks (uv venv)"
        "Evaluate binders: refold with Boltz-2 + AF2, ranked report (requires Mosaic)"
        "All-atom diffusion + LigandMPNN (${RED}NOT SUPPORTED on aarch64${RESET} — DGL lacks CUDA)"
        "Protenix-based de novo binder design (conda)"
    )

    # Check current install state once (avoid repeated conda calls in the loop)
    local inst_bc inst_bg inst_mo inst_ev inst_rfaa inst_pxd
    is_bindcraft_installed && inst_bc="${GREEN}installed${RESET}" || inst_bc="${YELLOW}not installed${RESET}"
    is_boltzgen_installed  && inst_bg="${GREEN}installed${RESET}" || inst_bg="${YELLOW}not installed${RESET}"
    is_mosaic_installed    && inst_mo="${GREEN}installed${RESET}" || inst_mo="${YELLOW}not installed${RESET}"
    is_evaluator_installed && inst_ev="${GREEN}installed${RESET}" || inst_ev="${YELLOW}not installed${RESET}"
    is_rfaa_installed      && inst_rfaa="${GREEN}installed${RESET}" || inst_rfaa="${YELLOW}not installed${RESET}"
    is_pxdesign_installed  && inst_pxd="${GREEN}installed${RESET}" || inst_pxd="${YELLOW}not installed${RESET}"
    local inst_states=("$inst_bc" "$inst_bg" "$inst_mo" "$inst_ev" "$inst_rfaa" "$inst_pxd")

    # Helper: print current state
    _print_menu() {
        echo ""
        echo -e "${BOLD}${CYAN}  Select tools to install${RESET}"
        echo -e "  Type a number to toggle selection, then press Enter when done."
        echo ""
        local states=("$sel_bc" "$sel_bg" "$sel_mo" "$sel_ev" "$sel_rfaa" "$sel_pxd")
        for i in 0 1 2 3 4 5; do
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
            5) [[ "$sel_rfaa" == true ]] && sel_rfaa=false || sel_rfaa=true ;;
            6) [[ "$sel_pxd" == true ]] && sel_pxd=false || sel_pxd=true ;;
            a) sel_bc=true;  sel_bg=true;  sel_mo=true;  sel_ev=true;  sel_rfaa=true;  sel_pxd=true  ;;
            n) sel_bc=false; sel_bg=false; sel_mo=false; sel_ev=false; sel_rfaa=false; sel_pxd=false ;;
            "")
                # Confirm: at least one must be selected
                if [[ "$sel_bc" == false && "$sel_bg" == false && "$sel_mo" == false && "$sel_ev" == false && "$sel_rfaa" == false && "$sel_pxd" == false ]]; then
                    echo -e "  ${RED}No tools selected. Select at least one.${RESET}"
                    continue
                fi
                break
                ;;
            *) echo -e "  ${RED}Invalid input. Enter 1–6, a, n, or press Enter.${RESET}" ;;
        esac
    done

    DO_BINDCRAFT="$sel_bc"
    DO_BOLTZGEN="$sel_bg"
    DO_MOSAIC="$sel_mo"
    DO_EVALUATOR="$sel_ev"
    DO_RFAA="$sel_rfaa"
    DO_PXDESIGN="$sel_pxd"

    echo ""
    echo -e "  ${BOLD}Installing:${RESET}"
    [[ "$DO_BINDCRAFT" == true ]] && echo -e "    ${GREEN}✓${RESET} BindCraft"
    [[ "$DO_BOLTZGEN"  == true ]] && echo -e "    ${GREEN}✓${RESET} BoltzGen"
    [[ "$DO_MOSAIC"    == true ]] && echo -e "    ${GREEN}✓${RESET} Mosaic"
    [[ "$DO_EVALUATOR" == true ]] && echo -e "    ${GREEN}✓${RESET} Evaluator"
    [[ "$DO_RFAA"      == true ]] && echo -e "    ${GREEN}✓${RESET} RFAA"
    [[ "$DO_PXDESIGN"  == true ]] && echo -e "    ${GREEN}✓${RESET} PXDesign"
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

    local bundled_dir="${BINDMASTER_DIR}/tools/aarch64"

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
        if confirm "Remove and reclone?"; then
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
        local _link_dir="/tmp/bindmaster_bindcraft_bin"
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
        if confirm "Remove and recreate the BindCraft conda environment?"; then
            run_logged "Removing BindCraft conda env" \
                "${CONDA_CMD}" env remove -n BindCraft -y || return 1
        else
            print_warn "Keeping existing env — skipping package installation."
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
    # Pinned to 0.4.34 — tested working on DGX Spark (GH200, CUDA 12.1).
    print_step "Installing JAX 0.4.34 with CUDA 12 plugins (PyPI)"
    run_logged "Installing JAX + CUDA 12 plugins" \
        "${CONDA_CMD}" run -n BindCraft \
        pip install \
            "numpy<2.0.0" \
            "jax==0.4.34" \
            "jax-cuda12-pjrt==0.4.34" \
            "jax-cuda12-plugin==0.4.34" \
            "jaxlib==0.4.34" \
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
        if confirm "Remove and reclone?"; then
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
        if confirm "Remove and recreate the BoltzGen conda environment?"; then
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
        pip install torch --index-url https://download.pytorch.org/whl/cu130 \
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
}

install_mosaic() {
    print_step "Installing Mosaic (aarch64 / CUDA ${CUDA_VERSION})"

    # Clone if missing (matches x86_64 installer behavior)
    print_step "Cloning Mosaic repository"
    if [[ -d "${MOSAIC_DIR}" ]]; then
        print_warn "Directory ${MOSAIC_DIR} already exists."
        if confirm "Remove and reclone?"; then
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

    # Copy BindMaster custom examples into Mosaic/examples/
    local src_examples="${BINDMASTER_DIR}/bindmaster_examples"
    local dst_examples="${MOSAIC_DIR}/examples/bindmaster_examples"
    if [[ -d "${src_examples}" ]]; then
        mkdir -p "${dst_examples}"
        cp -r "${src_examples}/." "${dst_examples}/" 2>/dev/null || true
        rm -f "${dst_examples}/.gitkeep" 2>/dev/null || true
        local count
        count=$(find "${dst_examples}" -maxdepth 1 -type f | wc -l)
        if [[ "${count}" -gt 0 ]]; then
            print_ok "Copied ${count} custom example(s) to ${dst_examples}"
        else
            print_ok "bindmaster_examples/ ready at ${dst_examples} (add your Marimo scripts there)"
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
        print_warn "It should be bundled in the repository. Try re-cloning BindMaster."
        return 1
    fi
    print_ok "Evaluator directory: ${EVALUATOR_DIR}"

    # Install binder-compare into Mosaic venv (Boltz-2 step)
    print_step "Installing binder-compare into Mosaic venv"
    run_logged "pip install binder-compare into Mosaic venv" \
        uv pip install --python "${MOSAIC_VENV}/bin/python" -q -e "${EVALUATOR_DIR}[boltz2]" \
        || { print_fail "Failed to install binder-compare into Mosaic venv"; return 1; }

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

    # binder-eval-af2 conda env (AF2 refolding via ColabDesign)
    print_step "Creating binder-eval-af2 conda environment (Python 3.10)"
    if env_exists binder-eval-af2; then
        print_warn "Conda environment 'binder-eval-af2' already exists — skipping creation."
    else
        run_logged "Creating binder-eval-af2 conda env" \
            "${CONDA_CMD}" env create -f "${EVALUATOR_DIR}/envs/binder-eval-af2.yml" -y \
            || { print_fail "Failed to create binder-eval-af2 conda env"; return 1; }
    fi
    run_logged "Installing ColabDesign + binder-compare into binder-eval-af2" \
        "${CONDA_CMD}" run -n binder-eval-af2 pip install -q "colabdesign @ git+https://github.com/sokrypton/ColabDesign.git" -e "${EVALUATOR_DIR}[af2]" \
        || { print_fail "Failed to install packages into binder-eval-af2"; return 1; }

    # JAX CUDA plugin — ColabDesign/AF2 uses JAX; on aarch64 the default jaxlib is CPU-only.
    run_logged "Installing JAX CUDA plugin into binder-eval-af2" \
        "${CONDA_CMD}" run -n binder-eval-af2 pip install -q "jax[cuda]" \
        || { print_fail "Failed to install JAX CUDA plugin"; return 1; }

    # Smoke test
    smoke_test "binder-compare --help" \
        "${CONDA_CMD}" run -n binder-eval binder-compare --help \
        || return 1

    # Shortcut
    print_step "Installing evaluate shortcut"
    _write_evaluator_shortcut
    print_ok "Shortcut installed at ${SHORTCUTS_DIR}/evaluate"

    print_ok "Evaluator installation complete"
    print_ok "  AF2 weights (~4 GB) must be at \$AF2_DATA_DIR — see Evaluator/docs/pipeline_reference.md"
}

_write_evaluator_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    {
        echo "#!/bin/bash"
        echo "# BindMaster Evaluator shortcut — launches the interactive evaluation wizard."
        echo ""
        echo "EVALUATOR_DIR=\"${EVALUATOR_DIR}\""
    } > "${SHORTCUTS_DIR}/evaluate"
    cat >> "${SHORTCUTS_DIR}/evaluate" << 'EOF'

exec bash "${EVALUATOR_DIR}/run.sh"
EOF
    chmod +x "${SHORTCUTS_DIR}/evaluate"
}

# ─── RFAA + LigandMPNN ──────────────────────────────────────────────────────

install_rfaa() {
    print_warn "RFAA is NOT SUPPORTED on aarch64 (DGL has no CUDA-enabled aarch64 wheels)."
    print_warn "The SE3-Transformer requires DGL CUDA operations which are unavailable on this platform."
    print_warn "RFAA will be installed but will only work for CPU-based tasks (not inference)."
    print_warn "Use x86_64 for full RFAA support."
    echo ""

    print_step "Installing RFDiffusionAA + LigandMPNN (limited — no GPU inference on aarch64)"

    # Clone RFAA
    if [[ -d "${RFAA_DIR}" ]]; then
        print_ok "RFAA already cloned at ${RFAA_DIR}"
    else
        run_logged "Cloning RFAA" \
            git clone "${RFAA_REPO}" "${RFAA_DIR}" \
            || { print_fail "Failed to clone RFAA"; return 1; }
    fi

    # Init submodules
    run_logged "RFAA submodules" \
        bash -c "cd '${RFAA_DIR}' && git submodule init && git submodule update" \
        || print_warn "RFAA submodule init failed (may not have submodules)"

    # Create conda env
    print_step "Creating bindmaster_rfaa conda environment"
    run_logged "Creating bindmaster_rfaa env" \
        "${CONDA_CMD}" create -n bindmaster_rfaa -y python=3.11 \
            gcc_linux-aarch64 gxx_linux-aarch64 -c conda-forge \
        || { print_fail "Failed to create bindmaster_rfaa env"; return 1; }

    # aarch64: install PyTorch from PyPI with cu130 index (no conda pytorch-cuda for aarch64)
    run_logged "Installing PyTorch (aarch64, CUDA 13.0)" \
        "${CONDA_CMD}" run -n bindmaster_rfaa \
        pip install torch --index-url https://download.pytorch.org/whl/cu130 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # Install RFAA dependencies (RFAA is not pip-installable; used via PYTHONPATH)
    run_logged "Installing RFAA dependencies" \
        "${CONDA_CMD}" run -n bindmaster_rfaa \
        pip install -q hydra-core omegaconf icecream scipy numpy pandas tqdm fire assertpy deepdiff opt-einsum e3nn "dgl==1.1.3" "torchdata==0.7.1" prody openbabel-wheel \
        || print_warn "Some RFAA deps failed — may need manual install"

    # Install LigandMPNN
    if [[ -d "${LIGANDMPNN_DIR}" ]]; then
        print_ok "LigandMPNN already cloned at ${LIGANDMPNN_DIR}"
    else
        run_logged "Cloning LigandMPNN" \
            git clone "${LIGANDMPNN_REPO}" "${LIGANDMPNN_DIR}" \
            || { print_fail "Failed to clone LigandMPNN"; return 1; }
    fi

    print_ok "LigandMPNN cloned (used via PYTHONPATH, not pip-installable)"

    # Download LigandMPNN weights
    if [[ -d "${LIGANDMPNN_DIR}/model_params" ]]; then
        print_ok "LigandMPNN weights already present"
    else
        run_logged "Downloading LigandMPNN weights" \
            bash -c "cd '${LIGANDMPNN_DIR}' && bash get_model_params.sh ./model_params" \
            || print_warn "LigandMPNN weights download failed — download manually later"
    fi

    # Download RFAA weights
    local rfaa_weights="${RFAA_DIR}/weights"
    local rfaa_weights_file="${rfaa_weights}/RFDiffusionAA_paper_weights.pt"
    if [[ -f "${rfaa_weights_file}" ]]; then
        print_ok "RFAA weights already present"
    else
        mkdir -p "${rfaa_weights}"
        run_logged "Downloading RFAA weights" \
            wget -q -O "${rfaa_weights_file}" \
            "http://files.ipd.uw.edu/pub/RF-All-Atom/weights/RFDiffusionAA_paper_weights.pt" \
            || print_warn "RFAA weights download failed — retry: wget -O ${rfaa_weights_file} http://files.ipd.uw.edu/pub/RF-All-Atom/weights/RFDiffusionAA_paper_weights.pt"
    fi

    # Smoke test
    smoke_test "RFAA import check" \
        "${CONDA_CMD}" run -n bindmaster_rfaa python -c "import torch; print('RFAA env OK')" \
        || return 1

    # Shortcut
    mkdir -p "${SHORTCUTS_DIR}"
    cat > "${SHORTCUTS_DIR}/rfaa" << RFAAEOF
#!/bin/bash
# BindMaster RFAA shortcut — adds RFAA + LigandMPNN to PYTHONPATH
export PYTHONPATH="${RFAA_DIR}:${LIGANDMPNN_DIR}\${PYTHONPATH:+:\$PYTHONPATH}"
exec ${CONDA_CMD} run -n bindmaster_rfaa bash
RFAAEOF
    chmod +x "${SHORTCUTS_DIR}/rfaa"

    print_ok "RFAA + LigandMPNN installation complete"
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

    # Create conda env
    print_step "Creating bindmaster_pxdesign conda environment"
    run_logged "Creating bindmaster_pxdesign env" \
        "${CONDA_CMD}" create -n bindmaster_pxdesign -y python=3.11 \
        || { print_fail "Failed to create bindmaster_pxdesign env"; return 1; }

    # aarch64: install PyTorch from PyPI with cu130 index (no conda pytorch-cuda for aarch64)
    run_logged "Installing PyTorch (aarch64, CUDA 13.0)" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install torch --index-url https://download.pytorch.org/whl/cu130 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # Install PXDesign
    run_logged "Installing PXDesign (pip)" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign pip install -q -e "${PXDESIGN_DIR}" \
        || { print_fail "Failed to install PXDesign"; return 1; }

    # Install Protenix (PXDesign-specific fork) and PXDesignBench
    run_logged "Installing Protenix (PXDesign fork)" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install --no-cache-dir "git+https://github.com/bytedance/Protenix.git@v0.5.0+pxd" \
        || print_warn "Protenix install failed — PXDesign may not work"

    run_logged "Installing PXDesignBench" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install --no-cache-dir "git+https://github.com/bytedance/PXDesignBench.git@v0.1.2" --no-deps \
        || print_warn "PXDesignBench install failed — PXDesign may not work"

    # PXDesign setup.py has install_requires commented out; install deps from requirements.txt
    if [[ -f "${PXDESIGN_DIR}/requirements.txt" ]]; then
        run_logged "Installing PXDesign requirements" \
            "${CONDA_CMD}" run -n bindmaster_pxdesign pip install -q -r "${PXDESIGN_DIR}/requirements.txt" \
            || print_warn "Some PXDesign deps failed — may need manual install"
    fi
    # click is needed by pxdesign CLI but not in requirements.txt
    run_logged "Installing PXDesign CLI deps" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign pip install -q click \
        || print_warn "Failed to install click — pxdesign CLI may not work"

    # requirements.txt pins torch==2.3.1 (CPU-only from PyPI); reinstall with CUDA
    run_logged "Reinstalling PyTorch with CUDA 13.0 (aarch64)" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install torch --force-reinstall --index-url https://download.pytorch.org/whl/cu130 \
        || print_warn "PyTorch CUDA reinstall failed — GPU may not work"

    # ColabDesign from GitHub (PyPI version 1.1.1 too old, missing 'weights' param)
    run_logged "Installing ColabDesign from GitHub" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install --no-cache-dir "git+https://github.com/sokrypton/ColabDesign.git" \
        || print_warn "ColabDesign install failed — AF2 eval may not work"

    # Pin JAX <=0.4.34 (newer JAX removes jax.lib.xla_bridge, breaks ColabDesign)
    run_logged "Pinning JAX for ColabDesign compatibility" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install -q "jax<=0.4.34" "jaxlib<=0.4.34" \
        || print_warn "JAX pin failed — AF2 eval may not work"

    # Upgrade deepspeed for PyTorch 2.10+ compatibility (torch.amp.custom_fwd changes)
    run_logged "Upgrading deepspeed" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install -q "deepspeed>=0.18" \
        || print_warn "deepspeed upgrade failed"

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
        "${CONDA_CMD}" run -n bindmaster_pxdesign python << 'PATCHEOF'
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

    # Patch: protenix torch_ext_compile.py (CUDA 13 dropped sm_70; Blackwell needs sm_120)
    run_logged "Patching protenix CUDA arch (sm_120 for Blackwell)" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign python << 'PATCHEOF'
import importlib.util, pathlib, re
spec = importlib.util.find_spec('protenix')
if not spec or not spec.submodule_search_locations:
    print('protenix not found — skipping'); exit(0)
base = pathlib.Path(spec.submodule_search_locations[0])
fp = base / 'model' / 'layer_norm' / 'torch_ext_compile.py'
if not fp.exists():
    print(f'{fp} not found — skipping'); exit(0)
t = fp.read_text()
if 'compute_120' in t:
    print('Already patched'); exit(0)
# Set TORCH_CUDA_ARCH_LIST
if 'TORCH_CUDA_ARCH_LIST' not in t:
    t = t.replace(
        'def compile(name, sources, extra_include_paths, build_directory):',
        'def compile(name, sources, extra_include_paths, build_directory):\n'
        '    os.environ["TORCH_CUDA_ARCH_LIST"] = "12.0"'
    )
# Replace all gencode lines with sm_120 only
t = re.sub(
    r'(\s*"-gencode",\s*"arch=compute_\d+,code=sm_\d+",?\s*\n?)+',
    '            "-gencode",\n            "arch=compute_120,code=sm_120",\n',
    t
)
fp.write_text(t)
print('Patched torch_ext_compile.py for sm_120')
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
        "${CONDA_CMD}" run -n bindmaster_pxdesign python -c "import torch; print('PXDesign env OK')" \
        || return 1

    # Shortcut
    mkdir -p "${SHORTCUTS_DIR}"
    cat > "${SHORTCUTS_DIR}/pxdesign" << PXDEOF
#!/bin/bash
# BindMaster PXDesign shortcut
exec ${CONDA_CMD} run -n bindmaster_pxdesign bash
PXDEOF
    chmod +x "${SHORTCUTS_DIR}/pxdesign"

    print_ok "PXDesign installation complete"
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
            env_exists binder-eval-af2 && run_logged "Removing binder-eval-af2 conda env" \
                "${CONDA_CMD}" env remove -n binder-eval-af2 -y
            rm -f "${EVALUATOR_DIR}/envs/mosaic_venv_path"
            rm -f "${SHORTCUTS_DIR}/evaluate"
            print_ok "Evaluator uninstalled"
            ;;
        rfaa)
            print_step "Uninstalling RFAA"
            env_exists bindmaster_rfaa && run_logged "Removing bindmaster_rfaa conda env" \
                "${CONDA_CMD}" env remove -n bindmaster_rfaa -y
            rm -f "${SHORTCUTS_DIR}/rfaa"
            [[ -d "${RFAA_DIR}" ]] && { rm -rf "${RFAA_DIR}"; print_ok "Removed ${RFAA_DIR}"; }
            [[ -d "${LIGANDMPNN_DIR}" ]] && { rm -rf "${LIGANDMPNN_DIR}"; print_ok "Removed ${LIGANDMPNN_DIR}"; }
            print_ok "RFAA uninstalled"
            ;;
        pxdesign)
            print_step "Uninstalling PXDesign"
            env_exists bindmaster_pxdesign && run_logged "Removing bindmaster_pxdesign conda env" \
                "${CONDA_CMD}" env remove -n bindmaster_pxdesign -y
            rm -f "${SHORTCUTS_DIR}/pxdesign"
            [[ -d "${PXDESIGN_DIR}" ]] && { rm -rf "${PXDESIGN_DIR}"; print_ok "Removed ${PXDESIGN_DIR}"; }
            print_ok "PXDesign uninstalled"
            ;;
        *)
            print_fail "Unknown tool: ${tool}"
            return 1
            ;;
    esac
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo -e "${BOLD}=== BindMaster Installer — DGX Spark (aarch64) — $(date) ===${RESET}"
    echo -e "Platform: ${ARCH} | CUDA: ${CUDA_VERSION} | Standalone: ${STANDALONE}"

    check_arch
    detect_conda || exit 1
    local _name _ver
    _name="$(basename "${CONDA_CMD}")"; _ver="$("${CONDA_CMD}" --version 2>/dev/null | awk '{print $2}')"
    print_ok "${_name} ${_ver} at: ${CONDA_BASE}"
    if [[ "${CONDA_BASE}" == "${LOCAL_CONDA_DIR}" ]]; then
        print_ok "Standalone mode — all environments local to ${BINDMASTER_DIR}"
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

    # ── Uninstall mode ───────────────────────────────────────────────────────
    if [[ "${UNINSTALL_MODE}" == true ]]; then
        echo ""
        echo -e "${BOLD}=== Uninstall Mode ===${RESET}"
        echo -e "This removes conda envs, venvs, and shortcuts."
        echo -e "User data (runs/, configs, logs) is ${GREEN}preserved${RESET}."
        confirm "Proceed with uninstall?" || { echo "Aborted."; exit 0; }

        local failed_uninstalls=()
        [[ "${DO_BINDCRAFT}" == true ]] && { uninstall_tool bindcraft  || failed_uninstalls+=("BindCraft"); }
        [[ "${DO_BOLTZGEN}"  == true ]] && { uninstall_tool boltzgen   || failed_uninstalls+=("BoltzGen");  }
        [[ "${DO_MOSAIC}"    == true ]] && { uninstall_tool mosaic     || failed_uninstalls+=("Mosaic");    }
        [[ "${DO_EVALUATOR}" == true ]] && { uninstall_tool evaluator  || failed_uninstalls+=("Evaluator"); }
        [[ "${DO_RFAA}"      == true ]] && { uninstall_tool rfaa      || failed_uninstalls+=("RFAA"); }
        [[ "${DO_PXDESIGN}"  == true ]] && { uninstall_tool pxdesign  || failed_uninstalls+=("PXDesign"); }

        # Offer to remove local Miniforge when all tools are uninstalled
        if [[ "${DO_BINDCRAFT}" == true && "${DO_BOLTZGEN}" == true && \
              "${DO_MOSAIC}" == true && "${DO_EVALUATOR}" == true ]]; then
            if [[ -d "${LOCAL_CONDA_DIR}" ]]; then
                if confirm "Also remove local Miniforge3 installation (${LOCAL_CONDA_DIR})?"; then
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
    [[ "${DO_RFAA}"      == true ]] && (( total++ ))
    [[ "${DO_PXDESIGN}"  == true ]] && (( total++ ))

    local failed_tools=()
    FAILED_EXAMPLES=()   # populated by install functions on example failure

    [[ "${DO_BINDCRAFT}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BindCraft${RESET}"; install_bindcraft || failed_tools+=("BindCraft"); }
    [[ "${DO_BOLTZGEN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BoltzGen${RESET}";  install_boltzgen  || failed_tools+=("BoltzGen");  }
    [[ "${DO_MOSAIC}"    == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Mosaic${RESET}";    install_mosaic    || failed_tools+=("Mosaic");    }
    [[ "${DO_EVALUATOR}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Evaluator${RESET}"; install_evaluator || failed_tools+=("Evaluator"); }
    [[ "${DO_RFAA}"      == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] RFAA${RESET}";      install_rfaa      || failed_tools+=("RFAA"); }
    [[ "${DO_PXDESIGN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] PXDesign${RESET}";  install_pxdesign  || failed_tools+=("PXDesign"); }

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
    [[ "${DO_RFAA}"      == true ]] && echo -e "  ${GREEN}rfaa${RESET}       — open RFAA shell"
    [[ "${DO_PXDESIGN}"  == true ]] && echo -e "  ${GREEN}pxdesign${RESET}   — open PXDesign shell"
    # Add shortcuts dir to PATH in .bashrc (idempotent)
    local path_line="export PATH=\"${SHORTCUTS_DIR}:\$PATH\""
    if ! grep -qF "${SHORTCUTS_DIR}" "${HOME}/.bashrc" 2>/dev/null; then
        echo "" >> "${HOME}/.bashrc"
        echo "# BindMaster shortcuts" >> "${HOME}/.bashrc"
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
