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

- [ ] D1.  Add `Dockerfile` for full CI install test (install.sh --tool all --yes in container)
- [ ] D2.  Add `test_install.sh` — dry-run validation (checks clones, envs, shortcuts without running ML)
- [ ] D3.  Unify shared functions between `install.sh` and `install_aarch.sh` into `lib/installer_common.sh`
- [ ] D4.  Add `--cuda` flag to `install_aarch.sh` (currently hardcoded 12.1)
- [ ] D5.  Add retry logic to `run_logged()` — optional `--retries N` for flaky network operations
- [ ] D6.  Add progress summary at each stage — "Step 3/7: Installing BoltzGen..."
- [ ] D7.  Add `--uninstall` flag — removes conda envs and shortcuts cleanly
- [ ] D8.  Pin tool repo commits (git clone --branch / --depth 1) for reproducible installs

## Part E: Batch 3 — Evaluator enhancements

- [ ] E1.  Add `--resume` flag to `evaluate.sh` — skip already-completed binders using checkpoint
- [ ] E2.  Add parallel binder evaluation — process N binders concurrently on multi-GPU
- [ ] E3.  Add PXDesign extractor integration into configurator.py tool selection
- [ ] E4.  Add `binder-compare validate` subcommand — sanity-check input sequences before refolding
- [ ] E5.  Add ipSAE computation for AF2 results in the report (currently Boltz-2 only via aux)
- [ ] E6.  Add composite score (ipSAE × |ΔG/ΔSASA|) when native metrics are available
- [ ] E7.  Add per-binder structure overlay visualization (PyMOL script or py3Dmol widget)
- [ ] E8.  Add JSON schema validation for evaluator config / pipeline inputs

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
