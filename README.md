# BindMaster

A unified installer for three GPU-accelerated protein design tools:

| Tool | What it does | Environment |
|---|---|---|
| **BindCraft** | Designs protein binders for a target using AlphaFold2 | conda (Python 3.10) |
| **BoltzGen** | Generates protein structures with the Boltz-1 model | conda (Python 3.12) |
| **Mosaic** | Interactive protein design via Marimo notebooks + JAX | uv venv |

---

## Requirements

- Linux with an NVIDIA GPU
- CUDA driver ≥ 12.1
- Miniconda/Anaconda installed at `~/miniconda3`
- `git` available in PATH
- ~60 GB free disk space (conda envs + model weights)
- Stable internet connection

---

## Running the installer

```bash
cd ~/BindMaster
bash install.sh
```

The installer opens an **interactive menu** — all three tools are pre-selected:

```
  Select tools to install
  Type a number to toggle selection, then press Enter when done.

    1)  [x]  BindCraft     Binder design via AlphaFold2 (conda, Python 3.10)
    2)  [x]  BoltzGen      Structure generation with Boltz-1 (conda, Python 3.12, ~6 GB download)
    3)  [x]  Mosaic        JAX-based protein design with Marimo notebooks (uv venv)

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

### Stage 1 — Git clone
Clones the tool's repository into `~/BindMaster/<Tool>/`. Takes a few seconds.

If the directory already exists, the installer asks whether to remove and reclone, or keep what's there.

### Stage 2 — Environment setup

Package installation runs silently behind a spinner — all the verbose conda/pip/uv output goes to `install.log` only, keeping the terminal readable:

```
  \  Installing BindCraft (conda packages + AlphaFold2 weights)...
✓ Installing BindCraft (conda packages + AlphaFold2 weights)
```

**BindCraft** — conda env (Python 3.10) with JAX, PyRosetta, ColabDesign, and CUDA libraries.

**BoltzGen** — conda env (Python 3.12) with PyTorch (CUDA 12.1), gcc (required by Triton for GPU kernel compilation), and the BoltzGen package.

**Mosaic** — `uv` virtual environment at `~/BindMaster/Mosaic/.venv/`. If `uv` is not installed, the official installer runs automatically.

### Stage 3 — AlphaFold2 weights (BindCraft only)
Downloads ~4.5 GB from Google storage and extracts 15 `.npz` model weight files into `~/BindMaster/BindCraft/params/`. Runs behind the spinner. Do not interrupt — a partial download requires reinstall.

### Stage 4 — Smoke test
A minimal import or `--help` call verifies the environment is working. If this fails the tool is marked as failed in the summary.

### Stage 5 — Example (optional)
If you did not use `--skip-examples`, the installer asks whether to run the bundled example for each tool. You can safely say **N** — the tools are fully installed either way. **An example failure does not mark the tool as failed.**

| Tool | Example | What you see |
|---|---|---|
| BindCraft | 1 PDL1 binder design | Live Python output, as if run in terminal |
| BoltzGen | 2 designs of protein 1g13 | Live output; downloads ~6 GB weights on first run |
| Mosaic | Example notebook | Opens in browser; press **Enter** in terminal to close and continue |

### Stage 6 — Shortcut
A launcher script is written to `~/.local/bin/` for each tool. These are already in your PATH.

---

## Expected total time

| Tool | Typical install time |
|---|---|
| BindCraft | 45–90 minutes |
| BoltzGen | 20–40 minutes |
| Mosaic | 5–15 minutes |
| All three | 60–120 minutes |

The installers run **sequentially** — BindCraft first, then BoltzGen, then Mosaic.

---

## Monitoring progress

Package installs show only a spinner on the terminal. To see the full verbose output live:

```bash
tail -f ~/BindMaster/install.log
```

Example runs (BindCraft, BoltzGen) print directly to the terminal so you can follow what the model is doing in real time.

---

## Installation summary

At the end the installer prints two separate sections:

```
✓ All selected tools installed successfully.
⚠ Examples failed (tools themselves are usable): BindCraft
  Check the log for details: ~/BindMaster/install.log
```

Installation failures and example failures are reported independently. A failed example means the tool installed correctly but the test run hit an error (e.g. GPU out of memory).

---

## After installation

Each tool gets a shortcut command that activates its environment and drops you into an interactive shell:

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
Target JSON files live in `~/BindMaster/BindCraft/settings_target/`. The installer automatically patches these files to use local paths (the upstream repo ships with Google Colab paths).

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
This starts a local web server and opens the notebook in your browser.

---

## Reinstalling a tool

Re-run the installer and answer **Y** when prompted to remove the existing directory and/or conda environment:

```bash
bash install.sh --tool bindcraft
```

---

## Troubleshooting

**BindCraft example crashes with "Out of memory"**
JAX's default behaviour is to pre-allocate 75% of GPU VRAM. Set this variable to disable pre-allocation and let it grow on demand:
```bash
XLA_PYTHON_CLIENT_PREALLOCATE=false python -u ./bindcraft.py ...
```
The installer already sets this automatically when running the bundled example.

**BindCraft smoke test fails after install**
Verify that `~/BindMaster/BindCraft/params/` contains `.npz` weight files. If the AlphaFold2 download was interrupted, reinstall BindCraft.

**BoltzGen model download fails on first example run**
BoltzGen downloads Boltz-1 weights (~6 GB) on first use, not during install. If it fails mid-download, re-run the command — it will resume from where it stopped.

**`uv` not found after Mosaic install**
Open a new terminal (the PATH update takes effect in new sessions), or run:
```bash
source ~/.bashrc
```

**A tool failed but others succeeded**
The installer continues with remaining tools on failure. Re-run with just the failed tool:
```bash
bash install.sh --tool <toolname>
```

**Checking what's installed**
```bash
conda env list              # shows BindCraft and BoltzGen envs
ls ~/BindMaster/            # shows cloned directories
ls ~/.local/bin/            # shows bindcraft, boltzgen, mosaic shortcuts
```
