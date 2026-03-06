# Integration Status: RFDiffusionAA + PXDesign

Branch: `feature/rfaa-pxdesign-integration`

## Safety Architecture
- All new code is in `bindmaster/tools/rfaa/` and `bindmaster/tools/pxdesign/`
- Feature flags (default OFF): `BINDMASTER_ENABLE_RFAA`, `BINDMASTER_ENABLE_PXDESIGN`
- Existing tools (BindCraft, BoltzGen, Mosaic) are UNTOUCHED
- Run `bash scripts/test_new_tools.sh` to verify nothing broke

## RFDiffusionAA
- **What:** Baker Lab all-atom diffusion — designs binders to SMALL MOLECULES + proteins
- **Unique capability:** Only BindMaster tool with ligand (small molecule) conditioning
- **Env:** `conda activate bindmaster_rfaa`
- **Weights:** `$BINDMASTER_RFAA_WEIGHTS` (set in ~/.bashrc by install_rfaa.sh)
- **Key class:** `bindmaster.tools.rfaa.runner.RFAARunner`
- **Key config:** `RFAAConfig.inference.ligand` = 3-letter CCD code (e.g. "OQO")
- **Output:** Backbone PDB only — NO sequence. Must run LigandMPNN downstream.
- **Test (no GPU):** `python -m pytest tests/tools/rfaa/ -v`
- **Test (GPU):** `BINDMASTER_ENABLE_RFAA=true python examples/ligand_binder_test.py`

## PXDesign
- **What:** ByteDance de novo binder design — diffusion + Protenix + AF2-IG full pipeline
- **Unique capability:** Complete self-contained pipeline with 2 independent confidence models
- **Env:** `conda activate bindmaster_pxdesign`
- **Key class:** `bindmaster.tools.pxdesign.runner.PXDesignRunner`
- **Key param:** `preset="preview"` for testing, `preset="extended"` for production
- **MSA cache:** `msa_cache/<target_hash>/` — auto-populated, reused across runs
- **Filters (use these for wet-lab):**
  - `Protenix-basic`: ptx_ipTM > 0.80, ptx_pTM > 0.80, complex RMSD < 2.5 A
  - `Protenix`: ptx_ipTM > 0.85, ptx_pTM > 0.88 (strict, for easy targets)
- **Test (no GPU):** `python -m pytest tests/tools/pxdesign/ tests/scoring/ -v`
- **Test (GPU):** `BINDMASTER_ENABLE_PXDESIGN=true python examples/pxdesign_pdl1_test.py --preset preview --n 50`

## Unified Scoring
- **Class:** `bindmaster.scoring.unified.BinderScore`
- **Composite formula:** ipTM(40%) + pLDDT(30%) + ipAE_norm(30%), redistributed if missing
- **Activate:** `BINDMASTER_ENABLE_UNIFIED_SCORING=true`

## When to use which tool
| Goal | Tool(s) |
|------|---------|
| Small-molecule binder design | **RFDiffusionAA** + LigandMPNN |
| Protein binder, fast check | **PXDesign** (preview, 50-100 samples) |
| Protein binder, wet-lab ready | **PXDesign** (extended, 5000+ samples) |
| Benchmark all approaches | **BindCraft + BoltzGen + PXDesign** parallel |
| Compare confidence models | **PXDesign** (Protenix) vs **Mosaic** (Boltz2) |

## Promotion to master — Checklist
- [ ] `bash scripts/test_new_tools.sh` passes clean
- [ ] GPU smoke test on DGX Spark: both tools produce valid outputs
- [ ] PXDesign PDL1 benchmark: Protenix-basic pass rate > 1%
- [ ] RFAA 7v11 benchmark: at least 1 backbone PDB produced
- [ ] Peer review: second person confirms existing campaigns unaffected
- [ ] `git merge feature/rfaa-pxdesign-integration --no-ff`
