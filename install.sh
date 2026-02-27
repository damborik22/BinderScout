#!/bin/bash
# BindMaster Installer
# Installs BindCraft, BoltzGen, and/or Mosaic protein design tools.
#
# Usage:
#   ./install.sh [--tool bindcraft|boltzgen|mosaic|all] [--cuda VERSION] [--skip-examples]
#
# With no --tool flag, an interactive menu lets you choose which tools to install.

# ─── Constants ────────────────────────────────────────────────────────────────
# BINDMASTER_DIR is wherever this script lives — works on any machine.
BINDMASTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHORTCUTS_DIR="${HOME}/.local/bin"
LOG_FILE="${BINDMASTER_DIR}/install.log"

BINDCRAFT_DIR="${BINDMASTER_DIR}/BindCraft"
BOLTZGEN_DIR="${BINDMASTER_DIR}/BoltzGen"
MOSAIC_DIR="${BINDMASTER_DIR}/Mosaic"

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
TOOL_SPECIFIED=false   # set to true when --tool is passed on CLI

# Per-tool install flags (set by arg parsing or interactive menu)
DO_BINDCRAFT=false
DO_BOLTZGEN=false
DO_MOSAIC=false

# ─── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tool)
            TOOL_SPECIFIED=true
            case "${2,,}" in
                all)
                    DO_BINDCRAFT=true; DO_BOLTZGEN=true; DO_MOSAIC=true ;;
                bindcraft)
                    DO_BINDCRAFT=true ;;
                boltzgen)
                    DO_BOLTZGEN=true ;;
                mosaic)
                    DO_MOSAIC=true ;;
                *)
                    echo -e "${RED}Invalid --tool value: $2. Must be one of: all, bindcraft, boltzgen, mosaic${RESET}"
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
        -h|--help)
            cat <<EOF
Usage: $0 [--tool all|bindcraft|boltzgen|mosaic] [--cuda VERSION] [--skip-examples]

  --tool        Which tool(s) to install. Omit for interactive selection.
  --cuda        CUDA version for conda package resolution (default: 12.4).
  --skip-examples
                Do not prompt to run bundled examples after install.
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

# run_logged <label> <command...>
# Runs a verbose command showing only a spinner on the terminal.
# All output is written to LOG_FILE only. On failure the last 30 lines
# are printed to the terminal for diagnosis.
run_logged() {
    local label="$1"
    shift
    local tmpfile
    tmpfile=$(mktemp)

    "$@" >> "${tmpfile}" 2>&1 &
    local pid=$!

    local frames='/-\|'
    local i=0
    while kill -0 "${pid}" 2>/dev/null; do
        printf "\r  ${CYAN}%s${RESET}  %s" "${frames:$((i % 4)):1}" "${label}" >/dev/tty
        sleep 0.15
        (( i++ ))
    done
    wait "${pid}"
    local rc=$?
    printf "\r\033[K" >/dev/tty   # clear spinner line

    cat "${tmpfile}" >> "${LOG_FILE}"
    rm -f "${tmpfile}"

    if [[ ${rc} -eq 0 ]]; then
        print_ok "${label}"
    else
        echo -e "${RED}  Last output:${RESET}"
        tail -30 "${LOG_FILE}" | sed 's/^/  /'
        print_fail "${label}"
    fi
    return ${rc}
}

# confirm <prompt>
# Returns 0 (yes) or 1 (no).
confirm() {
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
    "${CONDA_BASE}/bin/conda" env list | grep -qw "$1"
}

# ensure_conda_in_path
ensure_conda_in_path() {
    export PATH="${CONDA_BASE}/bin:${PATH}"
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
}

# detect_conda
# Finds the conda base directory and sets CONDA_BASE.
detect_conda() {
    # If conda is already on PATH, ask it where it lives
    if command -v conda &>/dev/null; then
        local base
        base=$(conda info --base 2>/dev/null) && { CONDA_BASE="${base}"; return 0; }
    fi
    # Fall back to common install locations
    local candidate
    for candidate in \
        "$HOME/miniconda3" \
        "$HOME/anaconda3" \
        "$HOME/miniforge3" \
        "$HOME/mambaforge" \
        "$HOME/conda" \
        "/opt/conda" \
        "/opt/miniconda3" \
        "/opt/anaconda3"; do
        if [[ -f "${candidate}/etc/profile.d/conda.sh" ]]; then
            CONDA_BASE="${candidate}"
            return 0
        fi
    done
    print_fail "Could not find a conda installation. Please install Miniconda or Anaconda first."
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

# print_tool_status
# Shows installed/not-installed for each tool.
print_tool_status() {
    echo ""
    echo -e "${BOLD}=== Installed Tools ===${RESET}"
    local _status _icon
    for _tool in BindCraft BoltzGen Mosaic; do
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

    local tools=("BindCraft" "BoltzGen" "Mosaic")
    local descs=(
        "Binder design via AlphaFold2 (conda, Python 3.10)"
        "Structure generation with Boltz-1 (conda, Python 3.12, ~6 GB download)"
        "JAX-based protein design with Marimo notebooks (uv venv)"
    )

    # Check current install state once (avoid repeated conda calls in the loop)
    local inst_bc inst_bg inst_mo
    is_bindcraft_installed && inst_bc="${GREEN}installed${RESET}" || inst_bc="${YELLOW}not installed${RESET}"
    is_boltzgen_installed  && inst_bg="${GREEN}installed${RESET}" || inst_bg="${YELLOW}not installed${RESET}"
    is_mosaic_installed    && inst_mo="${GREEN}installed${RESET}" || inst_mo="${YELLOW}not installed${RESET}"
    local inst_states=("$inst_bc" "$inst_bg" "$inst_mo")

    # Helper: print current state
    _print_menu() {
        echo ""
        echo -e "${BOLD}${CYAN}  Select tools to install${RESET}"
        echo -e "  Type a number to toggle selection, then press Enter when done."
        echo ""
        local states=("$sel_bc" "$sel_bg" "$sel_mo")
        for i in 0 1 2; do
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
        # Re-print menu on each iteration (scroll-friendly, no tput)
        _print_menu
        read -rp "  > " choice
        case "${choice,,}" in
            1) [[ "$sel_bc" == true ]] && sel_bc=false || sel_bc=true ;;
            2) [[ "$sel_bg" == true ]] && sel_bg=false || sel_bg=true ;;
            3) [[ "$sel_mo" == true ]] && sel_mo=false || sel_mo=true ;;
            a) sel_bc=true;  sel_bg=true;  sel_mo=true  ;;
            n) sel_bc=false; sel_bg=false; sel_mo=false ;;
            "")
                # Confirm: at least one must be selected
                if [[ "$sel_bc" == false && "$sel_bg" == false && "$sel_mo" == false ]]; then
                    echo -e "  ${RED}No tools selected. Select at least one.${RESET}"
                    continue
                fi
                break
                ;;
            *) echo -e "  ${RED}Invalid input. Enter 1, 2, 3, a, n, or press Enter.${RESET}" ;;
        esac
    done

    DO_BINDCRAFT="$sel_bc"
    DO_BOLTZGEN="$sel_bg"
    DO_MOSAIC="$sel_mo"

    echo ""
    echo -e "  ${BOLD}Installing:${RESET}"
    [[ "$DO_BINDCRAFT" == true ]] && echo -e "    ${GREEN}✓${RESET} BindCraft"
    [[ "$DO_BOLTZGEN"  == true ]] && echo -e "    ${GREEN}✓${RESET} BoltzGen"
    [[ "$DO_MOSAIC"    == true ]] && echo -e "    ${GREEN}✓${RESET} Mosaic"
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
        git clone https://github.com/martinpacesa/BindCraft "${BINDCRAFT_DIR}" \
            || { print_fail "Failed to clone BindCraft"; return 1; }
        print_ok "BindCraft cloned to ${BINDCRAFT_DIR}"
    fi

    # Fix Colab paths in target settings
    _fix_target_settings

    # Remove existing conda env if present
    if env_exists BindCraft; then
        print_warn "Conda environment 'BindCraft' already exists."
        if confirm "Remove and recreate the BindCraft conda environment?"; then
            run_logged "Removing existing BindCraft conda env" \
                "${CONDA_BASE}/bin/conda" env remove -n BindCraft -y \
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
            bash -c "cd '${BINDCRAFT_DIR}' && bash install_bindcraft.sh --cuda '${CUDA_VERSION}' --pkg_manager conda" \
            || { print_fail "BindCraft install script failed"; return 1; }
    fi

    # Smoke test
    smoke_test "colabdesign import" \
        "${CONDA_BASE}/bin/conda" run -n BindCraft \
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
                "${CONDA_BASE}/bin/conda" run -n BindCraft \
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
        git clone https://github.com/HannesStark/boltzgen "${BOLTZGEN_DIR}" \
            || { print_fail "Failed to clone BoltzGen"; return 1; }
        print_ok "BoltzGen cloned to ${BOLTZGEN_DIR}"
    fi

    # Conda environment
    print_step "Creating BoltzGen conda environment (Python 3.12)"
    if env_exists BoltzGen; then
        print_warn "Conda environment 'BoltzGen' already exists."
        if confirm "Remove and recreate the BoltzGen conda environment?"; then
            run_logged "Removing existing BoltzGen conda env" \
                "${CONDA_BASE}/bin/conda" env remove -n BoltzGen -y \
                || return 1
        else
            print_warn "Keeping existing BoltzGen conda env."
        fi
    fi
    if ! env_exists BoltzGen; then
        run_logged "Creating BoltzGen conda env (Python 3.12)" \
            "${CONDA_BASE}/bin/conda" create -n BoltzGen python=3.12 -y \
            || { print_fail "Failed to create BoltzGen conda env"; return 1; }
    fi

    # Install gcc — required by Triton to JIT-compile CUDA kernels at runtime
    run_logged "Installing gcc into BoltzGen env (required by Triton)" \
        "${CONDA_BASE}/bin/conda" install -n BoltzGen -c conda-forge gcc -y \
        || { print_fail "Failed to install gcc into BoltzGen env"; return 1; }

    # Install packages
    print_step "Installing PyTorch (cu121) and BoltzGen"
    run_logged "Installing PyTorch cu121" \
        "${CONDA_BASE}/bin/conda" run -n BoltzGen \
        pip install torch==2.5.1+cu121 --index-url https://download.pytorch.org/whl/cu121 \
        || { print_fail "Failed to install PyTorch"; return 1; }
    run_logged "Installing BoltzGen package" \
        "${CONDA_BASE}/bin/conda" run -n BoltzGen \
        pip install -e "${BOLTZGEN_DIR}" \
        || { print_fail "Failed to install BoltzGen package"; return 1; }

    # Smoke test
    smoke_test "boltzgen --help" \
        "${CONDA_BASE}/bin/conda" run -n BoltzGen boltzgen --help \
        || return 1

    # Example
    if [[ "${SKIP_EXAMPLES}" == false ]]; then
        print_step "BoltzGen example run"
        print_warn "The example downloads ~6 GB of model weights on first run."
        if confirm "Run the BoltzGen example (2 designs of 1g13)?"; then
            print_warn "First run downloads ~6 GB of model weights — this will take a while."
            (
                cd "${BOLTZGEN_DIR}" || exit 1
                "${CONDA_BASE}/bin/conda" run -n BoltzGen \
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
        git clone https://github.com/escalante-bio/mosaic "${MOSAIC_DIR}" \
            || { print_fail "Failed to clone Mosaic"; return 1; }
        print_ok "Mosaic cloned to ${MOSAIC_DIR}"
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
            read -rp "$(echo -e "${YELLOW}  Press Enter to stop Marimo and continue the installer...${RESET}")"
            kill "${marimo_pid}" 2>/dev/null && print_ok "Marimo stopped" || print_warn "Marimo already exited"
            cd - > /dev/null
        else
            print_warn "Skipped Mosaic example."
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

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo -e "${BOLD}=== BindMaster Installer — $(date) ===${RESET}"
    echo -e "CUDA: ${CUDA_VERSION} | Skip examples: ${SKIP_EXAMPLES}"

    detect_conda || exit 1
    print_ok "Conda found at: ${CONDA_BASE}"

    print_tool_status

    # Show interactive menu if no --tool was given
    if [[ "${TOOL_SPECIFIED}" == false ]]; then
        select_tools_interactive
    fi

    echo ""
    echo -e "Log file: ${LOG_FILE}"

    local failed_tools=()
    FAILED_EXAMPLES=()   # populated by install functions on example failure

    [[ "${DO_BINDCRAFT}" == true ]] && { install_bindcraft || failed_tools+=("BindCraft"); }
    [[ "${DO_BOLTZGEN}"  == true ]] && { install_boltzgen  || failed_tools+=("BoltzGen");  }
    [[ "${DO_MOSAIC}"    == true ]] && { install_mosaic    || failed_tools+=("Mosaic");    }

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

    # Shortcuts
    echo ""
    echo -e "Shortcuts available in ${SHORTCUTS_DIR}:"
    [[ "${DO_BINDCRAFT}" == true ]] && echo -e "  ${GREEN}bindcraft${RESET}  — open BindCraft shell"
    [[ "${DO_BOLTZGEN}"  == true ]] && echo -e "  ${GREEN}boltzgen${RESET}   — open BoltzGen shell"
    [[ "${DO_MOSAIC}"    == true ]] && echo -e "  ${GREEN}mosaic${RESET}     — open Mosaic shell"
    echo ""
    echo -e "Full log: ${LOG_FILE}"

    [[ ${#failed_tools[@]} -gt 0 ]] && exit 1 || exit 0
}

main
