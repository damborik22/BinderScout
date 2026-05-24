# CLAUDE.md — BindMaster / BoltzGen Pipeline

## Overview

BindMaster is a unified toolkit for GPU-accelerated **protein binder design**. It wraps seven independent design tools (BindCraft, BoltzGen, Mosaic, PXDesign, Proteina-Complexa, Protein-Hunter, RFD3) plus the legacy RFAA, behind a single CLI (`bindmaster`) that handles installation, interactive configuration, execution, and cross-tool evaluation of designed binders.

**Current status:** v0.7.0 + Parts I, J, K, L, M landed on `[Unreleased]`. Latest milestones: Evaluator AF2 refolding removed (Part I), AF3 v3.0.2 stood up as the canonical 2nd refolding engine on big-VRAM hardware (Part K — Spark / H200, >100 GB unified memory), Protenix v0.5.0 retained as an optional alternative for smaller GPUs (Part J — 24 GB OK), Protein-Hunter installed and configurable (Part L), RFD3 installed and configurable (Part M). Active development on `master`; `aarch64` branch tracks DGX Spark / Grace-Hopper and is periodically rebased.

**Repository:** `github.com/damborik22/BindMaster`

---

## Behavioral Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. These apply on top of the project-specific instructions below.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### Think before coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity first

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

### Goal-driven execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Architecture

### Pipeline flow

```
Target structure (.pdb / .mmcif)
  → Configurator wizard (interactive, generates configs + run scripts)
    → Design tools run in sequence (configurable per run):
       Mosaic               (JAX + Boltz-2 hallucination)
       BoltzGen             (Boltz-1 diffusion)
       BindCraft            (AF2 + MPNN + PyRosetta)
       PXDesign             (Protenix + MPNN + AF2 eval)
       Proteina-Complexa    (NVIDIA flow matching + ITO)
       Protein-Hunter       (Boltz-2 / Chai-1; 6 modalities: protein / cyclic / ligand CCD / ligand SMILES / DNA / RNA)
       RFD3                 (RosettaCommons foundry diffusion + ProteinMPNN)
       [RFAA               (LigandMPNN; deprecated, opt-in only via --tool rfaa)]
    → Evaluator (canonical pipeline = Boltz-2 + AF3):
       1. Extract sequences from all tool outputs (one extractor per tool)
       2. Refold with Boltz-2 (Mosaic venv)                                    [live, all platforms]
       3. Refold with AlphaFold 3 v3.0.2 (binder-eval-af3 env)                 [live, canonical 2nd engine — Spark / H200 / >100 GB VRAM]
       4. (optional) Refold with Protenix v0.5.0 (bindmaster_pxdesign env)     [live, fits 24 GB GPUs — opt-in]
       5. Rank by agreement_count then ipsae_min; generate HTML + CSV report
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
│   ├── scripts/               ← standalone refold scripts (refold_boltz2.py, refold_af3.py — canonical; refold_protenix.py — optional fallback)
│   ├── evaluate.sh            ← shell orchestrator (extract → refold-boltz2 → refold-af3 → report; Protenix runs only when explicitly enabled)
│   ├── envs/                  ← conda env specs (binder-eval.yml, binder-eval-af3.yml [Spark / H200 / big-VRAM])
│   ├── docs/                  ← pipeline_reference.md (metrics, known issues)
│   └── pyproject.toml         ← package: "binder-comparison" v0.1.0
├── bindmaster_examples/       ← canonical run-script templates
│   ├── hallucinate_bindmaster.py     ← Mosaic template (copied into Mosaic/ on install)
│   ├── run_rfd3.sh.template          ← RFD3 two-stage (backbone diffusion + MPNN)
│   └── run_protein_hunter.sh.template ← Protein-Hunter Boltz-2 hallucination
├── tools/
│   └── aarch64/               ← pre-built ARM64 binaries (DAlphaBall, dssp)
├── .github/workflows/ci.yml  ← shellcheck + ruff + Docker build
├── test_env.sh                ← Docker test environment launcher
├── Dockerfile.test            ← CUDA 12.4, Ubuntu 22.04, Miniforge
├── docker-entrypoint.sh       ← container init (conda, HOME setup)
├── ruff.toml                  ← Python linting/formatting config
├── STAGES.md                  ← implementation milestones (Parts A–H; later parts live in CHANGELOG)
├── CONTRIBUTING.md            ← dev setup, PR conventions
├── CHANGELOG.md               ← Keep a Changelog format
└── LICENSE                    ← MIT
```

**Gitignored (created at runtime):**
- `BindCraft/`, `BoltzGen/`, `Mosaic/`, `PXDesign/`, `Proteina-Complexa/`, `Protein-Hunter/`, `rf_diffusion_all_atom/`, `LigandMPNN/` — cloned by installer
- `weights/foundry/` — RFD3 / ProteinMPNN / LigandMPNN checkpoints fetched by `foundry install` (no clone dir; `rc-foundry` is pip-installed into `bindmaster_rfd3`)
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
| `bindmaster_pxdesign` | PXDesign | 3.11 | conda | Protenix binder design + eval; ALSO hosts the *optional* Evaluator Protenix refolder (Part J — fits 24 GB GPUs) |
| `Proteina-Complexa/.venv` | Proteina-Complexa | 3.12 | uv | Flow matching + test-time compute binder design |
| `bindmaster_protein_hunter` | Protein-Hunter | 3.10 | conda | Boltz-2 / Chai-1 hallucination, 6 modalities |
| `bindmaster_rfd3` | RFD3 (`rc-foundry`) | 3.12 | conda | RosettaCommons foundry diffusion + ProteinMPNN |
| `binder-eval` | Evaluator | 3.10 | conda | Sequence extraction + reporting |
| `binder-eval-af3` | AF3 refolder | 3.10 | conda | AlphaFold 3 v3.0.2 refolding — **canonical 2nd engine** (Part K, live on Spark / H200 / >100 GB VRAM hardware) |
| `bindmaster_rfaa` *(deprecated)* | RFAA + LigandMPNN | 3.11 | conda | All-atom diffusion (x86_64 only; superseded by RFD3, opt-in via `--tool rfaa`) |

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
- Mosaic: `esmj` excluded (no aarch64 wheel); `torchtext` also may fail
- RFD3: fully supported on aarch64 (no DGL dependency; pip-installs cleanly)
- Protein-Hunter: NOT supported on aarch64 (PyRosetta has no aarch64 wheels)
- RFAA: NOT supported on aarch64 (DGL has no CUDA aarch64 wheels)
- Pre-cached AF2 weights path: `Documents/OLD/BindMaster/bindcraft-tools`

### Design decisions and WHY

- **Monorepo:** The Evaluator was merged from a separate repo (`BindMaster-evaluator`, now archived) into `Evaluator/` so the full pipeline ships in one `git clone`.
- **stdlib-only CLI:** `bindmaster.py` uses only stdlib so it works on any Python 3.10+ without pip installs.
- **uv for Mosaic:** Mosaic uses `uv` instead of conda because it needs JAX with CUDA, and uv resolves this faster and more reliably.
- **Pinned commits:** Tool repos are cloned at pinned commits (`BINDCRAFT_COMMIT`, `BOLTZGEN_COMMIT`, `MOSAIC_COMMIT`) for reproducible installs.
- **Separate evaluator envs:** Boltz-2 refolding runs in the Mosaic venv (JAX). AF3 v3.0.2 (Part K, live) is the canonical 2nd engine and runs in a dedicated `binder-eval-af3` conda env on DGX Spark / H200 / any host with >100 GB unified or device memory — full AF3 inference needs that headroom. Protenix v0.5.0 (Part J, live) rides the existing `bindmaster_pxdesign` conda env as an *optional* alternative for smaller GPUs (24 GB is enough). `evaluate.sh` orchestrates Boltz-2 + AF3 by default; Protenix runs only when explicitly enabled.

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
- Conda envs: BindCraft, BoltzGen, binder-eval, binder-eval-af3 (canonical 2nd refold engine, Spark / H200), bindmaster_pxdesign, bindmaster_protein_hunter, bindmaster_rfd3; bindmaster_rfaa (deprecated, opt-in only)

### Per-run `settings.json` (reproducibility convention)

Every tool run script MUST write a `settings.json` into its tool output subdir
(`runs/<name>/<tool>/settings.json`) **before** the design step starts. This
is how future sessions answer "what params produced these designs" without
grepping through `run.log` or trusting the parent run script (which may have
been edited since the run).

Required keys:

```json
{
  "tool":         "<tool-name>",
  "started_at":   "<ISO-8601 UTC>",
  "version":      { "bindmaster_git_sha": "...", "bindmaster_git_branch": "...", "tool_repo_git_sha or tool_pkg_version": "..." },
  "target":       { "name": "...", "sequence": "...", "length": N },
  "design_params":{ ... tool-specific CLI flags ... },
  "env":          { "conda_env": "...", "python": "...", "gpu_id": N, "gpu_name": "...", "gpu_memory_mib": N }
}
```

Implementation: write the JSON via a `cat > $RUN_DIR/settings.json <<JSON …
JSON` heredoc immediately after conda activation but **before** launching
the heavy workload. Capture `git rev-parse HEAD` of both the BindMaster repo
and the tool's repo (or its installed package version), plus
`nvidia-smi --query-gpu=name,memory.total`. The shipped templates
`bindmaster_examples/run_rfd3.sh.template` and
`bindmaster_examples/run_protein_hunter.sh.template` are the canonical
examples — copy that block when adding a new tool's run script.

When relaunching the same tool with different parameters (e.g. PH at 700×5
then 700×7), back up the previous output dir to a versioned name like
`protein_hunter_v2_700x5/` so the side-by-side `settings.json` files document
the parameter sweep.

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
| **PXDesign** | Protenix-based de novo binder design (diffusion + MPNN + AF2 eval) | `bytedance/PXDesign` |
| **Proteina-Complexa** | Flow matching + inference-time optimization (beam search / MCTS) | `NVIDIA-Digital-Bio/proteina-complexa` |
| **Protein-Hunter** | Boltz-2 / Chai-1 hallucination; 6 modalities (protein, cyclic, ligand CCD, ligand SMILES, DNA, RNA) | Cho et al. 2025 |
| **RFD3** | RosettaCommons foundry diffusion (RFdiffusion3) + ProteinMPNN; BSD-3, commercial-use OK | `RosettaCommons/foundry` (`rc-foundry` on PyPI) |
| ~~RFAA~~ *(deprecated)* | All-atom diffusion + LigandMPNN for ligand binder design; superseded by RFD3 | `baker-laboratory/rf_diffusion_all_atom` |

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

- **Parts A–H complete** (see STAGES.md); **Parts I, J, K, L, M landed on `[Unreleased]`** (see CHANGELOG). All Roadmap items are done.
- **Part I — AF2 refolding removed from Evaluator.** Deleted `refold_af2.py`, `af2_runner.py`, `binder-eval-af2.yml`; pruned all `af2_*` schema fields and report plots. BindCraft / PXDesign / Proteina-Complexa still use AF2 internally — only the Evaluator's AF2 refolding step was removed.
- **Part K — AF3 v3.0.2 is the canonical 2nd refolding engine.** Runs in its own `binder-eval-af3` conda env on DGX Spark, H200, or any host with >100 GB unified / device memory (full AF3 inference doesn't fit on consumer 24 GB GPUs). Schema: `af3_*` columns in `StandardisedMetrics`; pLDDT rescaled 0–100 → 0–1 on ingest; PAE transposed from token-order to `[binder|target]` to match Boltz-2.
- **Part J — Protenix v0.5.0 as the optional fallback refolder.** `binder-compare refold-protenix` runs inside the existing `bindmaster_pxdesign` conda env (no new env). ByteDance's open-source AF3 reimplementation, ~3–4 GB weights, fits 24 GB GPUs — useful when AF3 isn't an option. Schema: `protenix_*` columns. Opt-in via `evaluate.sh` flags; **not part of the default Boltz-2 + AF3 pipeline.**
- **Part L — Protein-Hunter** installable via `bindmaster install --tool protein-hunter` (x86 only; aarch64 blocked by PyRosetta). Conda env `bindmaster_protein_hunter`, vendored Boltz-2 + LigandMPNN + Chai-1 (sokrypton fork). New `ProteinHunterExtractor` reads `summary_high_iptm.csv` by default (`--all-protein-hunter-designs` for all runs). Configurator generates `run_protein_hunter.sh`.
- **Part M — RFD3** installable via `bindmaster install --tool rfd3` (x86 + aarch64). Conda env `bindmaster_rfd3`, `rc-foundry[rfd3,mpnn]` from PyPI, weights at `weights/foundry/`. New `RFD3Extractor`. Configurator generates `run_rfd3.sh`. **RFAA deprecated** — dropped from the interactive menu and from `--tool all`; still installable via `bindmaster install --tool rfaa` for reproducing existing runs. `docs/rfaa_manual_reinstall.md` captures commit SHAs and post-install patches for long-term maintenance.
- **Standalone mode** (Part H, v0.7.0): Installer auto-detects whether system conda is writable. If not, downloads Miniforge3 into `BindMaster/conda/` and creates all environments locally. Shortcuts go to `BindMaster/bin/` instead of `~/.local/bin/`. `--standalone` forces this; `--system-conda` opts out. All generated run scripts and Evaluator shell scripts search local conda first.
- **Mosaic is_top filter**: Both `MosaicExtractor` and legacy `_parse_mosaic()` default to extracting only `is_top=1` designs. `--all-mosaic-designs` flag exposed on `binder-compare extract`, `binder-compare run`, and `bindmaster evaluate`. The `REPLACE_ME` target_sequence placeholder is guarded in the legacy evaluator's CSV fallback path.
- **Deferred items:**
  - F2: `--headless` mode for configurator (accept JSON config, skip prompts)
  - F6: Multi-chain binder support in BoltzGen YAML generation
- **PXDesign** full pipeline integrated: diffusion → MPNN → AF2 complex/monomer eval → summary CSV. Works on both x86_64 and aarch64 (with automated post-install patches).
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

### RFD3 / foundry runtime gotchas

The configurator now generates `run_rfd3.sh` from
`bindmaster_examples/run_rfd3.sh.template`. The gotchas below still apply —
they live in the template and bit me on the CALCA run before being encoded
there:

- **Output format.** RFD3 writes `.cif.gz` (compressed mmCIF), NOT `.pdb`. Decompress for downstream tools that need PDB.
- **Chain IDs.** Output mmCIF labels target as chain `A` (preserved residues from the input contig) and binder as chain `B` (designed). The `label_entity_id` column shows `0`/`1`, but the actual chain IDs at `label_asym_id` are letters.
- **MPNN CLI is `mpnn`, not `foundry mpnn`.** The `foundry` umbrella CLI only has `install` / `list-available` / `list-installed` / `clean`. Sequence design is its own console-script (`mpnn`).
- **`mpnn` requires `--is_legacy_weights True`** when called directly (the legacy `.pt` format is what `foundry install proteinmpnn` ships).
- **`--designed_chains` wants a JSON list of letter strings**, e.g. `'["B"]'` — not bare `B` and not `1`. Bare digits get parsed as int and rejected with `chain-id strings, got <class 'int'>`.
- **`FOUNDRY_CHECKPOINT_DIRS` is plural-S.** Singular `FOUNDRY_CHECKPOINT_DIR` is silently ignored (foundry's `checkpoint_registry.py` reads only the plural form). Effect: `rfd3 design` aborts with `Invalid checkpoint: rfd3` even when the .ckpt sits in your weights dir.
- **ProteinMPNN weights are NOT bundled with rfd3.** `foundry install rfd3` only fetches `rfd3_latest.ckpt` (~2.5 GB). Run `foundry install proteinmpnn` separately for the ~7 MB `proteinmpnn_v_48_020.pt` file. (For ligand binders you also need `foundry install ligandmpnn`.)
- **Reinit warnings on weight load are benign.** `foundry.utils.weights: Failed to apply policy: 'copy' to 'model.token_initializer.chunked_pairwise_embedder.*': Falling back to policy: 'reinit'` — these come from the chunked low-memory code path that the v0.1.9 checkpoint wasn't trained with. Output structures verify clean (n_chainbreaks=0, n_clashing=0, helix_fraction~0.9 for our CALCA helix).
- **MPNN best-of-N filter.** `mpnn --number_of_batches 5` writes 5 sequences per backbone in one `.fa` (each header tagged with `sequence_recovery=...`). To keep "best-of-5 per backbone", post-process: pick the highest-recovery sequence per file, strip the target prefix (first `len(target_seq)` chars), the remainder is the designed binder.
- **24 GB Ampere OOM mid-run from fragmentation, not capacity.** With `diffusion_batch_size=10 low_memory_mode=true`, peak live allocation is ~15 GiB but PyTorch reserves another ~6 GiB unallocated. Around batch 7 the next 3 GiB alloc fails even though the live working set fits 24 GiB easily. Fix: `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before launching `rfd3 design`. The configurator's `write_run_rfd3` and `bindmaster_examples/run_rfd3.sh.template` set this. (BM4 2VDY run: died at batch 7 of try-1; relaunched with this env var, completed all 20 batches cleanly in 23 h.)
- **`Found N existing example IDs` is informational, not skip-behavior.** RFD3 prints this at startup when example IDs already exist in `out_dir`, but it then re-runs all `n_batches` anyway and overwrites the existing files. There is no built-in resume — if a run crashes mid-way, expect a full re-run, not a delta. (Workaround if you only want the missing slice: move the completed `<id>.cif.gz`/`<id>.json` pairs aside, run with smaller `n_designs`, then put them back.)

### Protein-Hunter / boltz_ph runtime gotchas

The configurator now generates `run_protein_hunter.sh` from
`bindmaster_examples/run_protein_hunter.sh.template`. The gotchas below
still apply — they live in the template and bit me on the CALCA run before
being encoded there:

- **`--msa_mode` valid values are `single` or `mmseqs`** — NOT `single_sequence`. The literal `single_sequence` raises `argparse: invalid choice`. `single` is the no-MSA mode (fastest, what we used on CALCA); `mmseqs` calls the ColabFold server.
- **Boltz-2 cache must live at `~/.boltz/`** with three things: `boltz2_conf.ckpt` (~2.3 GB), `boltz2_aff.ckpt` (~2.1 GB), and a populated `mols/` directory (~45 k .pkl files). If `mols/ALA.pkl` is missing, `design.py` aborts on startup with `ValueError: CCD component ALA not found!` — the canonical-residue tokenizer probes the directory for every standard amino acid.
- **`download_boltz2` requires a positional `cache: pathlib.Path` argument.** Bootstrap the cache with: `python -c "from boltz.main import download_boltz2; from pathlib import Path; download_boltz2(cache=Path.home()/'.boltz')"`. Passing a `str` (or omitting `cache=`) silently no-ops on some versions.
- **`pyrosetta-installer` ≥ 0.3 renamed `download_pyrosetta` → `install_pyrosetta`.** Our installer (`install/install.sh`) was updated in `7642942`. If you stand up a fresh `bindmaster_protein_hunter` env outside the installer, use the new name.
- **Output layout creates a `{name}/` subdirectory under `save_dir`.** With `--save_dir runs/CALCA_helix/protein_hunter --name CALCA_helix`, the actual CSVs are at `protein_hunter/CALCA_helix/summary_*.csv` (path printed twice in the run banner — confusing but correct).
- **`summary_high_iptm.csv` row count > num_designs is normal.** Every cycle that crosses the `--high_iptm_threshold` gets a row, so 7-cycle runs with several passing cycles produce more rows than designs (CALCA: 133 rows from 100 designs).
- **"No structure was generated for run N (no eligible best design …)" is not a failure.** It just means none of the N cycles produced a sequence under the `--percent_X` alanine cap. Final-run row may be absent from `summary_all_runs.csv` for that reason.

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
bindmaster install --tool all               # install all current-generation tools (RFAA excluded)
bindmaster install --tool mosaic            # install one tool
bindmaster install --tool all --yes --skip-examples  # non-interactive (CI)
bindmaster install --tool proteina-complexa # install Proteina-Complexa
bindmaster install --tool protein-hunter    # install Protein-Hunter (Part L)
bindmaster install --tool rfd3              # install RFD3 / foundry (Part M)
bindmaster install --tool rfaa              # install legacy RFAA (opt-in only)
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
    --bindcraft DIR --boltzgen DIR --mosaic DIR \
    --pxdesign DIR --proteina-complexa DIR \
    --protein-hunter DIR --rfd3 DIR \
    -o seqs.fasta
# To include all Mosaic designs (not just refolded):
#   binder-compare extract --mosaic DIR --all-mosaic-designs -o seqs.fasta

# Refold with Boltz-2 (must use Mosaic venv, NOT conda)
Mosaic/.venv/bin/binder-compare refold-boltz2 \
    --sequences seqs.fasta --target-seq SEQ -o boltz2.csv

# Refold with AF3 v3.0.2 (canonical 2nd engine — Spark / H200, >100 GB VRAM)
conda run -n binder-eval-af3 binder-compare refold-af3 \
    --sequences seqs.fasta --target-seq SEQ -o af3.csv

# (Optional) Refold with Protenix v0.5.0 — fits 24 GB GPUs; runs in PXDesign env
# conda run -n bindmaster_pxdesign binder-compare refold-protenix \
#     --sequences seqs.fasta --target-seq SEQ -o protenix.csv

# Generate report (any subset of refold outputs can be passed)
conda run -n binder-eval binder-compare report \
    --boltz2-results boltz2.csv \
    --af3-results af3.csv \
    --sequences seqs.fasta -o ./report
```
