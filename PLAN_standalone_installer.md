# Part H: Standalone Installer — Detailed Implementation Plan

> **Status:** Ready for implementation.
> **Branch:** `master`
> **Goal:** Every file created by BindMaster lives under `BindMaster/`. Zero writes to
> system conda, `~/.local/bin`, or any location outside the project directory.

---

## Problem

On HPC/shared servers, users typically:
1. Cannot write to the system conda envs directory (`/opt/conda/envs/`, etc.)
2. May have a read-only system conda (can run `conda` binary but not create envs)
3. May have no conda at all
4. Cannot (or prefer not to) write to `~/.local/bin/`

Current installer uses `conda create -n NAME` which writes to `$CONDA_BASE/envs/` — a
location the user doesn't control. This blocks installation entirely.

## Solution

Install Miniforge3 locally into `BindMaster/conda/`. All conda environments are then
created inside `BindMaster/conda/envs/` automatically. Shortcuts go to `BindMaster/bin/`.

### Why Miniforge3?

- Ships with `mamba` (faster solver)
- Defaults to `conda-forge` channel (wider package availability)
- MIT licensed (no Anaconda ToS concerns for institutional use)
- Supports both x86_64 and aarch64
- Batch install mode (`-b -p PREFIX`) requires zero interaction

### Why not `--prefix` on existing conda?

- BindCraft's upstream `install_bindcraft.sh` hardcodes `conda create --name BindCraft`
  and `conda activate ${CONDA_BASE}/envs/BindCraft`. We'd need to patch their installer.
- `conda run --prefix ./path` is clunkier than `conda run -n NAME`
- Every reference in configurator, evaluator, and generated run scripts would change
- With local Miniforge, ALL existing `-n NAME` commands work unchanged

---

## New directory layout

```
BindMaster/
├── conda/                         NEW — local Miniforge3 (~500 MB base)
│   ├── bin/conda, mamba, python
│   ├── envs/
│   │   ├── BindCraft/             was in /opt/conda/envs/ or ~/miniconda3/envs/
│   │   ├── BoltzGen/
│   │   ├── binder-eval/
│   │   └── binder-eval-af2/
│   ├── etc/profile.d/conda.sh
│   └── pkgs/                      (conda package cache)
├── bin/                           NEW — local shortcuts (was ~/.local/bin/)
│   ├── bindmaster
│   ├── bindcraft
│   ├── boltzgen
│   ├── mosaic
│   └── evaluate
├── Mosaic/.venv/                  unchanged (already local via uv)
└── ... (everything else unchanged)
```

---

## File-by-file changes

### H1–H7: `install/install.sh`

#### H1: New CLI flags

Add `--standalone` and `--system-conda` to argument parsing:

```bash
# New defaults
STANDALONE="auto"   # auto | true | false

# In argument parsing:
--standalone)
    STANDALONE=true
    shift
    ;;
--system-conda)
    STANDALONE=false
    shift
    ;;
```

- `--standalone` (or auto-detected): install Miniforge3 locally, use it for everything
- `--system-conda`: use existing system conda (current behavior, opt-in for users who
  have writable conda and prefer it)
- `auto` (default): check if local conda exists → use it; else check if system conda
  is writable → use it; else auto-install local Miniforge

Update `--help` text to document these flags.

#### H2: `install_local_conda()` function

New function, placed after `detect_conda()`:

```bash
LOCAL_CONDA_DIR="${BINDMASTER_DIR}/conda"

install_local_conda() {
    print_step "Installing local Miniforge3 into ${LOCAL_CONDA_DIR}"

    if [[ -d "${LOCAL_CONDA_DIR}" && -x "${LOCAL_CONDA_DIR}/bin/conda" ]]; then
        print_ok "Local Miniforge3 already installed"
        CONDA_BASE="${LOCAL_CONDA_DIR}"
        CONDA_CMD="${LOCAL_CONDA_DIR}/bin/mamba"
        [[ -x "${CONDA_CMD}" ]] || CONDA_CMD="${LOCAL_CONDA_DIR}/bin/conda"
        return 0
    fi

    # Determine installer URL
    local installer_url
    if [[ "${ARCH}" == "aarch64" ]]; then
        installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh"
    else
        installer_url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
    fi

    local installer_path
    installer_path="$(mktemp /tmp/miniforge3-XXXXXXXX.sh)"

    run_logged --retries 3 "Downloading Miniforge3" \
        curl -fSL -o "${installer_path}" "${installer_url}" \
        || { print_fail "Failed to download Miniforge3"; rm -f "${installer_path}"; return 1; }

    # Install in batch mode (-b), to prefix (-p), no PATH modification (-s is implicit in -b)
    run_logged "Installing Miniforge3" \
        bash "${installer_path}" -b -p "${LOCAL_CONDA_DIR}" \
        || { print_fail "Miniforge3 installation failed"; rm -f "${installer_path}"; return 1; }

    rm -f "${installer_path}"

    # Set globals
    CONDA_BASE="${LOCAL_CONDA_DIR}"
    CONDA_CMD="${LOCAL_CONDA_DIR}/bin/mamba"
    [[ -x "${CONDA_CMD}" ]] || CONDA_CMD="${LOCAL_CONDA_DIR}/bin/conda"

    print_ok "Miniforge3 installed at ${LOCAL_CONDA_DIR}"
}
```

Key points:
- `-b` = batch mode (no prompts, no license question)
- `-p PREFIX` = install to specific directory
- Miniforge installer does NOT modify `.bashrc` in batch mode
- Download is ~80 MB, installed is ~500 MB
- Idempotent — skips if already installed

#### H3: Modified `detect_conda()`

Replace the current `detect_conda()` function:

```bash
detect_conda() {
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

    # 2. If --standalone was forced, install local conda
    if [[ "${STANDALONE}" == "true" ]]; then
        install_local_conda
        return $?
    fi

    # 3. Try system conda/mamba (existing logic)
    _try_cmd mamba && return 0
    _try_cmd conda && return 0

    # 4. Probe common install locations (existing logic)
    for candidate in ... ; do
        ...
    done

    # 5. If system conda found, check if envs dir is writable
    if [[ -n "${CONDA_BASE:-}" ]]; then
        local envs_dir="${CONDA_BASE}/envs"
        if [[ -d "${envs_dir}" && -w "${envs_dir}" ]]; then
            return 0  # system conda is usable
        fi
        # System conda exists but envs dir is not writable
        if [[ "${STANDALONE}" == "false" ]]; then
            print_fail "System conda found at ${CONDA_BASE} but envs directory is not writable."
            print_fail "Use --standalone to install a local conda, or ask your admin for write access."
            return 1
        fi
        # auto mode: fall through to local install
        print_warn "System conda found but envs dir not writable — installing local Miniforge3"
    fi

    # 6. No usable conda found — install locally (auto or standalone mode)
    if [[ "${STANDALONE}" != "false" ]]; then
        install_local_conda
        return $?
    fi

    print_fail "Could not find conda or mamba. Use --standalone to install locally."
    return 1
}
```

Decision flow:
```
--standalone forced? → install_local_conda()
local conda exists?  → use it
system conda exists + writable? → use it
system conda exists + NOT writable + auto mode? → install_local_conda()
system conda exists + NOT writable + --system-conda? → error with helpful message
nothing found + auto/standalone? → install_local_conda()
nothing found + --system-conda? → error
```

#### H4: `SHORTCUTS_DIR` change

Change from:
```bash
SHORTCUTS_DIR="${HOME}/.local/bin"
```
To:
```bash
SHORTCUTS_DIR="${BINDMASTER_DIR}/bin"
```

At the end of `main()`, add PATH instructions:
```bash
echo ""
echo -e "${BOLD}To use BindMaster, add to your PATH:${RESET}"
echo -e "  ${CYAN}export PATH=\"${SHORTCUTS_DIR}:\$PATH\"${RESET}"
echo -e "  ${CYAN}# Add to ~/.bashrc for persistence:${RESET}"
echo -e "  ${CYAN}echo 'export PATH=\"${SHORTCUTS_DIR}:\$PATH\"' >> ~/.bashrc${RESET}"
```

#### H5: PATH before BindCraft installer

In `install_bindcraft()`, before calling BindCraft's `install_bindcraft.sh`:

```bash
# Ensure our local conda is found first by BindCraft's installer
# (it calls `conda info --base` which must return our local conda)
export PATH="${CONDA_BASE}/bin:${PATH}"
```

This is critical: BindCraft's installer line 49 does:
```bash
CONDA_BASE=$(conda info --base 2>/dev/null)
```
With our local conda on PATH, this returns `BindMaster/conda/` — exactly what we want.

Also line 54: `$pkg_manager create --name BindCraft` — with our local conda, this
creates the env in `BindMaster/conda/envs/BindCraft/`. No changes needed to their script.

#### H6: Updated `ensure_conda_in_path()`

```bash
ensure_conda_in_path() {
    export PATH="${CONDA_BASE}/bin:${PATH}"
    # shellcheck source=/dev/null
    source "${CONDA_BASE}/etc/profile.d/conda.sh"
}
```

No functional change needed — it already uses `CONDA_BASE` which now points to local.

#### H7: Updated uninstall

Add option to remove local Miniforge:

```bash
# In the uninstall section, after tool-specific removal:
if [[ "${DO_BINDCRAFT}" == true && "${DO_BOLTZGEN}" == true && \
      "${DO_MOSAIC}" == true && "${DO_EVALUATOR}" == true ]]; then
    # All tools being uninstalled — offer to remove local conda too
    if [[ -d "${LOCAL_CONDA_DIR}" ]]; then
        if confirm "Also remove local Miniforge3 installation (${LOCAL_CONDA_DIR})?"; then
            rm -rf "${LOCAL_CONDA_DIR}"
            print_ok "Removed local Miniforge3"
        fi
    fi
fi
```

### H8: `install/install_aarch.sh`

Mirror all H1–H7 changes. The only difference is the Miniforge3 download URL
uses `Miniforge3-Linux-aarch64.sh` (already handled by the `ARCH` check in
`install_local_conda()`).

Since both installers share the same logic, consider extracting shared functions
into `install/common.sh` and sourcing it. But this is optional — can also just
duplicate with minor differences as currently done.

### H9: `bindmaster.py`

#### Shortcut location change

```python
REPO = Path(__file__).resolve().parent
LOCAL_BIN = REPO / "bin"

def _install_bindmaster_shortcut() -> None:
    """Write BindMaster/bin/bindmaster pointing at this script."""
    LOCAL_BIN.mkdir(exist_ok=True)
    shortcut = LOCAL_BIN / "bindmaster"
    script = Path(__file__).resolve()
    target_line = f'exec python3 "{script}" "$@"\n'

    if shortcut.exists():
        try:
            if target_line in shortcut.read_text():
                return
        except OSError:
            pass

    shortcut.write_text(
        f"#!/usr/bin/env bash\n"
        f"# BindMaster shortcut — auto-generated\n"
        f"{target_line}"
    )
    shortcut.chmod(0o755)

    # Also try ~/.local/bin as a convenience (non-fatal if not writable)
    home_bin = Path.home() / ".local" / "bin"
    try:
        home_bin.mkdir(parents=True, exist_ok=True)
        home_shortcut = home_bin / "bindmaster"
        if not home_shortcut.exists():
            home_shortcut.write_text(
                f"#!/usr/bin/env bash\n"
                f"# BindMaster shortcut — auto-generated (convenience copy)\n"
                f"{target_line}"
            )
            home_shortcut.chmod(0o755)
    except OSError:
        pass  # ~/.local/bin not writable — that's fine, BindMaster/bin/ is primary
```

### H10: `bindmaster.py` — local conda detection

Update `_dispatch()` for the evaluate command:

```python
# Check for local conda's Mosaic venv first
LOCAL_CONDA_MOSAIC_VENV = REPO / "Mosaic" / ".venv" / "bin" / "python"

# In evaluate dispatch — no change needed, MOSAIC_VENV_PYTHON already
# points to REPO / "Mosaic" / ".venv" / "bin" / "python" which is the
# same regardless of whether conda is local or system. Mosaic uses uv,
# not conda. No change required here.
```

Actually, no change needed for evaluate dispatch — the Mosaic venv is always at
`BindMaster/Mosaic/.venv/` regardless of conda location.

### H11: `configurator/configurator.py` — `_find_conda_base()`

Add `BINDMASTER_DIR / "conda"` as the FIRST candidate:

```python
def _find_conda_base() -> Path | None:
    """Find conda/mamba base directory. Prefers local standalone install."""
    # Check local standalone conda first
    local_conda = BINDMASTER_DIR / "conda"
    if (local_conda / "etc" / "profile.d" / "conda.sh").exists():
        return local_conda

    # Then check PATH (existing logic)
    for cmd in ("mamba", "conda"):
        ...

    # Then check common system locations (existing logic)
    for candidate in [
        local_conda,  # already checked but kept for completeness
        Path.home() / "miniforge3",
        ...
    ]:
        ...
```

### H12: `configurator/configurator.py` — generated run scripts

In `write_run_bindcraft()`, `write_run_boltzgen()`, and `write_run_evaluate()`,
add the local conda path as the FIRST entry in the conda-search loop:

```python
conda_base = str(CONDA_BASE) if CONDA_BASE else ""
bindmaster_dir = str(BINDMASTER_DIR)

# In the f-string template, the for loop becomes:
for _conda_sh in \\
    "{bindmaster_dir}/conda/etc/profile.d/conda.sh" \\
    "{conda_base}/etc/profile.d/conda.sh" \\
    "${{HOME}}/miniforge3/etc/profile.d/conda.sh" \\
    ...
```

This way generated run scripts will find the local conda even if the user's
PATH doesn't include it.

### H13–H15: `Evaluator/evaluate.sh`, `run.sh`, `install.sh`

Each of these has a conda init block. Add the local conda path.

The pattern is the same in all three files. Currently:

```bash
_CONDA_INIT="${HOME}/miniforge3/etc/profile.d/conda.sh"
for _f in "$_CONDA_INIT" \
           "${HOME}/miniconda3/etc/profile.d/conda.sh" \
           "${HOME}/anaconda3/etc/profile.d/conda.sh"; do
    [[ -f "$_f" ]] && { source "$_f"; break; }
done
```

Change to:

```bash
# Locate conda — prefer local standalone install
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_BINDMASTER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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
```

For `evaluate.sh` specifically, it resolves `$SCRIPT_DIR` as the Evaluator dir,
so `_BINDMASTER_DIR` is `"$SCRIPT_DIR/.."`.

For `run.sh` and `install.sh` (both in `Evaluator/`), same pattern.

### H16: `.gitignore`

Add:
```
# Local Miniforge3 installation (standalone mode)
conda/

# Local shortcuts
bin/
```

### H17–H19: Documentation updates

**CLAUDE.md** — update the environment isolation table:
- Add note that in standalone mode, all conda envs live under `BindMaster/conda/envs/`
- Add `--standalone` / `--system-conda` to the Commands section
- Update the directory layout diagram to show `conda/` and `bin/`

**README.md** — add section:
```markdown
### Server / HPC Installation (no admin required)

BindMaster can run fully standalone — no system conda or admin permissions needed.
The installer automatically downloads Miniforge3 into the project directory:

    git clone https://github.com/damborik22/BindMaster.git
    cd BindMaster
    python3 bindmaster.py install --tool all --yes

    # Add to PATH:
    export PATH="$(pwd)/bin:$PATH"
    echo 'export PATH="/path/to/BindMaster/bin:$PATH"' >> ~/.bashrc

Everything is installed under `BindMaster/` — nothing touches system directories.
To remove completely: `rm -rf BindMaster/`.
```

**CHANGELOG.md** — add entry under next version.

### H20: CI / Docker test

Update `Dockerfile.test` to test standalone mode:
- Remove pre-installed conda from the test image (or use a separate stage)
- Run `install.sh --standalone --tool mosaic --yes --skip-examples`
- Verify envs land in `BindMaster/conda/envs/`

---

## Execution order

The items have dependencies:

```
H2 (install_local_conda)
  ↓
H3 (detect_conda rewrite) ← depends on H1 (flags) and H2
  ↓
H5 (PATH before BindCraft) ← depends on H3
H6 (ensure_conda_in_path)  ← depends on H3
  ↓
H4 (SHORTCUTS_DIR)         ← independent
H7 (uninstall)             ← depends on H2
  ↓
H8 (aarch64 mirror)        ← depends on H1-H7
  ↓
H9-H10 (bindmaster.py)     ← depends on H4
H11-H12 (configurator.py)  ← depends on H3
H13-H15 (Evaluator/*.sh)   ← independent
H16 (.gitignore)            ← independent
H17-H19 (docs)             ← after all code changes
H20 (CI)                   ← after all code changes
```

Suggested commit grouping:
1. **H1-H7**: Core installer changes (install.sh) — single commit
2. **H8**: aarch64 mirror — single commit
3. **H9-H12**: Python files (bindmaster.py, configurator.py) — single commit
4. **H13-H16**: Evaluator scripts + .gitignore — single commit
5. **H17-H19**: Documentation — single commit
6. **H20**: CI — single commit

Or combine all into 1-2 commits if preferred.

---

## Testing checklist

- [ ] Fresh clone + `install.sh --standalone --tool mosaic --yes --skip-examples`
  - Miniforge3 downloaded and installed in `BindMaster/conda/`
  - Mosaic venv created in `BindMaster/Mosaic/.venv/`
  - Shortcut at `BindMaster/bin/mosaic`
  - `conda/envs/` is empty (Mosaic uses uv, not conda)

- [ ] Fresh clone + `install.sh --standalone --tool boltzgen --yes --skip-examples`
  - `conda/envs/BoltzGen/` exists
  - `conda/bin/conda run -n BoltzGen boltzgen --help` works
  - `bin/boltzgen` shortcut works

- [ ] Fresh clone + `install.sh --standalone --tool bindcraft --yes --skip-examples`
  - BindCraft's own installer finds local conda
  - `conda/envs/BindCraft/` exists with PyRosetta, JAX, etc.
  - AF2 weights in `BindCraft/params/`

- [ ] Fresh clone + `install.sh --standalone --tool evaluator --yes` (after mosaic)
  - `conda/envs/binder-eval/` and `conda/envs/binder-eval-af2/` exist
  - `binder-compare --help` works from both envs

- [ ] `install.sh --standalone --tool all --yes --skip-examples`
  - All of the above in one go

- [ ] `install.sh --system-conda --tool mosaic --yes --skip-examples`
  - Uses existing system conda (backward compat)
  - Env created in system conda's envs dir

- [ ] Auto-detect mode (no flag):
  - With writable system conda → uses system conda
  - Without system conda → installs local Miniforge
  - With read-only system conda → installs local Miniforge + prints warning

- [ ] Generated run scripts (`configurator.py`):
  - `run_bindcraft.sh` finds local conda
  - `run_boltzgen.sh` finds local conda
  - `run_evaluate.sh` finds local conda

- [ ] Evaluator scripts:
  - `evaluate.sh` sources local conda
  - `run.sh` sources local conda

- [ ] Uninstall:
  - `install.sh --uninstall --tool all --yes` removes envs from `conda/envs/`
  - Offers to remove local Miniforge when all tools uninstalled
  - `BindMaster/conda/` removed after confirmation

- [ ] Idempotent:
  - Running installer twice doesn't break anything
  - `install_local_conda()` skips if already present

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Miniforge download blocked by firewall | Clear error message; user can manually download and place in `conda/` |
| Disk space (500 MB for Miniforge base) | Document in help text; acceptable — envs are same size either way |
| User has conda on PATH, expects system behavior | `--system-conda` flag; auto-detect prefers local if it exists |
| BindCraft installer finds wrong conda | We prepend `CONDA_BASE/bin` to PATH before calling it |
| `uv` installer writes to `~/.local/bin` | Already the case; uv binary is small and this is standard |
| Existing installs with system conda break | No — if local conda dir doesn't exist, auto-detect falls through to system |
