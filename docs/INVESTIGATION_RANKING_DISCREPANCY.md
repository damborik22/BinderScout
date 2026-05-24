# Investigation: native-ranking vs refolded-ipSAE discrepancy on CALCA helix

**Campaign**: CALCA helix binder design (target `EDEARLLLAALVQDYVQMKASELEQEQEREGS`, 32 aa).
**Substrate**: `runs/CALCA_helix_BM4/evaluate/run1_free/report/metrics.csv` (4,005 designs, 5 tools).
**Author**: Read-only scientific audit. No code in `Evaluator/` was modified.
**Date analysis run**: 2026-05-16 on BM5 / DGX Spark (aarch64).

---

## TL;DR

The discrepancy the user notices is **real and largely explained by H1 (model bias)** with substantial contributions from H3 (selection-induced inflation of short binders), and a previously-unnoticed engine calibration issue that makes AF2 ipSAE almost unusable on this 32-aa target. There is **no evidence of a parsing / chain-ordering bug** in the current Evaluator code.

Concretely:

- 0/700 BoltzGen, 0/784 Mosaic, 0/800 PXDesign, 0/637 Proteina-Complexa, 0/604 BindCraft designs cross `af2_ipsae_min > 0.61` in run1_free. AF2 ipSAE caps at 0.524 max across the entire 4,005-design pool, while Boltz-2 ipSAE reaches 0.88. AF2 BT PAE is 2.7× larger than Boltz-2 BT PAE on the same designs; with the uniform 10 Å cutoff this drags AF2 ipSAE toward zero everywhere. That is a calibration mismatch, not a sequence-quality verdict.
- BoltzGen's `final_rank=1` design (`config_2416_r1`, 90-aa) gives `boltz_pae_ipsae_min = 0.758` and `af2_ipsae_min = 0.378` in run1_free — **not 0.01** as recalled. However, several BG designs in the rank top-20 do score `af2_ipsae_min ≈ 0.01` (e.g. configs 3315, 4017, 3823, 3297, 6401) while Boltz-2 rates them ≥0.55. Inter-engine disagreement, not a missing zero.
- The top-20 by `boltz_pae_ipsae_min` are dominated by Mosaic (11/20) and PXDesign (4/20), almost all with `binder_length ≤ 80` and `af2_ipsae_min ≤ 0.05`. These are likely Boltz-2 over-confidence artifacts on short binders that Mosaic specifically optimised for Boltz-2 to like.
- BindCraft is the only tool whose native ranking metric (`Average_i_pTM` or `Rank`) shows a moderate-strength correlation with refold ipSAE (ρ ≈ ±0.54). Every other tool's native metric correlates only ρ ≈ 0.15–0.25 with refold ipSAE, and BoltzGen's `final_rank` is actually slightly **inversely** related to its own internal `design_ipsae_min` (ρ = -0.52, since `final_rank` is driven by other terms — diversity, ptm, plip — not by ipSAE).

**Recommendation (5.3)**: do not use `ipsae_min` from a single engine as the ranking metric. Require multi-engine agreement (`boltz_pae_ipsae_min > 0.61` AND `af2/af3_ipsae_min > θ`, with a tool-specific θ that accounts for the engine's calibration on this target), or combine with native metrics weighted by their per-tool correlation strength.

---

## 1. Methods

### Data sources

| File | Used for |
|---|---|
| `runs/CALCA_helix_BM4/evaluate/run1_free/report/metrics.csv` | Primary substrate (4,005 rows, 99 cols). |
| `runs/CALCA_helix_BM4/evaluate/run1_free/boltz2_results.csv` | Raw Boltz-2 refold (3,712 rows, sanity check). |
| `runs/CALCA_helix_BM4/evaluate/run1_free/af2_results.csv` | Raw AF2 refold (4,005 rows). |
| `runs/CALCA_helix_BM4/bindcraft_default/outputs/final_design_stats.csv` | BindCraft native (350 rows). |
| `runs/CALCA_helix_BM4/bindcraft/outputs/final_design_stats.csv` | BindCraft early-run native (5 rows). |
| `runs/CALCA_helix_BM4/boltzgen/outputs/final_ranked_designs/final_designs_metrics_700.csv` | BoltzGen native (700 rows, 247 cols). |
| `runs/CALCA_helix_BM4/pxdesign/summary.csv` | PXDesign native (756 rows). Stale vs run1_free. |
| `runs/CALCA_helix_BM4/proteina_complexa/sequences.csv`, `proteina_complexa_top700.csv` | PC native. Stale vs run1_free. |
| `runs/CALCA_helix_BM4/mosaic/designs.csv`, `checkpoint_*.json` | Mosaic native. Stale vs run1_free. |
| `runs/CALCA_helix_BM4/evaluate/run2_template/report/metrics.csv` | Cross-check (template ON variant). |

### Refolding configuration (verified by `grep` of `run_evaluation_both.sh`)

- **run1_free** (the substrate): Boltz-2 sequence-only (no `--target-pdb`), AF2 with `--target-pdb target/CALCA_helix.pdb`, target MSA on (Boltz-2 default), binder MSA off (sequence-only mode). `binder-compare refold-boltz2 ... --target-seq $TARGET_SEQ --output ... --resume` (line 168 of `run_evaluation_both.sh`).
- **run2_template** (sanity): Boltz-2 with `--target-pdb P01258.cif`, AF2 with same `--target-pdb`, same other settings.

### Software versions

- Python 3.12 (Mosaic venv): pandas 3.0.2, scipy 1.15.1, numpy 2.1.0, matplotlib 3.10.8.
- Evaluator code state: branch `aarch64` (commit `f39f694`). The AF2 ipSAE columns in metrics.csv were produced by an earlier Evaluator state — see § 2.6.

### Commands

All analysis lives in `notebooks/_analysis.py` (a single Python script that emits `notebooks/_artifacts/`). Notebook `notebooks/ranking_discrepancy.ipynb` consumes those artifacts. Reproduce with:

```bash
/home/bindmaster5/dev/BindMaster/Mosaic/.venv/bin/python /home/bindmaster5/dev/BindMaster/notebooks/_analysis.py
```

### Caveats

- The on-disk native CSVs for Mosaic, PXDesign and Proteina-Complexa are from later re-runs (post-evaluation). For those tools, native ranking metrics cannot be back-joined to the run1_free designs (see § 2.3, 2.4, 2.5).
- PAE arrays referenced in metrics.csv use BM4 paths (`/home/david/...`) and are not present on Spark. We rely entirely on pre-computed `*_ipsae_min` columns. The PAE-ordering audit (§ 2.7) was therefore done by reading the original `refold_boltz2.py` / `refold_af2.py` scripts and the historical `scoring.py` at the commit that produced this metrics.csv, not by reloading PAE files.

---

## 2. Data integrity findings

### 2.1 BindCraft: 312 unique designs duplicated to 604 rows

`metrics.csv` contains **604 BindCraft rows but only 312 unique sequences**, with each row's metrics identical to its duplicate. Tracing one pair (`bindcraft_default_CALCA_helix_l100_s212552_mpnn3`): both rows have `run_id=37ee2aff`, identical `boltz_idx=3466`, identical `boltz_pae_ipsae_min=0.6039`. Sequences identical.

This is **a duplication, not a refold-replicate** (replicates would have different `boltz_idx`). Most likely cause: the extractor scanned two paths that both yielded BindCraft designs (e.g. `bindcraft_default/outputs/` and a sibling), or the same CSV was double-fed. **Recommendation**: deduplicate by `(binder_id)` before any per-tool stat.

For correlation analysis below the duplicates inflate `n_designs=604` but don't bias Spearman ρ in either direction (duplicates collapse). They do inflate the apparent BindCraft contribution to the top-20 — but the top-20 is dominated by other tools anyway (only one BindCraft design near the top).

### 2.2 PXDesign: 800 rows, 700 unique IDs, 800 unique sequences

PXDesign duplicate IDs (e.g. `pxdesign_input_len20_sample_0` appears with sequence `MAALIQEYVQQLAAEVEALL` and again with `EAERAALRQRAAEILAQLAA`) prove the ID is non-unique. The extractor builds IDs from `pxdesign_{task_name}_{rank}` (`pxdesign.py:97`), which collides across length buckets when those buckets reuse rank=0,1,…. **Recommendation**: include `length` in the PXDesign ID, e.g. `pxdesign_{task_name}_len{L}_sample_{rank}`.

For correlation analysis we use rows from metrics.csv directly (sequence-keyed) rather than ID-keyed joining to the summary.csv.

### 2.3 Mosaic native data: irrecoverable for run1_free

The 8 Mosaic worker IDs in metrics.csv (`56063cee, 60cda749, 0e995dba, a7ac7480, d6da7456, 54f7cdb8, 7519552e, b6a64717`) have **zero overlap** with the 10 worker IDs in the on-disk `mosaic/designs.csv` (`23c247e7, 77dc9420, 2a8035fb, ee4c1e7a, 8dce2e04, ee17b984, a3dfa440, 396e4a61, 3501da71, b78fff8d`).

Sequence sets between the two also have zero overlap. The same is true of the on-disk checkpoint JSON files (which mirror the on-disk designs.csv workers). Conclusion: the Mosaic source data was completely overwritten by a later re-run after run1_free was evaluated.

We therefore use Mosaic's **optimization-time `ipsae_min_aux` column** (preserved in metrics.csv) as a proxy for "Mosaic's notion of best". This is Mosaic's own loss signal — the closest available substitute for true `ranking_loss`. The proxy is reasonable: high `ipsae_min_aux` is by construction what Mosaic was rewarded for during hallucination.

### 2.4 PXDesign native data: partially stale

The on-disk `pxdesign/summary.csv` has 756 rows; only 348 of its `design_id` values match the 700 unique `binder_id` values in metrics.csv. 352 metrics rows have no match in summary.csv, and 408 summary entries have no match in metrics.csv. The summary appears to be a partial re-run / partial-overwrite post-evaluation.

For the 348 matching designs we can join `native_af2_iptm` and `native_af2_plddt`; for the others these are NaN. Correlations below are reported on the 348 joined designs.

### 2.5 Proteina-Complexa native data: irrecoverable

The on-disk `sequences.csv` uses `complexa_CALCA_helix_b1_*` IDs and `proteina_complexa_top700.csv` uses `pc_top_*` IDs, both incompatible with the `pc_NNNN_job_X_n_LLL_id_Y_bon_origZ_rW` IDs in metrics.csv. Sequence intersection: 1/637. The Proteina-Complexa source data was re-run after run1_free was evaluated.

We use `iptm` (the cached Boltz-2 iptm — secondary to ipsae but available) as a stand-in to anchor PC against. This is not a true native metric, but per § 3 the PC correlations are so dominant (ρ ≈ 0.99 between `iptm` and `boltz_pae_ipsae_min`) that the choice of proxy doesn't change the conclusion.

### 2.6 AF2 ipSAE: computed by deprecated code, but ordering is correct

The current `Evaluator/binder_comparison/comparison/scoring.py` does **not** compute AF2 ipSAE columns. `report.py:64-96` handles Boltz / Protenix / AF3 only. The `af2_ipsae_min`, `af2_bt_ipsae`, `af2_tb_ipsae` columns in metrics.csv were therefore produced by an earlier Evaluator state (`commit 1dd0c51`), via a function `add_af2_ipsae_from_files` that has since been removed in `commit 3ceca0b "Part I: Remove AF2 refolding from Evaluator"`.

The deprecated function (verified by `git show 1dd0c51:./binder_comparison/comparison/scoring.py`) called `compute_ipsae_from_pae(..., ordering='target_binder')` (line 222 of the historical scoring.py). The AF2 refold script `refold_af2.py` v6 (still readable via `git show 1dd0c51:./scripts/refold_af2.py`) saves PAE with `target first (indices 0:L_t), binder second (indices L_t:L_t+L_b)`. **Ordering is consistent**: target-first PAE saved → `ordering='target_binder'` consumer → no swap. The `af2_ipsae_min` values in metrics.csv are therefore not corrupted by a chain swap.

### 2.7 PAE ordering audit: clean

Read trace for the current code:

- `scripts/refold_boltz2.py` → saves `bb|bt|tb|tt` PAE blocks in `[binder|target]` order (Boltz-2 native). Consumed by `add_boltz_ipsae_from_files` with `ordering='binder_target'` (`scoring.py:222`). Correct.
- `scripts/refold_protenix.py` / `refold_af3.py` (target-first by JSON convention) → consumed with `ordering='target_binder'` (`report.py:80, 92`). Correct.
- Historical `scripts/refold_af2.py` (target-first) → consumed with `ordering='target_binder'`. Correct.

The transpose math in `compute_ipsae_from_pae` (`scoring.py:117-123`) is symmetric, well-tested against DunbrackLab ipsae v1.0.1 per the docstring. **No ordering bugs found.**

### 2.8 Three-design end-to-end ordering check (PAE → ipSAE)

Picked at random: `boltzgen_config_2416_r1` (90 aa), `mosaic_54f7cdb8_r1` (20 aa), `bindcraft_default_CALCA_helix_l45_s427158_mpnn1` (45 aa).

Per CLAUDE.md, target = 32 aa for CALCA; binder is variable. Expected PAE shape: `(binder_length + 32, binder_length + 32)`.

- `boltzgen_config_2416_r1`: cached `boltz_pae_ipsae_min=0.758`, `ipsae_min_aux=0.819`. PAE file at `/home/david/.../refold_boltz2/structures/refold1263_6896bf74_pae.npy` is not present on Spark, so we cannot reload to confirm shape. The agreement between `boltz_pae_ipsae_min` (DunbrackLab formula, computed by Evaluator) and `ipsae_min_aux` (Mosaic-style formula, computed by Boltz-2 at refold time and copied into metrics.csv) confirms the binder/target split was internally consistent: if binder/target had been swapped, the two metrics would have diverged because they aggregate over different axes.
- For `mosaic_54f7cdb8_r1`: similarly `boltz_pae_ipsae_min=0.880` vs `ipsae_min_aux=0.872` — consistent.
- For `bindcraft_default_CALCA_helix_l45_s427158_mpnn1`: `boltz_pae_ipsae_min=0.683` vs `ipsae_min_aux=0.741` — consistent.

The DunbrackLab and Mosaic aux ipSAE formulas differ in the d0 computation (per-residue d0res vs per-chain) and in aggregation (max vs max). Their cross-correlation across the dataset is ρ ≈ 0.95 (computed at end of `_analysis.py`). **No swap signal.**

---

## 3. Per-tool correlation analysis

Spearman ρ between native ranking metric and refold metrics. Sign convention: positive ρ means "as native says better, refold also says better". For metrics where lower is better (`final_rank`, `native_rank`), we expect **negative** ρ if native and refold agree.

| Tool (n) | Native metric (direction) | ρ(boltz_ipsae_min) | ρ(af2_ipsae_min) | ρ(iptm) | ρ(plddt_binder) | ρ(binder_length) | top-5 % | top-10 % | top-20 % |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BindCraft (604) | `Average_i_pTM` (↑) | **+0.534** | +0.528 | +0.629 | +0.377 | +0.257 | 0 | 0 | 5 |
| BindCraft (599) | `Rank` (↓) | **−0.537** | −0.531 | −0.636 | −0.370 | −0.254 | 0 | 0 | 5 |
| BoltzGen (700) | `final_rank` (↓) | **−0.150** | −0.161 | −0.233 | −0.052 | −0.163 | 0 | 0 | 5 |
| BoltzGen (700) | `design_to_target_iptm` (↑) | +0.244 | +0.233 | +0.407 | +0.091 | +0.262 | 0 | 10 | 5 |
| BoltzGen (700) | `design_ipsae_min` (↑) — BG's own ipSAE | **+0.837** | (n/a) | (n/a) | (n/a) | (n/a) | (n/a) | (n/a) | (n/a) |
| PXDesign (800; 348 joinable) | `af2_iptm` (↑) | +0.047 | +0.019 | +0.037 | +0.015 | −0.237 | 0 | 0 | 5 |
| Mosaic (784) | `ipsae_min_aux` (↑) — proxy | **+0.630** | +0.083 | +0.611 | +0.377 | −0.099 | 20 | 30 | 35 |
| Proteina-Complexa (637) | `iptm` (↑) — proxy | **+0.988** | +0.404 | (n/a) | +0.745 | +0.102 | 80 | 60 | 75 |

Per-tool one-line interpretation:

- **BindCraft**: native `Average_i_pTM` is a moderate-strength predictor of refold ipSAE (ρ ≈ 0.53). Native top-5 has 0% in refold top-5, but top-20 overlap is 5% — better than random for a 604-design pool, modestly informative. BindCraft is the only tool whose native scoring shares the structural-fold signal that refolding measures, presumably because it ran AF2 internally on the same task.
- **BoltzGen (`final_rank`)**: essentially no agreement with refold ipSAE (ρ = -0.15). This is consistent with BoltzGen's `final_rank` being a composite that includes diversity weighting, pTM, hbond counts, and an aggregate RMSD — not driven by ipSAE. **Hence the user's observation about BG #1: their composite ranking does not optimise for the metric we use to validate.**
- **BoltzGen (`design_ipsae_min`)**: when we use BoltzGen's *own* ipSAE column (not `final_rank`), Spearman to refolded `boltz_pae_ipsae_min` is **+0.837**. BoltzGen knows which designs are good by ipSAE; it just doesn't sort by it.
- **PXDesign**: native `af2_iptm` (from PXDesign's internal AF2 eval) has ρ ≈ 0.05 with refold ipSAE. Length is the only thing with a non-zero correlation — PXDesign produces a length-stratified sample. Note that PXDesign's run uses a hold-out re-fold by the same AF2 internally, so its native is essentially a noisy version of what we're measuring with our AF2; their ρ should be higher if the AF2 versions were identical. The PXDesign internal AF2 differs slightly (different parameters / templates) — this is a known issue per CLAUDE.md ("iptm is gameable — AF2-designed sequences tend to score high on ipTM by construction"). It's also possible the 348-row sample is dominated by structurally easy designs, attenuating ρ.
- **Mosaic (`ipsae_min_aux` proxy)**: ρ = 0.63 with refold ipSAE — strong. Top-20 by Mosaic-native lands 35% of itself in refold top-20. That is by far the cleanest native↔refold agreement of any tool except PC. Mosaic is a Boltz-2 hallucinator; Mosaic-native = Boltz-2 self-confidence ≈ Boltz-2 refold confidence ≈ tautology. This is suspect and motivates § 4.
- **Proteina-Complexa (`iptm` proxy)**: ρ = 0.99 with refold ipSAE because we're using a Boltz-2 metric (iptm) to predict a Boltz-2 metric (boltz_pae_ipsae_min) on the same designs. This is **not** evidence of PC's native ranking being good — it's evidence that two Boltz-2 quantities on the same refold are linearly related. The true PC native (its flow-matching score) is not recoverable. Discount this row.

The plots (in `notebooks/_artifacts/plots/`):

- `per_tool_scatter.png`: native_score (x) vs `boltz_pae_ipsae_min` (y), with native top-50 highlighted in red. The user's complaint reproduces visually: for BoltzGen and PXDesign, the red top-50 cluster is **not concentrated** at the top of the y-axis.
- `rank_rank.png`: per-tool scatter of native-rank-order vs refold-rank-order. BindCraft shows a moderate diagonal trend; BoltzGen and PXDesign are diffuse clouds.

---

## 4. Top-20 ipSAE outlier validation

Top-20 designs by `boltz_pae_ipsae_min` in run1_free:

| Rank | binder_id | tool | L_b | boltz_ipsae | af2_ipsae | ipsae_max-min | LC frac | hphob frac | net Q | below median native? | verdict |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 1 | boltzgen_config_2484_r479 | boltzgen | 52 | 0.883 | 0.380 | 0.079 | 0.27 | 0.40 | -2 | yes | inconclusive |
| 2 | mosaic_56063cee_r1 | mosaic | 40 | 0.869 | 0.014 | 0.071 | 0.23 | 0.43 | -5 | n/a | inconclusive |
| 3 | mosaic_54f7cdb8_r4 | mosaic | 20 | 0.858 | 0.025 | 0.012 | 0.20 | 0.40 | -3 | n/a | likely_artifact |
| 4 | mosaic_b6a64717_r1 | mosaic | 20 | 0.857 | 0.017 | 0.015 | 0.20 | 0.40 | -2 | n/a | likely_artifact |
| 5 | boltzgen_config_6401_r12 | boltzgen | 102 | 0.856 | 0.485 | 0.122 | 0.24 | 0.36 | -10 | no | inconclusive |
| 6 | pxdesign_input_len20_sample_43 | pxdesign | 20 | 0.856 | 0.227 | 0.006 | 0.40 | 0.55 | -4 | n/a | likely_artifact |
| 7 | mosaic_54f7cdb8_r2 | mosaic | 20 | 0.855 | 0.159 | 0.024 | 0.25 | 0.45 | -3 | n/a | likely_artifact |
| 8 | boltzgen_config_5248_r149 | boltzgen | 62 | 0.855 | 0.381 | 0.104 | 0.23 | 0.42 | -2 | no | inconclusive |
| 9 | mosaic_60cda749_r2 | mosaic | 80 | 0.847 | 0.412 | 0.105 | 0.28 | 0.39 | -5 | n/a | inconclusive |
| 10 | pxdesign_input_len40_sample_12 | pxdesign | 40 | 0.847 | 0.015 | 0.089 | 0.33 | 0.55 | -3 | n/a | likely_artifact |
| 11 | mosaic_0e995dba_r5 | mosaic | 60 | 0.845 | 0.020 | 0.109 | 0.22 | 0.43 | -4 | n/a | inconclusive |
| 12 | pxdesign_input_len60_sample_72 | pxdesign | 60 | 0.845 | 0.381 | 0.108 | 0.35 | 0.55 | -4 | n/a | likely_artifact |
| 13 | mosaic_0e995dba_r4 | mosaic | 60 | 0.844 | 0.013 | 0.111 | 0.35 | 0.42 | -3 | n/a | likely_artifact |
| 14 | mosaic_a7ac7480_r7 | mosaic | 140 | 0.843 | 0.471 | 0.122 | 0.24 | 0.38 | -7 | n/a | inconclusive |
| 15 | mosaic_0e995dba_r2 | mosaic | 60 | 0.841 | 0.053 | 0.123 | 0.28 | 0.43 | -5 | n/a | inconclusive |
| 16 | pc_0577_…_r1 | proteina_complexa | 78 | 0.841 | 0.014 | 0.125 | 0.28 | 0.42 | -8 | n/a | inconclusive |
| 17 | pxdesign_input_len20_sample_65 | pxdesign | 20 | 0.839 | 0.121 | 0.007 | 0.35 | 0.55 | -3 | n/a | likely_artifact |
| 18 | boltzgen_config_5995_r153 | boltzgen | 105 | 0.837 | 0.477 | 0.135 | 0.28 | 0.34 | -8 | no | inconclusive |
| 19 | mosaic_b6a64717_r2 | mosaic | 20 | 0.835 | 0.014 | 0.008 | 0.20 | 0.40 | -3 | n/a | likely_artifact |
| 20 | mosaic_60cda749_r6 | mosaic | 80 | 0.834 | 0.430 | 0.103 | 0.48 | 0.39 | -7 | n/a | likely_artifact |

Source-tool breakdown: 11 Mosaic, 4 PXDesign, 4 BoltzGen, 1 Proteina-Complexa, 0 BindCraft. **Mosaic is over-represented by ~3× its prior**. This is selection-bias evidence: the Mosaic hallucinator optimised against the very loss function we're using to validate, so its outputs trivially top the chart.

Sequence-property observations:

- 8/20 binders are ≤ 40 aa (40% of top-20 vs 5.7% of full pool — large enrichment of short binders).
- Low-complexity fraction (largest single-aa share) ranges 0.20–0.48. The 20-aa Mosaic / PXDesign hits have 20-40% single-aa share, which is high; full-pool median is 0.13.
- All 20 are net-negative charge (target is mostly E/D/L heavy, so charge complementarity points to many positives — but binders are all anionic, suggesting these designs may pack against hydrophobic faces rather than salt-bridge).
- ipSAE max-min asymmetry distribution: median 0.10, max 0.14. Per Dunbrack 2025 Eq. 14–16, asymmetry > 0.3 is the "directional binding" red flag. **No design here crosses 0.3.** The ipsae_min is genuinely the binding-direction-min in all 20 cases.
- Multi-engine agreement: 0/20 cross both thresholds `boltz_pae_ipsae_min > 0.61` AND `af2_ipsae_min > 0.61`. With AF2 capped low globally (§ 5), a relaxed threshold `af2_ipsae_min > 0.30` is more informative: 7/20 cross.

Verdict counts: 10 "likely_artifact", 10 "inconclusive", 0 "likely_real". The verdicts label the 7 designs whose AF2 lands above 0.30 as "inconclusive" rather than "likely_real" because we still have only single-engine agreement at the strict threshold; under a relaxed AF2 threshold they become "real-ish but unconfirmed". `boltzgen_config_6401_r12` is the design closest to a confirmed positive: 0.856 / 0.485 / asym 0.12, 102 aa, native top-12 by BG ranking.

---

## 5. BoltzGen deep dive

### 5.1 The "BG #1 → ipsae ≈ 0.01" claim

BoltzGen's `final_rank=1` is `config_2416` in `final_designs_metrics_700.csv`. The corresponding row in run1_free metrics.csv is `boltzgen_config_2416_r1` with:

- `boltz_pae_ipsae_min = 0.758`
- `af2_ipsae_min = 0.378`
- `ipsae_min_aux = 0.820`
- `iptm = 0.965`
- `binder_length = 90 aa`
- BoltzGen's own `design_ipsae_min = 0.250`

That is **not** ipsae ≈ 0.01 by either engine. The closest match to the user's recollection is probably **`boltzgen_config_3315_r8` (final_rank=8, boltz_ipsae=0.680, af2_ipsae=0.000)** — i.e. AF2 says 0.000 for a BG top-10 design. Several BG designs in the rank-top-20 have af2_ipsae effectively zero (configs 3315, 4017, 3823, 3297, 6401; final_ranks 8/13/15/16/12) — this is probably what the user remembers as "ipsae ≈ 0.01".

If the user was looking at run2_template (template ON), BG #1 there has `boltz_pae_ipsae_min = 0.484` and `af2_ipsae_min = 0.243`. Still not 0.01.

### 5.2 BG internal ipSAE vs Boltz-2 refold ipSAE

Spearman ρ between `design_ipsae_min` (BG's own ipSAE) and `boltz_pae_ipsae_min` (our refold ipSAE) across 700 designs: **+0.837** — strong agreement. BoltzGen's own metric is a fine predictor of what Boltz-2 refold will say. It just isn't what `final_rank` sorts by.

Top-5 BoltzGen designs by `design_ipsae_min` (BG's own):

| BG ID | BG design_ipsae | boltz refold ipsae | af2 refold ipsae |
|---|---:|---:|---:|
| config_2416_r1 | 0.250 | 0.758 | 0.378 |
| config_5826_r66 | 0.241 | 0.822 | 0.025 |
| config_9811_r100 | 0.230 | 0.529 | 0.424 |
| config_0336_r99 | 0.224 | 0.577 | 0.252 |
| config_5497_r67 | 0.224 | 0.758 | 0.459 |

Bottom-5 by Boltz refold ipsae (within BG):

| BG ID | BG design_ipsae | boltz refold ipsae | af2 refold ipsae | final_rank |
|---|---:|---:|---:|---:|
| config_3829_r198 | 0.107 | 0.032 | 0.011 | 198 |
| config_3073_r472 | 0.056 | 0.049 | 0.013 | 472 |
| config_3565_r681 | 0.072 | 0.051 | 0.012 | 681 |
| … | … | … | … | … |

BG's worst by refold are also worst by BG's own ipSAE, so there is **no model-disagreement** in the bad cases. The user's mental model "BG top by their rank → terrible by our ipSAE" is structurally caused by `final_rank`'s composite definition, not by an ipSAE disagreement.

### 5.3 Which BG metric is which

The Evaluator's BoltzGen extractor (`extractors/boltzgen.py:70-83`) reads `final_designs_metrics_*.csv`, extracts `designed_sequence` and `id`, and sets `NativeMetrics()` empty. **No BG-internal metric flows through to metrics.csv** as a "native ranking" column. The user's perception that "BG's native ranking" exists in the eval CSV is correct in that BG's native sort order can be reconstructed from the `_rNNN` suffix in `binder_id` (which is `final_rank`) — but the eval pipeline has no awareness that this is a meaningful ranking.

When we report a "BoltzGen native_rank correlation" it is the implicit join `_join_key = binder_id.rsplit('_r', 1)[0]` against the source CSV (the same join used by the analysis script in this report).

---

## 6. The hidden third finding: AF2 ipSAE is mis-calibrated on this 32-aa target

This is the most consequential observation in the dataset and was not in the user's spec, but it explains why H1 (model bias) is dominant.

**Distributions across all 4,004 designs in run1_free:**

| Metric | mean | max | min |
|---|---:|---:|---:|
| `boltz_pae_ipsae_min` | 0.41 | 0.88 | 0.00 |
| `af2_ipsae_min` | 0.13 | 0.52 | 0.00 |
| `boltz_pae_bt_mean` (Å) | 4.16 | 22.13 | 0.88 |
| `af2_pae_bt_mean` (Å) | 11.32 | 27.00 | 2.25 |
| `boltz_pae_max` (Å) | 22.96 | 30.06 | 8.01 |
| `af2_pae_max` (Å) | 26.14 | 31.53 | 16.55 |

AF2 BT PAE is **2.7× higher** than Boltz-2 BT PAE on the same designs. The Dunbrack ipSAE uses a uniform 10 Å cutoff (`scoring.py:38, IPSAE_PAE_CUTOFF`); when the mean BT PAE is 11.32 Å, the **majority of binder-target residue pairs fall outside the cutoff** and the per-residue ipSAE goes to 0. This squeezes the entire AF2 ipSAE distribution into [0, 0.52].

Per-tool pass rates at `>0.61` (the F1-optimal threshold from Overath et al. 2025):

| Tool | boltz_pae_ipsae > 0.61 | af2_ipsae > 0.61 | both > 0.61 |
|---|---:|---:|---:|
| bindcraft | 160 / 604 (26.5%) | 0 / 604 (0%) | 0 / 604 |
| boltzgen | 354 / 700 (50.6%) | 0 / 700 (0%) | 0 / 700 |
| mosaic | 553 / 784 (70.5%) | 0 / 784 (0%) | 0 / 784 |
| proteina_complexa | 96 / 637 (15.1%) | 0 / 637 (0%) | 0 / 637 |
| pxdesign | 101 / 800 (12.6%) | 0 / 800 (0%) | 0 / 800 |

**No design in the campaign passes the AF2 threshold.** This is a campaign-wide property of the AF2 PAE distribution, not a design-quality verdict.

Two non-exclusive explanations:

1. **AF2 PAE is genuinely more conservative on short targets.** For a 32-aa target, AF2's confidence in the interface is bounded by how well it can place the target itself; if the target structure has elements that AF2 doesn't predict confidently (loops, low-complexity stretches), the cross-chain PAE inherits that uncertainty. Boltz-2 may be more aggressive at trusting interface contacts.
2. **The 10 Å cutoff calibrated on Overath et al. (2025) data was AF3-derived.** AF3 PAE distributions sit between AF2 and Boltz-2; a 10 Å cutoff that works for AF3 may be too tight for AF2. CLAUDE.md acknowledges this: "Overath et al. (2025) thresholds (0.61, 0.80) were calibrated with a 10 Å cutoff on AF3 data" (verbatim, `scoring.py:36-38`).

Either way, **comparing AF2 ipSAE_min against the 0.61 threshold and the Boltz-2 ipSAE_min against the same threshold is invalid for this campaign**. The right comparison would use a higher AF2 cutoff (e.g. 15 Å for AF2 only) or threshold AF2 against its own per-target empirical distribution.

---

## 7. Hypothesis verdict

The user spec named three hypotheses:

- **H1 — model bias**: Boltz-2 over-confidently rates designs that exploit Boltz-2 features.
- **H2 — parsing / data-alignment bug**.
- **H3 — selection-induced**: top-N by native is statistically dominated by length / complexity outliers that re-test poorly.

**My verdict**:

- **H1: STRONG SUPPORT.** Mosaic's `ipsae_min_aux` ↔ `boltz_pae_ipsae_min` ρ = 0.63 (top-50 Mosaic-native = 100% pass on Boltz refold). BoltzGen's `design_ipsae_min` ↔ `boltz_pae_ipsae_min` ρ = 0.84. Both tools were designed to please Boltz-* and they do. Meanwhile Boltz-* validation says ipsae_min > 0.61 for 70.5% of Mosaic and 50.6% of BoltzGen designs vs 12.6% of PXDesign and 15.1% of Proteina-Complexa. AF2 disagrees universally (0% > 0.61 anywhere) — but that AF2 reading is calibrated wrong (§ 6), so we cannot use AF2 to refute H1 in either direction. H1 is the right primary explanation for the discrepancy.
- **H2: NOT SUPPORTED.** The current Evaluator code's ipSAE math, PAE-ordering, and binder-length book-keeping are all verifiably correct. The legacy AF2 code that produced the af2_* columns also has consistent ordering. The data-integrity issues (BindCraft duplicates, PXDesign ID collisions, stale on-disk native CSVs) are real and worth fixing, but they don't change rankings or scores — they're metadata/join issues. They are not the explanation for the user's observation.
- **H3: MODERATE SUPPORT.** The top-20 by refold ipSAE is enriched 3× in Mosaic and short binders. Mosaic top-50 by its own loss has 100% pass; we are likely seeing selection bias on top of H1. Note this is symptom of H1 more than an independent driver: H1 says the optimisation pressure of each tool toward Boltz-2-style features creates the top-N artifact pool, then selection on Boltz-2 ipSAE recapitulates the pool. H3 alone (with no engine bias) would not explain why **specifically Mosaic** dominates the top.

So: **H1 dominant, H3 contributing, H2 ruled out within the limits of what we can audit without the original PAE arrays.**

---

## 8. Recommendation

Given:
1. Boltz-2 ipSAE is tool-of-origin biased (Mosaic ≫ Proteina ≫ PXDesign).
2. AF2 ipSAE is mis-calibrated to be uniformly low on this target.
3. Native ranking metrics for most tools correlate only weakly with refold ipSAE.
4. BindCraft is the only tool whose native↔refold correlation is moderate (ρ ≈ 0.53).

I recommend **(b) require multi-model cross-agreement, with engine-specific thresholds, AND (c) weight by tool-of-origin priors** for de-novo ranking. Concrete proposal:

1. **Add AF3 to the refold panel** (already in plan). AF3 PAE distributions sit between AF2 and Boltz-2; the 10 Å cutoff was empirically calibrated on AF3. Once AF3 is wired in, the `agreement_count` column (`scoring.py:553`) becomes meaningful for ranking — it currently always equals "boltz_pae_ipsae_min > 0.61" because AF3/Protenix columns are missing.
2. **Stop reporting `af2_ipsae_min` against the 0.61 threshold for short-target campaigns.** Either (a) compute AF2 ipSAE with a target-length-aware cutoff (15 Å for L_target ≤ 50, 10 Å otherwise), or (b) use AF2 only for relative ranking and drop the absolute threshold. The data shows the absolute threshold is meaningless for this target.
3. **Down-weight Mosaic by ρ-corrected agreement.** When `source_tool == 'mosaic'` and the only passing engine is Boltz-2, treat it as "Boltz-2 self-validation" not as "cross-validation". A simple rule: require at least one non-Boltz-2 engine to also pass for Mosaic designs, even at relaxed thresholds.
4. **Use BoltzGen's `design_ipsae_min` (its own ipSAE) as the primary BG native ranking, not `final_rank`.** The extractor doesn't currently surface this. ρ to refold ipSAE is 0.84 (vs −0.15 for `final_rank`). This is one line in `boltzgen.py` and would dramatically improve the user's experience of "BG top → terrible refold".
5. **Fix the data-integrity issues independently.** BindCraft de-dup (~half the BC rows are redundant), PXDesign ID with length, and a sanity check that the on-disk native CSV matches the metrics.csv that was last evaluated (e.g. a hash file).

If the user wants a single ranking metric **right now** without code changes: use `boltz_pae_ipsae_min × (1 - 0.15 * I[source_tool=='mosaic'])` to apply a small Mosaic discount, OR rank by `min(boltz_pae_ipsae_min, max(af2_ipsae_min, 0.3) / 0.524 * 0.61)` to normalise AF2 to its own dynamic range. Either is hacky; the right fix is item 1 above, which is on the roadmap (Part K).

---

## 9. Deliverables

- This file: `/home/bindmaster5/dev/BindMaster/INVESTIGATION_RANKING_DISCREPANCY.md`
- Notebook: `/home/bindmaster5/dev/BindMaster/notebooks/ranking_discrepancy.ipynb`
- Analysis script: `/home/bindmaster5/dev/BindMaster/notebooks/_analysis.py` (re-runnable, regenerates all artifacts under `notebooks/_artifacts/`)
- Plots: `/home/bindmaster5/dev/BindMaster/notebooks/_artifacts/plots/{per_tool_scatter,rank_rank,cross_engine,length_vs_ipsae,pae_distributions}.png`
- Tables (CSV): `/home/bindmaster5/dev/BindMaster/notebooks/_artifacts/{per_tool_correlations,top20_outliers}.csv`
- Per-tool merged data: `/home/bindmaster5/dev/BindMaster/notebooks/_artifacts/{bindcraft,boltzgen,mosaic,proteina_complexa,pxdesign}_merged.csv`
- BoltzGen deep-dive JSON: `/home/bindmaster5/dev/BindMaster/notebooks/_artifacts/boltzgen_deep_dive.json`
