# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **RFAA** (RFDiffusionAA + LigandMPNN): new design tool in installer, configurator, and evaluator (x86_64 only)
- **PXDesign** (Protenix): full pipeline support — diffusion, MPNN sequence design, AF2 complex/monomer evaluation
- Post-install patches in both installers for PXDesign upstream issues (NumpyEncoder, num_workers, CUDA arch, ColabDesign, deepspeed, JAX pin)
- aarch64 run scripts auto-detect platform and set `TORCH_CUDA_ARCH_LIST` and `JAX_PLATFORMS` for Blackwell GPUs
- RFAA platform warning in aarch64 installer (DGL lacks CUDA aarch64 wheels)

### Changed
- **BindCraft pin** `828fd9f` → `7cd4ace` (3 upstream bugfixes): graylab→west.rosettacommons.org PyRosetta wheels (x86_64), `range(11,15)→(11,16)` model-selection fix, stage-3 `onehot_plddt` init + `align_pdbs` crash guard

### Added (Parts L + M — Protein-Hunter & RFD3, on `refactor/af3-rfd3-ph`)
- **Part L — Protein-Hunter** (Cho et al. 2025) installable via `bindmaster install --tool protein-hunter` (x86 only; aarch64 blocked by pyrosetta). Conda env `bindmaster_protein_hunter` (Py 3.10), vendored Boltz-2 + LigandMPNN + Chai-1 (sokrypton fork), shortcut `bin/protein-hunter`. New Evaluator extractor reads `summary_high_iptm.csv` by default (`--all-protein-hunter-designs` for all runs). Supports all 6 modalities via upstream `design.py` flags (protein / cyclic / ligand-CCD / ligand-SMILES / DNA / RNA). `SourceTool` Literal + tool colors/displays extended.
- **Part M — RFD3 (RosettaCommons/foundry v0.1.9)** installable via `bindmaster install --tool rfd3`. Conda env `bindmaster_rfd3` (Py 3.12), `rc-foundry[rfd3,mpnn]` from PyPI, weights at `BindMaster/weights/foundry/`. BSD-3-Clause, commercial-use OK, works on aarch64 (no DGL). Shortcut `bin/rfd3` runs `rfd3 design ...` or opens an env shell. New `RFD3Extractor` with defensive CSV/FASTA parsing. Tool colors/displays added.
- **RFAA deprecated (not deleted)**. Dropped from interactive menu and from the `--tool all` meta-tool. Still installable via `bindmaster install --tool rfaa` for reproducing existing runs. `install_rfaa()` now prints a deprecation banner pointing at RFD3 and `docs/rfaa_manual_reinstall.md`.
- **New doc** `docs/rfaa_manual_reinstall.md` captures commit SHAs, post-install patches, and manual-reproducibility steps for long-term RFAA maintenance.

### Added (Part J — Protenix refolder, on `refactor/af3-rfd3-ph`)
- **Protenix v0.5.0 as universal 2nd refolding engine** — ByteDance's open-source AlphaFold 3 reimplementation (~3-4 GB weights auto-downloaded from ByteDance TOS, runs comfortably on 24 GB GPUs).
- New CLI: `binder-compare refold-protenix` — runs inside the existing `bindmaster_pxdesign` conda env (no new env needed).
- New files: `Evaluator/scripts/refold_protenix.py`, `Evaluator/binder_comparison/refolding/protenix_runner.py`, `Evaluator/binder_comparison/cli/refold_protenix.py`.
- Schema: `protenix_*` columns in `StandardisedMetrics` (iptm, ptm, ranking_score, plddt_binder_mean/min, plddt_target_mean, pae_bt/tb/bb, bt_ipsae, tb_ipsae, ipsae_min). `af3_*` counterparts also reserved for Part K. pLDDT rescaled 0-100 → 0-1 on ingest.
- Scoring: new generic `add_ipsae_from_pae_files(df, prefix=...)` for any engine's saved PAE matrix.
- Merger: multi-engine support — `merge_refold_results(boltz2_csv, ..., protenix_csv=..., af3_csv=...)`. Accepts any combination; outer-joins on `sequence`.
- `compute_agreement` now sums {boltz_pae_ipsae_min, protenix_ipsae_min, af3_ipsae_min} passing the 0.61 threshold (0–3 on Spark, 0–2 on x86).
- Orchestration:
  - `Evaluator/evaluate.sh` auto-detects `bindmaster_pxdesign`; Protenix step runs between Boltz-2 and report unless `--skip-protenix` or env missing.
  - `binder-compare run --protenix-env bindmaster_pxdesign` enables Protenix; omit to skip.
  - `binder-compare report` gains `--protenix-results` and `--af3-results`.
- Installer: PXDesign step now pip-installs `binder-compare` into `bindmaster_pxdesign` env so Protenix refolding is available after `bindmaster install --tool pxdesign`.
- **Live smoke test passed** — 2 × 43aa random binders against 76aa ubiquitin target: inference ~12 s/design on RTX 3090, CSV + `*_pae.npy` populated, token-pair PAE extracted via `need_atom_confidence=True`, DunbrackLab ipSAE computed downstream in the report.

### Removed (Part I — AF2 refolding removal, on `refactor/af3-rfd3-ph`)
- Evaluator AF2 refolding is gone. This is step 1 of the AF3/Protenix refactor; AF3 (aarch64-only, DGX Spark) and Protenix (universal) will provide the second engine in Parts J & K.
- Deleted files: `Evaluator/scripts/refold_af2.py`, `Evaluator/scripts/refold_Version6.py`, `Evaluator/binder_comparison/refolding/af2_runner.py`, `Evaluator/binder_comparison/cli/refold_af2.py`, `Evaluator/envs/binder-eval-af2.yml`
- Installer no longer creates `binder-eval-af2` conda env (uninstall path still cleans legacy installs)
- Schema: removed 8 `af2_*` fields from `StandardisedMetrics`, 2 from `PerResidueData`; pruned `af2_*` entries from `LOWER_IS_BETTER`, `ZSCORE_METRICS`; `model_weights` default now `{"boltz2": 1.0}`
- Scoring: deleted `add_af2_ipsae_from_files`; `compute_agreement` engine list now `[boltz_pae_ipsae_min, protenix_ipsae_min, af3_ipsae_min]` (Protenix/AF3 columns land in Parts J & K)
- Merger: `merge_refold_results(boltz2_csv, sequences_fasta)` (dropped `af2_csv` param)
- Report & plots: removed `_compute_af2_boltz2_r`, `_correlation_callout_html`, `plot_af2_vs_boltz2_scatter`; pruned all `af2_*` columns from display lists and tooltip map
- Evaluator orchestration: `evaluate.sh` is now 2-step (Boltz-2 + report); `binder-compare run` is 3-step (extract + refold-boltz2 + report)
- BindCraft's internal AF2 design path, PXDesign's internal AF2 eval, and Proteina-Complexa's AF2 cross-val **all stay** — only Evaluator AF2 refolding was removed

### Fixed
- Configurator `ask_choice()` return value destructuring for PXDesign mode and preset selection
- RFAA template: Python 3.12 f-string syntax replaced with 3.10-compatible `ligand_line` variable
- RFAA template: added missing PYTHONPATH export and `inference.ckpt_path`
- PXDesign requirements.txt overwrites PyTorch with CPU-only version — installer now force-reinstalls with CUDA

## [0.7.0] — Part H: Standalone installer (server-friendly)

### Added
- **Standalone mode**: installer auto-downloads Miniforge3 into `BindMaster/conda/` when system conda is unavailable or read-only (H1–H3)
- `--standalone` flag to force local Miniforge install (H1)
- `--system-conda` flag to opt out and use existing system conda (H1)
- Local conda detection in all Evaluator shell scripts — `evaluate.sh`, `run.sh`, `install.sh` (H13–H15)
- Local conda as first search entry in all generated run scripts from configurator (H12)
- `PLAN_standalone_installer.md` — detailed implementation plan for Part H
- `TODO_standalone_pack.md` — future plan for pre-packed distribution (Part I)

### Changed
- Shortcuts now write to `BindMaster/bin/` instead of `~/.local/bin/` (H4, H9)
- `detect_conda()` rewritten with priority: local conda → writable system conda → auto-bootstrap (H3)
- `_find_conda_base()` in configurator checks `BindMaster/conda/` first (H11)
- `bindmaster.py` shortcut writes to `REPO/bin/` as primary, `~/.local/bin/` as non-fatal fallback (H9)
- Uninstall offers to remove local Miniforge when all tools are uninstalled (H7)
- Install summary now prints PATH instructions for `BindMaster/bin/` (H4)
- All changes mirrored in `install_aarch.sh` for aarch64 / DGX Spark (H8)

## [0.6.1] — Part G: Documentation & CI

### Added
- GitHub Actions CI workflow — shellcheck, ruff, Docker build (G1)
- README badges: CI status, license, Python version, platform (G2)
- CONTRIBUTING.md with development setup and PR conventions (G3)
- CHANGELOG.md (G4)
- Mermaid architecture diagram in README (G5)
- Evaluator troubleshooting section with 7 common issues (G6)
- `ruff.toml` configuration for Python linting and formatting (G1)

### Changed
- Shell scripts now pass `shellcheck --severity=warning` with targeted directives (G1)
- Python code auto-formatted with `ruff format` (G1)

## [0.6.0] — Part F: Configurator UX

### Added
- Evaluator as a tool option in configurator wizard — Step 5 (F1)
- Run folder archiving: `configurator.py --archive <run>` creates tar.gz (F3)
- `configurator.py --status` shows all runs and their completion state (F4)
- Target sequence auto-extraction from mmCIF files (F5)

## [0.5.0] — Part E: Evaluator Enhancements

### Added
- DunbrackLab ipSAE formula: mean aggregation, model-specific PAE cutoffs (E1)
- `--resume` flag for evaluate.sh — skip completed binders via CSV check (E2)
- PXDesign as tool option in configurator wizard (E3)
- `binder-compare validate` subcommand for input sequence sanity checks (E4)
- Per-binder PAE heatmap visualisation in HTML report (E5)

### Changed
- ipSAE columns renamed: Mosaic aux columns get `_aux` suffix, PAE-based columns get `boltz_pae_`/`af2_` prefix (E1)
- Primary ranking column `ipsae_min` now promoted from best available PAE-based source (E1)

## [0.4.0] — Part D: Installer Robustness

### Added
- `Dockerfile.test` with GPU-capable CUDA base image and multi-stage test target (D1)
- `--dry-run` flag for `test_env.sh` — non-interactive install validation (D2)
- `--cuda` flag for `install_aarch.sh` with compatibility warning (D3)
- Retry logic in `run_logged()` with optional `--retries N` (D4)
- Numbered progress summary: "[1/4] BindCraft", "[2/4] BoltzGen", etc. (D5)
- `--uninstall` flag for per-tool removal of conda envs, venvs, and shortcuts (D6)

### Changed
- Tool repos pinned to specific commits for reproducible installs (D7)

## [0.3.0] — Part B: Batch 1 Fixes

### Added
- MIT LICENSE at repo root (B1)
- `--yes/-y` flag for non-interactive installs in `install.sh` (B3)
- Evaluator support in `install_aarch.sh` (B4)
- Exception-based checkpoint in `refold_boltz2.py` (B9)

### Fixed
- `run_logged()` tty guard and tmpfile for failure output (B2)
- Configurator Ctrl+C message (B5)
- `docker-entrypoint.sh` mamba.sh, HOME fallback, .bashrc (B6)
- CSV file handle leaks in refold scripts (B8)
- Hardcoded `AF2_DATA_DIR` in `refold_af2.py` (B10)
- Scatter plot crash on empty mask in `plots.py` (B11)
- Radar chart in `plots.py` — use z-scores (B12)

### Changed
- Added `.dockerignore` (B7)

## [0.2.0] — Part A: Monorepo Merge

### Added
- Evaluator files merged under `Evaluator/` directory (A1)

### Changed
- Root `.gitignore` updated for evaluator patterns (A2)
- `install.sh` `install_evaluator()` uses local dir instead of git clone (A3)
- README updated to reflect bundled evaluator (A4)

## [0.1.0] — Initial Release

### Added
- Unified `bindmaster` CLI entry point (`install`, `configure`, `evaluate`)
- Installers for BindCraft, BoltzGen, and Mosaic
- Interactive configurator wizard
- Evaluator with Boltz-2 and AF2 refolding pipeline
- aarch64 installer for DGX Spark / Grace-Hopper
- Docker test environment
