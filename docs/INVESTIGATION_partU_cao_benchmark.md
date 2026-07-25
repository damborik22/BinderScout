# Part U — Cao 2022 large-scale ranking-metric benchmark

> **Status: RUNNING (staged 2026-07-25).** Refolding a 4,442-design subsample of the
> Cao et al. 2022 yeast-display dataset through all three evaluator engines to settle the
> ranking-metric question with real statistical power. Data + scripts: `~/dev/cao_refold/`.

---

## 1. Why this run exists

Every metric comparison we had run was **noise-limited**. On our two existing labelled sets
(Adaptyv, BindCraft de-novo) only 4–6 targets have enough binders to score, and the
consequence is stark:

- ~45 candidate metrics/combinations all land in a narrow **0.71–0.74 macro-AUC** band, and
- the **Spearman correlation of the metric ranking between the two datasets is −0.107**.

That is: *which metric looks best is essentially random across datasets.* Picking the
top-of-45 on one dataset is overfitting, which is exactly how the (subsequently refuted)
length-crossover finding arose. To make any metric claim provable we need many targets and
many binders per target.

## 2. The dataset

Cao et al. 2022, *Design of protein-binding proteins from the target structure alone*
(Nature 605:551), Data Availability → `files.ipd.uw.edu/pub/robust_de_novo_design_minibinders_2021/`.

**Only `experimental_data_and_analysis.tar.gz` (234 MB) is needed.** The `design_models_pdb`
(63 GB) and `design_models_silent` (46 GB) tarballs are Cao's *own* predicted structures and
are irrelevant to us — we refold from sequence with our own engines. Do not download them.

Assembled master (`build_cao_dataset.py`): joins `ngs_analysis/affinities/<T>.sc`
(kd bounds, binder calls) with `sorting_ngs_data/<T>/sequences.list` (protein + DNA) by row
index — the files are index-aligned (identical row counts, same pooled-library order).

**654,716 designs across 12 targets**, 40–67 aa minibinders (median 65).

| | Adaptyv (previous best) | **Cao 2022** |
|---|---|---|
| labelled designs | 2,517 | **654,716** |
| targets | 24 (only 4–5 usable) | **12 (all usable)** |
| binders (kd < 1 µM) | 359 | **11,629** |
| design methods | many ML tools | one Rosetta pipeline, 7 scaffold families |
| complex size | up to 844 tok | **141–488 tok** |

### 2.1 Label definition — do not use "finite Kd"

The naive label (`kd_lb` finite) marks **55,886** designs as binders, but their **median Kd is
8 µM** — that is not binding, and it inflates e.g. FGFR2 to a 56 % hit rate. The defensible
label is a threshold: **binder ⇔ `kd_lb` < 1000 nM** → 11,629 binders (1.79 %).

Per-target hit rates then span FGFR2 11.1 % → Tie2 0.04 %. This ~275× spread is **expected**,
not an artifact: Cao's own protocol guide grades target tractability ("1 exposed PHE =
unlikely to work … 5 = easy target").

### 2.2 Design provenance

All designs come from **one Rosetta pipeline** (RIF docking + motif grafting onto a
miniprotein scaffold library) — *not* different design tools. What varies is scaffold
topology, and it matters:

| scaffold class | n | hit % |
|---|---|---|
| `ems_` | 206k | 1.63 |
| `bcov` | 144k | 1.60 |
| `HHH` (all-helical) | 85k | 0.92 |
| `HEEH` | 40k | **4.39** |
| `EHEE` | 23k | **4.38** |
| `cside/nside_mot` | 35k | ~0.75 |

β-containing topologies hit ~5× more often than all-helical ones.

**Complementarity:** Cao = 1 method × 12 targets × huge N (target generalisation, no
method-diversity confound). Adaptyv = many methods × few targets (method/gaming bias). They
answer different questions.

### 2.3 Affinity ranking — this dataset CANNOT settle it

The main hoped-for prize was ranking Kd among binders on a big clean set. **It does not hold
up.** Of 11,629 binders only **495** have tight, trustworthy bounds (`kd_ub/kd_lb ≤ 10`,
avidity-consistent, not low-conf), and those cluster against the assay's dynamic-range limit:

| target | clean-Kd n | Kd range | log-spread | IQR (log) |
|---|---|---|---|---|
| FGFR2 | 225 | 5.8 – 994 nM | **2.23** | 0.68 |
| PDGFR | 137 | 366 – 981 nM | 0.43 | **0.11** |
| InsulinR | 45 | 197 – 949 nM | 0.68 | 0.30 |
| VirB8 | 34 | 43.9 – 988 nM | 1.35 | 0.43 |
| TGFb | 28 | 202 – 991 nM | 0.69 | 0.50 |

Yeast-display titration saturates near 1 µM, so most "Kd" values are **censored, not
measured**. Only **FGFR2** carries a real affinity gradient (225 binders over 2.2 logs).

**→ Scope honestly: this is a well-powered SCREEN benchmark across 12 targets, plus a
single-target (FGFR2) affinity probe. It is not the affinity breakthrough.** The subsample
deliberately retains **all 495 clean-Kd binders** so the FGFR2 probe survives.

## 3. The run

**Subsample** (`build_subsample.py` → `cao_subsample.csv`): per target, all clean-Kd binders
plus up to 200 binders and 200 sampled non-binders → **4,442 designs / 2,042 binders / 12
targets**. EGFR is split into its two target sites via the `cside_mot`/`nside_mot` description
prefixes, matching the `EGFRc`/`EGFRn` constructs.

**Target constructs** (`cao_target_seqs.json`): extracted from chain B of the 13
`design_models_final_combo_optimized/*_mb.pdb` complexes in `scripts_and_main_pdbs.tar.gz`
(chain A = minibinder 55–65 res, chain B = target 82–423 res) — i.e. the paper's exact
constructs, no UniProt guesswork. SARS-CoV-2 RBD has affinity data but no construct in the
tarball and only 61 binders; excluded.

**Execution split** (Clara lacks an ESMFold2 env; Spark lacks the H200s):

| engine | host | job |
|---|---|---|
| Boltz-2 | Clara H200 | `cao_boltz2.sbatch`, `--array=0-11` (one task per target) |
| AF3 | Clara H200 | `cao_af3.sbatch`, `--array=0-11` |
| ESMFold2 | Spark GB10 | `run_esm_spark.sh` (sequential, `--model full`) |

**Prerequisites handled:**
- Clara compute nodes have no internet → target MSAs pre-fetched on the login node into
  `~/.cache/bindmaster/target_msa/`; array submission is chained to wait for it
  (`chain_submit.sh`).
- Clara's `binder-eval` env was missing `requests` (needed by `target_msa`) — installed.
- The Mosaic offline-MSA patch was already applied on Clara (it is **required**; without it
  Boltz-2 dies with `TargetChain unexpected keyword argument 'msa_path'` — see
  `install/patches/mosaic-offline-msa.patch`).

Complexes are 141–488 tokens, far below any memory ceiling and ~⅓ the size of the Adaptyv
run, so this is cheaper per fold than the Promera benchmark.

## 4. What it will answer

1. **Which metric/combination actually screens best**, with 12 targets and ~2,000 binders —
   enough power to resolve differences that were noise at 5 targets. Scored as **macro-AUC
   across targets** (pooling across targets with different binder rates is what produced the
   `promera_plddt` artifact).
2. **Whether metric choice transfers** — re-testing the ρ = −0.107 result against a
   third, much larger dataset. If rankings still don't transfer at this scale, the screen is
   genuinely saturated and no combination work is worth doing.
3. **Whether our shipped two-stage consensus is near-optimal** or leaves signal on the table.
4. **A single-target affinity probe** on FGFR2 (225 binders, 2.2 logs of Kd).
5. **Scaffold-topology stratification** (HEEH/EHEE vs HHH) — with the standing rule that any
   per-stratum effect must reproduce across targets before it is believed.
