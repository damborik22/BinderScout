# BindMaster — Completed Plans (Archive)

This document archives implementation plans that have been completed.
For active/future plans, see [docs/plans.md](plans.md).

---

## Phase 2: RFAA + PXDesign Integration (complete)

**Original file:** `PHASE2_PLAN.md`

Phase 1 created standalone adapter modules in `bindmaster/tools/rfaa/` and
`bindmaster/tools/pxdesign/`, install scripts in `scripts/`, and a unified scoring layer
in `bindmaster/scoring/`. All behind feature flags.

Phase 2 wired these into the three existing BindMaster integration points:

- **Installer** (`install/install.sh`): Added `install_rfaa()` and `install_pxdesign()`
  functions, `--tool rfaa|pxdesign` flags, interactive menu entries, uninstall cases.
  RFAA bundles LigandMPNN in the same conda env (`bindmaster_rfaa`).
- **Configurator** (`configurator/configurator.py`): Added RFAA and PXDesign as tool
  options in the wizard. PXDesign supports both "run locally" and "import external results"
  modes. Config generation writes `run_rfaa.sh` and `run_pxdesign.sh`.
- **Evaluator**: Added `RFAAExtractor` and `PXDesignExtractor` to parse tool outputs.
  Sequences from both tools participate in the standard Boltz-2 + AF2 refolding pipeline.

### Key decisions

- RFAA outputs backbone PDBs without sequences; LigandMPNN designs sequences downstream.
- PXDesign native metrics are not used for ranking — our refolding provides canonical scores.
- Both tools pinned to specific commits for reproducible installs.
- Post-install patches applied for PXDesign upstream issues (NumpyEncoder, num_workers, CUDA arch).

---

## Part H: Standalone Installer (complete, v0.7.0)

**Original file:** `PLAN_standalone_installer.md`

**Goal:** BindMaster installs and runs entirely within its own directory.
No writes to system conda, `~/.local/bin/`, or any location outside the project directory.

### What was implemented

- `install_local_conda()` downloads Miniforge3 into `BindMaster/conda/`
- `detect_conda()` rewritten: local conda → writable system conda → auto-bootstrap
- `--standalone` / `--system-conda` CLI flags
- Shortcuts write to `BindMaster/bin/` instead of `~/.local/bin/`
- BindCraft's upstream installer finds local conda via PATH prepend
- All Evaluator shell scripts (`evaluate.sh`, `run.sh`, `install.sh`) search local conda first
- Configurator-generated run scripts include local conda path
- Uninstall offers to remove local Miniforge when all tools uninstalled
- All changes mirrored in `install_aarch.sh` for aarch64

---

## RFAA + PXDesign Integration Status (complete)

**Original file:** `CLAUDE_INTEGRATION.md`

Feature flags (`BINDMASTER_ENABLE_RFAA`, `BINDMASTER_ENABLE_PXDESIGN`) were used during
development on the `feature/rfaa-pxdesign-integration` branch. Both tools are now
fully integrated into `master`:

- **RFAA**: All-atom diffusion + LigandMPNN for ligand binder design (x86_64 only)
- **PXDesign**: Protenix-based de novo binder design with full pipeline
- **Unified scoring**: `bindmaster.scoring.unified.BinderScore` composite formula
