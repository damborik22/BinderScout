# PLAN — Chai-1 refold engine + four new design tools (Parts O–S)

> Status: Draft. Continues alphabetical part numbering from Part N.
>
> Goal: Add a fourth refolding engine (Chai-1) and four new design tools
> (RFantibody, PPIFlow, lifted HyperMPNN/FAMPNN, OriginFlow) to BindMaster.
> Largest functional gap addressed: RFantibody is the first antibody/nanobody
> designer in the pipeline — every existing tool targets monomer binders / PPIs.

---

## Part O — Chai-1 as 4th refold engine

> Goal: Add a fourth independent refolding engine alongside Boltz-2, Protenix, AF3.
> Strengthens consensus ranking (`agreement_count` denominator: 3 → 4 on aarch64,
> 2 → 3 on x86). Architecture mirrors Part J (Protenix).

**Repo:** `chaidiscovery/chai-lab` · Apache-2.0 · pip-installable.

- [ ] O1. Add `Evaluator/envs/binder-eval-chai.yml` (Python 3.11, `chai_lab`, torch CUDA matching platform)
- [ ] O2. Installer: add `install_chai_eval()` to `install/install.sh` and `install/install_aarch.sh` (parallels `install_protenix_eval()`)
- [ ] O3. `Evaluator/binder_comparison/refolding/chai_runner.py` — wrap chai-lab's `run_inference`, write CSV with `chai_*` columns
- [ ] O4. `Evaluator/scripts/refold_chai.py` — standalone refold script (Mosaic/Protenix/AF3 pattern)
- [ ] O5. `binder-compare refold-chai` subcommand
- [ ] O6. Schema additions: `chai_iptm`, `chai_ptm`, `chai_ranking_score`, `chai_plddt_binder_{mean,min}`, `chai_pae_{bt,tb,bb}_mean`, `chai_pae_max`, `chai_bt_ipsae`, `chai_tb_ipsae`, `chai_ipsae_min`
- [ ] O7. PAE ordering: confirm Chai-1 token order; pre-arrange input as [target, binder] so transpose logic in `binder_comparison/scoring/ipsae.py` matches AF3 path
- [ ] O8. `evaluate.sh`: add Step-4 "Chai-1 refolding", `--skip-chai` flag
- [ ] O9. `binder_comparison/scoring/ranking.py`: bump `AGREEMENT_DENOMINATOR` per platform, add `chai` to engine list
- [ ] O10. HTML report: add Chai column to top-N table, per-engine PAE heatmap section, color in legend
- [ ] O11. Configurator wizard Step 5: add Chai toggle (default on)
- [ ] O12. README + CLAUDE.md: document 4th engine, update architecture diagram
- [ ] O13. Smoke test: refold the CBG r2 outputs through Chai-1, confirm rank correlation with Boltz-2/Protenix is sane (>0.6)

**Risks:** Chai-1 torch pin may conflict with Protenix env — keep envs separate. VRAM ≤24 GB confirmed for ≤450-token complexes per Chai-1 docs.

---

## Part P — RFantibody (antibody / nanobody design)

> Goal: First antibody-specific designer in BindMaster. Fills the largest functional
> gap — every existing tool is monomer-binder/PPI. *Nature* Nov 2025.

**Repo:** `RosettaCommons/RFantibody` · MIT · pinned commit + Baker-lab weights.

- [ ] P1. `install/install.sh`: add `install_rfantibody()` — clone, conda env `bindmaster_rfantibody` (Python 3.10), download `rf_antibody.pt` + `rf2_ab.pt` weights
- [ ] P2. `install/install_aarch.sh`: aarch64 best-effort (likely fails on jaxlib like BindCraft — gate behind warning, don't block)
- [ ] P3. Bundle aarch64 PyRosetta/DSSP shims (reuse `tools/aarch64/` pattern)
- [ ] P4. Pin commit: `RFANTIBODY_COMMIT` constant
- [ ] P5. Configurator wizard: add Step 4b "Antibody mode" — branches design path, prompts for:
  - Framework scaffold (VHH / VH-VL / scFv)
  - CDR loops to design (H1/H2/H3, L1/L2/L3)
  - Hotspot residues on target (existing field reused)
- [ ] P6. Generated `run_rfantibody.sh` template in `configurator/templates/`
- [ ] P7. New extractor `Evaluator/binder_comparison/extractors/rfantibody.py` — handles H/L chain naming, splits CDR sequences from framework
- [ ] P8. `binder-compare extract --rfantibody DIR` flag
- [ ] P9. Refold path: target+VH (single-chain Ab) and target+VH+VL (paired) handled in all four refold engines (Boltz-2, Protenix, AF3, Chai-1) — chain-count-aware target_seq construction
- [ ] P10. Report: separate "Antibody designs" section if RFantibody output present; CDR-loop-aware metrics (loop pLDDT vs framework pLDDT)
- [ ] P11. `bin/rfantibody` shortcut
- [ ] P12. Smoke test on lysozyme/CALCA target with VHH-only mode
- [ ] P13. Docs: `docs/antibody_design.md` workflow recipe

**Risks:** Antibody chain conventions (Kabat/Chothia numbering) not yet handled anywhere in the codebase. May need `anarci` or `abnumber` as a dep. Refold scripts assume binder = single chain — paired Ab needs schema adjustment.

---

## Part Q — PPIFlow (flow-matching binder designer with affinity maturation)

> Goal: Newest entrant (Jan 2026 preprint). Pairformer + flow + in-silico
> maturation stage offers something no other tool does — explicit affinity
> optimization post-design.

**Repo:** `Mingchenchen/PPIFlow` · weights on Google Drive (push for HF mirror in PR).

- [ ] Q1. Verify license (LICENSE.txt) before integration — block if non-permissive
- [ ] Q2. Audit: read paper + repo to understand (a) input format, (b) checkpoint locations, (c) affinity-maturation iteration loop
- [ ] Q3. `install/install.sh`: clone + uv venv (`PPIFlow/.venv`) — pattern from Mosaic since likely PyTorch-heavy
- [ ] Q4. Weights download script: handle Drive auth (use `gdown` or document manual download)
- [ ] Q5. Pin commit: `PPIFLOW_COMMIT`
- [ ] Q6. `bindmaster_examples/ppiflow_template.py` (mirrors `hallucinate_bindmaster.py`)
- [ ] Q7. Configurator: Step 4 add PPIFlow toggle + maturation iterations slider (default: 0 = design only, recommend 5–10 for production)
- [ ] Q8. Generated `run_ppiflow.sh` template
- [ ] Q9. Extractor: `Evaluator/binder_comparison/extractors/ppiflow.py`
- [ ] Q10. `binder-compare extract --ppiflow DIR` flag, report color
- [ ] Q11. `bin/ppiflow` shortcut
- [ ] Q12. Smoke test on CBG target — compare maturation-on vs maturation-off ipsae_min
- [ ] Q13. README: document affinity-maturation as a unique feature

**Risks:** Preprint-era code = unstable API. Pin commit aggressively. If Drive
weights become unavailable, integration breaks.

---

## Part R — HyperMPNN + FAMPNN modules (lifted from ProteinDJ)

> Goal: Surgical lift, not a wrapper. ProteinDJ's Nextflow shell conflicts with
> our configurator-driven flow, but its sequence-design modules are valuable as
> drop-in MPNN alternatives for RFD3, RFantibody, and BindCraft.

**Source:** `PapenfussLab/proteindj` v2.2.1 · permissive.

- [ ] R1. Audit ProteinDJ to extract HyperMPNN and FAMPNN as standalone Python modules (no Nextflow dep)
- [ ] R2. Confirm licenses on each module independently — they may be third-party
- [ ] R3. Add `bindmaster/mpnn/` directory with three backends: `proteinmpnn.py` (existing default), `hypermpnn.py`, `fampnn.py`
- [ ] R4. Install: extend `bindmaster_rfaa` (or equivalent) env with their deps; check whether they fit in existing envs
- [ ] R5. Add `--mpnn-backend {proteinmpnn,hypermpnn,fampnn}` flag to:
  - RFD3 run script
  - RFantibody run script (Part P)
  - BindCraft run script (BindCraft uses internal MPNN — gate as override)
- [ ] R6. Configurator: Step 4 add MPNN backend selector (advanced section)
- [ ] R7. Document: `docs/mpnn_backends.md` — when to prefer each (HyperMPNN: thermostable; FAMPNN: structurally precise per ProteinDJ docs)
- [ ] R8. A/B test on existing CBG run: same RFD3 backbones, three MPNN backends, compare downstream ipsae_min

**Risks:** Lift may not be cleanly modular — fallback is to wrap ProteinDJ's Python
entry points without the Nextflow shell. If lift fails, drop to "Part R-alt:
ProteinDJ as full integration" (heavier).

---

## Part S — OriginFlow (deferred / experimental)

> Goal: Validate the >95% success-rate claim under our eval stack before
> committing to integration.

**Repo:** `JoreyYan/Originflow` · Apr 2025 preprint.

- [ ] S1. **Validation gate first** — clone + run their published examples, refold through our 4-engine stack (post-Part O), confirm ipsae_min distribution matches paper claims
- [ ] S2. **If S1 fails:** stop. Document findings in `docs/originflow_validation.md` and skip integration.
- [ ] S3. **If S1 passes:** clone + uv venv, pattern from Mosaic
- [ ] S4. Configurator + extractor + report integration (mirrors Q5–Q11)

**Rationale for deferring:** newer than PPIFlow, less established lab provenance,
and "success rate" claims in protein design papers historically don't replicate.
Cheap experiment first; commit only on positive evidence.

---

## Cross-cutting

**Suggested ship order:**
1. **O (Chai-1)** — fastest win, value to all existing design tools
2. **P (RFantibody)** — biggest functional gap, longest effort (~2 weeks)
3. **R (HyperMPNN/FAMPNN)** — short, multiplies value of P
4. **Q (PPIFlow)** — novel maturation stage, but newest = highest API risk
5. **S (OriginFlow)** — validate-first, commit only on evidence

**Effort rough estimate:** O ≈ 3–5 days, P ≈ 1.5–2 weeks, Q ≈ 1 week,
R ≈ 4–6 days, S ≈ 1 day to validate / 1 week if greenlit.

**Schema-breaking change:** `agreement_count` denominator becomes platform-aware
(3 on x86, 4 on aarch64) once Chai-1 lands. Old reports are not directly
comparable — bump report version string.

**aarch64 caveats:** P, Q, S all use diffusion/flow models with possible
jaxlib/torchtext aarch64 wheel issues. Same approach as Mosaic — best-effort
install with `platform_machine != 'aarch64'` markers.
