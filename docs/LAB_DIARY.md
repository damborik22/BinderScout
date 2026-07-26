# BinderScout / BindMaster — Computational Lab Diary

**Purpose:** Chronological record of architectural decisions, metric breakthroughs, and tool integration milestones from BinderScout's development (Feb–Jun 2026).

**Generated:** 2026-06-16

---

## ⚠ Feb 2026 (approx) — First 2VDY BindCraft run: 1 accept at iPTM 0.90

**What changed:**
- Not in git (predates formal project history). Documented in 2VDY PROGRESS.md as `RESULTS/2VDY_0002/`.
- BindCraft run with `default_filters + default_4stage_multimer_hardtarget` preset, no hotspots, lengths 40–150.
- **Single accept**: `l78_s140877_mpnn11` (L=78, pLDDT 0.91, dG −60.17, **iPTM 0.90**).

**Why it mattered:**
- Establishes the empirical foundation for the hardtarget preset choice in the larger 2VDY campaign (2026-05-24 onward). Demonstrates that hardtarget + V1 filters can yield high-quality designs on known targets.

**Outcome:**
- Baseline design available; hardtarget strategy validated.



---

## 2026-02-27 — Initial release: unified CLI, 3 design tools + Evaluator, aarch64, Docker

**What changed:**
- Initial commit wave (14 commits on one day) bringing together:
  - Unified `bindmaster` CLI entry point dispatching `install`, `configure`, `evaluate`.
  - Installers for BindCraft, BoltzGen, Mosaic design tools.
  - Interactive configurator wizard.
  - Evaluator with Boltz-2 + AF2 refolding pipeline.
  - aarch64 installer for DGX Spark/Grace-Hopper (includes bundled DAlphaBall + dssp binaries).
  - Docker test environment (Dockerfile.test, docker-entrypoint.sh, test_env.sh).

**Why it mattered:**
- Establishes the unified BindMaster architecture; launches the project publicly.

**Outcome:**
- v0.1.0 released; 3 tools + Evaluator functional; x86 + aarch64 paths open.

---

## 2026-02-28 — Parts A–E: monorepo merge → DunbrackLab ipSAE (all in one day)

**What changed:**
- **Part A**: Evaluator merged from separate `BindMaster-evaluator` repo (now archived) into `Evaluator/` directory.
- **Part B (Batch 1 fixes)**: scatter plot crash on empty mask, radar chart z-score, CSV file-handle leaks, hardcoded `AF2_DATA_DIR` path.
- **Part D (Installer robustness)**: Docker test environment (CUDA 12.4, Ubuntu 22.04), `--dry-run` for non-interactive validation, `--uninstall` flag for per-tool removal, retry logic in `run_logged()`, numbered progress summary, tool repo commits pinned for reproducible installs.
- **Part E (Evaluator enhancements)**: DunbrackLab ipSAE formula implemented (`mean_j(1/(1+(PAE_ij/d0)²))`), `--resume` flag to skip completed designs, `binder-compare validate` subcommand for sequence sanity checks, per-binder PAE heatmap in HTML report.

**Why it mattered:**
- Monorepo consolidation; foundational DunbrackLab scoring adopted; CI infrastructure established.

**Outcome:**
- 5 parts landed; Evaluator now in-repo; DunbrackLab ipSAE as the standard metric; installer robust to network failures and supports uninstall.

---

## 2026-03-01 — Parts F + G: Configurator UX + Documentation & CI; ensemble averaging removed

**What changed:**
- **Part F (Configurator UX)**: Added mmCIF sequence extraction (not just PDB). Added `--archive <run>` to tar.gz run directories. Added `--status` to show all runs and their completion state. Evaluator integrated as a tool option in Step 5 of the wizard.
- **Part G (Documentation & CI)**: GitHub Actions CI workflow added (shellcheck, ruff, Docker build). README badges (license, CI, Python, platform). CONTRIBUTING.md with dev setup. CHANGELOG.md. Mermaid architecture diagram in README. Evaluator troubleshooting section (7 common issues).
- **Ensemble averaging removed**: Evaluator no longer blends models; uses Boltz-2 alone as the primary ranking signal.

**Why it mattered:**
- Configurator becomes the primary UX path (Evaluator accessible without command-line flags). CI gates code quality. Ensemble removal simplifies the ranking philosophy.

**Outcome:**
- CLI & configurator complete; public CI live; documentation foundation laid.

---

## 2026-03-03 — CLAUDE.md established as canonical project memory

**What changed:**
- Comprehensive `CLAUDE.md` committed at repo root.
- Sections: behavioral guidelines for AI-assisted development, architecture overview, pipeline flow, directory layout, environment isolation table, design decisions + WHY, conventions (Python style, shell style, naming), domain knowledge (key terminology, tool descriptions, evaluation metrics, calibration facts), current state (active work, recent decisions, known issues), commands (quick start, install, configure, evaluate, linting, testing).

**Why it mattered:**
- Creates a formal project memory accessible to future sessions and AI assistants. Single source of truth for requirements, conventions, and known gotchas.

**Outcome:**
- Comprehensive onboarding document; foundation for agentic integration.

---

## 2026-03-05 — Part H: Standalone installer; TUI menu; Mosaic `is_top=1` filter

**What changed:**
- **Part H (Standalone installer)**: When system conda is unwritable, installer downloads Miniforge3 into `BindMaster/conda/` instead of requiring system-level access. Shortcuts write to `BindMaster/bin/` instead of `~/.local/bin/`. `--standalone` flag to force local conda; `--system-conda` flag to opt out. All changes mirrored in `install_aarch.sh`.
- Added interactive TUI curses menu (`tui/app.py`) for no-args invocation (numbered fallback when curses unavailable).
- Mosaic evaluator now filters to refolded designs only (`is_top=1` from `designs.csv`); guards against the `"REPLACE_ME"` target-sequence placeholder.

**Why it mattered:**
- Enables installation on HPC/shared servers with zero system permissions. TUI improves UX. Mosaic filter prevents nan propagation from template placeholders.

**Outcome:**
- `--standalone` and `--system-conda` flags; `BindMaster/conda/` and `BindMaster/bin/` paths; Mosaic template guard.

---

## 2026-03-06 — Evaluator 2.0: uniform 10 Å PAE cutoff + `agreement_count`; ipTM from PAE files; RFAA + PXDesign merged

**What changed:**
- **Evaluator 2.0**: Replaced model-specific PAE cutoffs with a uniform 10 Å cutoff across all engines.
- Removed the `composite_score` (blend of ipSAE + pLDDT + PAE); now ipSAE is the primary metric.
- Added `agreement_count` column: number of engines passing the 0.61 ipSAE threshold (cross-validation signal).
- ipTM computed directly from PAE files (not trusting tool-reported values).
- **Phase 2 (RFAA + PXDesign) merged from `feature/rfaa-pxdesign-integration` branch**: both tools now integrated into the CLI, configurator, and evaluator.

**Why it mattered:**
- Unified scoring philosophy; DunbrackLab ipSAE formula becomes the standard; agreement signal enables multi-engine validation.

**Outcome:**
- Evaluator schema standardized; Phase 2 tools available; agreement_count opens the door to two-stage ranking.

---

## 2026-03-20 — Proteina-Complexa (NVIDIA, 7th design tool) integrated

**What changed:**
- Proteina-Complexa installed into a uv-managed venv (separate from Mosaic).
- Supports inference-time optimization: best-of-n, beam-search, and MCTS search algorithms.
- Shares AF2 weights with BindCraft (same `AF2_DATA_DIR` path).
- Evaluator gains `ProteinaComplexaExtractor`.

**Why it mattered:**
- Expands the design tool roster to 7; NVIDIA's flow-matching approach complements diffusion-based tools.

**Outcome:**
- Proteina-Complexa available for production runs; CLI integrated; colors/display added to report.

---

## 2026-04-10 — HTML report: PDB export, PyMOL script, methodology; `evaluator/ → evaluator_legacy/`

**What changed:**
- Top-20 refolded PDBs downloadable from HTML report.
- PyMOL analysis script for structural inspection embedded in report.
- Per-tool native-ranked top-10 viewer added (NGL 3D, per-tool metrics table).
- Methodology section added (documents ranking method, engines, scoring formulas).
- Legacy single-file evaluator moved from `evaluator/` to `evaluator_legacy/` to make room for the bundled `Evaluator/` package as the canonical path.
- `--tool-csv` flag added for per-tool native-ranked outputs.

**Why it mattered:**
- Report becomes an interactive analysis platform, not just a table. Path clarity for the package.

**Outcome:**
- Report HTML richer; evaluator CLI pathway clear; per-tool debugging enabled.

---

## 2026-04-20 — NGL 3D viewer added to HTML report; Boltz-2 OOM fix

**What changed:**
- HTML report now embeds an interactive NGL 3D viewer for top-20 refolded structures and per-tool top-10 PDBs.
- Boltz-2 refolding OOM on long binders fixed: sort sequences by length before batching, clear JAX caches between batches.

**Why it mattered:**
- 3D visualization aids structural validation; batch ordering + cache clearing enables long binders on 24 GB hardware.

**Outcome:**
- Report UX enhanced; Boltz-2 memory efficiency improved.

---

## 2026-04-23 — Part I: AF2 refolding removed from Evaluator

**What changed:**
- Deleted: `refold_af2.py`, `refold_Version6.py`, `af2_runner.py`, `binder-eval-af2.yml` conda env.
- Removed 8 `af2_*` fields from `StandardisedMetrics` schema.
- `evaluate.sh` becomes 2-step: Boltz-2 refold + report (AF2 step removed).
- BindCraft, PXDesign, Proteina-Complexa still use AF2 internally — only Evaluator's cross-validation step removed.

**Why it mattered:**
- AF2 PAE calibration issues identified; makes room for AF3 + ESMFold2 as the multi-engine panel.

**Outcome:**
- Cleaner schema; Evaluator architecture simplified; paves the way for Part K/J.

---

## 2026-04-24 — Parts J/K/L/M: Protenix + AF3 + Protein-Hunter + RFD3 land in one PR (#5)

**What changed:**
- **Part J**: Protenix v0.5.0 added as 2nd refold engine (24 GB capable, rides `bindmaster_pxdesign` conda env).
- **Part K**: AlphaFold 3 v3.0.2 added as canonical refold engine on big-VRAM hardware (aarch64/Spark-first; `binder-eval-af3` env; >100 GB requirement).
- **Part L**: Protein-Hunter integrated (`bindmaster_protein_hunter` conda env, x86 only — PyRosetta no aarch64 wheels). New `ProteinHunterExtractor` reads `summary_high_iptm.csv`.
- **Part M**: RFD3 (RosettaCommons/foundry) integrated (`bindmaster_rfd3` env, `rc-foundry[rfd3,mpnn]` from PyPI, x86 + aarch64, BSD-3, commercial-use OK). Weights at `BindMaster/weights/foundry/`. New `RFD3Extractor`.
- **RFAA deprecated** (not yet fully removed; deletion comes 2026-05-28).

**Why it mattered:**
- Opens the full multi-engine refold architecture (Protenix for 24 GB, AF3 for big VRAM, ESMFold2 coming soon). Adds two major new design tools (Protein-Hunter, RFD3) in one push.

**Outcome:**
- 4 new tools integrated; 3 refold engines available; aarch64 support for Protein-Hunter verified as blocked (PyRosetta), RFD3 verified as working.

---

## 2026-04-26 — RFD3 runtime gotchas documented

**What changed:**
- CLAUDE.md gotchas section added for RFD3 (`run_rfd3.sh.template` reference).
- Documented: `FOUNDRY_CHECKPOINT_DIRS` (plural-S; singular silently ignored); `mpnn` is a separate console-script (not `foundry mpnn`); `--designed_chains '["B"]'` must be JSON list of letter strings (not bare `B` or digits); `--is_legacy_weights True` required for legacy `.pt` format; `foundry install proteinmpnn` is separate from `foundry install rfd3`.

**Why it mattered:**
- Prevents silent failures and cryptic error messages on first RFD3 use.

**Outcome:**
- CLAUDE.md RFD3 section; template comments; explicit parameter examples.

---

## 2026-04-27 — Protein-Hunter runtime gotchas documented

**What changed:**
- CLAUDE.md gotchas section added for Protein-Hunter (`run_protein_hunter.sh.template` reference).
- Documented: `--msa_mode` valid values are `single` or `mmseqs` (not `single_sequence`); `download_boltz2(cache=Path.home()/'.boltz')` requires positional `Path` argument; `~/.boltz/mols/` must contain ~45k .pkl files (CCD components) or startup aborts; `pyrosetta-installer ≥ 0.3` renamed `download_pyrosetta → install_pyrosetta`.

**Why it mattered:**
- Operators avoid hours of debugging on common installation/invocation mistakes.

**Outcome:**
- CLAUDE.md Protein-Hunter section; template comments match.

---

## 2026-04-28 — Per-run `settings.json` reproducibility convention established

**What changed:**
- All run scripts write a `settings.json` into `runs/<name>/<tool>/` before the design step starts.
- Required keys: `tool`, `started_at` (ISO-8601 UTC), `version` (BindMaster git SHA + tool git SHA or package version), `target` (name, sequence, length), `design_params` (all CLI flags), `env` (conda env, Python version, GPU ID, GPU name, GPU memory MiB).
- `run_rfd3.sh.template` and `run_protein_hunter.sh.template` are the canonical examples.

**Why it mattered:**
- Future sessions can answer "what parameters produced these designs?" without grepping logs or trusting edited run scripts. Reproducibility anchor.

**Outcome:**
- Convention documented; templates implement it; CALCA/2VDY campaigns use it going forward.

---

## 2026-05-05 — GitHub Actions CI established; Mosaic grpcio-tools conflict patched

**What changed:**
- GitHub Actions CI wired: shellcheck, ruff, pytest, Docker build in `.github/workflows/ci.yml`.
- `install.sh` patched to override `grpcio-tools>=1.60` in Mosaic's `pyproject.toml` (upstream pin incompatible with JAX's gRPC).

**Why it mattered:**
- Automated quality gates; silent install failures prevented.

**Outcome:**
- CI pipeline active; reproducible dependency management.

---

## 2026-05-07 — RFD3 OOM fix: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments`

**What changed:**
- RFD3 design on BM4 (RTX 3090, 24 GB) died at batch 7/20 from PyTorch memory fragmentation (not capacity — peak live ~15 GiB but reserves ~6 GiB unallocated).
- Fix: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` environment variable.
- Encoded in `run_rfd3.sh.template` and configurator.

**Why it mattered:**
- Enables RFD3 completion on 24 GB GPUs without OOM; 2VDY run subsequently completed all 20 batches in 23 h.

**Outcome:**
- RFD3 now memory-safe on 24 GB hardware; template carries the fix forward.

---

## ~2026-05-06–10 — CALCA: phaseB multi-engine eval (Boltz-2 + Protenix + AF3)

**What changed:**
- `CALCA_eval_phaseB` — the first time three refolding engines were applied to a real CALCA campaign pool.
- Protenix served as the 2nd engine (before AF3 was available on x86); AF3 ran on Spark (>100 GB VRAM requirement).
- This round preceded the curated top50/top350 evaluations.

**Why it mattered:**
- Early proof-of-concept for multi-engine evaluation; Protenix later superseded by AF3 + ESMFold2.

**Outcome:**
- Feasibility confirmed; pipeline architecture validated.

---

## 2026-05-16 — CALCA INVESTIGATION: AF2 ipSAE mis-calibrated on short targets; model-bias confirmed

**What changed:**
- Scientific audit on `CALCA_helix_BM4` pool (4 005 designs, 5 tools; this is a separate, earlier CALCA run).
- Analysis run 2026-05-16 on BM5/Spark; findings documented in `INVESTIGATION_RANKING_DISCREPANCY.md`.
- **Finding H1 (model-origin bias)**: Mosaic and BoltzGen designs game Boltz-2 ipSAE by construction (Mosaic ρ = 0.63, BoltzGen `design_ipsae_min` ρ = 0.84 to refold ipSAE). Boltz-2 top-20 is 11/20 Mosaic, 4/20 PXDesign, 4/20 BoltzGen — biased toward tools that optimized for Boltz-2-style features.
- **Finding H2 (AF2 ipSAE mis-calibration)**: AF2 ipSAE 0% pass rate on 32-aa target (mean BT PAE 11.32 Å vs 10 Å cutoff). Calibration issue, not sequence quality.
- **Finding H3 (selection bias)**: 3× enrichment of short binders (≤40 aa) in Boltz-2 top-20 vs full pool (40% vs 5.7%).
- **Recommendation**: add AF3 + require multi-engine agreement (directly motivates Parts J/K and the two-stage ranking).

**Why it mattered:**
- Benchmark evidence for why single-engine ranking fails; validates the multi-engine consensus approach.

**Outcome:**
- Motivated architectural pivot to AF3 + ESMFold2 + two-stage ranking (deployed 2026-06-07, validated 2026-06-11).

---

## ~2026-05-16–28 — CALCA: curated top50/top350 evaluation rounds (Boltz-2 + AF3, 3-engine pending)

**What changed:**
- `CALCA_eval_top50` (May 17–28) and `CALCA_eval_top350` (May 18–21) evaluated 350 and 2 450 designs respectively (7 tools × 50 and 7 tools × 350).
- Refolded with Boltz-2 + AF3 (ESMFold2 not yet available; added later on 2026-06-11).
- Preliminary 2-engine reports generated with `passes_max_screen` and `agreement_count` columns.
- **BindCraft `variant_a` preset yielded 0 designs** (failed config); `default` preset gave 350 accepts.

**Why it mattered:**
- Established curated pools for final reporting; early multi-engine evaluation before the 3-engine panel completed.

**Outcome:**
- 2-engine reports later superseded by 3-engine canonical reports (2026-06-11).

---

## 2026-05-19 — 2VDY: Protein-Hunter MSA mode discovery: `single` → 1 design ≥0.85; `mmseqs` → 95

**What changed:**
- Two back-to-back runs on Clara H200 (SLURM 98065 and 99346, ~11 h each, otherwise identical config).
- R1 (`--msa_mode single`, no MSA): 1 design ≥0.85, median iPTM 0.357.
- R2 (`--msa_mode mmseqs`, ColabFold MSA on target): **95 designs ≥0.85**, median iPTM 0.857.

**Why it mattered:**
- Discovered that the **target MSA** (ColabFold via mmseqs on the known CBG sequence) drives Boltz-2's interface confidence even when the binder is de novo and has no MSA of its own.
- Lesson: for known targets, `--msa_mode mmseqs` is the correct default regardless of binder novelty.

**Outcome:**
- MSA mode selection now target-aware; ~100× quality improvement in this case.

---

## 2026-05-24 — Docs/skills refresh; orchestrator + worker skills published

**What changed:**
- CLAUDE.md and README updated to reflect Parts I–M status.
- `bindmaster-orchestrator` and `bindmaster-worker` Claude Code skills published with comprehensive reference docs: 14 reference files across tool-specific guides, evaluation pipeline, troubleshooting, learnings from 2VDY/CALCA campaigns.

**Why it mattered:**
- Formalizes the agentic interface for binder-design campaign execution (AI-assisted orchestration and per-machine workflows).

**Outcome:**
- Skills infrastructure ready for production use; campaign knowledge codified.

---

## 2026-05-24 — 2VDY: PC MCTS beats best-of-n — 10× rate at ≥0.85, ⅓ wall-clock

**What changed:**
- SLURM 109934 (9h 45m H200) vs baseline 101082 (29h 55m H200).
- MCTS config: `algorithm=mcts`, `n_simulations=8`, `step_checkpoints=[0,100,200,300,400]` (depth 4), `keep_lookahead_samples=false` (avoids beam-search wedge).
- **Rate at ≥0.85**: 1.0% vs 0.1% (**10×**); median iPTM 0.207 vs 0.149 (+39%); p95 0.675 vs 0.402 (+68%); top1 tied at ~0.85.

**Why it mattered:**
- MCTS proved superior search algorithm for this target; same top ceiling but far higher density of high-quality candidates.

**Outcome:**
- MCTS adopted as the standard PC search strategy going forward; baseline best-of-n abandoned for production.

---

## 2026-05-27 — 2VDY: Mosaic ColabFold rate-limit fixed (`binder use_msa=False`)

**What changed:**
- Bug: Mosaic's `hallucinate_bindmaster.py` template had `use_msa=True` for both target and de-novo binder chains.
- Each hallucination step triggered a fresh MMseqs request for an evolving sequence (no cache hits), hitting ColabFold's rate limit over hours.
- Fix: patch binder chain to `use_msa=False` at two code locations (Stage 1 design loop ~line 395, Stage 2 ranking eval ~line 513). Keep target `use_msa=True` for the MSA-on-known-targets quality benefit.

**Why it mattered:**
- Enables long Mosaic runs on known targets without hitting ColabFold's external rate limits.

**Outcome:**
- Template patched; no architecture changes needed.

---

## 2026-05-27 — 2VDY: PC MCTS + cortisol-pocket hotspots → 50/100 ≥ iPTM 0.85 (67× baseline)

**What changed:**
- SLURM 115830, ~10 h H200. Registering the cortisol-pocket 14-residue hotspot set (`A15,A18,A19,A22,A232,A240,A242,A260,A263,A264,A267,A366,A368,A371`) in Proteina-Complexa config.
- **Yield transformation**: 50/100 ≥ iPTM 0.85 vs the 0.75% baseline from 400 no-hotspot designs (**67× rate improvement**).
- Top design: id_gen=26, L=59, iPTM 0.906.
- Campaign unlock for the PC leg: "50 PC designs at iPTM ≥ 0.85" target achieved in a single overnight run.

**Why it mattered:**
- Demonstrates the power of hotspot targeting in PC's MCTS algorithm; dramatically shifts the accessible design space.

**Outcome:**
- 50/100 high-quality candidates; top iPTM ceiling moved from ~0.85 to >0.90.

---

## 2026-05-28 — 2VDY: BindCraft BM4 killed by kernel OOM (JAX allocation leak, 9 days)

**What changed:**
- BindCraft with hotspots on BM4 (RTX 3090) run killed by kernel OOM-killer after 9 days. RSS grew to 58 GB / 89% sysmem.
- 0 accepts from 203 trajectories (every MPNN sequence failed the V2 interface PAE filters before OOM).
- Root cause: JAX backend allocation leak across trajectories with no per-trajectory cleanup.

**Why it mattered:**
- Revealed memory scaling issue in BindCraft on 24 GB hardware; documented for future runs.

**Outcome:**
- Workaround documented: `systemd-run --user --scope -p MemoryMax=40G` (sets hard limit so process gets clean OOM at known threshold instead of kernel kill).

---

## 2026-05-28 — Major sprint: RFAA removed; AF3 + ESMFold2 land; native metrics; schema 9 → 36 fields

**What changed:**
- **RFAA removed** entirely (~2 689 lines); RFD3 replaces all all-atom diffusion use cases.
- **AF3 v3.0.2 ported from aarch64 to master** as canonical 2nd refold engine (`binder-compare refold-af3`, `binder-eval-af3` env; >100 GB VRAM requirement).
- **ESMFold2 (biohub) added as 4th refold engine** — lightweight, no gated weights, works on 24 GB GPUs.
- **Native design-time metrics preserved for all 7 tools** — every extractor (BindCraft, BoltzGen, Mosaic, PXDesign, Proteina-Complexa, Protein-Hunter, RFD3) populates `NativeMetrics`; report joins them alongside cross-validation scores.
- `StandardisedMetrics` schema grows 9 → 36 fields (tool-prefixed native columns).

**Why it mattered:**
- Three-engine refold panel now available on all platforms (AF3 on Spark/H200, ESMFold2 on any GPU). Native metrics enable per-tool debugging and confidence comparison.

**Outcome:**
- Major schema/tool expansion; consolidated architecture; evaluator now cross-validates against multiple engines by default.

---

## 2026-05-29 — SoluProt 1.0 integrated as pre-refold solubility screen; repo renamed BinderScout

**What changed:**
- SoluProt 1.0 (Hon et al. 2021, *E. coli* sequence-only solubility predictor) wired as `--tool soluprot`, `binder-compare filter-soluprot`, and `evaluate.sh` Step 0.5 (runs before any GPU work).
- `--soluprot-filter` drops sub-threshold designs from FASTA before refolding (no redundant GPU cycles on insoluble designs).
- Dedicated `binder-eval-soluprot` conda env (Python 3.7, scikit-learn 0.20.1, x86 only; USEARCH dependency).
- GitHub repo renamed from BindMaster → **BinderScout** (CLI/env names stay `bindmaster`, migrate incrementally).
- Extractor column-name drift fixes for RFD3, PXDesign, Proteina-Complexa from real campaign runs.

**Why it mattered:**
- SoluProt screen gates expensive refold computation; repo rename reflects the public-facing project name.

**Outcome:**
- New `--tool soluprot` option; evaluator pre-refold stage; project identity clarified.

---

## 2026-05-30 — Evaluator refold engine integration bugs fixed; installer GPU-dep gaps

**What changed:**
- First real-hardware smoke test of Boltz-2 + ESMFold2 pipeline revealed: (1) ESMFold2 runner missing `--device` flag (silent CPU fallback); (2) installer not installing CUDA-aware torch into `binder-eval-esmfold2` env.
- Six targeted fixes across installer, refold scripts, and GPU device handling.

**Why it mattered:**
- Prevents silent degradation to CPU inference (would have made ESMFold2 ~100× slower).

**Outcome:**
- Learnings captured in orchestrator skill; multi-engine pipeline now verified end-to-end.

---

## 2026-05-31 — ESMFold2 silent NaN bug fixed; JAX broken in Mosaic venv repaired

**What changed:**
- ESMFold2 returned all-NaN PAE when `num_diffusion_samples > 1` (mean of token confidence computed before per-sample loop). Fix: force `num_diffusion_samples=1`.
- JAX/jaxlib version mismatch from an earlier installer change broke Boltz-2 refolding in the Mosaic venv. Pinned jaxlib to restore compatibility.

**Why it mattered:**
- Both bugs silently produced wrong scores (NaN outputs in CSV, no Python error) — would have corrupted campaign evaluations if deployed.

**Outcome:**
- Errors caught before production use; both fixed in installer and refold scripts.

---

## 2026-06-04 — `consensus_iptm` (max-engine) ranking column; target MSA caching; Part N plan

**What changed:**
- `consensus_iptm = max(boltz_pae_iptm, af3_pae_iptm, esmfold2_pae_iptm)` added as explicit column to report.
- Target MSA computed once and cached to disk for AF3 and ESMFold2 refolders (large speedup on multi-design batches).
- Part N design doc written: interface ΔG ranking via Rosetta InterfaceAnalyzer, motivated by ProteinBase 4-target benchmark (175 designs with experimental Kd).

**Why it mattered:**
- Explicit consensus column aids diagnostics and secondary ranking. Target MSA cache eliminates redundant network calls.
- Part N framing: structure-confidence metrics separate binder from non-binder (~0.75 AUC) but cannot rank affinity among binders.

**Outcome:**
- Report schema extended; Part N plan documented (implemented 2026-06-16).

---

## 2026-06-04 — 2VDY: BindCraft tuned push completes — 55 unique backbones; campaign dG best −98.88

**What changed:**
- Four parallel Clara sessions (H200 ×2 + L40S ×2, 4-day walltime each, V4 advanced preset, `max_mpnn_sequences=1` patch for unique-backbone mode).
- Yields: 55 unique backbones total (h200-a: 14, h200-b: 15, l40s-c: 13, l40s-d: 13).
- **Campaign-best by binding-engineering metrics**: l40s-c L=109, iPTM 0.86 / pLDDT 0.90 / **dG −98.88** (eclipses prior best dG −84 from session 109936).
- Campaign refold pool now ~85 unique backbones (~70% over 50-design target).

**Why it mattered:**
- Pushes the 2VDY campaign past the target quantity margin and identifies the strongest predicted binder by multiple metrics.

**Outcome:**
- 239 trajectories, 1 010 MPNN sequences; median iPTM 0.755, top1 iPTM 0.900 (h200-a, L=46).

---

## 2026-06-07 — Two-stage cross-engine ranking introduced (`max_screen → mean_iptm`)

**What changed:**
- Stage 1 (screen): `consensus_iptm = max(boltz_pae_iptm, af3_pae_iptm, esmfold2_pae_iptm)`; keep top 50% (`passes_max_screen`).
- Stage 2 (rank): sort survivors by `consensus_iptm_mean` (mean of the three engine iPTMs).

**Why it mattered:**
- Benchmark (CALCA + ProteinBase): `max` alone (precision@top-10% 0.79) is gamed by same-model designs; mean of survivors penalizes engine disagreement continuously (precision@top-10% 0.92).
- Directly addresses the CALCA INVESTIGATION finding of Mosaic/BoltzGen model-origin bias.

**Outcome:**
- New default ranking method; ~284 lines of code added to `comparison/scoring.py`; test coverage added.

---

## 2026-06-07 — BoltzGen sequence column bug fixed (results changed for nanobody CDRs)

**What changed:**
- Bug: `BoltzGenExtractor` was reading `designed_sequence` (designed residues only, ~25–42 aa for CDR redesign) instead of `designed_chain_sequence` (full binder chain, 112–133 aa for VHH).
- Effect: refolding received truncated binder sequences, producing artificially low ipSAE for any BoltzGen nanobody/CDR run.
- Fix: reorder `_SEQUENCE_COL_CANDIDATES` to prefer `designed_chain_sequence`.

**Why it mattered:**
- Nanobody and CDR-redesign runs were being under-scored; results now reflect true interface quality.

**Outcome:**
- Verified on 2VDY target; BoltzGen results for CDR modes now traceable.

---

## 2026-06-08 — Report: per-tool structures linked; best-design dedup; method-aware sections

**What changed:**
- `binder-compare report` now matches each design back to the design tool's original PDB/CIF by binder sequence and surfaces download links.
- Best-design deduplication added: one row per unique binder sequence (eliminates redundant MPNN variants).
- Methodology section becomes tool-aware (documents which tool generated each sequence).

**Why it mattered:**
- Traceability from final ranking back to the design tool's structure enables validation and confidence building.

**Outcome:**
- Report HTML now includes per-tool structure links and dedup logic.

---

## 2026-06-11 — CALCA final 3-engine report + two-stage ranking made the default

**What changed:**
- ESMFold2 added to `CALCA_eval_top50` and `CALCA_eval_top350` evaluation rounds, completing the 3-engine panel (Boltz-2 + AF3 + ESMFold2).
- Canonical reports generated: `CALCA_top50_FINAL_report_3engine_iptm_mean/`, `CALCA_top350_FINAL_report_3engine_iptm_mean/` with two-stage ranking (`consensus_iptm_mean`).
- Two-stage ranking (`max_screen → mean_rank`) made the default in `binder-compare report` (motivated by CALCA results confirming it as the production method).
- `bindmaster evaluate` rewired as a passthrough to the `binder-compare` CLI in the `binder-eval` env (retiring the old direct dispatch path).
- Unused `bindmaster/` Python package (~1 080 lines: BinderScore, PXDesignRunner, FeatureFlags — "World B") deleted; `Evaluator` is now the single scoring layer.

**Why it mattered:**
- CALCA results validate the two-stage cross-engine ranking as the benchmark-proven method (precision@top-10% 0.92 vs 0.79 for max-only).
- Campaign lead identified: `ph_top_21` (Protein-Hunter, 134 aa) is #1 in both top50 and top350 pools at `iptm_mean` 0.945 — robust regardless of pool size.
- Architectural cleanup: single evaluation path (binder-compare), no dead code.

**Outcome:**
- 334 binders from 7 tools refolded with 3 engines; two-stage default; ~1 080 lines of dead code removed; benchmark-validated ranking method in production.

---

## 2026-06-12 — `binder-compare autosize`: ESMFold2-gated closed-loop binder-length selector

**What changed:**
- New command gates binder-length selection decisions on ESMFold2 `chain_iptm_interface`.
- Local closed-loop mode added: generate → ESMFold2 refold → decide → loop.
- Three tier-aware gates: permissive / default / strict (replacing a bare single default).

**Why it mattered:**
- Enables rapid iterative binder-length optimization without manual intervention.

**Outcome:**
- `binder-compare autosize` CLI command, unit tests, canonicalized `chain_iptm_interface` as the gate metric.

---

## 2026-06-14 — ESMFold2 promoted to default refold engine; Protenix demoted to optional-only

**What changed:**
- ESMFold2 moved from "4th optional engine" to `--tool all`, auto-detected by `evaluate.sh`, and required gate metric for `autosize`.
- Protenix (v0.5.0) becomes the sole opt-in engine for smaller GPUs (24 GB capable).

**Why it mattered:**
- ESMFold2 has no gated weights and fits any GPU size — better default. Protenix runs only when explicitly needed.

**Outcome:**
- Status flip in installer and documentation; no metric changes.

---

## 2026-06-14 — BindMaster2 grafts: 5 new `binder-compare` capabilities complete closed campaign loop

**What changed:**
- Five capabilities ported from the abandoned BindMaster2 concept: `wetlab` (ranked designs → experimental plan), `mature` (Kd → next-round diffusion/MPNN strategy), `monomer` (context-dependent fold detection via in-complex vs alone RMSD), `affinity` (interface ΔG composite + ipSAE gate, Part N), `analyze-target` (difficulty heuristic + hotspot suggestions).
- Together with existing `autosize` command, these close the full campaign loop: analyze-target → autosize → report → affinity → monomer → wetlab → [wet lab] → mature → autosize.
- All five have unit tests and Claude Code skill references.

**Why it mattered:**
- Completes the lifecycle infrastructure for closed-loop binder design campaigns (from target characterization through wet-lab handoff and maturation rounds).

**Outcome:**
- Five new `binder-compare` subcommands, five finalized Claude Code skills (`bindmaster-evaluator`, `bindmaster-wetlab`, `bindmaster-target-analyst`, `bindmaster-orchestrator`, `bindmaster-worker`).

---

## 2026-06-16 — Adaptyv benchmark validates two-stage; Part N redesigned (gate-then-density)

**What changed:**
- Two-stage ranking (`consensus_iptm_mean` for survivors vs `consensus_iptm_max` for screening) validated on Adaptyv 4-target / 662-design benchmark (experimental Kd). Macro AUC 0.710 vs 0.689 (previous max-only baseline), +20 true binders recalled, higher purity at 50% cut.
- `--screen-metric {max,mean}` flag added to report, then the **default flipped `max` → `mean`** (the Adaptyv benchmark uses real experimental Kd and is trusted over ProteinBase). The legacy max screen stays available via `--screen-metric max`. Column name `passes_max_screen` unchanged to preserve plot/viz compatibility.
- Part N affinity redesigned: structure confidence (`ipsae_min`) shown to carry ~0, sign-unstable correlation with Kd (Spearman pooled Boltz-2: −0.09; mean: +0.13; macro ≈ +0.04, sign flips per target). Affinity metric drops the `ipsae_min × |dG/dSASA|` composite: now pure `|dG/dSASA|` (interface energy density). `ipsae_min` becomes a **gate** only (`passes_affinity_gate = ipsae_min ≥ 0.61`).
- `affinity_composite` renamed `interface_energy_density`; `--gate-threshold` flag added to CLI. Evaluator skill + grafts docs updated.

**Why it mattered:**
- Benchmark validation confirms two-stage as the production ranking method (not just theory).
- Part N refocus on pure energy density eliminates spurious correlations and makes affinity ranking actionable.

**Outcome:**
- 103 tests pass (rewrote `test_affinity.py` for gate-then-density + ipsae-independence + screen-metric tests).
- **2VDY (CBG) reranked** with the new mean-screen — 400 designs across 8 tools, reusing the Jun-7 Boltz-2 + AF3 + ESMFold2 refolds (no GPU). The top-80 is **identical** to the old max-screen (first divergence at rank 81; 46 designs flip near the 50% boundary, all movers rank ≥81), so the wet-lab shortlist is robust to the screen choice. New report at `2VDY_CBG/RESULTS/2VDY_Evaluator_two_stage/report_two_stage_mean/`.
- Shipped on branch `two-stage-screen-metric-and-partn-affinity` (PR pending); CLAUDE.md ranking section + terminology aligned to the mean default.

---

## 2026-06-16 — Report generator surfaces SoluProt + qc-annotate panels (advisory); 2VDY enhanced

**What changed:**
- `binder-compare report --qc-results` ingests qc-annotate's BindCraft interface panel (`qc_pass` / `qc_fail_reasons` / `interface_*`) by `binder_id`. Advisory SoluProt (`native_soluprot_score`) + qc columns now render in the report's top-N table, full table, and a legend. Both ADVISORY — surfaced for review, never used to reorder or drop (hard-gating the BindCraft panel removes ~⅔ of cross-engine designs).
- New `tests/binder_comparison/test_report_advisory.py`; 108 tests pass.

**Why it mattered:**
- Adds solubility + interface-quality QC to the report without disturbing the benchmark-validated ranking.

**Outcome:**
- 2VDY (CBG) report enhanced end-to-end: SoluProt on all 400 designs (24/30 of the top-30 predicted soluble, median 0.65) + qc-annotate on the top-30 (4/30 pass the strict BindCraft panel; the rest fail mainly on buried-unsat H-bonds yet carry strongly favorable ΔG — `protein_hunter_13_c10` best: qc_pass, sc 0.75, ΔG −178.5). Report at `2VDY_CBG/RESULTS/2VDY_Evaluator_two_stage/report_two_stage_mean_enhanced/`.
- SoluProt aarch64 build exercised on real campaign data (`sklearn020-build` env + USEARCH v12).

---

## 2026-06-17 — Adaptyv full-batch confirms esm_chain as a binder SCREEN (0.69, not 0.745); 3-engine comparison

**What changed:**
- Refolded the full experimentally-labeled Adaptyv 4-target set (Nipah/EGFR/IL7R/PD-L1) with all 3 engines and computed per-engine screen AUCs (binder vs non-binder). ESMFold2 schema gap fixed: the unified refolder emits `iptm_pair`/`iptm_pair_min`; `cli/report.py` now derives `esmfold2_chain_iptm_interface = (iptm_pair+iptm_pair_min)/2` (commit `8405b11`).
- 3-engine leaderboard built: per-engine `iptm`/`ipSAE_min` + cross-engine max/mean/min combos, scored as binder screens. Run dir `runs/adaptyv_esmfold2_confirm/`.

**Why it mattered:**
- The earlier 180-design subset put `esm_chain` at macro AUC **0.745** — winner's curse. On the full batch it is **0.692** (IL7R alone collapsed 0.875 → 0.683 from 20 → 96 designs). The honest, de-biased screen number.

**Outcome:**
- Best single screen = **Boltz-2 `iptm` 0.712**; `mean` consensus ties it; **no combination beats the best single engine**; `ipSAE_min ≈ iptm`. Plateaus ~0.71. No universal engine winner (ESMFold2 wins Nipah, Boltz-2 EGFR, AF3 IL7R/PD-L1).
- HTML reports + `combinations`/`leaderboard` CSVs pushed to MUNI `EVALUATOR/3engine_binder_comparison/`.

---

## 2026-06-18 — Affinity RANKING: exhaustive in-silico search comes up empty; qc-annotate shipped

**What changed:**
- Tested whether *any* in-silico metric ranks binding STRENGTH (Strong/Medium/Weak), not just binder-vs-non. Per design, 3 structure engines: confidence (`iptm`/`ipSAE`), relaxed Rosetta interface ΔG + `|dG/dSASA|`, the full BindCraft 14-metric quality panel (shape complementarity, packstat, H-bonds, buried-unsat H-bonds, hydrophobicity, # interface residues), and **PRODIGY** (contact model *trained on experimental Kd*).
- New `binder-compare qc-annotate` (commit `2836ed8`): relax + BindCraft interface panel as an **advisory** annotation on a shortlist (`qc_pass`/`qc_fail_reasons` + panel values) — never drops/reorders (`--drop-failures` opt-in). Validated: hard-gating with BindCraft defaults removes ~⅔ of true binders on predicted structures (panel ≈ 0.52-AUC binder classifier).

**Why it mattered:**
- Closes the "find a strength metric" search and prevents re-running it expecting a win.

**Outcome:**
- **Nothing ranks strength.** Best |pooled ρ| across all metrics × engines = **0.34** (`dG/dSASA`, only 2/4 targets); the BindCraft panel does *no* better than raw dG (sc/packstat inverted); **PRODIGY |ρ| ≤ 0.15** despite being Kd-trained. Confidence/ΔG screen binders (~0.6–0.72) but the within-binder strength signal is ~0 / mildly inverted (length confound). The `ipSAE×dG` composite from the original Part N plan does *not* rescue it.
- "screen-then-invert" (filter top-20% by mean_iptm, rank ascending) looked usable pooled (66% vs 16% Strong, partial ρ −0.38) but is a **Simpson's-paradox artifact** — replicates on EGFR only (ρ −0.71); IL7R flat, Nipah reversed. Do not use.
- Reports `REPORT_partN_deltaG_affinity.html`, `REPORT_strength_ranking_search.html`, `REPORT_screen_then_invert_STRONG_binders.html` on MUNI.

---

## 2026-06-22 — External corroboration: OpenBind + SKEMPI; affinity unsolved everywhere, "structure-quality bottleneck" refined

**What changed:**
- Ran the **OpenBind A71EV2A** benchmark (RosettaCommons, released 2026-06-03) — crystal protein–ligand structures + real Creoptix Kd. Reproduced the authors' affinity table exactly.
- Ran a **SKEMPI 2.0** crystal control + a predicted-structure arm: PRODIGY + Rosetta ΔG on 343 crystal protein–protein complexes vs Kd, AND our ESMFold2 refold of the same complexes (243 ≤600-token) vs the same Kd. Positive control = the curated Affinity Benchmark v2. Work dir `~/dev/openbind/`.

**Why it mattered:**
- Two independent, gold-standard datasets test whether affinity ranking is solved by *anyone*, and whether crystal structures rescue it.

**Outcome:**
- **OpenBind:** the best affinity predictor is **molecular weight** (Spearman **0.48**), beating Boltz-2 (0.40) and dedicated ML models — the size confound, in someone else's benchmark. Affinity unsolved even on crystal/protein-ligand/wide-Kd.
- **SKEMPI:** PRODIGY ranks Kd at only **0.20** on broad crystals (positive control 0.56 — the famous ~0.73 is a curated-benchmark artifact); Rosetta ΔG **0.12** (weakest). Crucially, on the SAME complexes our **predicted-structure ipTM = 0.28 ≈ crystal PRODIGY 0.27**. This **refines** the earlier "predicted structure is the bottleneck": for natural complexes predicted ≈ crystal; no single-structure metric exceeds ~0.3 anywhere. Adaptyv de novo ≤0.15 is a *special* regime (OOD designs + coarse labels + length confound), not generic predicted-is-bad.

---

## 2026-06-23 — De novo replication (BindCraft) confirms the SCREEN half (0.91); combination report v2 adds ipSAE_mean

**What changed:**
- Independent de novo replication: extracted **BindCraft Nature 2025** designs (SI `m4.csv` — 152 with experimental Binding labels + SPR Kd + sequences) and refolded them through our pipeline. Targets sourced from the BindCraft repo (PD-L1) + UniProt/PDB (PD1, CLDN1, BetV1, IFNAR2, BBF-14, DerF7).
- Rebuilt the combination report symmetrically (`combination_report_v2.html`): 6 features = 3 engines × {`iptm`, `ipSAE_min`}, ALL aggregations (max/mean/min/median + single), full per-target table — because the old report only had Boltz-2's ipSAE, so `mean_ipSAE` was never searched.

**Why it mattered:**
- The screen half ("does it bind?") needed confirmation on an *independent* dataset + *independent* engine (BindCraft games AF2 ipTM by construction; ESMFold2 is independent).

**Outcome:**
- **Our ESMFold2 ipTM screens BindCraft experimental binders vs non-binders at AUC 0.91 pooled / 0.91 on PD1 (13b/40n)** — *stronger* than Adaptyv's 0.69. The screen half is robustly confirmed across datasets and engines.
- `combination_report_v2`: `mean ipSAE_min` macro AUC **0.709** ≈ `mean ipTM` **0.710** (interchangeable); best overall median(3×iptm) 0.737. Everything still plateaus ~0.70–0.74. On MUNI next to the original.
- Net stance: **SCREEN solved (cross-engine ipTM, ~0.69–0.91); affinity RANK unsolved in-silico everywhere** — needs experimental Kd + active-learning, or better/ensemble structures.

---

## 2026-06-24 — AF3 unified-memory OOM reboots the Spark; capped via `XLA_PYTHON_CLIENT_MEM_FRACTION`

**What changed:**
- A 3-engine de novo refold rebooted the DGX Spark mid-run. Forensics (previous-boot kernel log) showed a sustained `NVRM: Out of memory [NV_ERR_NO_MEMORY] _memdescAllocInternal` cascade (01:14–01:42 → reboot 01:46). **AF3 preallocates ~93.7 of 96 GB unified memory (~0.976)**, leaving ~2 GB for the OS/NVRM → whole-box reboot. (CLAUDE.md already notes AF3 wants >100 GB; the Spark's 96 GB is under-spec.)
- Fix in `Evaluator/scripts/refold_af3.py`: AF3 subprocess now runs with `XLA_PYTHON_CLIENT_PREALLOCATE=true` + `XLA_PYTHON_CLIENT_MEM_FRACTION=0.8` (override via `AF3_XLA_MEM_FRACTION`). `run_alphafold.py` does not set MEM_FRACTION itself, so the env var is honored. A too-big complex then fails as a clean per-design JAX OOM (recorded empty), not a box reboot. Keep PREALLOCATE=true (`false` fragments/hangs).
- Separately, **Boltz-2 IFNAR2** crashed non-fatally: transient MSA-server hiccup → empty dataloader → `IndexError` (Mosaic `load_features_and_structure_writer`); recoverable by rerun.

**Why it mattered:**
- The reboots were AF3 starving the box, not our complexes (all ≤349 tokens) — a deterministic guard was needed before any large AF3 run.

**Outcome:**
- AF3 runs to completion with the cap (exit 0, valid metrics, log confirms `mem fraction 0.8`); exact peak MiB to be confirmed on the first batch of a real run. De novo refold otherwise reached 6/7 targets fully 3-engine before being stopped to protect the box.
- Next: source the 19 missing Adaptyv target sequences for the full 23-target / ~5253-design refold (the user-selected scope).

---

## 2026-06-24 — SoluProt 1.0 dist + aarch64 USEARCH v12 vendored into the repo (durable screen)

**What changed:**
- Vendored the full SoluProt 1.0 distribution (scripts + GradientBoosting model pickles + USEARCH reference DBs) and the from-source aarch64 USEARCH v12 binary into `Evaluator/tools/soluprot/` — the installer's canonical `SOLUPROT_DIR` (commit `f0bc5d3`). Previously these lived only in `/tmp`, which gets wiped, losing the hard-to-rebuild USEARCH build and forcing a full re-download + recompile each time.
- `soluprot.py` + `feature_scripts/` are pre-patched for biopython ≥ 1.78 and the `usearch_global` command spelling (aarch64). `usearch` is a static ARM64 ELF built from `rcedgar/usearch12` (the bioconda `12.0_beta` crashes on aarch64). Both model pickles shipped: `grad_clf_v1_tc.pkl` (full, with TMHMM) and `grad_clf_v1_tc_notmhmm.pkl` (TMHMM-free, aarch64 default).

**Why it mattered:**
- Makes the SoluProt screen durable and self-contained in `git clone` — the installer's "already present" check short-circuits the expensive rebuild, and the aarch64 USEARCH build no longer evaporates on reboot.

**Outcome:**
- 53 MB vendored (44 MB is the two re-downloadable reference FASTAs). The screen now resolves its scripts-path + USEARCH + model variant with zero `/tmp` dependency.

---

## 2026-06-26 — Report: Boltz-2 fold-back prefilter for tools lacking a native metric (RFD3); native-section enhancements

**What changed:**
- New `binder-compare prefilter` (commit `902729f`) — ranks designs by a cheap single-engine Boltz-2 fold-back *interface* score (`boltz_pae_ipsae_min` default, or `boltz_pae_iptm`), recomputed from the Boltz-2 PAE files so the numbers match the evaluator's consensus inputs. This is the literature-standard RFdiffusion recipe (diffusion gives geometry, the fold-back gives the rank; Bennett 2023; the 2025 3,766-binder meta-analysis ranks ipSAE the best single in-silico predictor). Falls back to raw Boltz-2 columns when PAE files are absent. New `cli/prefilter.py`; `test_prefilter.py` (117 pass).
- Targets **RFD3** — the one tool with no native interface metric, previously selected by `mpnn_sequence_recovery` (a sequence proxy with no binding signal), which is why its refold pool was full of non-interfacing designs (ipSAE_min = 0). Output is sorted best-first with a `sequence` column → drops straight into `report --tool-csv rfd3=<sel>`.
- Report native-section polish (commits `c36a652`→`44c1f43`): honors `--top-per-tool` in the Top-Designs-per-Tool section; populates `eval_rank` from the full df; adds `consensus_ipsae_min_mean` (mean of per-engine ipSAE_min) surfaced in tables; friendly `METRIC_META` labels for native/consensus columns; main refold candidates Top-20 → Top-30; emits a combined `candidates.csv` (per-tool native + refold shortlist).

**Why it mattered:**
- RFD3 designs were being chosen by a metric blind to binding — the fold-back prefilter applies the field-standard recipe so the expensive AF3 pass is spent on designs that actually interface.
- The report now presents a single, friendly, deduplicated candidate list spanning native + cross-engine signals.

**Outcome:**
- `binder-compare prefilter` in production; 117 tests pass; native section + `candidates.csv`/`top30_candidates.csv` are the canonical shortlist surface.

---

## 2026-06-28 — SoluProt screen runs by default on BM5 (aarch64): env rename + dead-env cleanup

**What changed:**
- Cloned the validated `sklearn020-build` env → **`binder-eval-soluprot`** — the name `evaluate.sh` auto-detects and the configurator checks via `_env_exists`. So `bindmaster evaluate` / `evaluate.sh` now RUN the SoluProt screen by default on BM5 with NO extra flags (previously silently skipped: nothing on the box was named `binder-eval-soluprot`).
- **Deleted the broken `soluprot-py37` env** (had scikit-learn 0.21.3 → `'BinomialDeviance' has no attribute 'get_init_raw_predictions'` crash at `predict()` — a trap that loaded but never scored).
- Resolved the USEARCH version ambiguity: the deployed `~/soluprot-dist/usearch` banner = `usearch v12.0`; the vendored repo copy + dist copy + source build all share BuildID `920b9334` (identical aarch64 v12 source builds). Removed a stray x86 leftover (`usearch12-src/tmp/usearch_linux_x86_12.0-beta`).

**Why it mattered:**
- The default canonical pipeline (Boltz-2 + AF3 + ESMFold2 + SoluProt screen) was silently dropping the solubility screen on BM5 purely because of an env-name mismatch — a "wired but never fires" footgun.

**Outcome:**
- Verified end-to-end: the vendored `Evaluator/tools/soluprot/` is self-contained on aarch64 (patched `soluprot.py`, both pickles, 22 MB ref DB, bundled v12 USEARCH); the runner auto-resolves scripts-path + USEARCH + `--no_tmhmm`. SoluProt now screens by default on BM5.

---

## 2026-06-29 — SoluProt 2.0 web UI (standalone) + x86 validation: full TMHMM model reproduces the public server

**What changed:**
- Built **SoluProt 2.0 UI** — a standalone local web app that reproduces the public SoluProt server (`loschmidt.chemi.muni.cz/soluprot/`): paste FASTA → the host computes the *E. coli* solubility score via `soluprot.py` → a color-graded results table + score-distribution histogram, with per-job persistence retrievable by Job ID. FastAPI (py3.10) serving env shells into the py3.7 `binder-eval-soluprot` model env via `$SOLUPROT_PYTHON`; vanilla-JS SPA (no external libs); keeps the original branding/affiliation banner. **This project lives OUTSIDE this repo** (`~/dev/SoluProt-2.0-UI/`, deliberately not under BinderScout) — it was the validation vehicle, not a BindMaster component. Diary records the *finding*, not the code.
- Used it to settle the open question: **does the aarch64/BM5 SoluProt screen differ from the public server because of a wrapper/USEARCH/sklearn bug, or solely the TMHMM-free model variant?** Staged the bundle + a `compare.py` validator + a Claude Code kickoff doc to MUNI; ran it on BM1 (x86) with the FULL native stack (TMHMM binary → 96-feature model, scikit-learn 0.20.1 wheel, x86 USEARCH).
- Found + fixed a TMHMM x86 setup gotcha (folded into the standalone's `setup_tmhmm.sh`, also on MUNI): TMHMM 2.0's `tmhmm` wrapper AND `tmhmmformat.pl` BOTH ship `#!/usr/local/bin/perl`; the wrapper execs the formatter via its shebang, so rewriting only `tmhmm`'s shebang makes the formatter silently fail → empty `-short` output, exit 0 → SoluProt backfills every TMHMM feature with the training mean → WRONG scores for membrane sequences while passing an exit-code check. Fix: rewrite the perl shebang on BOTH files; smoke test must assert `PredHel=` on a membrane control, not just exit 0.

**Why it mattered:**
- Pins down exactly what the aarch64 screen's ~0.03–0.12 offset from the public server is — and whether to trust the BM5 numbers.

**Outcome:**
- **x86 + full TMHMM model + scikit-learn 0.20.1 MATCHES the public SoluProt server** (max|Δ| < 0.01). This confirms the aarch64/BM5 offset (~0.03–0.12, Pearson r ≈ 0.98, identical ranking) is **solely the TMHMM-free model variant** — NOT a wrapper / USEARCH-v12 / sklearn-0.20.4 bug. So: need exact public-server parity → use x86 (full TMHMM); aarch64 gives the screen-equivalent TMHMM-free variant (AUC 0.62, immaterial for a screen). A working TMHMM x86 is now stored on MUNI, reusable for future x86 deploys (or to drive the full model on BM5 via qemu per `setup_tmhmm.sh`).


---

## 2026-06-30 — Evaluator report Phases 1–4: methodology sync + fairness banner + epitope/diversity + UX polish

**What changed:**
- Implemented the 13 items of `docs/PLAN_evaluator_improvements_2026-06-30.md` across 4 commits (Phases 1–4), distilled from 3 external AI reviews of the 2026-06-24 reports (2VDY_CBG + CALCA).
- **Phase 1 — methodology + presentation sync.** Methodology rewrite cites the exact Adaptyv 0.710 mean vs 0.689 max AUC + ProteinBase 0.755 + precision@top-10% 0.92 vs 0.79 numbers, restates "internal 4-target benchmark" (not "benchmark-validated"), and adds a serpin/flexible-target transferability caveat. New `consensus_iptm_spread` (max − min across engines) column drives a ⚠ Top-30 warning when `agreement_count < 2` or spread > 0.3. Top-30 legend + screening summary are now rank-method-aware (iPTM tier legend appears alongside the ipSAE tier legend when ranking by two-stage). QC thresholds from `cli/qc_annotate.py` rendered in a collapsible methodology block.
- **Phase 2 — fairness + transparency.** New `comparison/tool_classification.py` is the single source of truth for per-tool framing (modality, native-metric interpretation, convergence rule). `extractors/base.py` grows `extractor_metadata()`; `protein_hunter.py` overrides it to self-declare `pool_pre_filtered=True` when reading `summary_high_iptm.csv`. Report's per-tool banner shows count + modality + source CSV + status badge (PRE-FILTERED POOL / VHH-CDR-REDESIGN / FAILED RUN — fires for BoltzGen family with mean consensus_ipsae_min_mean < 0.20). New `--tool-meta` CLI for per-run overrides. **Provenance footer** auto-detects git_sha + evaluator_version + sys.argv + UTC timestamp; `--engine-versions FILE` (JSON/YAML) for checkpoints/seeds. **CI fix**: `pytest` job needed `matplotlib` (Phase 1 failed CI on the pytest-only matrix; visualisation imports drag matplotlib in transitively).
- **Phase 3 — high-value science.** New `comparison/epitope.py` (pure-Python PDB+CIF Cα extractor, no PyRosetta/Biopython) + `binder-compare epitope` CLI computes `epitope_match_fraction = overlap(refold interface residues, intended hotspots)`. New `comparison/diversity.py` + `binder-compare diversity` CLI does CD-HIT-style greedy sequence clustering by k-mer Jaccard (default 0.70 / k=4), no MMseqs2/Foldseek required. Both surface as advisory report columns; the Top-30 grows a "Top per family" recommendations block underneath. Advisory only — never reorders ranking.
- **Phase 4 — UX polish.** `wetlab_recommended` (SoluProt pass + agreement_count ≥ 2 + min binder pLDDT ≥ 0.50 + no FAILED RUN) — strike-through render in Top-30. Two new plots: `plot_metric_correlation_heatmap` (Spearman ρ over the 10 default ranking/confidence/cross-validation metrics) + `plot_pareto_front` (confidence × solubility × interface-energy 2-D scatter with Pareto-optimal points highlighted via O(n²) dominance). Interface energy decomposition columns (`interface_interface_hbonds`, `interface_hydrophobicity`) surfaced in the advisory legend (Item 13). `--lightweight` flag wired into `generate_report` skips the inline NGL viewer (≈ 5 MB → 150 KB on big pools); points reader at on-disk `top20_structures/` + `view_top20.pml` instead.
- **Rejected reviewer suggestions held**: ipSAE 8 Å cutoff (kept 10 Å DunbrackLab/Overath default), drop mean-iPTM screening (kept mean as Adaptyv-validated default), ESMFold2 normalization/z-scoring/rank aggregation (kept raw mean). All advisories never reorder ranking — `active_rank` stays the rank.
- **Tests**: 191 pass locally (was 117 → +74 new, across `test_scoring.py`, `test_report_advisory.py`, new `test_tool_classification.py`, `test_epitope.py`, `test_diversity.py`, `test_phase4.py`). CI green on Phases 2/3/4 commits.

**Why it mattered:**
- The reviews flagged the report's surface (methodology label, "Primary metric: ipSAE_min" header, missing per-tool transparency, missing diversity-aware shortlisting, missing provenance) drifted significantly from what the underlying ranking actually does. Without the sync the report contradicted its own methodology — every other downstream improvement got partly hidden behind stale labels.
- Serpins (2VDY/CBG), small peptide receptors (CALCA), and any flexible/membrane target have multiple distinct functional pockets; iPTM/ipSAE alone don't distinguish where on the target the binder binds. Epitope-match fraction now closes that gap as a per-design column + Top-30 warning.
- The reviewers flagged motif-redundancy (Protein-Hunter "ASATAILLE" / Mosaic helical-repeat dominance) as a wet-lab portfolio risk — selecting 5 variants of one motif wastes a wet-lab round. Diversity clustering surfaces this and the "Top per family" block recommends 1-2 representatives per family.

**Outcome:**
- End-to-end smoke verified without Claude (`PYTHONPATH=Evaluator python -m binder_comparison.main report ...` on a synthetic 12-design Boltz-2 CSV) — all Phase 1-4 features present in the rendered HTML. CI passes on Phases 2/3/4 commits.
- 4 new CLI subcommands: `binder-compare epitope`, `binder-compare diversity`, plus `--lightweight` / `--engine-versions` / `--tool-meta` / `--epitope-results` / `--diversity-results` flags on `report`.


---

## 2026-07-01 — Phase 1–4 reapplied on BM5 (GPU-free), 6 review fixes, + `epitope-map` binding map

**What changed:**
- **Reapplied the Phases 1–4 work on the real data.** The 2026-06-30 BM1 commits were rolled back from master because the v2 report was rebuilt on top of v1's (2026-06-24) *merged* `metrics.csv`, so data-layer fixes between 06-24 and 06-30 weren't picked up. On BM5 the archived branch (`fc40196..22de7bf` + tier-consolidation `e19386d`) fast-forwards cleanly onto our report HEAD `d72658e` — the rollback was a **data** problem, not a code conflict. Regenerated **CALCA (350) + 2VDY (400) Full Phase 1–4** through the proper extract→merge→report path from the **cached per-engine refold CSVs** (`runs/CALCA_eval_top50/`, `eval_workdir/2VDY/refold/`) — **zero GPU** (the sequences didn't change; only merge/score/report code did). Both bundles pushed + md5-verified to muni RESULTS.
- **6 review findings fixed** (user review of the regenerated reports; commit `09934e8` + follow-ups):
  1. **Benchmark provenance was overstated** — methodology + provenance table claimed "Adaptyv: 8 hand-curated targets, n > 3,700", contradicting the repo's own diary. Corrected to **Adaptyv 4-target / 662-design** (mean-default 0.710 vs 0.689) + **ProteinBase 4-target / 175-design** (max-screen ~0.755); both share Nipah/EGFR/IL7R/PD-L1. The "3,700 / 8 targets" was the *planned* 23-target scope conflated in, never run.
  2. **Two tier systems, one tier-count table** — collapsed the screening-summary legend to a single ipSAE_min tier band (matches the one count table); iPTM ranking named in prose (continuous, not tier-banded).
  3. **agreement_count read as 0–2** with 3 engines — reworded legends to "X of 3 engines".
  4. **Wet-lab strike-through too definitive** — replaced the line-through with an advisory wavy-underline **mark**; then, because "hover isn't immediate", promoted `wetlab_reason` into an always-visible **"Why flagged (wet-lab)"** Top-30 column (blank = ready, else `SoluProt FAIL` / `agreement 1 < 2` / `min pLDDT 0.48 < 0.5`). This is a *separate axis* from the ⚠ engine-disagreement flag — a top design can be marked (predicted-insoluble) while all 3 engines agree.
  5. **CALCA native ranks missing** for mosaic / proteina_complexa / boltzgen (no native `--tool-csv`) — built standardized `*_native.csv` from the per-tool `rank=` pool-selection token in the source-tagged FASTA. All 7 tools now show a native rank.
  6. **Per-tool viewer length bug** — `str(length).rstrip(".0")` stripped trailing zeros (140 → "14", 60 → "6"); format as `int` instead.
- **New viz: `binder-compare epitope-map`** (`comparison/epitope_map.py` + `cli/epitope_map.py`). Renders a standalone `binding_map.html`: the target cartoon + surface coloured by **per-residue contact frequency** (B-factor recolor from the `epitope` interface residues), plus **footprint-clustered binding-mode** toggles (designs grouped by *which* residues they contact — the structural analogue of the sequence `family_id`) and an optional intended-pocket outline. Wired a `--binding-map HREF` callout link into the main `report`. 2VDY: 8 modes converging on the steroid-pocket shutter (368 **74%**, 267/264 70%); CALCA: 5 modes on helix residues **5–16 (95–99%)**.
- **Tests**: 191 → **198** (epitope-map 6 + binding-map-link 1; mark/tier/length tests updated). ruff + format clean.

**Why it mattered:**
- The rollback reason (stale merged `metrics.csv`) is fixed by feeding the report the **per-engine refold CSVs** — reproducible from cache at no GPU cost, so the report always reflects current data-layer code.
- The benchmark overstatement undercut the methodology's credibility; the real numbers (662 + 175) are what the mean-default and max-screen decisions actually rest on.
- The wet-lab mark was being conflated with engine uncertainty; an inline reason column makes the two independent axes legible at a glance.
- Epitope-match was a per-design *number*; the binding map aggregates those footprints **onto the structure**, answering "where do the families bind" visually — the natural next question after the epitope column.

**Outcome:**
- Both Full Phase 1–4 reports live on muni (`.../2VDY_CBG/RESULTS/2VDY_CBG_fullphase_2026-06-30/`, `.../P01258_CALCA/RESULTS/CALCA_top50_fullphase_2026-06-30/`), each with the corrected report, the standalone `binding_map.html`, and the epitope/diversity/soluprot(/qc) CSVs; file-count + report-md5 verified on every push.
- Working branch `two-stage-screen-metric-and-partn-affinity` carries the reapply + 6 fixes + `epitope-map` + link (commits `e19386d → 09934e8 → 75605ea → 8111467 → b03073c → 2f72252`). Local only — not pushed to the git remote.
- Binding-map link verified to resolve to the co-located map file (well-formed anchor → existing 262 KB `2VDY_CBG_binding_map.html` in the same bundle dir); a live browser render is still pending (Chrome extension disconnected, no headless Chrome on BM5).


---

## 2026-07-07 → 07-15 — ApoE4 (6NCO) campaign: full refold, RFD3/PC redo (hotspots), RFD3 alanine catch, upstream-PC Blackwell port

Target: ApoE4 N-terminal 4-helix bundle (6NCO chain A, 185-aa construct = His-tag + mature 24–164). All work on BM5/Spark (GB10, aarch64, sm_121). Campaign source of truth: muni `6NCO_ApoE/RESULTS/BinderScout/PROGRESS_ApoE.md`.

**What changed (chronological):**

1. **Cross-engine refold of the full 1,520-design pool** (7 tools) → two-stage report at `~/eval_workdir/ApoE4/probes… /eval/report/`. Result: **80 High / 177 Medium tier; 13 designs pass all 3 engines (agreement=3), 99 pass ≥2.** Top-60 tool mix PXDesign 22 / Mosaic 17 / BindCraft 11 / PH 9 / BoltzGen 1 — **RFD3 (600) + PC (501) contributed ZERO to the top-60** despite being 72 % of the pool.
2. **Boltz-2 refold "fetch-once" MSA fix** (`Evaluator/scripts/refold_boltz2.py`, working tree, +30/−9). Root cause: `Mosaic/losses/boltz2.py:115` allocates a fresh `TemporaryDirectory` per `target_only_features()`, so `process_inputs→compute_msa→run_mmseqs2` re-queried ColabFold for the (constant) target on **every binder** (~1 fetch/binder; the `_processing_dir` "cache" was a dead variable). Crashed the first run at design 625 on a transient ColabFold timeout. Fix: memoize `boltz.main.run_mmseqs2` by query sequence → **1 fetch/process** (validated: 895-design completion made exactly 1 server call, zero crashes). Score-equivalent (deterministic mmseqs).
3. **Binding-mode + dedup analyses** (`binder-compare epitope`/`epitope-map`/`diversity` on the 99 cross-validators, saved to muni `RESULTS/BinderScout/ANALYSIS_redo/`). Dedup: 99 → **97 unique families** (shortlist already non-redundant). Binding modes: cross-validators cluster on the **Trp34-pocket region (~52–59, incl. W54/D55)** + a ~115–140 patch; ~51/99 touch the Trp pocket.
4. **Two research dossiers** (`ANALYSIS_redo/`): **ApoE4 hotspots** → Set 1 = **Trp34 druggable pocket, construct A54/A55/A173** (validated 3 ways: 6NCO crystal fragment binds it, literature #1, our winners land there); Set 2 = LDLR cluster A162–167. **PC settings** → its 0/500 was single-cofolder reward-hacking; fix = hotspots + composite reward + best-of-N (not deep MCTS) + independent gate (our refold is that gate).
5. **RFD3 installed on Spark/aarch64** (was never actually installed here — only ran on Clara x86). `install_aarch.sh` has NO rfd3 fn → `--tool rfd3` fell to x86 `install.sh` (cu121, no aarch64 torch wheel). Fixed manually: `torch` from **cu130** index (2.12.1+cu130 works on GB10) + `rc-foundry[rfd3,mpnn]==0.1.9` + `foundry install rfd3/proteinmpnn`. RFD3 hotspot spec key = **`select_hotspots: "A54,A55,A173"` + `infer_ori_strategy: hotspots`** (NOT `atom_level_hotspots` — rejected by `DesignInputSpecification`).
6. **RFD3 v3 Trp-pocket probe** (300 backbones, len 60–100). Smoke docked at 6.1 Å. **Then caught the real RFD3 failure mode: alanine collapse** — all RFD3 runs are ~50 % Ala (v1 0.36 / v2 0.47 / v3 0.51, all at ProteinMPNN default `T=0.1`) vs cross-validating winners **0.21**. A 50 %-Ala binder can't form a specific interface → **very likely why RFD3 got 0/top-60**, independent of hotspots. Fix: **`mpnn --temperature 0.25 --bias '{"ALA": -1.5}'`** → Ala **0.51 → 0.09** (near-natural, diverse). Backbones fine → re-ran MPNN only.
7. **PC v2 port probe** (300 designs, Mosaic jproteina port + hotspots + beam search). Compositionally healthy (Ala 0.15).
8. **Probe refold** (Boltz-2 + AF3 + ESMFold2 on 593 unique probe seqs). Caught + fixed a **collision bug**: probe Boltz-2 ran without `--output-dir` → defaulted to `./refold_boltz2` (main-pool dir) and index-based `--resume` skipped all 593, copying the wrong 1520-row CSV. Corrected with a dedicated dir. **Result: RFD3 v3 improved ~2.5× on ESMFold2 (>0.7 rate 4 %→10 %); PC port stayed flat (3 %→3 %)** — hotspots alone didn't help PC, exactly as the dossier predicted (port reward-hacks its Protenix score).
9. **Upstream Proteina-Complexa (`complexa`) ported to Blackwell** — the real composite-reward designer (the port test was inconclusive because the port reward-hacks). `install_aarch.sh` has no PC fn either; `build_uv_env.sh` is x86/cu126-pinned. Built the venv MANUALLY, cleared 5 blockers: **torch cu126→cu130** (2.13.0+cu130 on GB10); **torch_scatter → native shim** (PC only uses `scatter_mean`; drop a `torch_scatter.py` using `scatter_add_`/`scatter_reduce_`); **AF2 reward JAX → CPU** (`jax[cpu]==0.4.29` + colabdesign; JAX-CUDA dead on sm_121); **tmol** installs; foldseek/mmseqs+rf3 deferred → use our refold as gate. Also `atomworks`/graphein/biotite 1.6.0. **The full `complexa` CLI imports + runs, and the flow-matching model GENERATES binders on the GB10 (core smoke: 2 PDBs / 59 s).** Patched `rewards/alphafold2_reward.py:125` (`jax.devices("gpu")` → CPU fallback) so the AF2 reward instantiates; reward-guided best-of-N runs end-to-end.

**Why it mattered:**
- The refold is the funnel: 72 % of the pool (RFD3+PC) produced nothing in the top tier — but two *separate* fixable causes, not "the tools are bad": RFD3's alanine collapse (a ProteinMPNN settings bug) and PC's reward-hacking (needs the upstream composite reward, not the port).
- The alanine catch is the highest-value finding — it likely under-used RFD3 across the whole program, and it's a one-line MPNN fix.
- The Blackwell PC port unblocks a *proper* PC test on the hardware we have (no Clara dependency).

**Outcome / status:**
- RFD3 v3 (hotspots + Ala-fix) is the clear win — improved on the independent engine; **worth scaling.**
- Upstream PC generates on Blackwell. **AF2-CPU reward is too slow for scale: measured ~6 min/structure (23:47 for 4 structures) → a 300-design best-of-N ≈ 10 days.** → pivoting the reward to **RF3 (RoseTTAFold3, torch-GPU, independent of our eval engines)** + our refold as the gate — in progress.

**Propositions / TODOs (for the codebase + campaign):**
- **Configurator:** bake `--temperature 0.25 --bias '{"ALA": -1.5}'` into `write_run_rfd3` + `bindmaster_examples/run_rfd3.sh.template` (currently emit `T=0.1`, no bias). Re-check 2VDY/CBG RFD3 outputs for the same collapse.
- **Installer:** add aarch64 install paths to `install_aarch.sh` for **RFD3** (cu130 torch) and **Proteina-Complexa** (the 5-blocker Blackwell recipe) — both currently fall to the x86 `install.sh` and die at cu121/cu126.
- **Evaluator:** `refold-boltz2` defaults `--output-dir` to CWD-relative `./refold_boltz2`; combined with index-based `--resume` this silently emits a prior pool's CSV. Give it a per-run default or make `--resume` sequence-keyed (footgun in `evaluate.sh` for multi-pool runs).
- **PC on Blackwell:** finish the RF3-GPU reward route (install `rc-foundry[all]` + RF3 ckpt into the PC venv, swap reward to `rf3_reward`), then run the proper PC v3 (hotspots + best-of-N + RF3 reward) → refold → head-to-head vs original-PC and port-PC.
- **Scale decision (pending PC v3):** RFD3 v3 config validated → scale; PC verdict awaits the upstream-RF3 run.
- Memories written this session: `ops_spark_gpu_driver_kernel_upgrade`, `reference_rfd3_mpnn_alanine_collapse`, `reference_pc_upstream_blackwell_port`.

## 2026-07-16 → 07-23 — ApoE4 **isoform-selectivity** campaign: 44 AF3-selective from 3 tools + first multi-state Mosaic; offline-MSA `msa_path` fix lands; two-stage screen reverted to max; T–X roadmap

Target: ApoE4 isoform (P02649, 6NCO chain A, N-terminal 4-helix bundle 24–164). Goal is **selectivity, not affinity**: bind ApoE4 (**Arg112**), reject ApoE3 (Cys112) and ApoE2 (Cys112+Cys158) — residue 112 is **buried**, so this needs epitope-forced design + an E4−E3/E2 counter-screen. Distinct from the prior generic-affinity 6NCO round (epitopes there were isoform-invariant → not reusable). Source of truth: `~/eval_workdir/ApoE4-isoform/PROGRESS.md`.

**What changed (chronological):**

1. **Definitive per-tool AF3-selective board: 44 selective from 3 tools.** Funnel per tool = Boltz-2+6NCO-template gate (GOOD ≥ 0.8) → E3/E2 template counter-screen → **AF3 confirm** (selective = af3_E4≥0.5 ∧ gap_E3≥0.15 ∧ gap_E2≥0.10). Result: **RFD3 30** (3 from the 1k run + 27 from 5k) · **PC 11** · **PH 3**. **BindCraft / PXDesign / Mosaic-hallucination / BoltzGen all 0** — potent on E4 but bind E3/E2 equally (they optimize affinity, not the buried-112 discriminator; BoltzGen's 29 Boltz-2-selectives were *gamed* → 0/29 on AF3). Top RFD3-5k: **E4=0.93 / E3=0.27 / E2=0.32** (gaps +0.66/+0.61), stronger than the 1k lead (0.73).
2. **MSA re-gate (user's "are we using MSA for all targets?" caveat).** Re-ran the RFD3-5k gate *with* the target MSA injected. The MSA gate found **1034 designs ≥0.7 vs 288 no-MSA (3.6×)**, but AF3 conversion was low (**10 selective / 245 Boltz-2-selective ≈ 4%** vs 22% on the no-MSA funnel) — and **all 10 were NEW (0 overlap** with the 17 no-MSA selectives). Net **+10 RFD3** (17→27 on the 5k run). Lesson: the MSA and no-MSA gates are **complementary, not redundant** — running both is worth it.
3. **First-of-its-kind multi-state Mosaic negative-design run (BM2).** Every tool above *hallucinates for affinity* then gets counter-screened; Mosaic's `LinearCombination` loss algebra lets us **design FOR selectivity directly**: `loss = NoCys(pos_E4) − w·NoCys(off_E3) − w·NoCys(off_E2)`. Gotcha solved: `serial_evaluation` needs a flat top-level `LinearCombination`, so each state is wrapped in `NoCys` *before* combining (not after). Built + launched on BM2 — the only tool in the campaign optimizing the E4−E3/E2 gap as its objective. (Still cooking at end of session.)
4. **7-tool scale-up launched** (user: "truly all 7 tools", "prefer our PCs over Clara"): RFD3-5k-v2 + PC-v3 (50 reps) + BoltzGen-v2 (5000) + BindCraft ×4 on Clara; PH 2000 (BM1), PXDesign 2000 (BM4), multi-state Mosaic (BM2). Each feeds the same Boltz-2→counter-screen→AF3 funnel on completion.
5. **Offline-MSA `msa_path` fix landed on `master`** (PR #18 = `b14e3ec`; commits `4343924`/`3274bc2`). The proper fix for Clara compute nodes that can't reach `api.colabfold.com`: `TargetChain.msa_path` now emits a `msa: <a3m>` line into the Boltz input YAML (`Mosaic .../boltz2.py:chain_yaml`), so all three refold engines read the **on-disk target-MSA cache** instead of re-querying ColabFold. Supersedes the earlier `use_msa=False`-template workaround (`0615a6d`) that dropped the target MSA entirely.
6. **Two-stage screen default reverted `mean` → `max`** (branch `fix/two-stage-screen-max-default`, pushed). A prior change had flipped Stage-1 to a **mean**-screen, which is too strict — it drops a candidate one engine strongly likes when another engine's per-target blind spot lowers its mean. Restored the intended **max-screen (lenient recall) → mean-rank (strict consensus)**; `--screen-metric mean` still available. `rank_by_two_stage(screen_metric="max")` + `report --screen-metric max` defaults; 2 tests + CLAUDE.md + CHANGELOG updated; pytest 201 pass. (Reaffirms the 2026-06-07 `max_screen → mean_iptm` design.)
7. **CI green-up** (branch `ci/fix-ruff-format-and-beta-test`, pushed): ruff-formatted 7 files left unformatted by recent merges, and fixed a stale `test_beta_intercalation` assertion (single-sided intercalation is now opt-in via `min_xbridge`, so `is_intercalating(3,0)` is `False`). Repo housekeeping: 3 merged branches deleted; `fix/soluprot-py37-cli-env` found superseded by #19 (doc-only after rebase) and closed.
8. **T–X roadmap doc** (`docs/PLAN_ranking_and_engines_roadmap.md`, branch `docs/ranking-engines-roadmap`, pushed). Evaluated the six proposed parts — Promera+iCS (T), ProtDBench calibration (U), Chai-1 refold (O), OpenGerminal antibody designer (V), RFD2-MI small-molecule designer (W), report gap audit (X) — as an **investigate-first** roadmap with hard validation gates. Ordered **X → T → U → O → V → W**: the ApoE4 campaign shows ranking quality (not design volume) is the bottleneck, so evaluation-layer work is front-loaded and new designers deferred.

**Why it mattered:**
- **Selectivity is a real, achievable target and it discriminates tools.** Only epitope-constrained designers (RFD3, PH) and the composite-reward PC read the buried Arg112; pure affinity-optimizers (PXDesign, Mosaic-hallucination, BindCraft, BoltzGen) can't, no matter how potent. 44 selective from 3 independent methods breaks the earlier RFD3 monoculture.
- **The MSA re-gate caveat paid off** (+10 all-new selectives from a method we'd have skipped as redundant).
- The `msa_path` fix is what makes the whole Clara funnel run at all — without it, the cross-engine refold crashes offline.

**Outcome / status:**
- **44 AF3-selective candidates banked**; multi-state Mosaic (the design-for-selectivity arm) + the 7-tool 2000-scale pools still running → each will re-enter the funnel.
- Three evaluator/CI branches pushed to origin: `ci/fix-ruff-format-and-beta-test`, `fix/two-stage-screen-max-default` (stacked on it), `docs/ranking-engines-roadmap` (off master) — PRs pending review/merge.

**Propositions / TODOs:**
- **Start the T–X roadmap with Part X** (report gap audit) — investigate which of `affinity/diversity/monomer/wetlab/epitope/…` analyses actually surface in the HTML report; report + fix plan, no code until approved.
- Merge order for the pushed branches: CI-fix → screen-metric (auto-retargets to master) → docs (independent).
- When the multi-state Mosaic + scale-up pools land, re-run the funnel and update the 44 count; verify whether the design-for-selectivity arm beats the counter-screen arm.

---

## 2026-07-23 → 07-25 — Part X report-gap audit shipped; **Part T (Promera) rejected as a negative result**; per-engine advantage map + a length crossover

Two roadmap parts closed. Part X turned the report honest; Part T spent H200 hours to prove a
candidate engine *isn't* worth adopting — and produced a more valuable side finding than the
engine itself would have been.

**What changed:**

1. **Part X — report gap audit + surgical fix (commit `be6134e`).** Audited all 16 modules in
   `Evaluator/binder_comparison/comparison/` through every layer (module → CLI → injected column →
   rendered HTML), each verdict independently re-verified. Finding: both default orchestrators
   (`cli/run.py`, `evaluate.sh`) run only *extract → refold → report*; every advisory analysis
   (`diversity`, `epitope`, `affinity`, `monomer`, `beta-check`, `qc-annotate`) surfaced **only** if
   its sidecar CSV was hand-threaded via a flag. `monomer` and `affinity` had no wire into the
   report at all; `beta_intercalates` was injected but in no display set. Fixes: diversity + epitope
   now run **inline by default** (`--epitope-residues`, `--no-diversity`, `--diversity-threshold`),
   new `--affinity-results` / `--monomer-results` attach paths, `esmfold2_chain_iptm_interface` (the
   autosize gate) surfaced, and a real radar bug fixed — AF3/Protenix referenced non-existent
   `*_pae_bt`/`*_pae_tb` (actual columns are `*_pae_bt_mean`), silently dropping two axes; ESMFold2
   (the default engine) had **no radar panel at all**. +11 tests, 196 pass, ruff + shellcheck clean.
2. **Part T — Promera benchmarked end-to-end and rejected.** T1 desk study (MIT licence, 1.89 GB
   ungated weights, Boltz-class GPU) → T2 folds: nipah pilot 87/90 on Spark, **Adaptyv labelled
   2515/2517 on a Clara H200 6-way sbatch array** (~1 h per 420-design chunk) → T3 scoring. Full
   write-up: `docs/INVESTIGATION_partT_promera.md`; data + scripts in `runs/adaptyv_promera_bench/`.
3. **Promera stood up on both platforms.** Vanilla `pip install` on Clara x86/Hopper. On Spark
   aarch64/GB10 (sm_121) it needed **three stacked fixes**, encapsulated in
   `Evaluator/scripts/promera_env.sh`: torch reinstalled from the **cu130** index (the pinned 2.9.0
   installs CPU-only; cu128 dies with `nvrtc: invalid --gpu-architecture` since CUDA-12.8 NVRTC
   doesn't know sm_121) · `LD_LIBRARY_PATH` exposing the cu12 NVIDIA libs so cuequivariance's
   kernels coexist with torch's cu13 runtime (Promera hard-calls cueq triangle-multiply, no
   pure-torch fallback) · `TRITON_PTXAS_PATH` → the system CUDA-13 `ptxas` (Triton bundles a
   cu12.8 one capped at sm_120).
4. **Found: Boltz-2 refolding was silently broken on Spark.** The master pull brought the
   offline-MSA feature into `refold_boltz2.py` (passes `TargetChain(msa_path=…)`), but its companion
   `install/patches/mosaic-offline-msa.patch` had **never been applied to Spark's Mosaic install** →
   every Boltz-2 refold died with `TypeError: unexpected keyword argument 'msa_path'`. Patch applied.

**Why it mattered:**

- Part X: wet-lab picks are made from `report.html`. Signal computed but never rendered is signal
  that doesn't exist. Selectivity (ApoE4) and dedup now surface by default instead of on request.
- Part T: the roadmap's premise was that Promera's **iCS** might be the affinity/selectivity ranker
  `ipsae_min` isn't. Testing it properly — rather than adopting it on the strength of a published
  enrichment number — is the whole point of an investigate-first roadmap with a hard gate.

**Outcome:**

- **Promera loses on every target with real binder counts** (same designs, 1963 with all 4 engines):
  egfr 0.52 vs incumbent 0.76 · il7r 0.50 vs 0.68 · pd-l1 0.61 vs 0.78. **Target wins: ESMFold2 ×2,
  Boltz-2 ×1, AF3 ×1, Promera ×0.** nipah pilot agreed (Promera ipSAE 0.641 vs Boltz-2 ipSAE_min 0.686).
- **The decisive test — Promera is not distinguishable from a random voter.** Binder-catch rate in
  the top-25% is **0.293 vs 0.25 chance** (incumbents 0.586–0.671). Adding it as a 4th consensus
  voter gains +4 binders of union recall; a **random** 4th voter gains **+9.2** on average and
  matches-or-beats Promera in **100 % of 200 simulations**. The naive "it catches 4 binders the
  others miss" complementarity argument fails its null test. → **Not wired into `evaluate.sh`.**
- **A metric that looked like a win and wasn't:** pooled `promera_plddt` scores 0.826 — a
  Simpson's-paradox artifact of pooling targets with wildly different binder rates (nipah 1/927 vs
  egfr 130/826); within-target it collapses to ~0.60. Second such trap this month — always run the
  within-target check before believing a pooled AUC.
- **Affinity ranking unchanged and unsolved** — Spearman vs −log₁₀Kd among binders ≈ 0 or negative
  for every metric including all of Promera's. Consistent with Part N / SKEMPI / OpenBind / Adaptyv.
- **The real payoff — a per-engine advantage map.** No engine dominates (ProtDBench's
  "verifier-dependent bias" reproduced on our own stack); dropping any one loses uniquely-caught
  binders (AF3 −7, Boltz-2 −4, ESMFold2 −3). And **Boltz-2 and AF3 are near-perfectly
  anti-correlated by binder length**: short (10–82 aa) Boltz-2 **0.80** / AF3 **0.44**; long
  (128–259 aa) Boltz-2 **0.51** / AF3 **0.78**. Within egfr alone (826 designs, widest length range)
  it is starker — short 0.85 vs **0.33**, long 0.63 vs 0.67. AF3 is *anti-predictive* on short
  binders exactly where Boltz-2 is strongest, and our uniform consensus averages the two together.
- **2 designs are unfoldable** (`scarlet-raven-snow`, `radiant-shark-iron`, fgf-r1): a `:` in the
  sequence raises `KeyError: ':'` inside tinyprot's DataLoader and **kills the whole worker**,
  silently truncating its chunk (cost 222 designs on the first pass; recovered by a targeted refold).
  Validate sequences for non-standard characters before any batch fold.

**Propositions / TODOs:**

- ~~In flight: independent validation of the length crossover~~ → **DONE, and REFUTED** — see the
  addendum below. Length-conditioned weighting is **not** implemented.
- Keep the `binder-eval-promera` env + weights on both machines (cheap); Promera's MIT **nanobody
  designer** may still be worth evaluating for **Part V** (would remove the aarch64 PyRosetta blocker).
- Part U (ProtDBench calibration harness) remains the way to make future metric decisions provable;
  its Cao ground truth is binary binder/non-binder, so it will settle screens, not affinity.

---

## 2026-07-25 (addendum) — Length-crossover **REFUTED** on independent data; uniform consensus stands

Follow-up to the Part T entry above. The per-engine advantage map had suggested a *length-dependent*
Boltz-2/AF3 crossover — on Adaptyv/egfr, AF3 was **anti-predictive on short binders (0.33)** exactly
where Boltz-2 peaked (0.85), implying our uniform consensus was averaging a strong signal with a
harmful one. That would have been a free accuracy win: length-conditioned engine weighting, no new
engine, no extra GPU. It was the most actionable thing to come out of the Promera benchmark, so it
was validated before implementing.

**What changed:**
- Refolded the **BindCraft Nature-2025** de-novo set through all three engines
  (`runs/denovo_lengthtest/`): 110 designs / 7 targets / **45 binders**, independent of Adaptyv,
  balanced **15/15/15** across length terciles, 69–178 aa (straddles the ~100 aa crossover).
  All three engines scored **the same 110 designs**.
- Found and fixed en route: Boltz-2 refolding was **silently broken on Spark** — master's
  `refold_boltz2.py` passes `TargetChain(msa_path=…)` but `install/patches/mosaic-offline-msa.patch`
  had never been applied to Spark's Mosaic. Also fixed the analysis join: refold CSVs key on
  `run_id`/`idx` + `sequence`, **not** the FASTA design name, so the join must be on sequence.

**Outcome — the crossover does not replicate:**

| tercile | binders | Boltz-2 | AF3 | ESMFold2 |
|---|---|---|---|---|
| short (69–92 aa) | 15 | 0.58 | **0.74** | 0.73 |
| mid (93–111 aa) | 15 | 0.67 | 0.71 | 0.74 |
| long (113–178 aa) | 15 | 0.42 | 0.50 | 0.50 |

- Discovery predicted short → Boltz-2 **0.85** ≫ AF3 **0.33**; independent set gives
  short → Boltz-2 **0.58 < AF3 0.74** — **opposite direction**.
- Within-target on PD1 (53 designs / 13 binders, the only powered independent target):
  short Boltz-2 0.82 vs **AF3 0.83**; long 0.79 vs 0.73. **AF3 is healthy on short binders.**
  Its egfr 0.33 was **target-specific**, not an engine property. Opposite-signed point estimates =
  evidence against, not an underpowered null.
- **→ Length-conditioned weighting NOT implemented. Uniform consensus stands.**

**What does replicate:**
- **All engines degrade on long binders** (0.58–0.74 short → 0.42–0.50 long) — a *shared*, not
  differential, effect. Long binders are harder for everyone; no per-engine action implied.
- **No engine dominates** (PD1 ESMFold2 0.88 · IFNAR2 Boltz-2 0.72 · DerF7 AF3 0.79 · PD-L1
  ESMFold2 0.64) — the cross-engine consensus design reconfirmed on a second independent dataset.
- **ESMFold2 most consistent** here (pooled 0.643, best on 3/5 powered targets), echoing the
  2026-06-23 BindCraft screen replication (0.91).

**Why it mattered:**
- Shipping the egfr crossover unvalidated would have baked a **target-specific artifact into the
  ranking layer** of every future campaign — and it looked compelling (a 0.52 AUC gap).
- **Third Simpson's-paradox-family trap in one investigation**: pooled `promera_plddt`
  (0.826 → ~0.60 within-target), Promera's "unique catches" (beaten by a random voter), and now
  this. Standing rule going forward: **a per-stratum effect found on one target must reproduce on
  an independent target set before it changes the ranking layer**, and two engines must be compared
  on the *same designs* — mid-run, Boltz-2 and AF3 had scored nearly disjoint sets and the
  preliminary table pointed the wrong way.

**Net:** two roadmap negatives banked (Promera not adopted; length-weighting not adopted). Both are
deliverables — we now know two things not to build. The affinity-ranking gap remains open, untouched.

---

## 2026-07-26 — Cao 2022 staged as the large-scale metric benchmark (654k designs / 12 targets); Clara node-hogging incident found and fixed

**What changed:**

1. **Part U — Cao et al. 2022 benchmark staged and running** (`docs/INVESTIGATION_partU_cao_benchmark.md`).
   Every metric comparison so far was **noise-limited**: on our two labelled sets only 4–6 targets
   are scorable, ~45 candidate metrics all land in **0.71–0.74 macro-AUC**, and the metric
   *ranking* correlates **ρ = −0.107** between datasets — i.e. which metric "wins" has been
   essentially random. That is how the (later refuted) length crossover arose. Fixing it needs
   many targets **and** many binders per target.
   Assembled the Cao yeast-display data — **654,716 designs / 12 targets**, 40–67 aa minibinders —
   by joining `ngs_analysis/affinities/<T>.sc` with `sorting_ngs_data/<T>/sequences.list` (index-aligned).
   Refolding a **4,442-design / 2,042-binder / 12-target** subsample through Boltz-2 + AF3 (Clara
   H200 arrays) and ESMFold2 (Spark). Target constructs taken from chain B of the 13
   `*_mb.pdb` complexes (chain A = minibinder), i.e. the paper's exact constructs.
2. **Clara node-hogging incident.** A colleague (Anička) emailed that our AF3 jobs were "blocking a
   whole node with a 1-GPU job". Correct: the sbatch had `--gres=gpu:H200:1` and `-c 8` but **no
   `--mem`**, and Slurm then reserves the node's entire `RealMemory` (h200 = 2,321,905 MB). Four
   running array tasks held **four whole nodes — 32 GPUs of capacity to use 4**. Cancelled, added
   `--cpus-per-gpu=32 / --mem-per-gpu=250G / --gpu-bind=closest`, resubmitted with `--resume`.
   Rule written into `references/clara-deploy.md` §2 / §3.3 / §5 (commit `9b9614b`).

**Why it mattered:**

- The metric question cannot be settled at 5 targets; Cao is the only labelled set big enough
  (12 targets, ~2,000 binders in the subsample) to resolve differences that were noise.
- The Slurm default is silent and invisible in `squeue` — it looked like a normal 1-GPU job.
  Only `scontrol show job <id> | grep TRES` reveals it. Worth a permanent rule, not a one-off fix.

**Outcome:**

- **Two findings that bound the scope, recorded up front:**
  - *Label:* the naive "finite Kd" label marks 55,886 binders but their **median Kd is 8 µM** —
    not binding, and it inflates FGFR2 to a 56 % hit rate. Use **`kd_lb < 1000 nM`** → 11,629
    binders (1.79 %). The resulting 275× per-target spread (FGFR2 11.1 % → Tie2 0.04 %) is
    **expected**, not an artifact — Cao's own protocol guide grades target tractability.
  - *Affinity:* **this dataset cannot settle affinity ranking.** Only **495 of 11,629** binders have
    trustworthy Kd bounds, and they cluster against the assay's ~1 µM dynamic-range limit
    (PDGFR IQR **0.11 logs**). Only **FGFR2** has a real gradient (225 binders, 2.2 logs). Scope is
    therefore a well-powered **screen** benchmark + a single-target affinity probe. The subsample
    deliberately retains all 495 clean-Kd binders.
- **Provenance:** all Cao designs come from **one Rosetta pipeline** (RIF docking + motif grafting),
  not different design tools; what varies is scaffold topology — and β-containing folds
  (HEEH 4.39 %, EHEE 4.38 %) hit ~5× more often than all-helical HHH (0.92 %). So Cao (1 method ×
  12 targets) and Adaptyv (many methods × few targets) are **complementary**, testing different things.
- **Refold status:** Boltz-2 **4,442/4,442** ✅, ESMFold2 **4,442/4,442** ✅ (zero errors), AF3 running.
  After the resource fix the same array packs 8 tasks per node and runs ~3× more concurrently.
- **Data note:** only `experimental_data_and_analysis.tar.gz` (234 MB) is needed; the
  `design_models_pdb`/`silent` tarballs (**109 GB**) are Cao's own predicted structures and are
  irrelevant — we refold from sequence.
- **Archived to MUNI** (`EVALUATOR/promera_partT_2026-07/`, `EVALUATOR/denovo_lengthtest_2026-07/`):
  the completed Part T Promera benchmark and the 3-engine de-novo length test (refold CSVs +
  analyses; structures left local). Cao waits until AF3 finishes.
