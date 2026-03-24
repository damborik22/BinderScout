# Target Misfolding in Cross-Validation Refolding

**Date:** 2024-03-24
**Target:** CALCA (Calcitonin gene-related peptide, UniProt P01258)
**Affected pipeline steps:** Boltz-2 refolding, AF2 refolding

---

## 1. The Problem

During independent cross-validation of CALCA binder designs, both Boltz-2 and AF2 **completely misfold the target protein** when predicting the binder–target complex from sequences alone.

| Engine | Target Cα RMSD vs PDB | Observed fold | Expected fold |
|--------|----------------------|---------------|---------------|
| Boltz-2 (sequence-only) | **28.8 Å** | Compact globular | Extended helical + disordered |
| AF2 (ColabDesign) | **~30+ Å** | Compact/misfolded | Extended helical + disordered |
| PDB reference (P01258) | 0.0 Å | Extended helical + disordered | — |

**Why CALCA is hard:**
- Small peptide hormone (32 aa mature calcitonin, 116 aa procalcitonin)
- Partially disordered — no stable globular fold in isolation
- Helical core (residues ~44–74) flanked by disordered regions
- Signal peptide (residues 1–25) cleaved post-translationally
- The experimental structure was likely determined in complex or with stabilizing conditions

**This is NOT a rare edge case.** Many therapeutic targets are small, disordered, or only fold correctly in context (e.g., peptide hormones, CDRs, IDPs, membrane-proximal domains). Any evaluation pipeline that assumes sequence → correct fold will silently produce invalid metrics for these targets.

---

## 2. Impact on Existing CALCA Evaluation Data

### What the data shows vs what it means

The existing CALCA evaluation (657 binders, `runs/CALCA_combined/evaluate/`) produced:

| Metric | Observed range | Reliability |
|--------|---------------|-------------|
| Boltz-2 `ipsae_min` | 0.0 – 0.91 | **Unreliable** — computed against wrong target geometry |
| Boltz-2 `iptm` | 0.1 – 0.95 | **Unreliable** — interface doesn't exist in misfolded target |
| AF2 `ipsae_min` | 0.0 – 0.85 | **Unreliable** — same issue |
| `agreement_count` | 0 – 2 | **Misleading** — two engines agreeing on wrong geometry |
| `plddt_binder_mean` | 0.4 – 0.9 | **Partially valid** — binder fold confidence is independent of target |
| `binder_ptm` | 0.5 – 0.98 | **Partially valid** — binder internal quality metric |

**Key insight:** High scores in the existing data mean the binder fits well against a *misfolded* target. This does NOT predict binding to the *real* CALCA structure. The rankings are essentially random with respect to actual binding potential.

### What IS still valid

- **Binder-internal metrics** (`binder_ptm`, `plddt_binder_mean`): These measure whether the binder itself folds into a stable structure, independent of the target. Still useful for filtering out badly folded designs.
- **Sequence diversity and coverage**: The 657 sequences from Mosaic, BoltzGen, BindCraft, PXDesign, and Proteina-Complexa are valid as a design pool.
- **Source tool annotations**: Which tool designed which binder is unaffected.

### What MUST be re-evaluated

- All interface metrics (`ipsae_min`, `iptm`, `pae_bt`, `pae_tb`, etc.)
- All rankings based on interface metrics
- The `agreement_count` column
- The HTML report and top-20 selection
- Any downstream decisions based on these rankings

---

## 3. Solutions Explored

### 3a. Template forcing in Boltz-2 (via Mosaic/joltz patch)

**Approach:** Use Boltz-2's `force: true` template support to constrain the target backbone during diffusion while leaving the binder free for de novo prediction.

**Implementation:**
1. Added `force_template` and `force_threshold` fields to Mosaic's `TargetChain` dataclass
2. Updated YAML generation to emit `force: true` and `threshold: 2.0`
3. Patched joltz's `AtomDiffusion2.sample()` to apply per-step Kabsch-aligned coordinate constraints

**Results:**
- Target Cα RMSD: **1.10 Å** (correctly constrained)
- But interface metrics collapsed: `bt_ipsae=0.065`, `iptm=0.22`, `bt_pae=20 Å`
- The per-step forcing disrupts the binder–target spatial relationship during diffusion
- The binder and target end up in disconnected spatial regions

**Root cause:** Boltz-2's native `force: true` works through a gradient-based potential (`TemplateReferencePotential`) during the PyTorch diffusion loop. Mosaic's JAX wrapper (`joltz`) doesn't implement the steering/potentials system. Our Kabsch-aligned displacement approach is a coarser approximation that constrains the target shape but disrupts the interface formation.

**Status:** Target shape works, interface metrics unreliable. Not suitable for production evaluation.

### 3b. Using `boltz predict` CLI directly

**Approach:** Bypass Mosaic's wrapper entirely. Call Boltz-2's official CLI (`boltz predict --use_potentials`) which implements the full steering system.

**Pros:**
- Correct template forcing via TemplateReferencePotential
- Official implementation, well-tested
- Supports `--diffusion_samples`, `--recycling_steps`, `--write_full_pae`

**Cons:**
- Lose Mosaic's multi-sample loss aggregation (can still compute ipSAE from PAE arrays post-hoc)
- Need to parse CLI output files (CIF, confidence JSON, PAE NPZ) instead of getting Python objects
- Adds a subprocess call to the pipeline

**Status:** Viable but not yet implemented. Would require a new `refold_boltz2_cli.py` script.

### 3c. Add Protenix (AF3) as third refolding engine ← **Recommended**

**Approach:** Add Protenix (ByteDance's open-source AF3 implementation) as a third independent cross-validation engine alongside Boltz-2 and AF2.

**Why Protenix helps:**
- **Native template support**: AF3 handles templates as input features (not bolted-on potentials). Template constraining is part of the core architecture.
- **Independent architecture**: Different from both Boltz-2 (diffusion) and AF2 (evoformer + structure module). Gives truly independent cross-validation.
- **Better for difficult targets**: AF3 was trained on a broader dataset including peptide–protein complexes, disordered regions, and multi-chain assemblies.
- **3-way agreement**: With three engines, `agreement_count` becomes a much stronger signal. If all three agree `ipsae_min > 0.61`, confidence is high.
- **Already installed**: Protenix is available in the Mosaic `.venv` and the `bindmaster_pxdesign` conda environment.

**Implementation plan:**
1. `refold_protenix.py` — lightweight Python wrapper (like refold_boltz2.py / refold_af2.py)
2. `binder-compare refold-protenix` CLI command
3. Update report pipeline to merge three engines
4. Update `agreement_count` to check three engines

**Status:** Design phase. Implementation estimated at ~1 day.

---

## 4. Strategy for Re-evaluation

### Recommended approach: Three-engine evaluation with template support

```
Binder sequences (657)
  ├── Boltz-2 (sequence-only, Mosaic venv)
  │     → boltz2_results.csv (PAE, ipSAE, ipTM, pLDDT)
  │
  ├── AF2 (with target PDB, binder-eval-af2 env)
  │     → af2_results.csv (PAE, ipSAE, ipTM, pLDDT)
  │
  └── Protenix/AF3 (with target PDB template, Mosaic venv)
        → protenix_results.csv (PAE, ipSAE, ipTM, pLDDT)

  → Merge + compute 3-way agreement_count
  → Rank by agreement_count → ipsae_min → iptm
  → Generate HTML report
```

### Per-engine target handling

| Engine | Target input | Template support | Expected target RMSD |
|--------|-------------|-----------------|---------------------|
| Boltz-2 | Sequence only | Not reliable via Mosaic | ~28 Å (misfolded) |
| AF2 | Target PDB (ColabDesign binder protocol) | Native | ~2-5 Å (reasonable) |
| Protenix | Target PDB + template | Native AF3 templates | <2 Å (expected) |

### Interpreting three-engine results for difficult targets

For well-folded targets (e.g., Nipah G protein):
- All three engines should fold the target correctly from sequence
- High agreement_count = strong prediction

For difficult targets (e.g., CALCA):
- Boltz-2 may misfold the target → its metrics are noisy/unreliable
- AF2 and Protenix use the target PDB → their metrics are more reliable
- **Strategy:** Weight AF2 + Protenix agreement more heavily for difficult targets
- **Or:** Flag targets where Boltz-2 target RMSD > 5 Å and discount its contribution

### Quality tiers with three engines

| agreement_count | Meaning | Action |
|----------------|---------|--------|
| 3/3 | All engines agree ipsae_min > 0.61 | Strong candidate for experimental testing |
| 2/3 | Majority agreement | Promising, investigate the dissenting engine |
| 1/3 | Only one engine scores well | Likely false positive |
| 0/3 | No engine scores well | Reject |

---

## 5. Broader Implications

### For other targets in the pipeline

Any target that is:
- Small (< 100 aa)
- Partially disordered
- A peptide or peptide hormone
- Only structured in complex
- Membrane-associated (with unstructured extracellular domains)

...should be flagged for potential misfolding during cross-validation. The evaluation pipeline should:

1. **Always save target structures** from each refolding run
2. **Compute target RMSD** against the input PDB as a quality check
3. **Flag runs** where target RMSD > 5 Å in the report
4. **Use template-constrained engines** (Protenix, AF2 with target PDB) as primary for difficult targets

### Independent confirmation

Colby Ford (Silico Biosciences) independently reported the same issue during the Nipah binder competition:
> Boltz-2's target structure prediction is non-deterministic and can place binders at completely different sites between runs, drastically changing ipSAE scores.

This validates that the problem is not CALCA-specific but a general limitation of sequence-only cross-validation for targets where the fold prediction is unreliable.

### The Adaptyv/Escalante precedent

The Escalante Bio Mosaic blog (Adaptyv Nipah competition) explicitly chose sequence-only prediction for cross-validation. This worked because their target (Nipah G, 532 aa) is a well-folded protein that Boltz-2 predicts correctly. They acknowledged: "Adaptyv probably didn't use a template for the target, so we don't either."

For CALCA, this assumption fails. The evaluation methodology must adapt to the target.

---

## 6. Recommendation

1. **Add Protenix as third refolding engine** (primary fix)
2. **Keep Boltz-2 sequence-only** for comparability with Adaptyv methodology
3. **Use AF2 + Protenix with target PDB** for reliable interface metrics
4. **Re-run CALCA evaluation** with all three engines into `evaluate_v2/`
5. **Add target RMSD check** to the pipeline as a standard quality metric
6. **Document the limitation** in the pipeline reference for future targets
