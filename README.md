# BindMaster

A unified installer for three GPU-accelerated protein design tools:

| Tool | What it does | Environment |
|---|---|---|
| **BindCraft** | Designs protein binders for a target using AlphaFold2 | conda (Python 3.10) |
| **BoltzGen** | Generates protein structures with the Boltz-1 model | conda (Python 3.12) |
| **Mosaic** | Interactive protein design via Marimo notebooks + JAX | uv venv |

Two installers are included:

| Installer | Target platform | Notes |
|---|---|---|
| `install.sh` | Any x86_64 Linux with NVIDIA GPU | General-purpose |
| `install_aarch.sh` | NVIDIA DGX Spark / Grace-Hopper (aarch64) | Fully self-contained — no external clones or downloads needed |

---

## DGX Spark (aarch64)

### Requirements

- NVIDIA DGX Spark or any Ubuntu 24.04 aarch64 machine with an NVIDIA GPU
- CUDA driver ≥ 12.1
- Miniforge / Mamba installed (mamba preferred for speed)
- ~60 GB free disk space

### Running the installer

```bash
cd ~/BindMaster
./install_aarch.sh
```

Or to install a specific tool non-interactively:

```bash
./install_aarch.sh --tool mosaic
./install_aarch.sh --tool bindcraft
./install_aarch.sh --tool boltzgen
./install_aarch.sh --tool all
```

### All flags

```bash
./install_aarch.sh [--tool all|bindcraft|boltzgen|mosaic] [--tools-dir PATH] [--skip-examples] [--yes]

  --tool          Which tool(s) to install. Omit for interactive selection.
  --tools-dir     Path to pre-cached resources (AF2 weights, ARM64 binaries).
                  Default: <repo>/../../OLD/BindMaster/bindcraft-tools
  --skip-examples Do not prompt to run bundled examples after install.
  --yes, -y       Auto-confirm all prompts (useful for CI / non-interactive runs).
```

### What's bundled for aarch64

The installer is fully self-contained — everything needed is in this repo:

| Resource | Location | Used by |
|---|---|---|
| ARM64 `DAlphaBall.gcc` binary | `tools/aarch64/DAlphaBall.gcc` | BindCraft |
| ARM64 `dssp` (mkdssp) binary | `tools/aarch64/dssp` | BindCraft |
| Custom Marimo notebooks | `bindmaster_examples/` | Mosaic |

AF2 model weights (~3 GB) are read from `--tools-dir` if available, or downloaded automatically on first install.

### aarch64 notes

- **BindCraft**: ARM64 binaries are copied from `tools/aarch64/` and all `settings_advanced/*.json` files are automatically patched with the correct paths.
- **BoltzGen**: PyTorch is installed from plain PyPI (`torch==2.5.1`) — aarch64 wheels already include CUDA, no `+cu121` suffix needed.
- **Mosaic**: `esmj` is excluded on aarch64 (no wheel available). JAX handles GPU; torch stays on the CPU PyPI index.

---

## General installer (x86_64)

### Requirements

- Linux x86_64 with an NVIDIA GPU
- CUDA driver ≥ 12.1
- Miniconda, Anaconda, or Miniforge installed
- `git` available in PATH
- ~60 GB free disk space
- Stable internet connection

### Running the installer

```bash
cd ~/BindMaster
bash install.sh
```

The installer opens an **interactive menu** — all three tools are pre-selected:

```
  Select tools to install
  Type a number to toggle selection, then press Enter when done.

    1)  [x]  BindCraft     not installed   Binder design via AlphaFold2 (conda, Python 3.10)
    2)  [x]  BoltzGen      not installed   Structure generation with Boltz-1 (conda, Python 3.12, ~6 GB download)
    3)  [x]  Mosaic        not installed   JAX-based protein design with Marimo notebooks (uv venv)

  a) Select all   n) Select none   Enter to confirm
```

- Type `1`, `2`, or `3` to toggle a tool on/off
- Type `a` to select all, `n` to deselect all
- Press **Enter** to confirm and start

### Non-interactive options

```bash
# Install a specific tool only (skips the menu)
bash install.sh --tool bindcraft
bash install.sh --tool boltzgen
bash install.sh --tool mosaic
bash install.sh --tool all

# Skip the bundled example prompts
bash install.sh --skip-examples

# Override CUDA version (default: 12.4)
bash install.sh --cuda 12.1
```

---

## What happens during installation

Each tool goes through the same stages. The installer prints a cyan `▶` header before each step and a green `✓` when it succeeds.

### Stage 1 — Environment setup

Package installation runs silently behind a spinner — all the verbose conda/pip/uv output goes to the log only, keeping the terminal readable:

```
  \  Installing Mosaic venv (uv sync --group jax-cuda)...
✓ Setting up Mosaic venv (uv sync --group jax-cuda)
```

**BindCraft** — conda env (Python 3.10) with JAX, PyRosetta, ColabDesign, and CUDA libraries.

**BoltzGen** — conda env (Python 3.12) with PyTorch, gcc (required by Triton for GPU kernel compilation), and the BoltzGen package.

**Mosaic** — `uv` virtual environment at `<repo>/Mosaic/.venv/`. If `uv` is not installed, the official installer runs automatically.

### Stage 2 — AlphaFold2 weights (BindCraft only)

Downloads ~4.5 GB from Google storage and extracts 15 `.npz` model weight files. On aarch64, the installer first checks `--tools-dir` for a local cache to avoid the download.

### Stage 3 — Smoke test

A minimal import or `--help` call verifies the environment is working.

### Stage 4 — Example (optional)

If you did not use `--skip-examples`, the installer asks whether to run the bundled example for each tool. **An example failure does not mark the tool as failed.**

| Tool | Example | What you see |
|---|---|---|
| BindCraft | 1 PDL1 binder design | Live Python output |
| BoltzGen | 2 designs of protein 1g13 | Live output; downloads ~6 GB weights on first run |
| Mosaic | Opens example notebook | Browser URL printed; press Enter (or auto-stopped with `--yes`) |

### Stage 5 — Shortcut

A launcher script is written to `~/.local/bin/` for each tool.

---

## Monitoring progress

Package installs show only a spinner on the terminal. To see the full verbose output live:

```bash
# General installer
tail -f install.log

# aarch64 installer
tail -f install_aarch.log
```

---

## After installation

### BindCraft
```bash
bindcraft
```
Then run a design job:
```bash
python -u ./bindcraft.py \
  --settings './settings_target/PDL1.json' \
  --filters './settings_filters/default_filters.json' \
  --advanced './settings_advanced/default_4stage_multimer.json'
```

### BoltzGen
```bash
boltzgen
```
Then run a generation:
```bash
boltzgen run example/vanilla_protein/1g13prot.yaml \
  --output output/my_run \
  --protocol protein-anything \
  --num_designs 4
```
The first run downloads ~6 GB of Boltz-1 model weights automatically.

### Mosaic
```bash
mosaic
```
Then open a notebook:
```bash
marimo edit examples/example_notebook.py
```
Custom notebooks can be placed in `bindmaster_examples/` at the repo root — the installer copies them to `Mosaic/examples/bindmaster_examples/` automatically.

---

## Test environment (Docker)

A Docker-based test environment simulates a fresh DGX Spark (Ubuntu 24.04 + Miniforge, aarch64):

```bash
# Build image and drop into an interactive shell
./test_env.sh

# Force rebuild of the Docker image
./test_env.sh --rebuild

# Pass GPU access to the container
./test_env.sh --gpu

# Don't mount the OLD tools dir (tests the download fallback)
./test_env.sh --no-old

# Remove artifacts created by previous test runs
./test_env.sh --clean
```

Inside the container:
```bash
# Full install (Mosaic only, using cached tools)
./install_aarch.sh --tool mosaic --tools-dir /old-tools

# Non-interactive install with examples
./install_aarch.sh --tool mosaic --tools-dir /old-tools --yes
```

---

## Reinstalling a tool

Re-run the installer and answer **Y** when prompted to remove the existing directory and/or conda environment:

```bash
# General
bash install.sh --tool bindcraft

# aarch64
./install_aarch.sh --tool bindcraft
```

---

## Troubleshooting

**BindCraft example crashes with "Out of memory"**
JAX pre-allocates 75% of VRAM by default. Set this variable to let it grow on demand:
```bash
XLA_PYTHON_CLIENT_PREALLOCATE=false python -u ./bindcraft.py ...
```
The installer sets this automatically for the bundled example.

**BindCraft smoke test fails after install**
Verify that `params/` inside the BindCraft directory contains `.npz` weight files. If the AF2 download was interrupted, reinstall BindCraft.

**BoltzGen model download fails on first example run**
BoltzGen downloads Boltz-1 weights (~6 GB) on first use, not during install. Re-run the command — it resumes from where it stopped.

**`uv` not found after Mosaic install**
Open a new terminal, or run:
```bash
source ~/.bashrc
```

**A tool failed but others succeeded**
The installer continues with remaining tools on failure. Re-run with just the failed tool:
```bash
bash install.sh --tool <toolname>         # x86_64
./install_aarch.sh --tool <toolname>      # aarch64
```

**Checking what's installed**
```bash
conda env list              # shows BindCraft and BoltzGen envs
ls ~/.local/bin/            # shows bindcraft, boltzgen, mosaic shortcuts
```
