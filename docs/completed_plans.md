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

---

## Part N: Binding ΔG / interface-energy metric (complete — negative result)

**Original file:** `docs/plans.md` Part N (N1–N7 + Rosetta checklist NR1–NR7).

**Goal.** Add an interface binding-energy (ΔG / ΔΔG) metric so the Evaluator could *rank
affinity among binders*, not just separate binders from non-binders — the gap left by
structure-confidence metrics (`iptm`, `ipsae_min`, pLDDT, PAE), which predict
binder-vs-non-binder at macro AUC ≈ 0.75 but are uncorrelated-to-negatively correlated
with affinity among binders.

**What was implemented.**

- `comparison/affinity.py` — `interface_energy_density(dg, dsasa)` = `|dG/dSASA|`,
  `add_affinity_ranking(...)`, `DEFAULT_AFFINITY_GATE = 0.61`.
- `binder-compare affinity` (`cli/affinity.py`) — `--metrics`, `--energy` /
  `--structures-dir` + `--run-rosetta`, `--interface B_A`, `--bindcraft-env`,
  `--gate-threshold`. Rosetta `InterfaceAnalyzer` runs in the `BindCraft` conda env
  (PyRosetta, x86); relax-before-score as BindCraft does.
- `binder-compare qc-annotate` — relax + the BindCraft 14-metric interface panel as an
  **advisory** annotation (`qc_pass` / `qc_fail_reasons` / `interface_*`), never dropping
  or reordering (`--drop-failures` is opt-in).

**Outcome — the metric does not rank affinity (documented negative).**

- Exhaustive search over 3 refold engines × confidence metrics, Rosetta interface ΔG,
  `|dG/dSASA|`, the full BindCraft 14-metric panel, and **PRODIGY** (contact model trained
  on experimental Kd): best pooled |Spearman ρ| vs strength = **0.34** (`dG/dSASA`, holding
  on only 2/4 targets). PRODIGY |ρ| ≤ 0.15. The `ipSAE × dG` composite from the original
  plan did not rescue it.
- "Screen-then-invert" looked usable pooled but is a **Simpson's-paradox artifact** —
  replicates on EGFR only (ρ −0.71); IL7R flat, Nipah reversed. **Do not use.**
- Externally corroborated: **OpenBind** (crystal protein–ligand + Creoptix Kd) — the best
  affinity predictor is **molecular weight**, ρ **0.48**, beating Boltz-2 (0.40) and
  dedicated ML models. **SKEMPI 2.0** (343 crystal protein–protein complexes) — PRODIGY
  **0.20**, Rosetta ΔG **0.12**; on the same complexes our predicted-structure ipTM 0.28 ≈
  crystal PRODIGY 0.27, so predicted structure is *not* the bottleneck for natural complexes.

**Design consequence (2026-06-16 redesign).** `ipsae_min` carries ~0 / sign-unstable
correlation with affinity, so it is no longer a multiplier. The shipped form is
**gate-then-density**: `passes_affinity_gate = ipsae_min ≥ 0.61` gates,
`interface_energy_density = |dG/dSASA|` ranks survivors — **advisory, not a validated
affinity ranker.** (`affinity_composite` / `add_affinity_composite` were renamed
`interface_energy_density` / `add_affinity_ranking`.)

**Net stance.** SCREEN solved (cross-engine ipTM, AUC ≈ 0.69 Adaptyv → 0.91 on an
independent BindCraft *Nature* 2025 replication). **Affinity RANK unsolved in-silico
everywhere** — needs experimental Kd + active learning, or better/ensemble structures.
Successor work: `PLAN_ranking_and_engines_roadmap.md` Parts T (Promera / iCS) and U
(ProtDBench calibration harness), which inherit this validation bar.
