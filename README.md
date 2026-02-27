# BindMaster

A toolkit for GPU-accelerated protein binder design — installer, configurator, and pipeline runner in one repository.

| Tool | What it does | Environment |
|---|---|---|
| **BindCraft** | Designs protein binders for a target using AlphaFold2 | conda (Python 3.10) |
| **BoltzGen** | Generates protein structures with the Boltz-1 model | conda (Python 3.12) |
| **Mosaic** | JAX-based binder hallucination (non-interactive, fully configured) | uv venv |

---

## Repository structure

```
BindMaster/
├── install.sh              ← installs BindCraft, BoltzGen, and/or Mosaic
├── configurator.py         ← wizard: configure targets and run pipelines
├── bindmaster_examples/    ← Mosaic non-interactive script (copied on install)
├── BindCraft/              ← installed tool (gitignored)
├── BoltzGen/               ← installed tool (gitignored)
├── Mosaic/                 ← installed tool (gitignored)
└── runs/                   ← generated run folders (gitignored)
```

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/damborik22/BindMaster.git ~/BindMaster
cd ~/BindMaster

# 2. Install tools
bash install.sh

# 3. Configure a run and optionally launch it
python configurator.py
```

---

## Configurator

`configurator.py` is an interactive wizard that:

1. Asks for a target name, PDB file, chain, and hotspot residues
2. Lets you set global binder length and design count, with per-tool overrides
3. Lets you enable/disable each tool (BindCraft, BoltzGen, Mosaic)
4. Shows a preview of the run folder structure
5. Writes all config files and shell scripts
6. Optionally runs the full pipeline immediately

```bash
# Via shortcut (installed automatically on first run)
bindmaster-config

# Or directly
python ~/BindMaster/configurator.py
```

### What gets generated

```
runs/<name>/
├── target/<name>.pdb
├── mosaic/
│   └── hallucinate.py          ← non-interactive, all params injected
├── boltzgen/
│   ├── config.yaml
│   └── outputs/
├── bindcraft/
│   ├── target_settings.json
│   ├── filters.json
│   ├── advanced.json
│   └── outputs/
├── run_mosaic.sh
├── run_boltzgen.sh
├── run_bindcraft.sh
└── run_all.sh                  ← runs all enabled tools in sequence
```

### Running later

```bash
bash runs/<name>/run_all.sh           # full pipeline

bash runs/<name>/run_mosaic.sh        # individual tools
bash runs/<name>/run_boltzgen.sh
bash runs/<name>/run_bindcraft.sh
```

---

## Installer

Two installers are included:

| Installer | Target platform |
|---|---|
| `install.sh` | Any x86_64 Linux with NVIDIA GPU |
| `install_aarch.sh` | NVIDIA DGX Spark / Grace-Hopper (aarch64) |

### Requirements

- Linux with an NVIDIA GPU
- CUDA driver ≥ 12.1
- Miniconda, Anaconda, or Miniforge installed
- `git` available in PATH
- ~60 GB free disk space

### Running the installer

```bash
bash install.sh
```

The installer opens an **interactive menu** — all three tools are pre-selected:

```
  Select tools to install
  Type a number to toggle selection, then press Enter when done.

    1)  [x]  BindCraft     not installed   Binder design via AlphaFold2 (conda, Python 3.10)
    2)  [x]  BoltzGen      not installed   Structure generation with Boltz-1 (conda, Python 3.12, ~6 GB download)
    3)  [x]  Mosaic        not installed   JAX-based protein design (uv venv)

  a) Select all   n) Select none   Enter to confirm
```

### Non-interactive options

```bash
bash install.sh --tool bindcraft
bash install.sh --tool boltzgen
bash install.sh --tool mosaic
bash install.sh --tool all
bash install.sh --skip-examples
bash install.sh --cuda 12.1        # override CUDA version (default: 12.4)
```

### What happens during installation

Each tool goes through:

1. **Clone** — repo cloned into `~/BindMaster/<Tool>/`
2. **Environment** — conda env or uv venv created and packages installed (spinner shown, full log in `install.log`)
3. **Smoke test** — minimal import or `--help` call
4. **Example** (optional) — bundled example run
5. **Shortcut** — launcher written to `~/.local/bin/`

| Tool | Example | Notes |
|---|---|---|
| BindCraft | 1 PDL1 binder design | Live output |
| BoltzGen | 2 designs of protein 1g13 | Downloads ~6 GB weights on first run |
| Mosaic | Opens example notebook | Browser URL printed |

---

## DGX Spark / aarch64

```bash
./install_aarch.sh
./install_aarch.sh --tool mosaic
./install_aarch.sh --tool all --yes     # non-interactive
```

### aarch64 notes

- **BindCraft**: ARM64 binaries (`DAlphaBall.gcc`, `dssp`) are bundled in `tools/aarch64/` and copied automatically.
- **BoltzGen**: Plain `pip install torch==2.5.1` (aarch64 wheels include CUDA — no `+cu121` suffix).
- **Mosaic**: `esmj` excluded on aarch64 (no wheel available).

---

## Monitoring installs

```bash
tail -f install.log         # x86_64
tail -f install_aarch.log   # aarch64
```

---

## Shortcuts

After installation, each tool has a launcher in `~/.local/bin/`:

```bash
bindcraft          # activates BindCraft conda env, cd to BindCraft dir
boltzgen           # activates BoltzGen conda env, cd to BoltzGen dir
mosaic             # activates Mosaic uv venv, cd to Mosaic dir
bindmaster-config  # runs configurator.py
```

---

## Reinstalling a tool

```bash
bash install.sh --tool bindcraft
```

Answer **Y** when prompted to remove the existing directory and conda environment.

---

## Troubleshooting

**BindCraft smoke test fails**
Check that `BindCraft/params/` contains `.npz` weight files. If the AF2 download was interrupted, reinstall BindCraft.

**BoltzGen model download fails**
BoltzGen downloads Boltz-1 weights (~6 GB) on first use. Re-run — it resumes automatically.

**`uv` not found after Mosaic install**
```bash
source ~/.bashrc
```

**A tool failed but others succeeded**
Re-run with just the failed tool:
```bash
bash install.sh --tool <toolname>
```

**Checking what's installed**
```bash
conda env list          # shows BindCraft and BoltzGen envs
ls ~/.local/bin/        # shows shortcuts
```
