# BindMaster — Implementation Stages

## Part A: Merge evaluator into monorepo

- [x] A1. Copy evaluator files under `Evaluator/` (exclude .git, __pycache__, *.egg-info, envs/mosaic_venv_path)
- [x] A2. Update root `.gitignore` — remove `Evaluator/` ignore, add evaluator-specific patterns
- [x] A3. Update `install.sh` `install_evaluator()` — remove git clone, use local dir check
- [x] A4. Update `README.md` — change Evaluator from "gitignored" to "bundled evaluator code"
- [x] A5. Commit merge

## Part B: Batch 1 fixes

- [x] B1.  Add MIT `LICENSE` at repo root
- [x] B2.  Fix `run_logged()` in `install.sh` — add has_tty guard + use tmpfile for failure output
- [x] B3.  Add `--yes/-y` flag to `install.sh` (port from install_aarch.sh)
- [x] B4.  Port `install_evaluator()` to `install_aarch.sh` + add to menu/--tool parsing
- [x] B5.  Fix `configurator.py` Ctrl+C message (line 1023)
- [x] B6.  Fix `docker-entrypoint.sh` — add mamba.sh, HOME fallback, .bashrc
- [x] B7.  Add `.dockerignore`
- [x] B8.  Fix CSV file handle leaks in `Evaluator/scripts/refold_boltz2.py` and `refold_af2.py`
- [x] B9.  Add exception-based checkpoint in `Evaluator/scripts/refold_boltz2.py`
- [x] B10. Fix hardcoded `AF2_DATA_DIR` in `Evaluator/scripts/refold_af2.py`
- [x] B11. Fix scatter plot crash in `Evaluator/binder_comparison/visualization/plots.py` — guard empty mask
- [x] B12. Fix radar chart in `Evaluator/binder_comparison/visualization/plots.py` — use z-scores
- [x] B13. Commit batch 1 fixes

## Part C: Finalize batch 1

- [x] C1. Push all changes to `origin/master`
- [x] C2. Archive `damborik22/BindMaster-evaluator` on GitHub

---

## Part D: Batch 2 — Installer robustness & testing

- [x] D1.  Rewrite `Dockerfile.test` with GPU-capable CUDA base image + multi-stage test target
- [x] D2.  Add `--dry-run` to `test_env.sh` — non-interactive install validation (pass/fail)
- [x] D3.  Add `--cuda` flag to `install_aarch.sh` (default 12.1, with compat warning)
- [x] D4.  Add retry logic to `run_logged()` — optional `--retries N` for flaky network operations
- [x] D5.  Add numbered progress summary — "[1/4] BindCraft", "[2/4] BoltzGen", etc.
- [x] D6.  Add `--uninstall` flag — per-tool removal of conda envs, venvs, and shortcuts (safe)
- [x] D7.  Pin tool repo commits (`--depth 50` + checkout) for reproducible installs

## Part E: Batch 3 — Evaluator enhancements

- [x] E1.  Fix ipSAE to match DunbrackLab formula: mean aggregation, model-specific PAE cutoffs, post-hoc from PAE files
- [x] E2.  Add `--resume` flag to evaluate.sh — skip already-completed binders via CSV check
- [x] E3.  Add PXDesign as tool option in `configurator.py` wizard
- [x] E4.  Add `binder-compare validate` subcommand — sanity-check input sequences
- [x] E5.  Add per-binder PAE heatmap visualisation in HTML report (top N binders)

## Part F: Batch 4 — Configurator & UX

- [x] F1.  Add Evaluator as a tool option in `configurator.py` wizard (Step 5)
- [ ] F2.  *(deferred — future)* Add `--headless` mode to `configurator.py` — accept JSON config, skip all prompts
- [x] F3.  Add run folder archiving (`configurator.py --archive <run>` → tar.gz)
- [x] F4.  Add `configurator.py --status` — show all runs and their completion state
- [x] F5.  Add target sequence auto-extraction from mmCIF files (not just PDB)
- [ ] F6.  *(deferred — future)* Add multi-chain binder support in BoltzGen YAML generation

## Part G: Batch 5 — Documentation & CI

- [x] G1.  Add GitHub Actions CI workflow — lint (shellcheck, ruff), test, Docker build
- [x] G2.  Add badges to README (license, CI, Python version, platform)
- [x] G3.  Add CONTRIBUTING.md with dev setup instructions
- [x] G4.  Add CHANGELOG.md
- [x] G5.  Add architecture diagram (Mermaid) in README — tool relationships and data flow
- [x] G6.  Add troubleshooting section for Evaluator (AF2 weight paths, CUDA version mismatches)

---

## Part H: Standalone installer — local Miniforge (server-friendly)

> Goal: BindMaster installs and runs entirely within its own directory.
> No writes to system conda, no writes to ~/.local/bin, no root/admin needed.
> Works on restricted HPC/shared servers where users cannot modify system packages.

- [x] H1.  `install.sh`: add `--standalone` / `--system-conda` flags + auto-detection logic
- [x] H2.  `install.sh`: add `install_local_conda()` — downloads + installs Miniforge3 into `BindMaster/conda/`
- [x] H3.  `install.sh`: modify `detect_conda()` — check local conda first, then system, auto-bootstrap if needed
- [x] H4.  `install.sh`: change `SHORTCUTS_DIR` from `~/.local/bin` to `BindMaster/bin/`
- [x] H5.  `install.sh`: ensure local conda is on PATH before calling BindCraft's `install_bindcraft.sh`
- [x] H6.  `install.sh`: update `ensure_conda_in_path()` to use local conda base
- [x] H7.  `install.sh`: update uninstall to handle local conda envs + local conda removal
- [x] H8.  `install_aarch.sh`: mirror all H1–H7 changes for aarch64
- [x] H9.  `bindmaster.py`: shortcut writes to `REPO/bin/` (fallback `~/.local/bin` if writable)
- [x] H10. `bindmaster.py`: detect local conda when resolving Mosaic venv path
- [x] H11. `configurator.py`: `_find_conda_base()` checks `BINDMASTER_DIR/conda/` first
- [x] H12. `configurator.py`: generated run scripts add local conda path as first entry in conda-search loop
- [x] H13. `Evaluator/evaluate.sh`: add local conda to conda init search
- [x] H14. `Evaluator/run.sh`: add local conda to conda init search
- [x] H15. `Evaluator/install.sh`: add local conda to conda init search
- [x] H16. `.gitignore`: add `conda/` and `bin/` entries
- [x] H17. Update CLAUDE.md: document standalone mode, local conda, new directory layout
- [x] H18. Update README.md: add "Server / HPC installation" section
- [x] H19. Update CHANGELOG.md
- [x] H20. CI: update Dockerfile.test to test standalone mode

## Part I: Pre-packed standalone distribution (future)

> Goal: Ship BindMaster as a single archive needing zero install on the target server.
> Depends on Part H (complete). Detailed plan in `docs/plans.md`.

- [ ] I1.  Add `conda-pack` dependency + verify env packing works
- [ ] I2.  Create `pack/build_pack.sh` — build relocatable archive on dev machine
- [ ] I3.  Create `pack/unpack.sh` — extract + fix paths on target server
- [ ] I4.  Create `pack/manifest.py` — version/checksum metadata
- [ ] I5.  Add `bindmaster pack` subcommand to CLI
- [ ] I6.  Handle Mosaic uv venv relocation (shebang + pyvenv.cfg patching)
- [ ] I7.  BoltzGen weights optional inclusion (`--include-boltzgen-weights`)
- [ ] I8.  Platform build matrix (x86_64-cuda124, aarch64-cuda130)
- [ ] I9.  Documentation: `docs/standalone_pack.md`
- [ ] I10. CI/release: GitHub Actions build + publish to Releases
