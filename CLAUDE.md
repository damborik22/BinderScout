# CLAUDE.md — BindMaster / BoltzGen Pipeline

## Overview

BindMaster is a unified toolkit for GPU-accelerated **protein binder design**. It wraps three independent design tools (BindCraft, BoltzGen, Mosaic) behind a single CLI (`bindmaster`) that handles installation, interactive configuration, execution, and cross-tool evaluation of designed binders.

**Current status:** v0.7.0 (Part H complete). Active development on the `master` branch. The `aarch64` branch tracks DGX Spark / Grace-Hopper support and is periodically rebased from master.

**Repository:** `github.com/damborik22/BindMaster`

---

## Architecture

### Pipeline flow

```
Target structure (.pdb / .mmcif)
  → Configurator wizard (interactive, generates configs + run scripts)
    → Design tools run in sequence:
       Mosaic (JAX + Boltz-2 hallucination)
       BoltzGen (Boltz-1 diffusion)
       BindCraft (AF2 + MPNN + PyRosetta)
       PXDesign (Protenix, optional)
       Proteina-Complexa (NVIDIA flow matching, optional)
    → Evaluator:
       1. Extract sequences from all tool outputs
       2. Refold with Boltz-2 (Mosaic venv)
       3. (x86) Refold with Protenix (bindmaster_pxdesign env)  [Part J, in progress]
       4. (aarch64 / DGX Spark) Refold with AlphaFold 3 v3.0.2 (binder-eval-af3)  [Part K, in progress]
       5. Rank, score, and generate HTML report
```

### Directory layout

```
BindMaster/
├── bindmaster.py              ← unified CLI entry point (system Python, stdlib only)
├── install/
│   ├── install.sh             ← x86_64 installer (master branch)
│   └── install_aarch.sh       ← aarch64 / DGX Spark installer
├── conda/                     ← LOCAL Miniforge3 (standalone mode, gitignored)
├── bin/                       ← LOCAL shortcuts (standalone mode, gitignored)
├── configurator/
│   └── configurator.py        ← interactive 5-step setup wizard (~1700 lines)
├── evaluator/
│   └── evaluator.py           ← lightweight evaluator (Mosaic venv, ~780 lines)
├── Evaluator/                 ← bundled full evaluation pipeline package
│   ├── binder_comparison/     ← core Python package (extractors, refolding, scoring, viz)
│   ├── scripts/               ← standalone refold scripts (refold_boltz2.py, refold_protenix.py [todo], refold_af3.py [todo])
│   ├── evaluate.sh            ← shell orchestrator for full 4-step pipeline
│   ├── envs/                  ← conda env specs (binder-eval.yml, binder-eval-af3.yml [aarch64 only, todo])
│   ├── docs/                  ← pipeline_reference.md (metrics, known issues)
│   └── pyproject.toml         ← package: "binder-comparison" v0.1.0
├── bindmaster_examples/
│   └── hallucinate_bindmaster.py  ← Mosaic template (copied into Mosaic/ on install)
├── tools/
│   └── aarch64/               ← pre-built ARM64 binaries (DAlphaBall, dssp)
├── .github/workflows/ci.yml  ← shellcheck + ruff + Docker build
├── test_env.sh                ← Docker test environment launcher
├── Dockerfile.test            ← CUDA 12.4, Ubuntu 22.04, Miniforge
├── docker-entrypoint.sh       ← container init (conda, HOME setup)
├── ruff.toml                  ← Python linting/formatting config
├── STAGES.md                  ← implementation milestones (Parts A–G)
├── CONTRIBUTING.md            ← dev setup, PR conventions
├── CHANGELOG.md               ← Keep a Changelog format
└── LICENSE                    ← MIT
```

**Gitignored (created at runtime):**
- `BindCraft/`, `BoltzGen/`, `Mosaic/`, `rf_diffusion_all_atom/`, `LigandMPNN/`, `PXDesign/`, `Proteina-Complexa/` — cloned by installer
- `runs/` — generated experiment directories
- `install.log`, `install_aarch.log` — installer output
- `refold_boltz2/` — intermediate refolding outputs

### Environment isolation (critical)

Each tool runs in its own isolated environment. **Never mix packages across environments.**

| Environment | Tool | Python | Manager | Purpose |
|---|---|---|---|---|
| `BindCraft` | BindCraft | 3.10 | conda | AF2 + MPNN + PyRosetta binder design |
| `BoltzGen` | BoltzGen | 3.12 | conda | Boltz-1 diffusion-based generation |
| `Mosaic/.venv` | Mosaic | 3.12 | uv | JAX + Boltz-2 hallucination |
| `bindmaster_rfaa` | RFAA + LigandMPNN | 3.11 | conda | All-atom diffusion (x86_64 only) |
| `bindmaster_pxdesign` | PXDesign | 3.11 | conda | Protenix binder design + eval |
| `Proteina-Complexa/.venv` | Proteina-Complexa | 3.12 | uv | Flow matching + test-time compute binder design |
| `binder-eval` | Evaluator | 3.10 | conda | Sequence extraction + reporting |

The `bindmaster.py` CLI dispatcher uses `os.execv()` to launch sub-commands in their correct environment — `install` runs in bash, `configure` runs in system Python, `evaluate` runs in the Mosaic `.venv` Python.

In **standalone mode** (`--standalone` or auto-detected), all conda environments live under `BindMaster/conda/envs/` instead of the system conda's envs directory. This requires zero system permissions.

### Machines and platforms

| Branch | Platform | Installer | CUDA default |
|---|---|---|---|
| `master` | x86_64 Linux + NVIDIA GPU | `install/install.sh` | 12.4 |
| `aarch64` | NVIDIA DGX Spark / Grace-Hopper (GB10 Blackwell) | `install/install_aarch.sh` | 13.0 |

**aarch64 specifics:**
- BindCraft ARM64 binaries (`DAlphaBall.gcc`, `dssp`) bundled in `tools/aarch64/`
- BoltzGen: PyTorch installed from PyPI (no `+cuXXX` suffix needed)
- Mosaic: `esmj` excluded (no aarch64 wheel)
- Pre-cached AF2 weights path: `Documents/OLD/BindMaster/bindcraft-tools`

### Design decisions and WHY

- **Monorepo:** The Evaluator was merged from a separate repo (`BindMaster-evaluator`, now archived) into `Evaluator/` so the full pipeline ships in one `git clone`.
- **stdlib-only CLI:** `bindmaster.py` uses only stdlib so it works on any Python 3.10+ without pip installs.
- **uv for Mosaic:** Mosaic uses `uv` instead of conda because it needs JAX with CUDA, and uv resolves this faster and more reliably.
- **Pinned commits:** Tool repos are cloned at pinned commits (`BINDCRAFT_COMMIT`, `BOLTZGEN_COMMIT`, `MOSAIC_COMMIT`) for reproducible installs.
- **Separate evaluator envs:** Boltz-2 refolding runs in the Mosaic venv (JAX). The new Protenix refolder (Part J) rides the existing `bindmaster_pxdesign` conda env. AF3 (Part K) on DGX Spark gets its own `binder-eval-af3` env. `evaluate.sh` orchestrates all three.

---

## Conventions

### Python style

- **Minimum version:** Python 3.10 (type hints with `|` union syntax are used)
- **Linter/formatter:** ruff (configured in `ruff.toml`)
  - Line length: 120
  - Quote style: double
  - Rules: E, W, F, I, UP, B, SIM, RUF (with specific ignores)
  - Per-file: `bindmaster_examples/*.py` exempted from all rules; `Evaluator/scripts/refold_*.py` allows E402
- **Check and format:**
  ```bash
  pip install ruff
  ruff check .
  ruff format --check .
  ruff format .            # auto-format
  ```

### Shell style

- **Linter:** shellcheck (`--severity=warning`)
- When suppressing warnings, use inline `# shellcheck disable=SCXXXX` directives
- Color output uses ANSI variables: `RED`, `GREEN`, `YELLOW`, `CYAN`, `BOLD`, `RESET`
- Helper functions: `print_step()`, `print_ok()`, `print_warn()`, `print_fail()`
- Logging: `run_logged <label> <command>` runs with spinner, logs to file, shows last 30 lines on failure

### Naming

- Directories: lowercase with underscores (`configurator/`, `binder_comparison/`)
- Python files: lowercase with underscores
- Python classes: PascalCase
- Python variables/functions: snake_case
- Bash constants: UPPER_CASE
- Conda envs: BindCraft, BoltzGen, binder-eval, bindmaster_pxdesign, bindmaster_rfaa (legacy — being replaced by bindmaster_rfd3)

### Git and branching

- **Primary branch:** `master` (x86_64)
- **Platform branch:** `aarch64` (periodically rebased from master)
- **Commit style:** `Part X: description` matching STAGES.md parts, or imperative mood for smaller changes
- **PR conventions:** imperative title < 70 chars, body references STAGES.md items, CI must pass, one logical change per PR

---

## Domain Knowledge

### Key terminology

| Term | Meaning |
|---|---|
| **Binder** | A designed protein that binds to a specific target protein |
| **Target** | The protein you want to design a binder for (provided as PDB/mmCIF) |
| **Hotspot residues** | Specific residues on the target that the binder should contact |
| **Refolding** | Re-predicting structure from sequence using an independent model (cross-validation) |
| **ipTM** | Interface predicted TM-score (0–1, higher = better). Measures binding interface quality |
| **iPSAE** | Interface Predicted Structural Alignment Error (DunbrackLab 2025 formula). TM-score analogue; **higher is better** |
| **ipsae_min** | min(binder→target iPSAE, target→binder iPSAE). **Primary ranking metric** |
| **PAE** | Predicted Aligned Error (Angstroms, **lower = better**). Raw error between residue pairs |
| **pLDDT** | Predicted Local Distance Difference Test (0–1, higher = better). Per-residue confidence |
| **MPNN** | ProteinMPNN — sequence design neural network |
| **SPR** | Surface Plasmon Resonance — experimental binding measurement technique |
| **CDR** | Complementarity-Determining Region (of nanobodies/antibodies) |

### Tools and what they do

| Tool | Method | Key papers/repos |
|---|---|---|
| **BindCraft** | AF2 hallucination + MPNN sequence design + PyRosetta filtering | `martinpacesa/BindCraft` |
| **BoltzGen** | Boltz-1 structure diffusion + flow matching for binder generation | `HannesStark/boltzgen` |
| **Mosaic** | JAX-based Boltz-2 gradient hallucination (no internal AF2 cross-val) | `escalante-bio/mosaic` |
| **RFAA** | All-atom diffusion + LigandMPNN for ligand binder design | `baker-laboratory/rf_diffusion_all_atom` |
| **PXDesign** | Protenix-based de novo binder design (diffusion + MPNN + AF2 eval) | `bytedance/PXDesign` |
| **Proteina-Complexa** | Flow matching + inference-time optimization (beam search / MCTS) | `NVIDIA-Digital-Bio/proteina-complexa` |

### Evaluation metrics and ranking

**Primary metric: `ipsae_min`** — the minimum of binder→target and target→binder iPSAE scores. Computed from PAE arrays using the DunbrackLab 2025 formula: `max_i[mean_j(1/(1+(PAE_ij/d0)²))]` (d0_res variant, uniform 10 Å PAE cutoff across all engines). Ranking uses agreement_count (how many engines agree ipsae_min > 0.61) as primary sort, then ipsae_min desc.

**Direction guide:**
- **Higher is better:** `iptm`, `bt_ipsae`, `tb_ipsae`, `ipsae_min`, `plddt_binder_mean`, `binder_ptm`
- **Lower is better:** `ranking_loss`, `pae_bt_mean`, `pae_tb_mean`, `pae_bb_mean`, `pae_max`

**Quality tiers (based on `ipsae_min`):**

| Tier | Threshold | Meaning |
|---|---|---|
| High | > 0.80 | Strong candidate for experimental testing |
| Medium | 0.61 – 0.80 | Promising, may need optimization |
| Low | 0.40 – 0.61 | Weak binding prediction |
| Reject | ≤ 0.40 | Unlikely to bind |

### Critical domain facts

- **iptm is gameable** — AF2-designed sequences (BindCraft) tend to score high on ipTM by construction. Use `ipsae_min` as the primary ranking metric instead.
- **Engine disagreement is signal, not noise** — For short binders (~60aa), different refolding engines often disagree on interface quality. The `agreement_count` column reflects how many engines pass the 0.61 threshold; higher = stronger candidate.
- **Binder length is a main driver** — Longer binders tend to score lower on `ipsae_min` (r ≈ -0.78).
- **Mosaic designs.csv format** — Can mix column formats between workers (old 11-col / new 13-col). The parser must handle this carefully or columns misalign. The `is_top` column marks the ~40 refolded designs out of ~800 total; extractors filter to `is_top=1` by default.
- **Mosaic `target_sequence` placeholder** — The Mosaic template (`hallucinate_bindmaster.py`) writes `"REPLACE_ME"` as `target_sequence` when not configured. The legacy evaluator guards against using this as a real target sequence.
- **pLDDT scale** — Boltz-2 returns [0,1]; AF3 native is [0,100] and is rescaled to [0,1] on ingest by the refold runner so report columns are directly comparable.
- **PAE ordering** — Boltz-2 is native [binder|target]. AF3 is token-order so we always put target first in the input JSON, giving [target|binder] — the evaluator transposes internally. Column prefixes distinguish engines (`boltz_pae_*`, `protenix_*`, `af3_*`).
- **Append-mode CSVs** — `refold_boltz2.py` appends to CSV. If rerun after partial failure, check for duplicate `run_id` entries.

### Lab-specific information

- **AF2 weights path** (`AF2_DATA_DIR`): Must point to AlphaFold2 parameter files (~4 GB). Typically at `bindcraft-tools/af2_params`.
- **DGX Spark specifics:** CUDA 13.0, sm_121 (Blackwell), aarch64 architecture. Pre-cached resources stored at `Documents/OLD/BindMaster/bindcraft-tools`.
- **Boltz-1 weights:** ~6 GB, auto-downloaded on first BoltzGen use. Resumable.
- **Disk requirement:** ~60 GB free for full installation of all tools.

---

## Current State

### Active work and recent decisions

- **Parts A–H complete** (see STAGES.md). Latest work was Part H (standalone installer for server-friendly operation).
- **Mosaic is_top filter** (`6bfbc4f`): Both `MosaicExtractor` and legacy `_parse_mosaic()` now default to extracting only `is_top=1` designs. `--all-mosaic-designs` flag added to `binder-compare extract`, `binder-compare run`, and `bindmaster evaluate`. The `REPLACE_ME` target_sequence placeholder is now guarded in the legacy evaluator's CSV fallback path.
- **Standalone mode** (`Part H`): Installer auto-detects whether system conda is writable. If not, downloads Miniforge3 into `BindMaster/conda/` and creates all environments locally. Shortcuts go to `BindMaster/bin/` instead of `~/.local/bin/`. `--standalone` forces this; `--system-conda` opts out. All generated run scripts and Evaluator shell scripts search local conda first.
- **Deferred items:**
  - F2: `--headless` mode for configurator (accept JSON config, skip prompts)
  - F6: Multi-chain binder support in BoltzGen YAML generation
- **PXDesign** full pipeline integrated: diffusion → MPNN → AF2 complex/monomer eval → summary CSV. Works on both x86_64 and aarch64 (with automated post-install patches).
- **RFAA** integrated for x86_64; not supported on aarch64 (DGL lacks CUDA aarch64 wheels).
- **Proteina-Complexa** integrated: NVIDIA flow matching + inference-time optimization. Uses uv venv (separate from Mosaic). Shares AF2 weights with BindCraft. Supports single-pass, best-of-n, beam-search, and MCTS search algorithms.

### Known issues

- **aarch64 RFAA:** Not supported. DGL (Deep Graph Library) has no CUDA-enabled aarch64 wheels. The SE3-Transformer requires DGL CUDA operations. The installer shows a warning but still installs dependencies. Use x86_64 for RFAA.
- **PXDesign site-packages patches:** The installer applies post-install patches to `protenix` (CUDA arch), `pxdbench` (NumpyEncoder), and `configs_infer.py` (num_workers). These patches are reapplied on each install but would be lost if packages are upgraded manually.
- **PXDesign requirements.txt:** Pins `torch==2.3.1` (CPU-only from PyPI). The installer force-reinstalls PyTorch with CUDA after requirements.txt. Do not run `pip install -r requirements.txt` manually without reinstalling PyTorch afterward.
- **Mosaic `is_top` filtering:** Both extractors (Evaluator package `MosaicExtractor` and legacy `evaluator.py`) now default to `is_top=1` rows only (~40 refolded designs instead of all ~800). Use `--all-mosaic-designs` to override. The `target_sequence` CSV fallback also skips `"REPLACE_ME"` placeholders.
- **Mosaic CSV column mismatch:** `designs.csv` can mix two column formats when multiple workers run. Parser may misalign columns for some workers. Documented in `Evaluator/docs/pipeline_reference.md`.
- **BoltzGen pass rate is low:** In CALCA target testing, only 1/50 BoltzGen designs passed the `ipsae_min > 0.61` threshold. Sequences designed for Boltz-2 often don't cross-validate well.
- **aarch64 BindCraft:** May fail because jaxlib CUDA conda packages are not available for aarch64.
- **aarch64 Mosaic:** May fail because `torchtext` has no Linux aarch64 wheel.
- **aarch64 Proteina-Complexa:** May need patches — PyTorch Geometric (PyG) and torchtext may lack aarch64 wheels. Core deps (PyTorch 2.7, JAX 0.4.29) are fine. Same approach as Mosaic: patch pyproject.toml to exclude problematic packages with `platform_machine != 'aarch64'` markers.
- **AF2 smoke test:** Fails if `BindCraft/params/` is missing `.npz` weight files (interrupted download).

### RFD3 / foundry runtime gotchas (no automated runner yet)

The configurator does not yet generate RFD3 run scripts. When writing one by
hand, watch for these (each one bit me on the CALCA run):

- **Output format.** RFD3 writes `.cif.gz` (compressed mmCIF), NOT `.pdb`. Decompress for downstream tools that need PDB.
- **Chain IDs.** Output mmCIF labels target as chain `A` (preserved residues from the input contig) and binder as chain `B` (designed). The `label_entity_id` column shows `0`/`1`, but the actual chain IDs at `label_asym_id` are letters.
- **MPNN CLI is `mpnn`, not `foundry mpnn`.** The `foundry` umbrella CLI only has `install` / `list-available` / `list-installed` / `clean`. Sequence design is its own console-script (`mpnn`).
- **`mpnn` requires `--is_legacy_weights True`** when called directly (the legacy `.pt` format is what `foundry install proteinmpnn` ships).
- **`--designed_chains` wants a JSON list of letter strings**, e.g. `'["B"]'` — not bare `B` and not `1`. Bare digits get parsed as int and rejected with `chain-id strings, got <class 'int'>`.
- **`FOUNDRY_CHECKPOINT_DIRS` is plural-S.** Singular `FOUNDRY_CHECKPOINT_DIR` is silently ignored (foundry's `checkpoint_registry.py` reads only the plural form). Effect: `rfd3 design` aborts with `Invalid checkpoint: rfd3` even when the .ckpt sits in your weights dir.
- **ProteinMPNN weights are NOT bundled with rfd3.** `foundry install rfd3` only fetches `rfd3_latest.ckpt` (~2.5 GB). Run `foundry install proteinmpnn` separately for the ~7 MB `proteinmpnn_v_48_020.pt` file. (For ligand binders you also need `foundry install ligandmpnn`.)
- **Reinit warnings on weight load are benign.** `foundry.utils.weights: Failed to apply policy: 'copy' to 'model.token_initializer.chunked_pairwise_embedder.*': Falling back to policy: 'reinit'` — these come from the chunked low-memory code path that the v0.1.9 checkpoint wasn't trained with. Output structures verify clean (n_chainbreaks=0, n_clashing=0, helix_fraction~0.9 for our CALCA helix).
- **MPNN best-of-N filter.** `mpnn --number_of_batches 5` writes 5 sequences per backbone in one `.fa` (each header tagged with `sequence_recovery=...`). To keep "best-of-5 per backbone", post-process: pick the highest-recovery sequence per file, strip the target prefix (first `len(target_seq)` chars), the remainder is the designed binder.

---

## Commands

### Quick start

```bash
git clone https://github.com/damborik22/BindMaster.git ~/BindMaster
cd ~/BindMaster

bindmaster install              # interactive menu (auto-detects standalone mode)
bindmaster configure            # interactive wizard
bash runs/<name>/run_all.sh     # run all enabled tools
bindmaster evaluate runs/<name> # rank and report

# Add BindMaster/bin to PATH:
export PATH="$(pwd)/bin:$PATH"
```

### Install

```bash
bindmaster install                          # interactive tool selection
bindmaster install --tool all               # install everything
bindmaster install --tool mosaic            # install one tool
bindmaster install --tool all --yes --skip-examples  # non-interactive (CI)
bindmaster install --tool proteina-complexa # install Proteina-Complexa
bindmaster install --uninstall --tool all   # remove envs + shortcuts (preserves runs/)
bindmaster install --standalone --tool all    # force local Miniforge install
bindmaster install --system-conda --tool all  # use existing system conda
```

### Configure

```bash
bindmaster configure             # interactive 5-step wizard
bindmaster configure --status    # show all runs and completion state
bindmaster configure --archive <run>  # tar.gz a run directory
```

### Evaluate

```bash
# Run-directory mode (parses tool outputs, ranks, writes report)
bindmaster evaluate runs/<name>
bindmaster evaluate runs/<name> --metric ipsae_min --top 20
bindmaster evaluate runs/<name> --refold 5 --target target.pdb
bindmaster evaluate runs/<name> --all-mosaic-designs  # include all ~800 Mosaic designs

# Sequence-only mode (fold bare sequences without a run directory)
bindmaster evaluate --sequences my_seqs.txt --refold 3 --target target.pdb
echo "MAEVKLSYVL..." | bindmaster evaluate --sequences - --refold 1
```

### Linting and CI

```bash
# Python
ruff check .
ruff format --check .

# Shell
shellcheck --shell=bash --severity=warning \
    install/install.sh install/install_aarch.sh \
    Evaluator/evaluate.sh Evaluator/install.sh Evaluator/run.sh \
    docker-entrypoint.sh test_env.sh
```

### Testing

```bash
# Docker test environment
docker build -f Dockerfile.test --target base -t bindmaster-test .
docker run --rm -it bindmaster-test bash

# Dry-run (non-interactive, reports pass/fail)
./test_env.sh --dry-run

# With GPU
./test_env.sh --gpu

# Clean up test artifacts
./test_env.sh --clean
```

### Full Evaluator pipeline (Evaluator/)

```bash
# Extract sequences from all tool outputs (Mosaic: is_top=1 only by default)
conda run -n binder-eval binder-compare extract \
    --bindcraft DIR --boltzgen DIR --mosaic DIR -o seqs.fasta
# To include all Mosaic designs (not just refolded):
#   binder-compare extract --mosaic DIR --all-mosaic-designs -o seqs.fasta

# Refold with Boltz-2 (must use Mosaic venv, NOT conda)
Mosaic/.venv/bin/binder-compare refold-boltz2 \
    --sequences seqs.fasta --target-seq SEQ -o boltz2.csv

# Generate report (Boltz-2 only for now; Protenix / AF3 land in Parts J & K)
conda run -n binder-eval binder-compare report \
    --boltz2-results boltz2.csv \
    --sequences seqs.fasta -o ./report
```
