[![CI](https://github.com/damborik22/BinderScout/actions/workflows/ci.yml/badge.svg)](https://github.com/damborik22/BinderScout/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Linux%20x86__64%20%7C%20aarch64-lightgrey.svg)]()

# BinderScout

A unified toolkit for GPU-accelerated protein binder design — installer, configurator, and evaluator in one repository.

> **Renamed from *BindMaster*.** This project was developed under the internal working name *BindMaster* and is now being released as **BinderScout**. The codebase still uses `bindmaster` in many places — the CLI command (`bindmaster install`, `bindmaster configure`, `bindmaster evaluate`), several conda env names (`bindmaster_pxdesign`, `bindmaster_protein_hunter`, `bindmaster_rfd3`), file and directory names (`bindmaster_examples/`, `bindmaster.py`), and environment variables (`BINDMASTER_*`). These are equivalent to the new name and will be migrated incrementally; functional behavior is unchanged. The GitHub remote is now `damborik22/BinderScout` (the old `damborik22/BindMaster` URL redirects).

---

## Components

| Component | What it does | Runs in |
|---|---|---|
| `bindmaster install` | Installs design tools (BindCraft, BoltzGen, Mosaic, PXDesign, Proteina-Complexa, Protein-Hunter, RFD3) and opt-in eval engines (AF3, ESMFold2, SoluProt) | bash |
| `bindmaster configure` | Interactive wizard: target → configs → run scripts | system Python |
| `bindmaster evaluate` | Parse tool outputs, optionally screen with SoluProt, refold with Boltz-2 / Protenix / AF3 / ESMFold2, rank by `agreement_count` × `ipsae_min`, generate HTML report | Mosaic uv venv |

### Installed tools

| Tool | What it does | Environment | Platform |
|---|---|---|---|
| **BindCraft** | AF2 hallucination + ProteinMPNN + PyRosetta filtering | conda env `BindCraft` (Python 3.10) | x86_64 |
| **BoltzGen** | Boltz-1 diffusion structure generation | conda env `BoltzGen` (Python 3.12) | x86_64 + aarch64 |
| **Mosaic** | JAX / Boltz-2 gradient hallucination | uv venv `Mosaic/.venv` (Python 3.12) | x86_64 |
| **PXDesign** | Protenix-based de novo design (diffusion + MPNN + AF2 eval) | conda env `bindmaster_pxdesign` (Python 3.11) | x86_64 + aarch64 |
| **Proteina-Complexa** | NVIDIA flow matching + inference-time optimisation (best-of-N, beam, MCTS) | uv venv `Proteina-Complexa/.venv` (Python 3.12) | x86_64 (aarch64 needs patches) |
| **Protein-Hunter** | Boltz-2 / Chai-1 hallucination across 6 modalities (protein / cyclic / ligand CCD / ligand SMILES / DNA / RNA) | conda env `bindmaster_protein_hunter` (Python 3.10) | x86_64 |
| **RFD3** | RosettaCommons foundry diffusion (RFdiffusion3 + ProteinMPNN, BSD-3, commercial-use OK) | conda env `bindmaster_rfd3` (Python 3.12) | x86_64 + aarch64 |

> Each tool runs in its own isolated environment. Environments must not be mixed.

### Evaluator engines & filters

The evaluator (`bindmaster evaluate` / `binder-compare`) runs on top of the design tools. Boltz-2 rides the Mosaic venv; Protenix rides the PXDesign env; AF3 and ESMFold2 have their own opt-in envs. SoluProt is a sequence-only solubility screen that runs **before** refolding so unsoluble designs can be dropped from the FASTA without burning GPU time.

| Engine / filter | Role | Environment | Platform | Opt-in flag |
|---|---|---|---|---|
| **Boltz-2** | Primary refold engine; default ranking reference | `Mosaic/.venv` (rides Mosaic install) | x86_64 + aarch64 | (auto) |
| **Protenix v0.5.0** | Optional 2nd refold engine; ByteDance AF3 re-impl | `bindmaster_pxdesign` (rides PXDesign install) | x86_64 + aarch64 | (auto-detect) |
| **AlphaFold 3 v3.0.2** | Optional 3rd refold engine; canonical 2nd opinion on big-VRAM hosts | conda env `binder-eval-af3` (Python 3.10, gated weights) | x86_64 + aarch64; needs ≥100 GB GPU memory | `--tool af3` |
| **ESMFold2** | Optional 4th refold engine; lightweight, no gated weights | conda env `binder-eval-esmfold2` (Python 3.10) | x86_64 + aarch64 | `--tool esmfold2` |
| **SoluProt 1.0** | Sequence-only *E. coli* solubility screen (Hon et al. 2021); filter, not a re-ranker | conda env `binder-eval-soluprot` (Python 3.7, scikit-learn 0.20.1) | x86_64 only (USEARCH x86 binary; aarch64 deferred — see [docs/PLAN_soluprot_integration.md](docs/PLAN_soluprot_integration.md)) | `--tool soluprot` |

### Architecture

```mermaid
flowchart LR
    Input["Target structure\n(.pdb / .mmcif)"]
    Config["Configurator\nwizard → run scripts"]

    subgraph Design["Design tools (configurator domain — run via run_all.sh)"]
        BC["BindCraft\n(AF2 + MPNN + PyRosetta)"]
        BG["BoltzGen\n(Boltz-1 diffusion)"]
        MosaicT["Mosaic\n(JAX + Boltz-2 hallucination)"]
        PX["PXDesign\n(Protenix + MPNN + AF2 eval)"]
        PC["Proteina-Complexa\n(flow matching + ITO)"]
        PH["Protein-Hunter\n(Boltz-2 / Chai-1, 6 modalities)"]
        RFD3T["RFD3\n(foundry diffusion + MPNN)"]
    end

    Extract["Extractors\n(one per tool →\nunified FASTA +\nnative_metrics.csv sidecar)"]

    SoluProt["SoluProt 1.0\n(sequence-only solubility screen,\nbinder-eval-soluprot env;\nx86 only, opt-in)"]

    Drop[("Drop\nbelow threshold\n(--soluprot-filter)")]

    subgraph Refold["Refolding engines (evaluator domain — independent cross-validation)"]
        Boltz2["Boltz-2\n(Mosaic venv;\nprimary engine)"]
        Protenix["Protenix v0.5.0\n(bindmaster_pxdesign;\nfits 24 GB GPU)"]
        AF3["AF3 v3.0.2\n(binder-eval-af3;\nneeds ≥100 GB GPU)"]
        ESMFold2["ESMFold2\n(binder-eval-esmfold2;\nlightweight, no gated weights)"]
    end

    Report["Report generator\nranked HTML + CSV\n(adaptyv_rank → quality_tier →\nagreement_count → ipsae_min;\nnative_* columns from extract)"]

    Input --> Config
    Config --> Design
    Design -->|tool-specific outputs| Extract
    Extract -->|FASTA of binders| SoluProt
    SoluProt -->|filtered FASTA<br/>(if --soluprot-filter)| Drop
    SoluProt -->|FASTA + soluprot_results.csv| Boltz2
    SoluProt --> Protenix
    SoluProt --> AF3
    SoluProt --> ESMFold2
    Boltz2 --> Report
    Protenix --> Report
    AF3 --> Report
    ESMFold2 --> Report
```

Three of the four refolding engines are opt-in (Protenix auto-detects from a PXDesign install; AF3 and ESMFold2 are explicit `--tool` flags). SoluProt is fully opt-in and acts as a filter, never as a re-ranker — its `soluprot_score` and `soluprot_passes` columns show up in `metrics.csv` alongside the refold scores so users can sort on them if they want.

### Components at a glance

```mermaid
flowchart TB
    classDef gen fill:#bbdefb,stroke:#1976d2,color:#0d47a1
    classDef eng fill:#c8e6c9,stroke:#388e3c,color:#1b5e20
    classDef opt fill:#fff9c4,stroke:#fbc02d,color:#5d4037
    classDef cli fill:#e1bee7,stroke:#7b1fa2,color:#311b92
    classDef arti fill:#cfd8dc,stroke:#455a64,color:#212121

    CLI["bindmaster\n(unified CLI, stdlib only)"]:::cli

    CLI -->|install| InstallSh["install.sh\n(x86) / install_aarch.sh\n(aarch64 / DGX Spark)"]
    CLI -->|configure| Configurator["configurator/\nconfigurator.py\n(5-step wizard)"]
    CLI -->|evaluate| EvaluateSh["Evaluator/\nevaluate.sh\n(orchestrator)"]

    subgraph GenEnvs["Design-tool environments (one per tool)"]
        EnvBC["BindCraft<br/>(conda, py3.10)"]:::gen
        EnvBG["BoltzGen<br/>(conda, py3.12)"]:::gen
        EnvMo["Mosaic/.venv<br/>(uv, py3.12)"]:::gen
        EnvPX["bindmaster_pxdesign<br/>(conda, py3.11)"]:::gen
        EnvPC["Proteina-Complexa/.venv<br/>(uv, py3.12)"]:::gen
        EnvPH["bindmaster_protein_hunter<br/>(conda, py3.10)"]:::gen
        EnvRF["bindmaster_rfd3<br/>(conda, py3.12)"]:::gen
    end

    subgraph EvalEnvs["Evaluator-side environments"]
        EnvEv["binder-eval<br/>(conda, py3.10) — extract + report"]:::eng
        EnvAF3["binder-eval-af3<br/>(conda, py3.10) — AF3 v3.0.2"]:::opt
        EnvESM["binder-eval-esmfold2<br/>(conda, py3.10) — ESMFold2"]:::opt
        EnvSP["binder-eval-soluprot<br/>(conda, py3.7) — SoluProt 1.0"]:::opt
    end

    subgraph Artifacts["Per-run artifacts"]
        Runs["runs/&lt;name&gt;/\n├── target/\n├── &lt;tool&gt;/        # one per enabled tool\n│   └── settings.json\n├── evaluate/\n│   ├── sequences.fasta\n│   ├── sequences_native_metrics.csv\n│   ├── boltz2_results.csv\n│   ├── protenix_results.csv      (opt)\n│   ├── af3_results.csv           (opt)\n│   ├── esmfold2_results.csv      (opt)\n│   ├── soluprot_results.csv      (opt)\n│   └── report/\n│       ├── metrics.csv\n│       ├── top20_candidates.csv\n│       ├── top20_structures/\n│       └── report.html\n├── run_&lt;tool&gt;.sh\n├── run_evaluate.sh\n└── run_all.sh"]:::arti
    end

    InstallSh -->|creates| GenEnvs
    InstallSh -->|creates| EvalEnvs
    Configurator -->|writes| Runs
    EvaluateSh -->|orchestrates| Runs
    EvaluateSh -->|conda run -n …| EvalEnvs
```

Solid blue boxes are the seven design tools' isolated environments; green / yellow boxes are the four evaluator environments (the three yellow ones are opt-in via `--tool af3 / esmfold2 / soluprot`). The grey panel shows the per-run output layout the configurator generates and `evaluate.sh` fills in.

---

## Repository structure

```
BindMaster/
├── bindmaster.py               ← unified CLI entry point (system Python, stdlib only)
├── bindmaster/                 ← Python package: tool adapter base, scoring, scheduler, feature flags
├── install/
│   ├── install.sh              ← x86_64 installer
│   └── install_aarch.sh        ← aarch64 / DGX Spark installer
├── configurator/
│   └── configurator.py         ← interactive 5-step setup wizard
├── evaluator/
│   └── evaluator.py            ← lightweight output parser + Boltz-2 re-fold
├── Evaluator/                  ← bundled full evaluation pipeline package
│   ├── binder_comparison/      ← core Python package (extractors, refolding, scoring)
│   ├── scripts/                ← standalone refold scripts (refold_boltz2.py, refold_protenix.py)
│   ├── docs/                   ← pipeline reference, analysis notes
│   └── envs/                   ← conda env specs (binder-eval, binder-eval-af3 [needs ≥100 GB GPU memory])
├── .claude/
│   └── skills/                 ← Claude Code skills (bindmaster-orchestrator, bindmaster-worker)
├── scripts/                    ← helper install scripts (PXDesign)
├── tests/                      ← unit + integration tests
├── examples/                   ← example scripts (PXDesign)
├── tui/                        ← interactive TUI menu (in development)
├── docs/                       ← development plans, completed plans, environments reference, scientific notes
├── bindmaster_examples/        ← canonical run-script templates (Mosaic hallucination, RFD3, Protein-Hunter)
├── tools/
│   └── aarch64/                ← pre-built ARM64 binaries (dssp, DAlphaBall)
├── conda/                      ← local Miniforge3 (standalone mode, gitignored)
├── bin/                        ← local shortcuts (standalone mode, gitignored)
└── runs/                       ← generated run folders (gitignored)
```

Tool directories (`BindCraft/`, `BoltzGen/`, `Mosaic/`, `PXDesign/`, `Proteina-Complexa/`, `Protein-Hunter/`) are cloned by the installer and gitignored. RFD3 has no clone — it is pip-installed (`rc-foundry`) into `bindmaster_rfd3` and stores weights at `weights/foundry/`. AF3 v3.0.2 refolding runs in its own `binder-eval-af3` conda env on any host with ≥100 GB GPU memory (DGX Spark today; H200 / GH200 should also work); `refold_af3.py` is the canonical wrapper.

---

## Quick start

```bash
# 1. Clone (x86_64)
git clone https://github.com/damborik22/BindMaster.git ~/BindMaster
cd ~/BindMaster

# 2. Install tools
bindmaster install             # interactive menu
bindmaster install --tool all  # install everything

# 3. Configure a run
bindmaster configure

# 4. Run (scripts generated by configure)
bash runs/<name>/run_all.sh

# 5. Evaluate results
bindmaster evaluate runs/<name>
```

---

## `bindmaster` CLI reference

```
bindmaster install   [--tool bindcraft|boltzgen|mosaic|pxdesign|proteina-complexa|protein-hunter|rfd3|all]
                     [--tool af3|esmfold2|soluprot]    # opt-in evaluator engines / filter
                     [--cuda VERSION] [--standalone] [--system-conda] [--yes] [--skip-examples]
bindmaster configure [options passed through to configurator.py]
bindmaster evaluate  <run-dir> [--metric METRIC] [--top N] [--refold N] [--target PDB] [--all-mosaic-designs]
bindmaster evaluate  --sequences FILE  [--target PDB] [--refold N]
bindmaster --help
```

### `bindmaster install`

Options:

| Flag | Description |
|---|---|
| `--tool all\|bindcraft\|boltzgen\|mosaic\|pxdesign\|proteina-complexa\|protein-hunter\|rfd3` | Which design tool(s) to install. Omit for interactive menu. |
| `--tool af3\|esmfold2\|soluprot` | Opt-in evaluator tools. `af3` = AlphaFold 3 v3.0.2 (≥100 GB GPU, gated weights). `esmfold2` = ESMFold2 lightweight refolder. `soluprot` = solubility screen (x86 only; TMHMM + USEARCH downloads required). None of these are in `--tool all`. |
| `--cuda VERSION` | CUDA version for conda package resolution (default: 12.4) |
| `--skip-examples` | Do not prompt to run bundled examples after install |
| `--standalone` | Force local Miniforge3 install (no system conda needed) |
| `--system-conda` | Use existing system conda instead of local install |
| `--uninstall` | Remove tool environments, directories, and shortcuts |
| `--yes` / `-y` | Non-interactive mode (accept all defaults) |

### `bindmaster configure`

Interactive wizard that:
1. Asks for a target name, PDB file, chain(s), and hotspot residues
2. Sets global binder length and design count, with per-tool overrides
3. Lets you enable/disable each current-generation tool (Mosaic, BoltzGen, BindCraft, PXDesign, Proteina-Complexa, Protein-Hunter, RFD3)
4. Writes all config files and shell scripts into `runs/<name>/`
5. Optionally runs the full pipeline immediately

```bash
bindmaster configure
bindmaster configure --status     # show all runs and completion state
bindmaster configure --archive <run>  # tar.gz a run directory
```

#### What gets generated

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
├── pxdesign/
├── proteina_complexa/
├── protein_hunter/
├── rfd3/
├── run_mosaic.sh
├── run_boltzgen.sh
├── run_bindcraft.sh
├── run_pxdesign.sh
├── run_proteina_complexa.sh
├── run_protein_hunter.sh
├── run_rfd3.sh
├── run_evaluate.sh
└── run_all.sh                  ← runs all enabled tools in sequence
```

Each per-tool run script writes a `runs/<name>/<tool>/settings.json` capturing tool version, design parameters, target sequence, and GPU info before the design step begins — so a run is self-describing without grepping the parent script (which may have been edited since).

### `bindmaster evaluate`

Parses design outputs from any combination of tools,
cross-ranks all designs by a configurable metric, and writes a summary.

**Refolding engines (canonical pipeline):**

| Engine | CLI subcommand | Env | Where it runs |
|---|---|---|---|
| **Boltz-2** | `binder-compare refold-boltz2` | Mosaic `.venv` | Anywhere with a 24 GB GPU |
| **AF3 v3.0.2** | `binder-compare refold-af3` | `binder-eval-af3` conda | Any host with ≥100 GB GPU memory — DGX Spark (aarch64), H200 (x86_64), GH200, etc. Full AF3 inference doesn't fit on consumer 24 GB GPUs. |

Cross-engine columns are namespaced (`boltz_pae_*`, `af3_*`). The `agreement_count` column (0–2 wherever AF3 is available, 0–1 otherwise) counts engines whose `ipsae_min > 0.61` and is the primary tiebreaker after `ipsae_min`. Both engines compute iPSAE via the DunbrackLab 2025 formula. AF3 produces token-order PAE which the evaluator transposes to match Boltz-2's `[binder|target]` order.

> Protenix v0.5.0 (`binder-compare refold-protenix`) is wired into the Evaluator package as an optional 3rd engine but is **not part of our canonical evaluation** — we run Boltz-2 + AF3. Enable it explicitly via `evaluate.sh` if you want the extra signal.

#### Run-directory mode

```bash
bindmaster evaluate runs/PDL1_test
bindmaster evaluate runs/PDL1_test --metric ipsae_min --top 20
bindmaster evaluate runs/PDL1_test --refold 5 --target runs/PDL1_test/target/PDL1.pdb
bindmaster evaluate runs/PDL1_test --all-mosaic-designs  # include all ~800 Mosaic designs
```

Output written to `runs/<name>/evaluation/`:
- `summary.csv` — all designs merged and ranked
- `report.txt` — top-N with key metrics
- `refolded/` — Boltz-2 PDB structures (if `--refold N` used)

#### Sequence-only mode

Re-fold a list of bare sequences from any source without a run directory:

```bash
# From a file (one sequence per line, # comments OK)
bindmaster evaluate --sequences my_seqs.txt --refold 3 --target target.pdb

# From stdin
echo "MAEVKLSYVL..." | bindmaster evaluate --sequences - --refold 1
```

#### Ranking metrics

| Metric | Direction | Notes |
|---|---|---|
| `ipsae_min` | higher = better | **Primary metric.** min(bt, tb) iPSAE (DunbrackLab 2025) |
| `iptm` | higher = better | Interface pTM |
| `bt_ipsae` | higher = better | Binder-to-target iPSAE |
| `tb_ipsae` | higher = better | Target-to-binder iPSAE |
| `ranking_loss` | lower = better | Mosaic design-stage ranking loss |
| `plddt_binder_mean` | higher = better | Mean binder pLDDT |
| `pae_bt_mean` | lower = better | Mean binder-to-target PAE |

---

## Installer details

### Requirements

- Linux with an NVIDIA GPU (CUDA driver >= 12.1)
- `git` and `curl` available in PATH
- ~60 GB free disk space
- Conda/Miniforge is **not required** — the installer downloads Miniforge3 automatically if needed

### What happens during install

Each tool goes through:
1. **Clone** — repo cloned at a pinned commit into `BindMaster/<Tool>/`
2. **Environment** — conda env or uv venv created (spinner + full log)
3. **Smoke test** — minimal import or `--help` call
4. **Example** (optional, skippable) — bundled example run
5. **Shortcut** — launcher written to `BindMaster/bin/`

### Non-interactive options

```bash
bash install/install.sh --tool all --yes --skip-examples
bash install/install.sh --tool mosaic
bash install/install.sh --cuda 12.1
bash install/install.sh --uninstall --tool all
```

### Server / HPC installation (no admin required)

BindMaster works fully standalone — no system conda, no admin, no writes outside the project directory:

```bash
git clone https://github.com/damborik22/BindMaster.git
cd BindMaster
python3 bindmaster.py install --tool all --yes

# Add to PATH:
export PATH="$(pwd)/bin:$PATH"
echo 'export PATH="/path/to/BindMaster/bin:$PATH"' >> ~/.bashrc
```

The installer auto-detects if system conda is unavailable or read-only and downloads
Miniforge3 into `BindMaster/conda/`. All environments and shortcuts stay inside the
project directory. To remove everything: `rm -rf BindMaster/`.

---

## Platform / branch

| Branch | Platform | Installer |
|---|---|---|
| `master` | x86_64 Linux + NVIDIA GPU | `install/install.sh` |
| `aarch64` | NVIDIA DGX Spark / Grace-Hopper | `install/install_aarch.sh` |

```bash
# x86_64
git clone https://github.com/damborik22/BindMaster.git

# aarch64 / DGX Spark
git clone -b aarch64 https://github.com/damborik22/BindMaster.git
```

Both branches: `bindmaster install` or `bash install/install.sh`.

### aarch64 notes

- **BindCraft**: ARM64 binaries (`DAlphaBall.gcc`, `dssp`) bundled in `tools/aarch64/` — copied automatically. May fail at smoke-test time because jaxlib CUDA conda packages are not yet available for aarch64.
- **BoltzGen**: PyTorch installed from PyPI without `+cuXXX` suffix (aarch64 wheels already include CUDA).
- **Mosaic**: `esmj` excluded (no aarch64 wheel). `torchtext` may also fail (no Linux aarch64 wheel).
- **PXDesign**: Full pipeline works on aarch64 / Blackwell. The installer applies automatic patches for CUDA arch compatibility (sm_120), JSON serialization (`NumpyEncoder`), and dataloader (`num_workers`) config.
- **Proteina-Complexa**: May need patches — PyTorch Geometric and `torchtext` may lack aarch64 wheels. Core deps (PyTorch 2.7, JAX 0.4.29) are fine. Same approach as Mosaic: mark missing packages with `platform_machine != 'aarch64'` in `pyproject.toml`.
- **Protein-Hunter**: **Not supported on aarch64** — PyRosetta has no aarch64 wheels. The installer prints a warning and skips it.
- **RFD3**: Fully supported on aarch64 — `rc-foundry` is pip-installed, no DGL dependency.
- **AF3 refolding**: Live on aarch64 / DGX Spark via the `binder-eval-af3` conda env and `binder-compare refold-af3`. Not aarch64-exclusive — AF3 runs anywhere with ≥100 GB GPU memory (an H200, GH200, etc. should work too); DGX Spark is just our primary host because Spark is where the unified memory headroom lives.

---

## Shortcuts

After installation, launchers are available in `BindMaster/bin/`:

```bash
bindmaster         # unified CLI (install / configure / evaluate)
bindcraft          # activates BindCraft conda env, cd to BindCraft dir
boltzgen           # activates BoltzGen conda env, cd to BoltzGen dir
mosaic             # activates Mosaic uv venv, cd to Mosaic dir
pxdesign           # activates PXDesign conda env
complexa           # activates Proteina-Complexa venv
protein-hunter     # activates Protein-Hunter conda env
rfd3               # runs `rfd3 design ...` or opens the bindmaster_rfd3 env shell
evaluate           # runs Evaluator/run.sh wizard
bindmaster-config  # runs configurator directly (legacy)
```

---

## Reinstalling a tool

```bash
bindmaster install --tool bindcraft
```

Answer **Y** when prompted to remove the existing directory and conda environment.

---

## Monitoring installs

```bash
tail -f ~/BindMaster/install.log         # x86_64
tail -f ~/BindMaster/install_aarch.log   # aarch64
```

---

## Troubleshooting

**BindCraft smoke test fails**
Check `BindCraft/params/` contains `.npz` weight files. If the AF2 download was interrupted, reinstall.

**BoltzGen model download fails**
BoltzGen downloads Boltz-1 weights (~6 GB) on first use. Re-run — it resumes automatically.

**`uv` not found after Mosaic install**
```bash
source ~/.bashrc
```

**`bindmaster evaluate` — Mosaic must be installed**
```bash
bindmaster install --tool mosaic
```

**A tool failed, others succeeded**
```bash
bindmaster install --tool <toolname>
```

**Checking what's installed**
```bash
conda env list                    # shows conda-managed envs
ls BindMaster/bin/                # shows shortcuts
ls BindMaster/conda/envs/         # shows local envs (standalone mode)
```

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for code style, testing, and PR conventions.

### Linting

```bash
ruff check .                # Python lint
ruff format --check .       # Python format check
shellcheck --shell=bash --severity=warning install/install.sh install/install_aarch.sh
```

### Testing

```bash
docker build -f Dockerfile.test --target base -t bindmaster-test .
docker run --rm -it bindmaster-test bash
./test_env.sh --dry-run     # non-interactive validation
./test_env.sh --gpu         # with GPU
```

---

## License

[MIT](LICENSE)
