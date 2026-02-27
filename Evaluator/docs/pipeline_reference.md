# BindMaster Repo — Project Memory

## Key Reference Files (in Claude memory/)
- `project_context.md` — Full project context: all tools, pipeline, architecture, known issues
- `metrics_reference.md` — Metric formulas, scales, thresholds, ranking weights, gotchas
- `native_comparison_findings.md` — Native vs pipeline correlations + Mosaic CSV mixed-format bug

---

## Repo Structure
```
/home/bindmaster5/Documents/BindMaster repo/
├── BindCraft/          # AF2 + MPNN + PyRosetta binder design
├── BoltzGen/           # Boltz-2 diffusion-based binder design
├── Mosaic/             # Boltz2-gradient hallucination (NO internal AF2 cross-val)
├── Protenix/           # ByteDance AF3-class model — prediction only, not yet integrated
├── binder_comparison/  # Our comparison pipeline (v0.1.0) — IMPLEMENTED
├── memory/             # Planning docs and references
└── pyproject.toml
```

## Conda Environments
| Env | Used for | Status |
|-----|----------|--------|
| `bindcraft_pr` | AF2 refolding + binder_comparison pipeline | **VERIFIED WORKING** — binder-compare installed |
| `mosaic` | (empty shell — do not use for refolding) | **Broken — empty** |
| `bg` | BoltzGen design (Python 3.12) | |
| `protenix` | Protenix structure prediction (Python 3.10) | Installed, not integrated |
| `bindcraft` | BindCraft design | |
| `colabfold` | ColabFold MSA | |

## uv Virtual Environment (for Boltz2/Mosaic)
- **Path**: `/home/bindmaster5/BindMaster/mosaic/.venv`
- **Python**: 3.12, numpy 2.1.0, jax 0.9.0.1, equinox, mosaic package
- **binder-compare installed**: YES — `/home/bindmaster5/BindMaster/mosaic/.venv/bin/binder-compare`
- **Use for**: `refold-boltz2` step (NOT `conda run -n mosaic` which is empty)

## Quick CLI Reference
```bash
# Step 1 (any env — binder-compare installed in bindcraft_pr)
conda run -n bindcraft_pr binder-compare extract --bindcraft DIR --boltzgen DIR --mosaic DIR -o seqs.fasta

# Step 2 — Boltz2 (use uv venv, NOT conda mosaic env which is empty)
/home/bindmaster5/BindMaster/mosaic/.venv/bin/binder-compare refold-boltz2 \
    --sequences seqs.fasta --target-seq SEQ -o boltz2.csv

# Step 3 — AF2
conda run -n bindcraft_pr binder-compare refold-af2 --sequences seqs.fasta --target-pdb PDB -o af2.csv

# Step 4 — Report
conda run -n bindcraft_pr binder-compare report \
    --boltz2-results boltz2.csv --af2-results af2.csv --sequences seqs.fasta -o ./report

# Full orchestrator (from bindcraft_pr env, use --boltz2-python to point at uv venv)
conda run -n bindcraft_pr binder-compare run \
    --bindcraft DIR --boltzgen DIR --mosaic DIR \
    --target-seq SEQ --target-pdb PDB \
    --boltz2-python /home/bindmaster5/BindMaster/mosaic/.venv/bin/python \
    -o ./comparison_report
```

## Critical Facts
- refold_Version5 (Boltz2): PAE ordering [binder|target], pLDDT [0,1], writes CSV to CWD
- refold_Version6 (AF2): PAE ordering [target|binder], all cols prefixed `af2_`, CSV to configurable path
- AF2 pLDDT scale: **[0,1] CONFIRMED** — ColabDesign get_plddt() sums bin_centers in [0,1]
- refold_Version6 **NOW SAVES PAE files** (added af2_pae_file col) → AF2 ipSAE computed automatically
- refold_Version6 AF2_DATA_DIR = `/home/bindmaster5/BindMaster/bindcraft-tools/af2_params` (NOT /home/.../bindcraft-tools/af2_params — note the BindMaster/ in path!)
- Mosaic designs with Boltz2 only; AF2 cross-val is added solely by our pipeline
- **ipsae_min direction: HIGHER IS BETTER** — it's a TM-score-like metric (Dunbrack 2025 formula); loss=-ipsae_min confirms this
- LOWER_IS_BETTER = {ipae, pae_bt, pae_tb, pae_bb} — raw PAE in Å; lower = less error
- ipsae_min is primary ranking metric (weight 4.0); iptm is gameable by AF2-designed sequences
- Boltz2 appends to refold_designs.csv if rerun — always check for duplicate run_ids and clean
- AF2 opens CSV in append mode — check for duplicates if rerun after partial failure
- **AF2 multimer vs Boltz2 can strongly disagree** for short binders (60aa): Boltz2 may score high while AF2 multimer scores low. This is meaningful — the composite score reflects the disagreement.

## Verified Pipeline Run (CALCA target, 12 sequences, 2026-02-26)
- Target: CALCA/P01258, PDB: RESULTS/P01258_V2.pdb (116 residues in PDB, 141aa sequence)
- Test FASTA: RESULTS/sequences_test10.fasta (12 seqs: 3×bindcraft, 3×boltzgen, 3×mosaic, 3×pxdesign)
- Boltz2 JAX first-run JIT compilation: ~6 min; per-sequence: ~2-3 min (includes ColabFold MSA call)
- AF2 model loading time: ~2 min; per-sequence: ~30-60s
- Top results: PXDesign 120aa sequences rank best (both models agree); Mosaic 60aa rank high on Boltz2 only

## Full Run Results (CALCA target, 216 sequences, 2026-02-27)
- Location: `RESULTS/full_run/` — report at `RESULTS/full_run/report/report.html`
- native_vs_pipeline comparison: `RESULTS/full_run/report/native_vs_pipeline.html`
- Counts: BindCraft=6, BoltzGen=50, Mosaic=60, PXDesign=100
- Pass rates (ipsae_min > 0.61): PXDesign 34%, Mosaic 27%, BindCraft 33%, BoltzGen 2%
- BoltzGen very poor: only 1/50 pass — sequences designed for Boltz2 but don't cross-validate

## Mosaic CSV Parsing Bug — CRITICAL
See `native_comparison_findings.md` for full details. Short version:
- CALCA designs.csv mixes two column formats (old 11-col / new 13-col with target_seq + binder_length inserted)
- `_read_mosaic_csv` reads with widest header but misaligns columns for bff5e244 and c6687481 workers
- Result: `iptm` column reads **binder_length** (80 or 160) for 40/60 sequences — NOT actual iptm
- The r=-0.710 "negative correlation" between Mosaic native iptm and pipeline ipsae_min is a **parsing artifact**
- True correlation (worker 5e99e151 only, correctly parsed): r(native_ipsae_min, pipeline_ipsae_min) = **+0.825**
- Real finding: **binder length is the main driver** — longer binders score lower on ipsae_min (r=-0.78)

## Native vs Pipeline Correlations (2026-02-27)
See `native_comparison_findings.md` for full table. Key results:
- BindCraft: r(native_i_pTM, pipeline_ipTM) = +0.72 — strong agreement across models
- BoltzGen: r(native_design_iptm, pipeline_ipsae_min) = +0.59 — moderate, consistent
- Mosaic: r(native_ipsae_min, pipeline_ipsae_min) = +0.83 (n=10, real data only)
- PXDesign: r(ptx_iptm, pipeline_ipsae_min) = +0.39 — moderate (Protenix vs Boltz2 model gap)
