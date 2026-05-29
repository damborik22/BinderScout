# Cross-Engine Refold + iPSAE Merge — Spark-Local Evaluation Recipe

**When to read this:** at the start of campaign Phase 3' — when enough tarballs have returned to RESULTS/ to constitute a pool worth merging. Typically when at least 3 design tools have completed and the orchestrator is starting to consolidate into a top-N for wet-lab handoff.

**What this is:** the orchestrator-side recipe for running cross-engine refolding locally on Spark, computing iPSAE under the uniform 10 Å PAE cutoff (DunbrackLab 2025 `d0_res` variant), merging into a unified `summary.csv`, and ranking.

**What this is NOT:** the implementation. The BindMaster `Evaluator/` package already implements these steps. This file is the orchestrator's mental model — what happens, why, and how to invoke it without surprises.

---

## 1. Mental model

Three refolders run as **library code, not jobs**, all locally on Spark:

| Refolder | Env | Status | Notes |
|---|---|---|---|
| Boltz-2 | `Mosaic/.venv` | stable, default | Native [binder\|target] ordering, pLDDT [0,1] |
| Protenix | `bindmaster_pxdesign` | Part J, live; optional 24 GB-friendly fallback | Target-first PAE → transposed; pLDDT [0,1] |
| AlphaFold 3 (v3.0.2) | `binder-eval-af3` | Part K, live; canonical 2nd engine | Cross-platform (x86_64 + aarch64) but needs >100 GB unified or device memory — Spark / H200 / GH200 fit; consumer 24 GB GPUs do not. Target-first PAE → transposed; pLDDT [0,100] → rescaled to [0,1] |

Each refolder takes a (binder sequence + target structure + chain assignment) tuple and produces a (`.cif` structure + PAE matrix `.npz`). The evaluator then computes iPSAE on each PAE matrix and merges results.

Because all three envs co-exist on Spark, the evaluation pipeline is a single Python orchestration:

```
for design in pool:
    boltz_out  = refold_boltz2(design)        # Mosaic venv
    protenix_out = refold_protenix(design)    # bindmaster_pxdesign venv (Part J)
    af3_out    = refold_af3(design)            # binder-eval-af3 venv (Part K, any host with >100 GB unified/device memory)

    boltz_ipsae   = compute_ipsae(boltz_out.pae, cutoff=10.0, d0='d0_res')
    protenix_ipsae = compute_ipsae(protenix_out.pae_transposed, cutoff=10.0, d0='d0_res')
    af3_ipsae     = compute_ipsae(af3_out.pae_transposed, cutoff=10.0, d0='d0_res')

    merged[design] = {
        'boltz_*': boltz_ipsae | boltz_out.confidence,
        'protenix_*': protenix_ipsae | protenix_out.confidence,
        'af3_*': af3_ipsae | af3_out.confidence,
        'agreement_count': sum(e.ipsae_min > 0.61 for e in [boltz, protenix, af3] if e),
        'ipsae_min_avg': mean(e.ipsae_min for e in [boltz, protenix, af3] if e),
    }
```

Conceptually three sequential refold passes per design, but in practice they're batched by tool and pipelined on the single Spark GPU.

---

## 2. Pre-flight before launching evaluation

Before running, verify:

1. **All target tarballs are in `RESULTS/`** and untarred (or stage them to `~/eval_workdir/<TARGET>/`).
2. **Each tool's source-of-truth CSV is parseable.** Specifically:
   - BindCraft: `final_design_stats.csv` (NOT `Accepted/` directory listing — see worker tools/bindcraft.md)
   - BoltzGen: `final_designs_metrics_<budget>.csv` or `all_designs_metrics.csv`
   - Mosaic: `designs.csv` (handle both 11-col and 13-col formats; check for `is_top=1` filter)
   - Protein-Hunter: `summary_high_iptm.csv` or `summary_all_runs.csv`
   - PXDesign: `design_outputs/<task_name>/summary.csv`
   - Proteina-Complexa: analysis CSVs in the `analyze/` output dir
   - RFD3 + MPNN: `out_dir/*.cif.gz` paired with MPNN `.fa` (post-process to pick best-of-N per backbone, strip target prefix)
3. **Boltz-2 cache** at `~/.boltz/` populated (the `mols/` directory with ~45k CCD `.pkl` files in particular). If missing, bootstrap:
   ```python
   from boltz.main import download_boltz2
   from pathlib import Path
   download_boltz2(cache=Path.home()/'.boltz')  # positional Path arg, not str
   ```
4. **GPU memory available** for the refold pass. Cross-engine refold can stack peak memory if not pipelined carefully. The evaluator's default sequential mode is safe on a single H200 / GH200.
5. **`expandable_segments:True`** if running on Ampere-class card with mixed batch sizes:
   ```bash
   export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
   ```
6. **Protenix CCD cache** location set if not default:
   ```bash
   export PROTENIX_DATA_ROOT_DIR=/path/to/ccd_cache
   ```
7. **AF3 env vars** for `binder-eval-af3` if aarch64 is available (database paths, model paths). See `Evaluator/docs/pipeline_reference.md`.

If AF3 isn't available (x86 environments), proceed with 2-engine evaluation — `agreement_count` denominator becomes 2 instead of 3. The orchestrator must note this in the final ranking (a design with `agreement_count = 2` out of 2 engines is *not* the same signal as `2 out of 3`).

---

## 3. The iPSAE computation

iPSAE is the inter-chain Predicted Aligned Error score per DunbrackLab 2025 (`d0_res` variant). Two directional scores per refolded complex:

- **`bt_ipsae`** — for each binder residue `i`, take the mean over all target residues `j` of `1/(1 + (PAE_ij / d0_res(i))²)` (where `d0_res(i)` depends on the chain-i length post-cutoff), then take the max over `i`. Captures "best-positioned binder residue's view of the target."
- **`tb_ipsae`** — symmetric, max over target residue `j`'s mean over binder residues `i`.
- **`ipsae_min = min(bt_ipsae, tb_ipsae)`** — the "weakest link" of the two directional scores. Per Overath 2025's 3,766-binder meta-analysis, this is the single best in-silico predictor of experimental binding affinity.

**Uniform 10 Å PAE cutoff** across all engines. PAE values above 10 Å are clamped (or contribute negligibly given the formula's `1/(1 + (PAE/d0)²)` falloff). This unification matters because each engine has its own PAE distribution; the cutoff normalizes.

**Critical: native vs. transposed PAE ordering.**

- Boltz-2 emits PAE in `[binder | target]` chain ordering natively. Used as-is.
- Protenix and AF3 emit PAE in `[target | binder]` ordering (target chain first). The evaluator **transposes** these into `[binder | target]` before computing iPSAE. Manual readers of raw Protenix/AF3 output must apply this transpose themselves.

**pLDDT scale unification:**

- Boltz-2 native: `[0, 1]`
- Protenix native: `[0, 1]`
- AF3 native: `[0, 100]` — evaluator **divides by 100** to match.

After unification, all three engines' confidence numbers are on the same scale and can be compared cell-by-cell across columns.

---

## 4. agreement_count and the four-tier classification

Per design, after all available refolders run:

```python
ipsae_threshold = 0.61   # the agreement threshold
agreement_count = sum(
    1 for engine in available_engines
    if engine.ipsae_min > ipsae_threshold
)
```

**Quality tiers** (applied to the best of {boltz_ipsae_min, protenix_ipsae_min, af3_ipsae_min}, *or* a campaign-defined function — typically `mean` or `min`; orchestrator decides):

| Tier | `ipsae_min` |
|---|---|
| **High** | > 0.80 |
| **Medium** | 0.61–0.80 |
| **Low** | 0.40–0.61 |
| **Reject** | ≤ 0.40 |

Threshold 0.61 is the per-engine "pass" cutoff (and the same number that goes into `agreement_count`).

**The orchestrator's ranking:**

1. Primary sort: `agreement_count` **descending** (3 > 2 > 1 > 0)
2. Secondary sort: chosen ipsae_min aggregator **descending** (typically `mean(ipsae_min across engines)` or `min(ipsae_min across engines)`; campaign choice)

This produces a single ranked CSV that respects "engine disagreement is signal" while still being deterministic.

---

## 5. Output schema (`summary.csv`)

The merged file has one row per design and these columns (subset shown):

```
design_id, source_tool, source_machine, binder_seq, binder_length, target,

# Native per-tool metrics (preserved alongside cross-method)
mosaic_ranking_loss, mosaic_iptm, ...
boltz_design_iptm, boltz_design_plddt, ...    # design-time Boltz-2 confidence (Mosaic / BoltzGen / PH)
bindcraft_iptm, bindcraft_iPAE, bindcraft_dG, bindcraft_ShapeComplementarity, ...
rfd3_n_clashing, rfd3_n_chainbreaks, ...
pxdesign_composite, pxdesign_af2ig_iptm, ...
proteina_reward_af2, proteina_reward_rf3, ...

# Evaluator outputs (cross-method comparator)
boltz_bt_ipsae, boltz_tb_ipsae, boltz_ipsae_min, boltz_iptm_refold, boltz_plddt_complex, ...
protenix_bt_ipsae, protenix_tb_ipsae, protenix_ipsae_min, protenix_iptm_refold, ...
af3_bt_ipsae, af3_tb_ipsae, af3_ipsae_min, af3_iptm_refold, ...   # if aarch64

# Cross-method rollup
agreement_count, ipsae_min_mean, ipsae_min_min, tier   # tier ∈ {High, Medium, Low, Reject}
```

**Column prefixing is load-bearing.** `boltz_*`, `protenix_*`, `af3_*` distinguish refolder-source. `mosaic_*`, `bindcraft_*`, `rfd3_*`, etc. distinguish design-tool-source. Don't collapse these — the orchestrator needs the source labels to interpret signal correctly (e.g., `boltz_ipsae_min` on a Mosaic-designed sequence has Boltz-2 self-judging bias; same column on a BindCraft-designed sequence is clean).

See `tools/README.md` cross-method bias matrix for which combinations are correlated.

---

## 6. Invoking the evaluator

The BindMaster `Evaluator/` package provides the entry points. Pseudocode (actual CLI in the repo):

```bash
# Stage all returned tarballs to local scratch
mkdir -p ~/eval_workdir/<TARGET>
cd ~/eval_workdir/<TARGET>
for tar in /path/to/RESULTS/<TARGET>_*.tar.gz; do
    tar xf "$tar"
done

# Activate the evaluator env (Mosaic venv hosts the Boltz-2 refolder and the merge code)
source ~/dev/BindMaster/Mosaic/.venv/bin/activate

# Run cross-engine evaluation
python -m bindmaster.evaluator \
    --target-cif /path/to/<TARGET>/PDB/target.cif \
    --inputs ~/eval_workdir/<TARGET>/ \
    --engines boltz2,protenix,af3 \
    --pae-cutoff 10.0 \
    --d0-variant d0_res \
    --output ~/eval_workdir/<TARGET>/summary.csv

# If aarch64 isn't available, drop af3:
#   --engines boltz2,protenix
```

The evaluator handles env switching (it shells out to the Protenix and AF3 envs as subprocesses), PAE transposition, pLDDT rescaling, iPSAE computation, and the merge. Output is the canonical `summary.csv`.

Wall time on Spark (rough budget):
- Boltz-2 refold: ~30-60 s per design
- Protenix refold: ~45-90 s per design (base v1; v2 slower; mini variants faster)
- AF3 refold: ~3-5 min per design (slowest; the inference-time scaling is significant)

For a 500-design pool, full 3-engine evaluation is ~30 GPU-hours. For a 5000-design pool, plan a multi-day run with kill checkpoints.

---

## 7. Common failure modes during evaluation

**Boltz-2 cache missing or stale.**
Symptom: `ValueError: CCD component ALA not found!` at startup.
Fix: bootstrap `~/.boltz/` per §2; verify `mols/ALA.pkl` exists.

**Protenix CUDA arch patches reverted.**
Symptom: PTX compilation errors on Blackwell sm_120.
Fix: rerun `install/install.sh --pxdesign` to reapply post-install patches (Protenix CUDA arch, `pxdbench` NumpyEncoder, `configs_infer.py` num_workers).

**PAE matrix shape mismatch on Protenix output.**
Symptom: `IndexError` or wrong-direction iPSAE values that don't make sense.
Cause: forgot to transpose target-first → `[binder|target]`. Should be handled by the evaluator automatically — if reading raw Protenix output, transpose first.

**pLDDT values >1 on AF3 outputs in the merged CSV.**
Symptom: tier classification looks wrong, pLDDT cells in the 70-99 range instead of 0.7-0.99.
Cause: AF3 [0,100] not rescaled. Should be handled by the evaluator automatically; manual readers must `/100`.

**agreement_count = 2 mixed with 3-engine designs in the same ranking.**
Cause: AF3 ran on some designs but not all (e.g. aarch64 went down mid-run).
Fix: rerun missing AF3 refolds, or annotate the ranking with `available_engines` and treat denominators correctly.

**Append-mode CSV with duplicate `run_id`.**
Symptom: same design appears twice in `summary.csv`.
Cause: evaluator was rerun after partial failure; the second run appended instead of replacing.
Fix: dedupe by `run_id` keeping the later row, or rerun with `--overwrite` if the evaluator supports it.

**Mosaic mixed 11/13-column `designs.csv`.**
Symptom: rows misalign in the parser; some designs have target_sequence in the wrong column.
Cause: documented in `Evaluator/docs/pipeline_reference.md`. Multiple workers wrote concurrently with different schema versions.
Fix: the evaluator's Mosaic parser auto-detects column count per row.

**`REPLACE_ME` in target_sequence column.**
Symptom: evaluator silently skips rows.
Cause: Mosaic run script wasn't fully configured before launch.
Fix: re-run the Mosaic worker with target_sequence properly populated, or post-edit the CSV.

---

## 8. After the merge — what the orchestrator does with `summary.csv`

The merged file is the input to the campaign's final selection. Typical orchestrator workflow:

1. **Top-tier sanity check.** Pull the top 30 by ranking. Inspect by hand — do they look diverse (binder length range, secondary-structure mix, hotspot coverage)? Are any obviously pathological (all-helix, all-ALA, RMSD outliers)?
2. **Tool diversity audit.** What fraction of the top 30 come from each design tool? If all 30 are BindCraft, the pool is under-explored — note this and consider expanding before wet-lab handoff.
3. **Bias check via the matrix.** For each top design, look at which refolders it agrees with. A BoltzGen design with only `boltz_ipsae_min > 0.61` and Protenix/AF3 disagreeing is a same-model self-judging artifact; tier-down or drop.
4. **Length bias correction.** Per CLAUDE.md `Critical domain facts`, `ipsae_min` correlates negatively with binder length (r ≈ -0.78). If the top-30 is dominated by short binders, the orchestrator may want to rank within length bands rather than globally.
5. **Final selection for wet-lab.** Hand-pick the top 20-30 with the user, balancing rank, diversity, and any campaign-specific priorities (e.g., specific hotspot coverage, preferred fold class).
6. **Archive the ranking.** `summary.csv` + the selection list go to RESULTS/ alongside the source tarballs.

The orchestrator does not silently apply a threshold and ship — selection is always confirmed with the user. The evaluator produces the ranking; the user picks.

---

## 9. References

- `tools/` — engine-level reference per refold engine (`boltz2.md`, `protenix.md`, `alphafold3.md`) and per design tool
- `tools/README.md` — cross-method bias matrix (which design tools have correlated bias with which refolders)
- `learnings.md` §5 — "Scoring engines are not comparable" and the cross-engine refold rationale
- `Evaluator/docs/pipeline_reference.md` (BindMaster repo) — implementation reference for the evaluator package
- `CLAUDE.md` `Evaluation metrics` section — iPSAE formula and 4-tier definitions, ranking rule
- DunbrackLab 2025 iPSAE paper — `d0_res` variant derivation
- Overath et al. 2025 — 3,766-binder meta-analysis identifying `ipsae_min` as the strongest in-silico predictor of experimental binding
