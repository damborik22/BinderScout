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

- [ ] F1.  Add Evaluator as a tool option in `configurator.py` wizard (Step 5)
- [ ] F2.  Add `--headless` mode to `configurator.py` — accept JSON config, skip all prompts
- [ ] F3.  Add run folder archiving (`configurator.py --archive <run>` → tar.gz)
- [ ] F4.  Add `configurator.py --status` — show all runs and their completion state
- [ ] F5.  Add target sequence auto-extraction from mmCIF files (not just PDB)
- [ ] F6.  Add multi-chain binder support in BoltzGen YAML generation

## Part G: Batch 5 — Documentation & CI

- [ ] G1.  Add GitHub Actions CI workflow — lint (shellcheck, ruff), test, Docker build
- [ ] G2.  Add badges to README (license, CI, Python version, platform)
- [ ] G3.  Add CONTRIBUTING.md with dev setup instructions
- [ ] G4.  Add CHANGELOG.md
- [ ] G5.  Add architecture diagram (Mermaid) in README — tool relationships and data flow
- [ ] G6.  Add troubleshooting section for Evaluator (AF2 weight paths, CUDA version mismatches)
