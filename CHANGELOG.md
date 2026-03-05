# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
