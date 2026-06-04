# BindMaster — Development Plans

This document consolidates all active and future development plans.
Completed plans are archived in [docs/completed_plans.md](completed_plans.md).

---

## Part I: Pre-packed Standalone Distribution (future)

> **Status:** Planned, not started. Depends on Part H (complete).
>
> **Goal:** Ship BindMaster as a single archive that requires zero installation, zero internet,
> and zero system permissions on the target server. Extract, set PATH, run.

### Overview

Use `conda-pack` to create relocatable archives of every conda environment, bundle them
with the Mosaic uv venv, tool source code, and model weights into a single distributable
tar.gz. An `unpack.sh` script on the target machine extracts and patches paths.

```
Build machine (full internet, GPU)         Target server (restricted, air-gapped OK)
─────────────────────────────────          ──────────────────────────────────────────
bindmaster install --tool all              tar xzf bindmaster-standalone-*.tar.gz
bindmaster pack --output FILE              cd BindMaster
                                           bash unpack.sh
   produces:                               export PATH="$(pwd)/bin:$PATH"
   bindmaster-standalone-v0.8.0-           bindmaster configure
     x86_64-cuda124.tar.gz                 bash runs/myrun/run_all.sh
   (~10-20 GB compressed)
```

### Checklist

- [ ] I1. Add `conda-pack` dependency + verify env packing works
- [ ] I2. Create `pack/build_pack.sh` — build relocatable archive on dev machine
- [ ] I3. Create `pack/unpack.sh` — extract + fix paths on target server
- [ ] I4. Create `pack/manifest.py` — version/checksum metadata
- [ ] I5. Add `bindmaster pack` subcommand to CLI
- [ ] I6. Handle Mosaic uv venv relocation (shebang + pyvenv.cfg patching)
- [ ] I7. BoltzGen weights optional inclusion (`--include-boltzgen-weights`)
- [ ] I8. Platform build matrix (x86_64-cuda124, aarch64-cuda130)
- [ ] I9. Documentation: `docs/standalone_pack.md`
- [ ] I10. CI/release: GitHub Actions build + publish to Releases

### Size estimates

| Component | Raw | Compressed | Notes |
|---|---|---|---|
| Miniforge3 base (stripped) | ~500 MB | ~200 MB | Remove pkgs/, docs |
| BindCraft env | ~12 GB | ~4 GB | Includes PyRosetta, JAX, CUDA |
| BindCraft AF2 weights | ~4 GB | ~3.5 GB | 15 x .npz files |
| BoltzGen env | ~8 GB | ~3 GB | PyTorch + CUDA 12.1 |
| BoltzGen weights | ~6 GB | ~5 GB | Exclude by default |
| Mosaic venv | ~6 GB | ~2 GB | JAX + Boltz-2 + CUDA |
| binder-eval env | ~2 GB | ~500 MB | Lightweight |
| binder-eval-af2 env | ~5 GB | ~1.5 GB | ColabDesign + JAX CUDA |
| **Total (no model weights)** | **~34 GB** | **~11 GB** | |
| **Total (all weights)** | **~44 GB** | **~20 GB** | |

### Risks

| Risk | Mitigation |
|---|---|
| glibc version mismatch | Check in `unpack.sh`, document requirements |
| CUDA driver too old | Check `nvidia-smi` in `unpack.sh`, warn |
| Archive too large for GitHub Releases (2 GB limit) | Split archives or external hosting (Zenodo) |
| Mosaic venv path patching misses files | Delete `__pycache__/`, smoke test in `unpack.sh` |

---

## Deferred Items

| Item | Description | Original part |
|---|---|---|
| F2 | `--headless` mode for configurator (accept JSON config, skip prompts) | Part F |
| F6 | Multi-chain binder support in BoltzGen YAML generation | Part F |

---

## Proteina-Complexa on aarch64

> **Status:** Planned. x86_64 integration is complete. Porting to the `aarch64` branch
> follows the Mosaic pattern: try building, identify packages without aarch64 wheels,
> patch them out with `platform_machine != 'aarch64'` markers.

### Key facts

- Core deps (PyTorch 2.7, JAX 0.4.29) have aarch64 CUDA wheels
- Likely blockers: `torchtext`, `torch-geometric` (PyG), `esmj`, `atomworks`
- Approach: clone → attempt build → note failures → write patch function → add to `install_aarch.sh`

### Steps

1. Rebase `aarch64` branch from `master`
2. Clone Proteina-Complexa and attempt naive build
3. Identify failing packages from build log
4. Write `_patch_complexa_pyproject()` to exclude unsupported packages
5. Handle PyTorch CUDA (force-reinstall for sm_121 if needed)
6. Add `install_proteina_complexa()` to `install/install_aarch.sh`
7. Verify end-to-end: install → configure → run → evaluate

---

## Part N: Binding ΔG / interface-energy metric in the Evaluator

> **Status:** Planned, not started. Motivated by the ProteinBase 4-target benchmark
> (Nipah / EGFR / IL7R / PD-L1, runs/phase5_multitarget + nipah_benchmark100).
>
> **Goal:** Add an interface binding-energy (ΔG / ΔΔG) metric so the Evaluator can
> *rank affinity among binders*, not just separate binders from non-binders.

### Why (benchmark evidence)

Across 175 designs with experimental binding data we established, with three independent
analyses (precision@K, direct affinity correlation, length-confound test, and a cascade
filter), that **structure-confidence metrics cannot rank affinity**:

- iPTM / ipSAE / pLDDT / PAE — from any engine, in any of 297 combinations — predict
  *binder vs non-binder* modestly (macro AUC ≈ 0.75, best = `max(iptm)`), but among
  binders they are **uncorrelated-to-negatively** correlated with affinity
  (Spearman ρ vs pKd ≈ −0.4 to +0.1; mostly the wrong sign, half explained by a
  binder-length confound).
- The cascade works for stage 1 only: `max(iptm)` top-40 % → ~87 % binder purity, but
  **no metric ranks affinity within the survivors**. The single least-bad signal is
  `boltz2_ipsae_min` (ρ ≈ +0.2 vs pKd) — too weak to deploy.
- Root cause: iPTM/ipSAE measure "is the model confident an interface forms" (a binary-ish
  property); affinity (ΔG, a continuous free energy) is a different physical quantity that
  structure-confidence does not encode. Boltz-2's `boltz2_aff` head is **protein–ligand
  only** (schema hard-rejects multi-residue/protein binders), so it is not an option here.

The missing piece is an **explicit binding-energy estimate** from the refolded complex.

### Approach

Compute interface ΔG from the refolded structures we already produce (Boltz-2 / AF3 /
ESMFold2 each write a complex PDB/CIF per design — reuse them, no re-fold needed).

Candidate engines (pick one to pilot first):

1. **Rosetta InterfaceAnalyzer** (`dG_separated`, dSASA, shape complementarity, packstat) —
   the standard interface-energy report. PyRosetta is already vendored for BindCraft, so the
   dependency exists on x86 (NOT aarch64 — no PyRosetta wheels; same blocker as Protein-Hunter).
   ~seconds–minutes per complex.
2. **PRODIGY** (Vangone & Bonvin contact-based ΔG predictor) — pure-Python, lightweight,
   no Rosetta; predicts ΔG (kcal/mol) and Kd from a complex PDB. Cross-platform incl. aarch64.
   Lower ceiling than Rosetta but trivial to install and a good first pilot.
3. **FoldX `AnalyseComplex`** — licensed binary; strong but not freely redistributable.

Recommended first pilot: **PRODIGY** (cross-platform, no licence, validates the idea), then
add **Rosetta InterfaceAnalyzer** on x86 as the higher-fidelity option.

### Checklist

- [ ] N1. Pilot PRODIGY on the phase5 binder subset (≈122 binders): does predicted ΔG/Kd
      correlate with experimental pKd where iPTM failed? (Spearman vs pKd, per target.)
      **Gate the whole part on this** — if ΔG also flat-lines, document and stop.
- [ ] N2. New module `binder_comparison/scoring/interface_energy.py` — takes a complex
      PDB/CIF (binder chain + target chain) → {dG, dG_per_contact, predicted_Kd}.
- [ ] N3. Wire into the report: add `deltaG_*` columns; surface in the per-design table and
      as a candidate stage-2 ranker (the cascade: filter by `max(iptm)`, rank survivors by ΔG).
- [ ] N4. Reuse existing refold structures (boltz/af3/esmfold2 PDBs) — no extra folding.
      Pick the structure source per the report's `primary_engine` preference.
- [ ] N5. Env: PRODIGY into `binder-eval` (pure-Python, all platforms). Rosetta path gated
      behind PyRosetta availability (x86 only) like Protein-Hunter.
- [ ] N6. CLI: `binder-compare score-interface --structures DIR -o deltaG.csv`; optional step
      in `evaluate.sh` after refolding.
- [ ] N7. Update the benchmark report with the ΔG-as-stage-2-ranker result.

### Risks

| Risk | Mitigation |
|---|---|
| ΔG predictors are also weak on de novo designs (trained on natural complexes) | N1 is a hard gate — pilot before building. PRODIGY/Rosetta were trained on crystal complexes; designed interfaces may be out of distribution. |
| PyRosetta unavailable on aarch64 (DGX Spark) | Ship PRODIGY as the cross-platform path; Rosetta is the x86-only high-fidelity add-on. |
| ΔG from a *predicted* (not crystal) structure inherits the refold's errors | Compute on the highest-confidence refold; report ΔG alongside the structure's pLDDT so low-confidence folds are flagged. |

### Part N (detail): Rosetta InterfaceAnalyzer — primary ΔG path

> Licensing is **not** a constraint (project is open-source / academic; PyRosetta is free
> for non-commercial use), so Rosetta is the primary engine, with PRODIGY as the
> cross-platform fallback (aarch64, where PyRosetta has no wheels).

**Strong reuse opportunity — BindCraft already does exactly this.** `BindCraft/functions/
pyrosetta_utils.py` ships `score_interface(pdb_file, binder_chain="B")` (builds an
`InterfaceAnalyzerMover`, calls `get_interface_dG()`, returns `interface_dG`,
`interface_dG_SASA_ratio`, dSASA, shape-complementarity, H-bonds, unsat-polars, …) and
`pr_relax(pdb_file, relaxed_pdb_path)` (constrained `FastRelax`). The PyRosetta env
(`BindCraft` conda env) is already installed on x86. The integration is mostly *adapting
and calling these*, not writing Rosetta from scratch.

**The make-or-break detail: relax before scoring.** Raw Boltz-2/AF3/ESMFold2 complexes have
clashes and non-ideal geometry; `dG_separated` on an unrelaxed predicted structure is
dominated by clash artifacts and is uninformative. BindCraft relaxes first — we must too.
Default = constrained `FastRelax` (coordinate constraints to stay near the prediction) or at
minimum interface side-chain repack. Expose `--relax {none,repack,fastrelax}`; fastrelax is
~1–5 min for a ~600-aa complex (the cost driver).

**Chain-ID handling.** Refold complexes differ: Boltz-2 writes binder=A/target=B; AF3 &
ESMFold2 write target=A/binder=B. The scorer must take an explicit `binder_chain` (read from
the refold runner's known convention per engine) so `dG_separated` measures the right jump.
DAlphaBall (`tools/aarch64/DAlphaBall.gcc` / x86 equiv) is needed for packstat/holes —
already bundled.

**Important honesty:** Rosetta `dG_separated` is in Rosetta Energy Units (REU), correlated
with but **not calibrated to** kcal/mol. Report it as a ranking score, not an absolute ΔG,
unless calibrated against the benchmark's experimental Kd.

#### Rosetta checklist (supersedes the engine choice in N1–N2)

- [ ] NR1. **Validation gate.** Pilot: relax + `score_interface` on the phase5 binder subset
      (122 binders, reuse their refold PDBs), correlate `interface_dG` and
      `interface_dG_SASA_ratio` vs experimental pKd, per target. Proceed only if a real
      affinity signal appears where iPTM failed (Spearman |ρ| ≳ 0.3, right sign).
- [ ] NR2. `binder_comparison/scoring/interface_energy.py` — thin wrapper that imports/adapts
      BindCraft's `score_interface` + `pr_relax`; input: complex PDB + binder_chain; output:
      `{interface_dG, dG_dSASA_ratio, dSASA, sc, hbonds, unsat, packstat}`.
- [ ] NR3. `scripts/score_rosetta.py` standalone batch scorer (mirror the `refold_*.py`
      pattern: read a structures dir, relax+score each, append to CSV, resumable).
- [ ] NR4. CLI `binder-compare score-rosetta --structures DIR --binder-chain X -o rosetta.csv`,
      run in the `BindCraft` conda env (has PyRosetta). Reuse existing refold PDBs — no re-fold.
- [ ] NR5. Report: merge `rosetta_dG_*` columns; add to per-design table + top-N; wire the
      cascade — rank stage-1 survivors (`max(iptm)` filter) by `interface_dG`.
- [ ] NR6. Platform: x86 via `BindCraft` env. aarch64 = PRODIGY fallback (Part N option 2),
      documented as a known split like Protein-Hunter.
- [ ] NR7. Optional: linear calibration of REU→kcal/mol (or →pKd) fit on the benchmark, so the
      reported number is interpretable; ship the fit coefficients, flag as approximate.
