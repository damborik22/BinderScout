#!/bin/bash
# BindMaster Installer
# Installs BindCraft, BoltzGen, Mosaic, RFAA, PXDesign, Proteina-Complexa,
# Protein-Hunter, and/or the Evaluator.
#
# Usage:
#   bash install/install.sh [--tool bindcraft|boltzgen|mosaic|evaluator|rfaa|pxdesign|proteina-complexa|protein-hunter|all] [--cuda VERSION] [--skip-examples] [--yes]
#   bindmaster install [same options]
#
# With no --tool flag, an interactive menu lets you choose which tools to install.

# ─── Constants ────────────────────────────────────────────────────────────────
# BINDMASTER_DIR is the repo root (one level above install/).
BINDMASTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHORTCUTS_DIR="${BINDMASTER_DIR}/bin"
LOCAL_CONDA_DIR="${BINDMASTER_DIR}/conda"
LOG_FILE="${BINDMASTER_DIR}/install.log"

BINDCRAFT_DIR="${BINDMASTER_DIR}/BindCraft"
BOLTZGEN_DIR="${BINDMASTER_DIR}/BoltzGen"
MOSAIC_DIR="${BINDMASTER_DIR}/Mosaic"
EVALUATOR_DIR="${BINDMASTER_DIR}/Evaluator"

# Pinned commits for reproducible installs (x86_64 clones only; aarch64 uses bundled)
BINDCRAFT_COMMIT="7cd4ace"
BOLTZGEN_COMMIT="da0f092"
MOSAIC_COMMIT="0599248"

RFAA_REPO="https://github.com/baker-laboratory/rf_diffusion_all_atom.git"
RFAA_DIR="${BINDMASTER_DIR}/rf_diffusion_all_atom"
LIGANDMPNN_REPO="https://github.com/dauparas/LigandMPNN.git"
LIGANDMPNN_DIR="${BINDMASTER_DIR}/LigandMPNN"
PXDESIGN_REPO="https://github.com/bytedance/PXDesign.git"
PXDESIGN_COMMIT="HEAD"
PXDESIGN_DIR="${BINDMASTER_DIR}/PXDesign"
PROTEINA_COMPLEXA_REPO="https://github.com/NVIDIA-Digital-Bio/proteina-complexa.git"
PROTEINA_COMPLEXA_COMMIT="HEAD"
PROTEINA_COMPLEXA_DIR="${BINDMASTER_DIR}/Proteina-Complexa"
PROTEIN_HUNTER_REPO="https://github.com/yehlincho/Protein-Hunter.git"
PROTEIN_HUNTER_COMMIT="d4bd9515882c2aa81e97f3d3bf7f42247a9fe80c"
PROTEIN_HUNTER_DIR="${BINDMASTER_DIR}/Protein-Hunter"
# RFD3 / Foundry (Baker lab's RFdiffusion3; replaces RFAA).
# Installed from PyPI as rc-foundry — no clone needed. Variables kept for
# documentation + uninstall (FOUNDRY_DIR is cleaned on uninstall if present).
# shellcheck disable=SC2034
FOUNDRY_REPO="https://github.com/RosettaCommons/foundry.git"
FOUNDRY_COMMIT="v0.1.9"
FOUNDRY_DIR="${BINDMASTER_DIR}/Foundry"
FOUNDRY_WEIGHTS_DIR="${BINDMASTER_DIR}/weights/foundry"

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
UNINSTALL_MODE=false
TOOL_SPECIFIED=false   # set to true when --tool is passed on CLI
STANDALONE="auto"      # auto | true | false — controls local Miniforge install

# Per-tool install flags (set by arg parsing or interactive menu)
DO_BINDCRAFT=false
DO_BOLTZGEN=false
DO_MOSAIC=false
DO_EVALUATOR=false
DO_RFAA=false           # legacy — opt-in via --tool rfaa; RFD3 is the default all-atom tool
DO_PXDESIGN=false
DO_PROTEINA_COMPLEXA=false
DO_PROTEIN_HUNTER=false
DO_RFD3=false

# ─── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tool)
            TOOL_SPECIFIED=true
            case "${2,,}" in
                all)
                    # "all" installs current-generation tools. RFAA is legacy
                    # (replaced by RFD3); opt in explicitly with --tool rfaa.
                    DO_BINDCRAFT=true; DO_BOLTZGEN=true; DO_MOSAIC=true; DO_EVALUATOR=true; DO_PXDESIGN=true; DO_PROTEINA_COMPLEXA=true; DO_PROTEIN_HUNTER=true; DO_RFD3=true ;;
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
                rfd3|foundry)
                    DO_RFD3=true ;;
                pxdesign)
                    DO_PXDESIGN=true ;;
                proteina-complexa|proteina_complexa|complexa)
                    DO_PROTEINA_COMPLEXA=true ;;
                protein-hunter|protein_hunter|phunter)
                    DO_PROTEIN_HUNTER=true ;;
                *)
                    echo -e "${RED}Invalid --tool value: $2. Must be one of: all, bindcraft, boltzgen, mosaic, evaluator, rfaa, rfd3, pxdesign, proteina-complexa, protein-hunter${RESET}"
                    exit 1
                    ;;
            esac
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
Usage: $0 [--tool all|bindcraft|boltzgen|mosaic|evaluator|rfaa|pxdesign|proteina-complexa] [--cuda VERSION] [--skip-examples] [--yes]
       $0 --uninstall --tool <tool|all> [--yes]

  --tool        Which tool(s) to install (or uninstall). Omit for interactive selection.
  --cuda        CUDA version for conda package resolution (default: 12.4).
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

# BindMaster standalone: pin envs + pkgs locally
envs_dirs:
  - ${conda_dir}/envs
pkgs_dirs:
  - ${conda_dir}/pkgs
RCEOF
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

is_rfaa_installed() {
    [[ -d "${RFAA_DIR}" ]] && env_exists bindmaster_rfaa
}

is_pxdesign_installed() {
    [[ -d "${PXDESIGN_DIR}" ]] && env_exists bindmaster_pxdesign
}

is_protein_hunter_installed() {
    [[ -d "${PROTEIN_HUNTER_DIR}" ]] && env_exists bindmaster_protein_hunter
}

is_rfd3_installed() {
    env_exists bindmaster_rfd3
}

is_proteina_complexa_installed() {
    [[ -d "${PROTEINA_COMPLEXA_DIR}" ]] && [[ -d "${PROTEINA_COMPLEXA_DIR}/.venv" ]]
}

# print_tool_status
# Shows installed/not-installed for each tool.
print_tool_status() {
    echo ""
    echo -e "${BOLD}=== Installed Tools ===${RESET}"
    local _status _icon
    for _tool in BindCraft BoltzGen Mosaic Evaluator RFAA PXDesign Proteina_Complexa; do
        local _fn="is_${_tool,,}_installed"
        if "${_fn}" 2>/dev/null; then
            _icon="${GREEN}✓${RESET}"; _status="installed"
        else
            _icon="${RED}✗${RESET}"; _status="not installed"
        fi
        local _display="${_tool//_/-}"
        printf "  %b  %-20s  %s\n" "${_icon}" "${_display}" "${_status}"
    done
    echo ""
}

# ─── Interactive Tool Selection ───────────────────────────────────────────────
# Called when no --tool flag was supplied. Displays a toggle menu; sets
# DO_BINDCRAFT / DO_BOLTZGEN / DO_MOSAIC based on user choices.

select_tools_interactive() {
    # Default: current-generation tools selected. RFAA is legacy and not shown
    # here; opt in with `--tool rfaa` on the CLI. RFD3 replaces it in the menu.
    local sel_bc=true
    local sel_bg=true
    local sel_mo=true
    local sel_ev=true
    local sel_rfd3=true
    local sel_pxd=false
    local sel_pc=false
    local sel_ph=false

    local tools=("BindCraft" "BoltzGen" "Mosaic" "Evaluator" "RFD3" "PXDesign" "Proteina-Complexa" "Protein-Hunter")
    local descs=(
        "Binder design via AlphaFold2 (conda, Python 3.10)"
        "Structure generation with Boltz-1 (conda, Python 3.12, ~6 GB download)"
        "JAX-based protein design with Marimo notebooks (uv venv)"
        "Evaluate binders: refold with Boltz-2 (+ Protenix on x86, AF3 on aarch64), ranked report (requires Mosaic)"
        "RFD3 / foundry — all-atom diffusion for protein + ligand + NA binders (conda, replaces RFAA)"
        "Protenix-based de novo binder design (conda)"
        "NVIDIA flow matching + test-time compute binder design (uv venv)"
        "Protein-Hunter — Boltz/Chai hallucination: protein/cyclic/ligand/DNA/RNA binders (conda)"
    )

    # Check current install state once (avoid repeated conda calls in the loop)
    local inst_bc inst_bg inst_mo inst_ev inst_rfd3 inst_pxd inst_pc inst_ph
    is_bindcraft_installed && inst_bc="${GREEN}installed${RESET}" || inst_bc="${YELLOW}not installed${RESET}"
    is_boltzgen_installed  && inst_bg="${GREEN}installed${RESET}" || inst_bg="${YELLOW}not installed${RESET}"
    is_mosaic_installed    && inst_mo="${GREEN}installed${RESET}" || inst_mo="${YELLOW}not installed${RESET}"
    is_evaluator_installed && inst_ev="${GREEN}installed${RESET}" || inst_ev="${YELLOW}not installed${RESET}"
    is_rfd3_installed      && inst_rfd3="${GREEN}installed${RESET}" || inst_rfd3="${YELLOW}not installed${RESET}"
    is_pxdesign_installed  && inst_pxd="${GREEN}installed${RESET}" || inst_pxd="${YELLOW}not installed${RESET}"
    is_proteina_complexa_installed && inst_pc="${GREEN}installed${RESET}" || inst_pc="${YELLOW}not installed${RESET}"
    is_protein_hunter_installed    && inst_ph="${GREEN}installed${RESET}" || inst_ph="${YELLOW}not installed${RESET}"
    local inst_states=("$inst_bc" "$inst_bg" "$inst_mo" "$inst_ev" "$inst_rfd3" "$inst_pxd" "$inst_pc" "$inst_ph")

    # Helper: print current state
    _print_menu() {
        echo ""
        echo -e "${BOLD}${CYAN}  Select tools to install${RESET}"
        echo -e "  Type a number to toggle selection, then press Enter when done."
        echo -e "  ${YELLOW}(note: RFAA is legacy — use ${CYAN}--tool rfaa${RESET}${YELLOW} on the CLI to opt in)${RESET}"
        echo ""
        local states=("$sel_bc" "$sel_bg" "$sel_mo" "$sel_ev" "$sel_rfd3" "$sel_pxd" "$sel_pc" "$sel_ph")
        for i in 0 1 2 3 4 5 6 7; do
            local box
            if [[ "${states[$i]}" == true ]]; then
                box="${GREEN}[x]${RESET}"
            else
                box="${RED}[ ]${RESET}"
            fi
            printf "    %d)  %b  ${BOLD}%-20s${RESET}  %-35b  %s\n" \
                $((i+1)) "$box" "${tools[$i]}" "${inst_states[$i]}" "${descs[$i]}"
        done
        echo ""
        echo -e "  ${YELLOW}a${RESET}) Select all   ${YELLOW}n${RESET}) Select none   ${YELLOW}Enter${RESET} to confirm"
        echo ""
    }

    while true; do
        # Re-print menu on each iteration (scroll-friendly, no tput)
        _print_menu
        read -rp "  > " choice
        case "${choice,,}" in
            1) [[ "$sel_bc" == true ]] && sel_bc=false || sel_bc=true ;;
            2) [[ "$sel_bg" == true ]] && sel_bg=false || sel_bg=true ;;
            3) [[ "$sel_mo" == true ]] && sel_mo=false || sel_mo=true ;;
            4) [[ "$sel_ev" == true ]] && sel_ev=false || sel_ev=true ;;
            5) [[ "$sel_rfd3" == true ]] && sel_rfd3=false || sel_rfd3=true ;;
            6) [[ "$sel_pxd" == true ]] && sel_pxd=false || sel_pxd=true ;;
            7) [[ "$sel_pc" == true ]] && sel_pc=false || sel_pc=true ;;
            8) [[ "$sel_ph" == true ]] && sel_ph=false || sel_ph=true ;;
            a) sel_bc=true;  sel_bg=true;  sel_mo=true;  sel_ev=true;  sel_rfd3=true;  sel_pxd=true;  sel_pc=true;  sel_ph=true  ;;
            n) sel_bc=false; sel_bg=false; sel_mo=false; sel_ev=false; sel_rfd3=false; sel_pxd=false; sel_pc=false; sel_ph=false ;;
            "")
                # Confirm: at least one must be selected
                if [[ "$sel_bc" == false && "$sel_bg" == false && "$sel_mo" == false && "$sel_ev" == false && "$sel_rfd3" == false && "$sel_pxd" == false && "$sel_pc" == false && "$sel_ph" == false ]]; then
                    echo -e "  ${RED}No tools selected. Select at least one.${RESET}"
                    continue
                fi
                break
                ;;
            *) echo -e "  ${RED}Invalid input. Enter 1–8, a, n, or press Enter.${RESET}" ;;
        esac
    done

    DO_BINDCRAFT="$sel_bc"
    DO_BOLTZGEN="$sel_bg"
    DO_MOSAIC="$sel_mo"
    DO_EVALUATOR="$sel_ev"
    DO_RFD3="$sel_rfd3"
    DO_PXDESIGN="$sel_pxd"
    DO_PROTEINA_COMPLEXA="$sel_pc"
    DO_PROTEIN_HUNTER="$sel_ph"

    echo ""
    echo -e "  ${BOLD}Installing:${RESET}"
    [[ "$DO_BINDCRAFT" == true ]] && echo -e "    ${GREEN}✓${RESET} BindCraft"
    [[ "$DO_BOLTZGEN"  == true ]] && echo -e "    ${GREEN}✓${RESET} BoltzGen"
    [[ "$DO_MOSAIC"    == true ]] && echo -e "    ${GREEN}✓${RESET} Mosaic"
    [[ "$DO_EVALUATOR" == true ]] && echo -e "    ${GREEN}✓${RESET} Evaluator"
    [[ "$DO_RFAA"      == true ]] && echo -e "    ${YELLOW}✓ RFAA (legacy)${RESET}"
    [[ "$DO_RFD3"      == true ]] && echo -e "    ${GREEN}✓${RESET} RFD3"
    [[ "$DO_PXDESIGN"  == true ]] && echo -e "    ${GREEN}✓${RESET} PXDesign"
    [[ "$DO_PROTEINA_COMPLEXA" == true ]] && echo -e "    ${GREEN}✓${RESET} Proteina-Complexa"
    [[ "$DO_PROTEIN_HUNTER" == true ]] && echo -e "    ${GREEN}✓${RESET} Protein-Hunter"
    echo ""

    confirm "Proceed with installation?" || { echo "Aborted."; exit 0; }
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

    # Fix Colab paths in target settings
    _fix_target_settings

    # Remove existing conda env if present
    if env_exists BindCraft; then
        print_warn "Conda environment 'BindCraft' already exists."
        if confirm "Remove and recreate the BindCraft conda environment?"; then
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
        run_logged "Installing BindCraft (conda packages + AlphaFold2 weights)" \
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

    # Conda environment
    print_step "Creating BoltzGen conda environment (Python 3.12)"
    if env_exists BoltzGen; then
        print_warn "Conda environment 'BoltzGen' already exists."
        if confirm "Remove and recreate the BoltzGen conda environment?"; then
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
    # aarch64: +cuXXX wheels don't exist; plain PyPI torch includes CUDA for Linux aarch64
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

    # Patch: pin grpcio-tools>=1.60 in override-dependencies.
    # Mosaic 0599248+ pulls flax 0.12.7 → orbax-checkpoint 0.11.37 → grpcio-tools==1.48.2,
    # whose setup.py imports pkg_resources without declaring setuptools as a build dep.
    # uv 0.5+ strict isolation rejects that, so the build fails with ModuleNotFoundError.
    # Forcing a modern grpcio-tools (which declares its build deps correctly) avoids it.
    local mosaic_pyproject="${MOSAIC_DIR}/pyproject.toml"
    if [[ -f "${mosaic_pyproject}" ]] && ! grep -q "grpcio-tools" "${mosaic_pyproject}"; then
        sed -i 's/^\(override-dependencies = \[[^]]*\)\]/\1, "grpcio-tools>=1.60"]/' "${mosaic_pyproject}" \
            && print_ok "Patched Mosaic pyproject.toml: override grpcio-tools>=1.60"
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

    # Copy BindMaster custom examples into Mosaic
    local src_examples="${BINDMASTER_DIR}/bindmaster_examples"
    local dst_examples="${MOSAIC_DIR}/examples/bindmaster_examples"
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
            print_ok "bindmaster_examples/ ready at ${dst_examples} (add your scripts there)"
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

    # (AF2 refolding was removed in the AF3/Protenix refactor; the
    #  binder-eval-af2 env is no longer created. Protenix refolding will
    #  reuse the existing bindmaster_pxdesign env; AF3 refolding lands on
    #  aarch64 only via install_aarch.sh.)

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
    print_step "Installing RFDiffusionAA + LigandMPNN (legacy)"
    print_warn "RFAA is LEGACY in this BindMaster release."
    print_warn "  Upstream has been dormant since 2024-03; Baker lab moved to"
    print_warn "  RFdiffusion3 (now available via --tool rfd3)."
    print_warn "  RFAA is kept for reproducibility of existing runs; see"
    print_warn "  docs/rfaa_manual_reinstall.md for long-term maintenance notes."

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
            "pytorch>=2.2" "pytorch-cuda=12.4" gcc_linux-64 gxx_linux-64 \
            -c pytorch -c nvidia -c conda-forge \
        || { print_fail "Failed to create bindmaster_rfaa env"; return 1; }

    # Install RFAA dependencies (RFAA is not pip-installable; used via PYTHONPATH)
    # DGL must be installed from the CUDA wheel repo — plain PyPI gives CPU-only
    run_logged "Installing RFAA dependencies" \
        "${CONDA_CMD}" run -n bindmaster_rfaa \
        pip install -q hydra-core omegaconf icecream scipy "numpy<2" pandas tqdm fire assertpy deepdiff opt-einsum e3nn ml_collections dm-tree "dgl==1.1.3+cu121" -f https://data.dgl.ai/wheels/cu121/repo.html "torchdata==0.7.1" prody openbabel-wheel \
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

    # ── Post-install patches for known upstream issues ──────────────────────

    # Patch: idealize_backbone.py — handle protein-only designs (0 ligands)
    local idealize="${RFAA_DIR}/idealize_backbone.py"
    if [[ -f "${idealize}" ]] && grep -q "assert len(ligands) == 1" "${idealize}"; then
        sed -i 's/assert len(ligands) == 1.*/ligands = list(ligands)/' "${idealize}"
        sed -i '/ligands = list(ligands)/a\    if len(ligands) == 0:\n        indep.write_pdb(outpath)\n    elif len(ligands) == 1:\n        indep.write_pdb(outpath, lig_name=ligands[0])\n    else:\n        raise ValueError(f"Found >1 ligand: {ligands}")' "${idealize}"
        print_ok "Patched idealize_backbone.py for protein-only designs"
    fi

    # Patch: openfold residue_constants.py — numpy 2.x removed np.int alias
    local resconst="${LIGANDMPNN_DIR}/openfold/np/residue_constants.py"
    if [[ -f "${resconst}" ]] && grep -q "dtype=np.int)" "${resconst}"; then
        sed -i 's/dtype=np\.int)/dtype=np.int64)/g' "${resconst}"
        print_ok "Patched residue_constants.py: np.int → np.int64"
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

    # Create conda env (gcc for Triton JIT, cuda-nvcc for deepspeed CUDA_HOME)
    print_step "Creating bindmaster_pxdesign conda environment"
    run_logged "Creating bindmaster_pxdesign env" \
        "${CONDA_CMD}" create -n bindmaster_pxdesign -y python=3.11 \
            "pytorch>=2.2" "pytorch-cuda=12.4" "gcc_linux-64<14" "gxx_linux-64<14" "cuda-nvcc=12.4" "cuda-cudart-dev=12.4" \
            -c pytorch -c nvidia -c conda-forge \
        || { print_fail "Failed to create bindmaster_pxdesign env"; return 1; }

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
    run_logged "Reinstalling PyTorch with CUDA ${CUDA_VERSION}" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install torch --force-reinstall --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION//./}" \
        || print_warn "PyTorch CUDA reinstall failed — GPU may not work"

    # ColabDesign from GitHub (PyPI version 1.1.1 too old, missing 'weights' param)
    run_logged "Installing ColabDesign from GitHub" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
        pip install --no-cache-dir "git+https://github.com/sokrypton/ColabDesign.git" \
        || print_warn "ColabDesign install failed — AF2 eval may not work"

    # Upgrade deepspeed for PyTorch 2.x compatibility
    run_logged "Upgrading deepspeed" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
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
        "${CONDA_CMD}" run -n bindmaster_pxdesign \
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

    # Patch: MPNN subprocess writes error JSON on failure (prevents JSONDecodeError)
    run_logged "Patching pxdbench MPNN error handling" \
        "${CONDA_CMD}" run -n bindmaster_pxdesign python << 'MPNNEOF'
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
        "${CONDA_CMD}" run -n bindmaster_pxdesign python << 'LAZYEOF'
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
        "${CONDA_CMD}" run -n bindmaster_pxdesign python << 'LNEOF'
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
        "${CONDA_CMD}" install -n bindmaster_pxdesign -c "nvidia/label/cuda-${CUDA_VERSION}.0" \
        libcusparse-dev -y \
        || print_warn "libcusparse-dev install failed — CUDA JIT will use fallback"

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

    # Install binder-compare into the PXDesign env so Protenix refolding
    # (Part J) can run via `conda run -n bindmaster_pxdesign binder-compare refold-protenix`.
    if [[ -d "${EVALUATOR_DIR}" ]]; then
        run_logged "Installing binder-compare into bindmaster_pxdesign (for Protenix refold)" \
            "${CONDA_CMD}" run -n bindmaster_pxdesign pip install -q -e "${EVALUATOR_DIR}[report]" \
            || print_warn "binder-compare install into bindmaster_pxdesign failed — Protenix refolding will be unavailable"
    fi

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

# ─── Proteina-Complexa ────────────────────────────────────────────────────────

# Reuse weights already downloaded by other BindMaster tools (symlinks).
_link_complexa_shared_weights() {
    local cm="${PROTEINA_COMPLEXA_DIR}/community_models"

    # AF2 weights from BindCraft
    if [[ -d "${BINDCRAFT_DIR}/params" ]] && [[ ! -e "${cm}/ckpts/AF2" ]]; then
        mkdir -p "${cm}/ckpts"
        ln -sfn "${BINDCRAFT_DIR}/params" "${cm}/ckpts/AF2"
        print_ok "AF2 weights → BindCraft/params (symlink)"
    elif [[ -d "${BINDMASTER_DIR}/bindcraft-tools/af2_params" ]] && [[ ! -e "${cm}/ckpts/AF2" ]]; then
        mkdir -p "${cm}/ckpts"
        ln -sfn "${BINDMASTER_DIR}/bindcraft-tools/af2_params" "${cm}/ckpts/AF2"
        print_ok "AF2 weights → bindcraft-tools/af2_params (symlink)"
    fi

    # ProteinMPNN ca_model_weights + vanilla_model_weights from PXDesign
    if [[ -d "${PXDESIGN_DIR}/tool_weights/mpnn/ca_model_weights" ]] && [[ ! -e "${cm}/ProteinMPNN/ca_model_weights" ]]; then
        ln -sfn "${PXDESIGN_DIR}/tool_weights/mpnn/ca_model_weights" "${cm}/ProteinMPNN/ca_model_weights"
        ln -sfn "${PXDESIGN_DIR}/tool_weights/mpnn/vanilla_model_weights" "${cm}/ProteinMPNN/vanilla_model_weights"
        print_ok "ProteinMPNN weights → PXDesign/tool_weights/mpnn (symlink)"
    fi

    # LigandMPNN model_params from BindMaster's LigandMPNN install
    local lmpnn_src="${BINDMASTER_DIR}/LigandMPNN/model_params"
    if [[ -d "${lmpnn_src}" ]] && [[ ! -e "${cm}/LigandMPNN/model_params" ]]; then
        ln -sfn "${lmpnn_src}" "${cm}/LigandMPNN/model_params"
        print_ok "LigandMPNN weights → LigandMPNN/model_params (symlink)"
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
        elif [[ -d "${BINDMASTER_DIR}/bindcraft-tools/af2_params" ]]; then
            af2_dir="${BINDMASTER_DIR}/bindcraft-tools/af2_params"
        fi
    fi

    cat > "${env_file}" <<ENVEOF
# BindMaster-generated .env for Proteina-Complexa
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
        if confirm "Remove and reclone?"; then
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

        # Download ALL models (Complexa + community models)
        print_step "Downloading Proteina-Complexa checkpoints & community models"
        run_logged --retries 2 "Downloading all models (complexa download --everything)" \
            bash -c "cd '${PROTEINA_COMPLEXA_DIR}' && .venv/bin/complexa download --everything" \
            || print_warn "Model download failed — download manually with: complexa download --everything"
    else
        print_warn "complexa CLI not found in .venv — skipping init/download"
    fi

    # Reuse existing weights from other BindMaster tools via symlinks
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
# Butcher et al. 2025. BSD-3-Clause. PyPI: `rc-foundry`. Replaces RFAA entirely
# — no DGL, no SE3-Transformer, works on aarch64 / DGX Spark. Weights live
# under BindMaster/weights/foundry.

install_rfd3() {
    print_step "Installing RFD3 (foundry)"

    # Conda env: Py 3.12 + PyTorch 2.2+ (CUDA 12.x)
    if env_exists bindmaster_rfd3; then
        print_warn "Conda environment 'bindmaster_rfd3' already exists — skipping creation."
    else
        run_logged "Creating bindmaster_rfd3 env" \
            "${CONDA_CMD}" create -n bindmaster_rfd3 -y python=3.12 pip \
            -c conda-forge \
            || { print_fail "Failed to create bindmaster_rfd3 env"; return 1; }
    fi

    # PyTorch (CUDA 12.1 wheels — works for 12.1–12.8 host drivers)
    run_logged "Installing PyTorch (CUDA 12.1)" \
        "${CONDA_CMD}" run -n bindmaster_rfd3 \
        pip install -q "torch>=2.2" "torchvision" "torchaudio" --index-url https://download.pytorch.org/whl/cu121 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # foundry + rfd3 extra (PyPI package name is `rc-foundry`)
    run_logged "Installing rc-foundry[rfd3] ${FOUNDRY_COMMIT}" \
        "${CONDA_CMD}" run -n bindmaster_rfd3 \
        pip install -q "rc-foundry[rfd3]==0.1.9" \
        || { print_fail "Failed to install rc-foundry"; return 1; }

    # Also install MPNN extra for post-diffusion sequence design (ProteinMPNN + LigandMPNN)
    run_logged "Installing rc-foundry[mpnn]" \
        "${CONDA_CMD}" run -n bindmaster_rfd3 \
        pip install -q "rc-foundry[mpnn]==0.1.9" \
        || print_warn "rc-foundry[mpnn] install failed — MPNN redesign step may not work"

    # Download RFD3 weights to a shared location inside BindMaster
    mkdir -p "${FOUNDRY_WEIGHTS_DIR}"
    if [[ -n "$(ls -A "${FOUNDRY_WEIGHTS_DIR}" 2>/dev/null)" ]]; then
        print_ok "Foundry weights dir already populated at ${FOUNDRY_WEIGHTS_DIR}"
    else
        run_logged "Downloading RFD3 weights (~few GB)" \
            "${CONDA_CMD}" run -n bindmaster_rfd3 \
            foundry install rfd3 --checkpoint-dir "${FOUNDRY_WEIGHTS_DIR}" \
            || print_warn "RFD3 weight download failed — retry: conda run -n bindmaster_rfd3 foundry install rfd3 --checkpoint-dir ${FOUNDRY_WEIGHTS_DIR}"
    fi

    # Smoke test: rfd3 CLI help
    smoke_test "RFD3 CLI check" \
        "${CONDA_CMD}" run -n bindmaster_rfd3 rfd3 --help \
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
        echo "# RFD3 shortcut — runs 'rfd3 design ...' in the bindmaster_rfd3 env."
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
    echo "RFD3 environment (bindmaster_rfd3). Weights: ${FOUNDRY_WEIGHTS_DIR}"
    echo "Examples:"
    echo "  rfd3 design out_dir=./run inputs=examples/ppi.yaml"
    echo "  foundry list-installed"
    exec "${CONDA_CMD}" run --live-stream -n bindmaster_rfd3 bash
fi

exec "${CONDA_CMD}" run --live-stream -n bindmaster_rfd3 rfd3 "$@"
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
    if env_exists bindmaster_protein_hunter; then
        print_warn "Conda environment 'bindmaster_protein_hunter' already exists — skipping creation."
    else
        print_step "Creating bindmaster_protein_hunter conda environment (Python 3.10)"
        run_logged "Creating bindmaster_protein_hunter env" \
            "${CONDA_CMD}" create -n bindmaster_protein_hunter -y python=3.10 pip \
            -c conda-forge \
            || { print_fail "Failed to create bindmaster_protein_hunter env"; return 1; }
    fi

    # Install PyTorch (matches upstream setup.sh expectations: torch>=2.2 with CUDA)
    run_logged "Installing PyTorch (CUDA 12.1)" \
        "${CONDA_CMD}" run -n bindmaster_protein_hunter \
        pip install -q "torch>=2.2" "torchvision" "torchaudio" --index-url https://download.pytorch.org/whl/cu121 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    # Install vendored Boltz_PH + upstream deps
    run_logged "Installing Protein-Hunter Python deps" \
        "${CONDA_CMD}" run -n bindmaster_protein_hunter bash -c \
        "cd '${PROTEIN_HUNTER_DIR}' && pip install -q -e './boltz_ph' && pip install -q matplotlib seaborn prody py3Dmol pyyaml ml_collections biopython modelcif jaxtyping pandera logmd==0.1.45 pyrosetta-installer" \
        || print_warn "Some Protein-Hunter deps failed — may need manual follow-up"

    # PyRosetta (required by boltz_ph.design at import time)
    # pyrosetta_installer >=0.1.2 renamed download_pyrosetta -> install_pyrosetta.
    run_logged "Installing PyRosetta" \
        "${CONDA_CMD}" run -n bindmaster_protein_hunter python -c \
        "from pyrosetta_installer import install_pyrosetta; install_pyrosetta(serialization=True, skip_if_installed=True)" \
        || print_warn "PyRosetta install failed — Protein-Hunter design will not work until this is fixed"

    # Install chai-lab (from sokrypton fork pinned by Protein-Hunter upstream)
    run_logged "Installing Chai-1 (sokrypton fork)" \
        "${CONDA_CMD}" run -n bindmaster_protein_hunter \
        pip install -q "git+https://github.com/sokrypton/chai-lab.git" \
        || print_warn "chai-lab install failed — only the Boltz-2 edition of Protein-Hunter will work"

    # Weight sharing: reuse LigandMPNN weights from RFAA install if present.
    # Protein-Hunter vendors LigandMPNN source in-repo but expects model_params/ locally.
    local ph_mpnn_dir="${PROTEIN_HUNTER_DIR}/LigandMPNN/model_params"
    if [[ -d "${LIGANDMPNN_DIR}/model_params" && ! -d "${ph_mpnn_dir}" ]]; then
        mkdir -p "$(dirname "${ph_mpnn_dir}")"
        ln -sfn "${LIGANDMPNN_DIR}/model_params" "${ph_mpnn_dir}"
        print_ok "LigandMPNN weights → ${ph_mpnn_dir} (symlink to RFAA install)"
    elif [[ ! -d "${ph_mpnn_dir}" ]]; then
        if [[ -f "${PROTEIN_HUNTER_DIR}/LigandMPNN/get_model_params.sh" ]]; then
            run_logged "Downloading LigandMPNN weights (Protein-Hunter)" \
                bash -c "cd '${PROTEIN_HUNTER_DIR}/LigandMPNN' && bash get_model_params.sh ./model_params" \
                || print_warn "LigandMPNN weights download failed — download manually"
        fi
    fi

    # Boltz-2 weight cache (~/.boltz) — shared with Mosaic if Mosaic populates it first.
    # Protein-Hunter pulls Boltz-2 weights on first run; we don't pre-download here.

    # Smoke test: import boltz_ph package
    smoke_test "Protein-Hunter import check" \
        "${CONDA_CMD}" run -n bindmaster_protein_hunter bash -c \
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
        echo "# Protein-Hunter shortcut — activates bindmaster_protein_hunter conda env"
        echo "# and opens an interactive shell in the Protein-Hunter directory."
        echo ""
        echo "PROTEIN_HUNTER_DIR=\"${PROTEIN_HUNTER_DIR}\""
        echo "CONDA_CMD=\"${CONDA_CMD}\""
    } > "${SHORTCUTS_DIR}/protein-hunter"
    cat >> "${SHORTCUTS_DIR}/protein-hunter" << 'EOF'

cd "${PROTEIN_HUNTER_DIR}"

echo "Protein-Hunter environment (bindmaster_protein_hunter) activated."
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

exec "${CONDA_CMD}" run --live-stream -n bindmaster_protein_hunter bash
EOF
    chmod +x "${SHORTCUTS_DIR}/protein-hunter"
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
            env_exists bindmaster_protein_hunter && run_logged "Removing bindmaster_protein_hunter env" \
                "${CONDA_CMD}" env remove -n bindmaster_protein_hunter -y
            rm -f "${SHORTCUTS_DIR}/protein-hunter"
            [[ -d "${PROTEIN_HUNTER_DIR}" ]] && { rm -rf "${PROTEIN_HUNTER_DIR}"; print_ok "Removed ${PROTEIN_HUNTER_DIR}"; }
            print_ok "Protein-Hunter uninstalled"
            ;;
        rfd3|foundry)
            print_step "Uninstalling RFD3"
            env_exists bindmaster_rfd3 && run_logged "Removing bindmaster_rfd3 env" \
                "${CONDA_CMD}" env remove -n bindmaster_rfd3 -y
            rm -f "${SHORTCUTS_DIR}/rfd3"
            [[ -d "${FOUNDRY_WEIGHTS_DIR}" ]] && { rm -rf "${FOUNDRY_WEIGHTS_DIR}"; print_ok "Removed ${FOUNDRY_WEIGHTS_DIR}"; }
            [[ -d "${FOUNDRY_DIR}" ]] && { rm -rf "${FOUNDRY_DIR}"; print_ok "Removed ${FOUNDRY_DIR}"; }
            print_ok "RFD3 uninstalled"
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
    echo -e "${BOLD}=== BindMaster Installer — $(date) ===${RESET}"
    echo -e "CUDA: ${CUDA_VERSION} | Arch: ${ARCH} | Standalone: ${STANDALONE} | Skip examples: ${SKIP_EXAMPLES}"

    detect_conda || exit 1
    local _conda_name _conda_ver
    _conda_name="$(basename "${CONDA_CMD}")"
    _conda_ver="$("${CONDA_CMD}" --version 2>/dev/null | awk '{print $2}')"
    print_ok "${_conda_name} ${_conda_ver} at: ${CONDA_BASE}"
    if [[ "${CONDA_BASE}" == "${LOCAL_CONDA_DIR}" ]]; then
        print_ok "Standalone mode — all environments local to ${BINDMASTER_DIR}"
    fi

    if [[ "${ARCH}" == "aarch64" ]]; then
        print_warn "aarch64 detected (e.g. DGX Spark / Grace-Hopper)."
        print_warn "  BindCraft: may fail — jaxlib CUDA conda packages not available for aarch64."
        print_warn "  BoltzGen:  PyTorch will be installed from PyPI (no +cuXXX suffix)."
        print_warn "  Mosaic:    may fail — torchtext has no Linux aarch64 wheel."
        print_warn "  Proteina-Complexa: may need patches — some deps (PyG, torchtext) may lack aarch64 wheels."
    fi

    print_tool_status

    # Show interactive menu if no --tool was given
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
        [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && { uninstall_tool proteina-complexa || failed_uninstalls+=("Proteina-Complexa"); }
        [[ "${DO_PROTEIN_HUNTER}" == true ]] && { uninstall_tool protein-hunter || failed_uninstalls+=("Protein-Hunter"); }
        [[ "${DO_RFD3}"      == true ]] && { uninstall_tool rfd3      || failed_uninstalls+=("RFD3"); }

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
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && (( total++ ))
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && (( total++ ))
    [[ "${DO_RFD3}"      == true ]] && (( total++ ))

    local failed_tools=()
    FAILED_EXAMPLES=()   # populated by install functions on example failure

    [[ "${DO_BINDCRAFT}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BindCraft${RESET}"; install_bindcraft || failed_tools+=("BindCraft"); }
    [[ "${DO_BOLTZGEN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] BoltzGen${RESET}";  install_boltzgen  || failed_tools+=("BoltzGen");  }
    [[ "${DO_MOSAIC}"    == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Mosaic${RESET}";    install_mosaic    || failed_tools+=("Mosaic");    }
    [[ "${DO_EVALUATOR}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Evaluator${RESET}"; install_evaluator || failed_tools+=("Evaluator"); }
    [[ "${DO_RFAA}"      == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] RFAA (legacy)${RESET}"; install_rfaa || failed_tools+=("RFAA"); }
    [[ "${DO_RFD3}"      == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] RFD3${RESET}";      install_rfd3      || failed_tools+=("RFD3"); }
    [[ "${DO_PXDESIGN}"  == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] PXDesign${RESET}";  install_pxdesign  || failed_tools+=("PXDesign"); }
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Proteina-Complexa${RESET}"; install_proteina_complexa || failed_tools+=("Proteina-Complexa"); }
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && { (( step++ )); echo -e "\n${BOLD}[${step}/${total}] Protein-Hunter${RESET}"; install_protein_hunter || failed_tools+=("Protein-Hunter"); }

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
    [[ "${DO_RFAA}"      == true ]] && echo -e "  ${YELLOW}rfaa${RESET}       — open RFAA shell ${YELLOW}(legacy)${RESET}"
    [[ "${DO_RFD3}"      == true ]] && echo -e "  ${GREEN}rfd3${RESET}       — run RFD3 design / open env shell"
    [[ "${DO_PXDESIGN}"  == true ]] && echo -e "  ${GREEN}pxdesign${RESET}   — open PXDesign shell"
    [[ "${DO_PROTEINA_COMPLEXA}" == true ]] && echo -e "  ${GREEN}complexa${RESET}   — open Proteina-Complexa shell"
    [[ "${DO_PROTEIN_HUNTER}" == true ]] && echo -e "  ${GREEN}protein-hunter${RESET} — open Protein-Hunter shell"
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
