#!/bin/bash
# BindMaster Installer — DGX Spark (aarch64) Edition
# Platform: NVIDIA DGX Spark / Grace-Hopper GH200, aarch64, CUDA 12.1, Ubuntu 24.04
#
# All three tools (BindCraft, BoltzGen, Mosaic) are bundled in this repo —
# no cloning needed. Pre-cached resources (AF2 weights, ARM64 binaries) are
# read from TOOLS_DIR to avoid redundant downloads.
#
# Usage:
#   ./install_aarch.sh [--tool bindcraft|boltzgen|mosaic|all] [--tools-dir PATH] [--skip-examples]
#
# --tools-dir: path to pre-cached resources. Defaults to the sibling
#              Documents/OLD/BindMaster/bindcraft-tools directory.

# ─── Constants ────────────────────────────────────────────────────────────────
BINDMASTER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHORTCUTS_DIR="${HOME}/.local/bin"
LOG_FILE="${BINDMASTER_DIR}/install_aarch.log"

BINDCRAFT_DIR="${BINDMASTER_DIR}/BindCraft"
BOLTZGEN_DIR="${BINDMASTER_DIR}/BoltzGen"
MOSAIC_DIR="${BINDMASTER_DIR}/Mosaic"

ARCH="$(uname -m)"     # expected: aarch64
CUDA_VERSION="12.1"    # DGX Spark GB10 / GH200

# Pre-cached resources: two levels up → Documents/OLD/BindMaster/bindcraft-tools
_default_tools="$(cd "${BINDMASTER_DIR}" && cd ../../OLD/BindMaster/bindcraft-tools 2>/dev/null && pwd || true)"
TOOLS_DIR="${_default_tools}"

CONDA_CMD=""   # set by detect_conda: full path to mamba (preferred) or conda

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
TOOL_SPECIFIED=false

DO_BINDCRAFT=false
DO_BOLTZGEN=false
DO_MOSAIC=false

# ─── Argument Parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tool)
            TOOL_SPECIFIED=true
            case "${2,,}" in
                all)       DO_BINDCRAFT=true; DO_BOLTZGEN=true; DO_MOSAIC=true ;;
                bindcraft) DO_BINDCRAFT=true ;;
                boltzgen)  DO_BOLTZGEN=true ;;
                mosaic)    DO_MOSAIC=true ;;
                *)
                    echo -e "${RED}Invalid --tool: $2. Must be: all, bindcraft, boltzgen, mosaic${RESET}"
                    exit 1 ;;
            esac
            shift 2
            ;;
        --tools-dir)
            TOOLS_DIR="$2"
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
        -h|--help)
            cat <<EOF
Usage: $0 [--tool all|bindcraft|boltzgen|mosaic] [--tools-dir PATH] [--skip-examples] [--yes]

DGX Spark (aarch64) edition. CUDA ${CUDA_VERSION}. All tools are bundled — no git clones needed.

  --tool        Which tool(s) to install. Omit for interactive selection.
  --tools-dir   Path to pre-cached resources (AF2 weights, ARM64 binaries).
                Default: <repo>/../../OLD/BindMaster/bindcraft-tools
  --skip-examples
                Do not prompt to run bundled examples after install.
  --yes, -y     Auto-confirm all prompts (useful for non-interactive/CI runs).
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

# ─── Logging ──────────────────────────────────────────────────────────────────
mkdir -p "${BINDMASTER_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

# ─── Helpers ──────────────────────────────────────────────────────────────────

print_step() { echo ""; echo -e "${CYAN}${BOLD}▶ $1${RESET}"; }
print_ok()   { echo -e "${GREEN}✓ $1${RESET}"; }
print_warn() { echo -e "${YELLOW}⚠ $1${RESET}"; }
print_fail() { echo -e "${RED}✗ $1${RESET}"; }

run_logged() {
    local label="$1"; shift
    local tmpfile; tmpfile=$(mktemp)

    # Check once whether /dev/tty is usable (not available in non-TTY containers)
    local has_tty=false
    { true >/dev/tty; } 2>/dev/null && has_tty=true

    "$@" >> "${tmpfile}" 2>&1 &
    local pid=$! frames='/-\|' i=0

    if [[ "${has_tty}" == true ]]; then
        while kill -0 "${pid}" 2>/dev/null; do
            printf "\r  ${CYAN}%s${RESET}  %s" "${frames:$((i % 4)):1}" "${label}" >/dev/tty
            sleep 0.15; (( i++ ))
        done
        printf "\r\033[K" >/dev/tty
    fi
    wait "${pid}"; local rc=$?

    # Append to log if writable; silently skip otherwise
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

smoke_test() {
    local label="$1"; shift
    print_step "Smoke test: ${label}"
    if "$@"; then
        print_ok "Smoke test passed: ${label}"; return 0
    else
        print_fail "Smoke test FAILED: ${label}"; return 1
    fi
}

env_exists() { "${CONDA_CMD}" env list | grep -qw "$1"; }

ensure_conda_in_path() {
    export PATH="${CONDA_BASE}/bin:${PATH}"
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
}

# Finds conda/mamba and sets CONDA_BASE + CONDA_CMD.
# Prefers mamba (faster installs).
detect_conda() {
    _try_cmd() {
        local bin="$1"
        command -v "${bin}" &>/dev/null || return 1
        # `mamba info --base` may output "base environment : /path" in some versions;
        # extract the last path-like token regardless of format.
        local base; base=$(${bin} info --base 2>/dev/null | awk '/\// {print $NF}' | tail -1) || return 1
        [[ -n "${base}" ]] || return 1
        CONDA_BASE="${base}"
        CONDA_CMD="$(command -v "${bin}")"
        return 0
    }

    _try_cmd mamba && return 0
    _try_cmd conda && return 0

    for candidate in \
        "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" \
        "$HOME/anaconda3"  "$HOME/conda"      "/opt/conda" \
        "/opt/miniforge3"  "/opt/miniconda3"; do
        [[ -f "${candidate}/etc/profile.d/conda.sh" ]] || continue
        CONDA_BASE="${candidate}"
        if [[ -x "${candidate}/bin/mamba" ]]; then
            CONDA_CMD="${candidate}/bin/mamba"
        else
            CONDA_CMD="${candidate}/bin/conda"
        fi
        return 0
    done

    print_fail "Could not find conda or mamba. Install Miniforge first."
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

# ─── Tool Status ──────────────────────────────────────────────────────────────

is_bindcraft_installed() { [[ -d "${BINDCRAFT_DIR}" ]] && env_exists BindCraft; }
is_boltzgen_installed()  { [[ -d "${BOLTZGEN_DIR}" ]]  && env_exists BoltzGen; }
is_mosaic_installed()    { [[ -d "${MOSAIC_DIR}" ]]    && [[ -d "${MOSAIC_DIR}/.venv" ]]; }

print_tool_status() {
    echo ""
    echo -e "${BOLD}=== Current Install Status ===${RESET}"
    for _tool in BindCraft BoltzGen Mosaic; do
        local _icon _status
        if "is_${_tool,,}_installed" 2>/dev/null; then
            _icon="${GREEN}✓${RESET}"; _status="${GREEN}installed${RESET}"
        else
            _icon="${RED}✗${RESET}";  _status="${YELLOW}not installed${RESET}"
        fi
        printf "  %b  %-12s  %b\n" "${_icon}" "${_tool}" "${_status}"
    done
    echo ""
}

# ─── Interactive Menu ─────────────────────────────────────────────────────────

select_tools_interactive() {
    local sel_bc=true sel_bg=true sel_mo=true
    local tools=("BindCraft" "BoltzGen" "Mosaic")
    local descs=(
        "Binder design via AlphaFold2 (mamba env, Python 3.10)"
        "Structure generation with Boltz-1 (mamba env, Python 3.12)"
        "JAX-based multi-objective design with Marimo notebooks (uv venv)"
    )

    local inst_bc inst_bg inst_mo
    is_bindcraft_installed && inst_bc="${GREEN}installed${RESET}"   || inst_bc="${YELLOW}not installed${RESET}"
    is_boltzgen_installed  && inst_bg="${GREEN}installed${RESET}"   || inst_bg="${YELLOW}not installed${RESET}"
    is_mosaic_installed    && inst_mo="${GREEN}installed${RESET}"   || inst_mo="${YELLOW}not installed${RESET}"
    local inst_states=("$inst_bc" "$inst_bg" "$inst_mo")

    _print_menu() {
        echo ""; echo -e "${BOLD}${CYAN}  Select tools to install${RESET}"
        echo -e "  Type a number to toggle, then press Enter when done."; echo ""
        local states=("$sel_bc" "$sel_bg" "$sel_mo")
        for i in 0 1 2; do
            local box
            [[ "${states[$i]}" == true ]] && box="${GREEN}[x]${RESET}" || box="${RED}[ ]${RESET}"
            printf "    %d)  %b  ${BOLD}%-12s${RESET}  %-35b  %s\n" \
                $((i+1)) "$box" "${tools[$i]}" "${inst_states[$i]}" "${descs[$i]}"
        done
        echo ""; echo -e "  ${YELLOW}a${RESET}) Select all   ${YELLOW}n${RESET}) Select none   ${YELLOW}Enter${RESET} to confirm"; echo ""
    }

    while true; do
        _print_menu; read -rp "  > " choice
        case "${choice,,}" in
            1) [[ "$sel_bc" == true ]] && sel_bc=false || sel_bc=true ;;
            2) [[ "$sel_bg" == true ]] && sel_bg=false || sel_bg=true ;;
            3) [[ "$sel_mo" == true ]] && sel_mo=false || sel_mo=true ;;
            a) sel_bc=true; sel_bg=true; sel_mo=true ;;
            n) sel_bc=false; sel_bg=false; sel_mo=false ;;
            "")
                if [[ "$sel_bc" == false && "$sel_bg" == false && "$sel_mo" == false ]]; then
                    echo -e "  ${RED}No tools selected.${RESET}"; continue
                fi; break ;;
            *) echo -e "  ${RED}Invalid input. Enter 1, 2, 3, a, n, or press Enter.${RESET}" ;;
        esac
    done

    DO_BINDCRAFT="$sel_bc"; DO_BOLTZGEN="$sel_bg"; DO_MOSAIC="$sel_mo"
    echo ""; echo -e "  ${BOLD}Installing:${RESET}"
    [[ "$DO_BINDCRAFT" == true ]] && echo -e "    ${GREEN}✓${RESET} BindCraft"
    [[ "$DO_BOLTZGEN"  == true ]] && echo -e "    ${GREEN}✓${RESET} BoltzGen"
    [[ "$DO_MOSAIC"    == true ]] && echo -e "    ${GREEN}✓${RESET} Mosaic"
    echo ""; confirm "Proceed with installation?" || { echo "Aborted."; exit 0; }
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
    wget -q --show-progress -O "${params_file}" \
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

    [[ -d "${BINDCRAFT_DIR}" ]] \
        || { print_fail "BindCraft not found at ${BINDCRAFT_DIR}"; return 1; }
    print_ok "BindCraft source: ${BINDCRAFT_DIR}"

    _fix_target_settings
    _install_bindcraft_binaries_aarch64
    _install_af2_params || return 1
    _fix_advanced_settings

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
    # jax-cuda12-plugin pulls in all nvidia-cuda-*-cu12 CUDA libraries automatically.
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
        || { print_fail "Failed to install JAX"; return 1; }

    # ── Step 3: ColabDesign and BindCraft Python dependencies ─────────────────
    print_step "Installing ColabDesign and dependencies"
    run_logged "Installing ColabDesign" \
        "${CONDA_CMD}" run -n BindCraft \
        pip install \
            "colabdesign==1.1.1" \
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
        python -c "from colabdesign import mk_af_model; print('OK')"
}

_write_bindcraft_shortcut() {
    mkdir -p "${SHORTCUTS_DIR}"
    { echo "#!/bin/bash"
      echo "BINDCRAFT_DIR=\"${BINDCRAFT_DIR}\""
      echo "CONDA_BASE=\"${CONDA_BASE}\""; } > "${SHORTCUTS_DIR}/bindcraft"
    cat >> "${SHORTCUTS_DIR}/bindcraft" << 'EOF'
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate BindCraft
cd "${BINDCRAFT_DIR}"
echo "BindCraft environment activated. Working directory: ${BINDCRAFT_DIR}"
echo "Run: XLA_PYTHON_CLIENT_PREALLOCATE=false python -u ./bindcraft.py \\"
echo "       --settings './settings_target/<target>.json' \\"
echo "       --filters './settings_filters/default_filters.json' \\"
echo "       --advanced './settings_advanced/default_4stage_multimer.json'"
exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/bindcraft"
}

# ─── BoltzGen ─────────────────────────────────────────────────────────────────

install_boltzgen() {
    print_step "Installing BoltzGen (aarch64)"
    ensure_conda_in_path

    [[ -d "${BOLTZGEN_DIR}" ]] \
        || { print_fail "BoltzGen not found at ${BOLTZGEN_DIR}"; return 1; }
    print_ok "BoltzGen source: ${BOLTZGEN_DIR}"

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

    # On aarch64, plain PyPI torch already bundles CUDA support — no +cuXXX suffix needed.
    run_logged "Installing PyTorch (aarch64, plain PyPI)" \
        "${CONDA_CMD}" run -n BoltzGen \
        pip install torch==2.5.1 \
        || { print_fail "Failed to install PyTorch"; return 1; }

    run_logged "Installing BoltzGen package" \
        "${CONDA_CMD}" run -n BoltzGen \
        pip install -e "${BOLTZGEN_DIR}" \
        || { print_fail "Failed to install BoltzGen package"; return 1; }

    smoke_test "boltzgen --help" \
        "${CONDA_CMD}" run -n BoltzGen boltzgen --help || return 1

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
    { echo "#!/bin/bash"
      echo "BOLTZGEN_DIR=\"${BOLTZGEN_DIR}\""
      echo "CONDA_BASE=\"${CONDA_BASE}\""; } > "${SHORTCUTS_DIR}/boltzgen"
    cat >> "${SHORTCUTS_DIR}/boltzgen" << 'EOF'
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate BoltzGen
cd "${BOLTZGEN_DIR}"
echo "BoltzGen environment activated. Working directory: ${BOLTZGEN_DIR}"
echo "Run: boltzgen run <config.yaml> --output <output_dir> --protocol protein-anything --num_designs 2"
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

    [[ -d "${MOSAIC_DIR}" ]] \
        || { print_fail "Mosaic not found at ${MOSAIC_DIR}"; return 1; }
    print_ok "Mosaic source: ${MOSAIC_DIR}"

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
            cd - > /dev/null
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
    { echo "#!/bin/bash"; echo "MOSAIC_DIR=\"${MOSAIC_DIR}\""; } > "${SHORTCUTS_DIR}/mosaic"
    cat >> "${SHORTCUTS_DIR}/mosaic" << 'EOF'
source "${MOSAIC_DIR}/.venv/bin/activate"
cd "${MOSAIC_DIR}"
echo "Mosaic environment activated. Working directory: ${MOSAIC_DIR}"
echo "Run: marimo edit examples/example_notebook.py"
exec bash
EOF
    chmod +x "${SHORTCUTS_DIR}/mosaic"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo -e "${BOLD}=== BindMaster Installer — DGX Spark (aarch64) — $(date) ===${RESET}"
    echo -e "Platform: ${ARCH} | CUDA: ${CUDA_VERSION} | Package manager: $(basename "${CONDA_CMD:-conda}")"

    check_arch
    detect_conda || exit 1
    local _name _ver
    _name="$(basename "${CONDA_CMD}")"; _ver="$("${CONDA_CMD}" --version 2>/dev/null | awk '{print $2}')"
    print_ok "${_name} ${_ver} found at: ${CONDA_BASE}"
    check_tools_dir

    print_tool_status

    if [[ "${TOOL_SPECIFIED}" == false ]]; then
        select_tools_interactive
    fi

    echo ""; echo -e "Log file: ${LOG_FILE}"

    local failed_tools=()
    FAILED_EXAMPLES=()

    [[ "${DO_BINDCRAFT}" == true ]] && { install_bindcraft || failed_tools+=("BindCraft"); }
    [[ "${DO_BOLTZGEN}"  == true ]] && { install_boltzgen  || failed_tools+=("BoltzGen");  }
    [[ "${DO_MOSAIC}"    == true ]] && { install_mosaic    || failed_tools+=("Mosaic");    }

    echo ""; echo -e "${BOLD}=== Installation Summary ===${RESET}"

    if [[ ${#failed_tools[@]} -eq 0 ]]; then
        print_ok "All selected tools installed successfully."
    else
        print_fail "The following tools failed to install: ${failed_tools[*]}"
    fi

    if [[ ${#FAILED_EXAMPLES[@]} -gt 0 ]]; then
        print_warn "Examples failed (tools are usable): ${FAILED_EXAMPLES[*]}"
        echo -e "  See log: ${LOG_FILE}"
    fi

    echo ""; echo -e "Shortcuts in ${SHORTCUTS_DIR}:"
    [[ "${DO_BINDCRAFT}" == true ]] && echo -e "  ${GREEN}bindcraft${RESET}  — open BindCraft shell"
    [[ "${DO_BOLTZGEN}"  == true ]] && echo -e "  ${GREEN}boltzgen${RESET}   — open BoltzGen shell"
    [[ "${DO_MOSAIC}"    == true ]] && echo -e "  ${GREEN}mosaic${RESET}     — open Mosaic shell"
    echo ""; echo -e "Full log: ${LOG_FILE}"

    [[ ${#failed_tools[@]} -gt 0 ]] && exit 1 || exit 0
}

main
