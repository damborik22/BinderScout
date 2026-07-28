# Part U — Cao 2022 large-scale ranking-metric benchmark

> **Status: ✅ COMPLETE (staged 2026-07-25, finished 2026-07-28).** All 4,442 designs
> refolded by all three engines (Boltz-2 + AF3 + ESMFold2), 100 % coverage, zero failures.
> Verdict in §5–§10. One code change shipped (`f63e18b`, Stage-1 screen retired).
> Data + scripts: `~/dev/cao_refold/` (gitignored — see §10 for what is reproducible where).
>
> **Headline:** metric choice is a solved-and-closed question — nothing beats what we already
> ship, and *selecting* a metric from labelled data does worse. The apparent 0.56 ceiling is
> mostly **label censoring**, not a weak screen: on label-clean positives it is **0.73**.

---

## 0. Reading guide — what is verified how

Findings below carry a provenance marker, because a 15-agent workflow produced them and its
own adversarial verifiers **struck 11 of the original claims**. Do not treat agent output as
established.

| marker | meaning |
|---|---|
| **[V]** | Re-run and confirmed by hand against `cao_merged.csv` after the workflow finished. Trust these. |
| **[A]** | Produced by an analysis agent **and** survived an independent adversarial verifier that re-ran it. |
| **[✗]** | Claimed during the run and **struck**. Recorded so it is not rediscovered. |

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

---

## 5. Execution record

| engine | host | result |
|---|---|---|
| Boltz-2 | Clara H200, array `cao_boltz2` | 4,442 / 4,442 |
| ESMFold2 | Spark GB10, `run_esm_spark.sh --model full` | 4,442 / 4,442, zero errors |
| AF3 | Clara H200, array `153471` | 4,442 / 4,442, all 12 tasks `COMPLETED 0:0` |

**Every design has all three engines — 100 % coverage, zero NaN.** This makes every
engine comparison perfectly matched, which no previous benchmark of ours achieved.

Two excluded designs: `scarlet-raven-snow` and `radiant-shark-iron` carry a `:` in the
sequence, which kills the DataLoader and truncates the whole chunk. Excluded; the 220
innocent designs in their chunks were refolded separately.

**Metrics were recomputed from the PAE matrices using the shipped code path**
(`binder_comparison.comparison.scoring.add_{boltz_,}ipsae_from_pae_files` /
`add_iptm_from_pae_files`) on whichever host held each engine's `.npy` files, so the columns
are identical to what `binder-compare report` produces — not a reimplementation.

**Plumbing verified before any analysis [V]:** all 12 target sequences correct in all three
engines (including the `TGFb`/`TGF-b` key mismatch), labels clean (binders median Kd 37 nM,
non-binders Kd = ∞), no duplicate `(tgt, sequence)` rows, merge preserved row count exactly
4,442 → 4,442.

Shared primitives live in `cao_lib.py`. Two choices there are load-bearing:

- **Macro over pooled**, always. Base rates span 15.3 % (Tie2) to 52.9 % (FGFR2).
- **Metric direction is learned out-of-fold.** For each held-out target the sign is decided
  on the other 11. Orienting a metric on the data you score it on inflates every metric, and
  inflates *useless* metrics most. This is applied uniformly, so no a-priori direction table
  is needed and no metric gets a free parameter.

## 6. The headline: a 0.56 ceiling that is mostly a label artifact

### 6.1 The raw result

Full 72-metric leave-one-target-out leaderboard **[V]**:

| metric | macro-AUC | pooled | note |
|---|---|---|---|
| `af3_pae_iptm` | **0.5603** ± 0.0854 | 0.5739 | best of 72 |
| `esmfold2_pae_iptm` | 0.5507 | 0.5547 | |
| `consensus_iptm_mean` (shipped) | 0.5552 | 0.5733 | |
| `boltz_pae_iptm` | 0.5281 | 0.5535 | worst engine |
| `binder_length` | 0.4709 | 0.5302 | inconsistent sign |

Everything sits in a **0.471–0.560** band. Per-engine means: AF3 0.554 (n=16 metrics),
ESMFold2 0.549 (n=17), Boltz-2 0.528 (n=33) **[A]**.

Against Adaptyv (~0.69) and the de novo BindCraft set, that looked alarming.

### 6.2 …but 73 % of the "binders" are not binders

**73.41 % of Cao binder labels (1,499 / 2,042) have a one-sided Kd** (`kd_ub = inf`) — the
yeast-display titration saturated and the fit reports only a lower bound **[V]**.

Split on that, over the 6 targets with ≥ 20 two-sided binders **[V]**:

| positives used | `af3_pae_iptm` | `esmfold2_pae_iptm` | `consensus_iptm_mean` |
|---|---|---|---|
| all | 0.6175 | 0.5973 | 0.6112 |
| **two-sided Kd only** | **0.7343** | **0.6911** | **0.7228** |
| one-sided only | 0.5350 | 0.5184 | 0.5321 |

This is **not** circular reasoning from the same Kd fit. It is corroborated by Cao's own
fixed-concentration binary assay, an independent measurement, across the full 654,716-design
library **[A]**:

| class (`kd_lb` < 1000 nM) | n | passes `binder_400_nm` | passes `binder_4000_nm` |
|---|---|---|---|
| two-sided Kd | 677 | **35.90 %** | **89.96 %** |
| one-sided Kd | 11,013 | **0.073 %** | **1.03 %** |
| labelled non-binder | 643,026 | 0.0023 % | 0.119 % |

**One-sided "binders" are experimentally indistinguishable from non-binders.** Our metrics
scoring 0.535 on them is correct behaviour, not failure. (Note 94.2 % of the natural
library's sub-µM designs are one-sided; the 73.4 % here reflects the subsample deliberately
over-retaining clean labels.)

### 6.3 The corrected cross-dataset ladder

| dataset | macro-AUC | note |
|---|---|---|
| Cao, all labels | 0.56 | 73 % censored positives |
| **Cao, label-clean positives** | **0.73** | comparable to Adaptyv |
| Adaptyv | 0.68–0.72 | |
| de novo BindCraft | **0.72–0.78** | **not 0.91** — see below |

**The "0.91" was a Simpson artifact and must not be quoted [V].** Traced to
`~/dev/denovo_refold/denovo_esm_results.csv` and reproduced exactly: pooled `esm_iptm`
**0.9058** over 66 designs / 2 targets — PD1 **0.9096** (13 binders / 40 non) pooled with
PD-L1 **0.6364** (11 binders / **2** non). **Macro over the two targets = 0.7730**; pooling
inflated it **+0.1328**, the exact trap this project's own macro-over-pooled rule forbids.
On the larger 7-target ESMFold2 run (`runs/denovo_lengthtest`, 110 designs) macro is 0.7191.
Memory `reference_denovo_bindcraft_replication.md` was corrected.

### 6.4 The residual gap is design regime

What remains after label correction is real and matters: Cao is 4,442 **near-miss** Rosetta
minibinders — negatives drawn from the *same* pipeline as the positives, 75.1 % of them
exactly 65 aa, 8 scaffold families. Our metrics separate binder-from-obvious-junk far better
than binder-from-near-miss. **Real campaign pools are Cao-like.**

## 7. The five staged questions, answered

### (a) Which metric screens best? — nothing beats what we ship

`af3_pae_iptm` at 0.5603 is nominally top, but **honest nested selection over the 72 metrics
scores 0.5170** — six different metrics win across the 12 folds **[A]**. Selecting a metric
from labelled data generalises *worse* than the metric already shipped.

The strongest pro-consensus result in the whole investigation: **`consensus_iptm_mean`
(0.5552) beats honest nested single-metric selection by +0.0382, CI [+0.0142, +0.0633],
p = 0.0014, winning 8/12 targets [A].**

Combination search is closed: best nested combination **0.5591** over 2,489 combinations ×
2 model families, and the apparent gain sits **inside a label-permutation null**
(p ≈ 0.06–0.08, seed-dependent). Real metrics deliver 2.8–3.6× *less* combination gain than
equally-informative independent ones — 14 of 22 pool metrics correlate |r| > 0.97 with
another. They are redundant, not complementary **[A]**.

### (b) Does metric choice transfer? — not usably

| pair | ρ | p |
|---|---|---|
| Cao vs de novo | +0.630 | 3.0e-09 |
| Adaptyv vs de novo | +0.384 | 8.8e-04 |
| Cao vs Adaptyv | −0.026 | 0.83 |

So "never transfers" was too strong — but three qualifications kill the practical use **[A]**:

1. **All target-resampled CIs include zero** (cao–denovo [−0.211, +0.728]). With 4–12 targets
   the contrast is not estimable.
2. **The +0.630 is mostly engine-block agreement.** Partialling out engine means drops it to
   +0.230. The datasets agree on which *engine* is good, not which *statistic*.
3. **Transferring a winner buys nothing.** Each dataset's #1 lands at the 31st–75th
   percentile elsewhere: Cao's `af3_pae_iptm` → 31st percentile on Adaptyv; Adaptyv's
   `boltz_pTMEnergy` → 54th on Cao; de novo's `esmfold2_tb_ipsae` → 49th on Cao.

**→ Stop running combination searches to decide what to ship.**

### (c) Is the shipped consensus near-optimal? — yes, ≤ 0.005 on the table

**Stage 0 (≥3-engine gate):** inert here (all designs have 3 engines), so untestable. The
argument for lowering it to 2 rested on a **random-dropout (MCAR)** simulation whose result
flipped sign under reseeding; under informative dropout the gate buys +0.006–0.038 **[A]**.
**Keep 3.**

**Stage 1 (top-50 % max screen): RETIRED — shipped in `f63e18b`.** Measured inert **[V]**:
0 designs removed from the top-5/10/20/50/10 % on **12/12 targets**; earliest rank moved was
**21.0 % down the pool** (EGFRc, rank 84/400); full-list Spearman 0.983–0.999.

> **This is empirical, not a theorem.** Elementwise `mean ≤ max` does *not* imply the screen
> preserves the head of the mean ordering: A=(0.5,0.5,0.5) has mean 0.5/max 0.5, B=(0.9,0.1,0.1)
> has mean 0.367/max 0.9 — a cut at 0.6 drops A, keeps B, despite A's higher mean. It holds
> here because max and mean co-rank at Spearman **0.894–0.975** within target **[V]**. On a
> pool where engines disagree far more, it would bite.

**Max vs mean was backwards in the docs [V].** At the same 50 % cut the **mean** screen
retained *more* true binders — **1,114 vs 1,093**, +0.0123 macro recall, CI [+0.0027,+0.0226],
p = 0.0094, 8/12 targets. Recorded so `max` is not reinstated on the "lenient recall"
rationale (already flipped twice: `f1bc405` → mean, `5769064` → back to max).

**Stage 2 (rank by mean):** statistically tied with AF3 alone (−0.0052, p = 0.449) and with
every engine subset. Worst-case regret across the three datasets **[A]**:

| candidate | Cao | Adaptyv | de novo | worst regret |
|---|---|---|---|---|
| boltz+esm | 0.5456 | 0.7295 | 0.7052 | 0.021 |
| af3+esm | 0.5608 | 0.7025 | 0.7262 | 0.027 |
| **3-engine mean (shipped)** | 0.5562 | 0.7215 | 0.6842 | **0.042** |
| boltz alone | 0.5281 | 0.7204 | 0.6204 | 0.106 |
| af3 alone | 0.5603 | 0.6134 | 0.6907 | **0.116** |

Every 2-engine subset wins somewhere and loses somewhere; the 3-engine mean is **never
worst**. **The largest available mistake is committing to one engine.** AF3 is best on Cao
and *worst* on Adaptyv. **Do not drop Boltz-2** — `af3+esm` loses to the 3-engine mean on
Adaptyv by −0.0190, CI [−0.0307, −0.0074], p < 0.001, 0/4 targets.

### (d) FGFR2 affinity — Part N survives, with one narrow correction

The signal is real: `esmfold2_pae_overall_mean` **ρ = +0.3024, n = 225, p = 3.9e-06**,
permutation-FWER P = 0.0002, surviving length (partial +0.314), scaffold (+0.246),
sequence-relatedness and censoring controls **[A]**. So "no structure-confidence metric ranks
affinity among binders" is false *as an absolute*.

Every operational leg still holds **[A]**:

- **It does not transfer.** FGFR2's winners score mean oriented ρ = −0.047 on the other four
  targets, against a random-metric null of −0.019 (P = 0.674).
- **PDGFR is a decisive non-replication.** Matched to PDGFR's actual Kd window, FGFR2 gives
  **+0.373** (n = 56, p = 0.005), PDGFR **−0.014** (CI −0.177…+0.160). They do not abut.
- **The shipped ranker gains nothing:** macro ρ −0.018 across the 5 usable targets.
- **Two-thirds of it needs no structure prediction.** Net charge (K+R−D−E) of the raw
  sequence gives **ρ = +0.2385, p = 3.1e-04** on the same slice — 79 % of the best structure
  metric's magnitude.

**Revised wording:** on 1 of 5 adequately-powered targets, structure confidence correlates
with Kd among binders at ρ ≈ 0.30 (~9 % of rank variance); it does not transfer, is not
capturable by out-of-fold metric choice, and is largely reproduced by net charge.
**Do not re-open affinity ranking on structure confidence.**

### (e) Strata — four of five are flat nulls

- **Scaffold:** the 0.512–0.633 spread across 8 families is slice-size noise
  (permutation p = 0.42). The one survivor — HEEH scoring worse *within its own target*
  (af3 −0.061, p = 0.008, 8/10 targets; `consensus_iptm_mean` −0.070, p = 0.0008, 7/10) —
  fails on the third metric (ESMFold2 −0.045, p = 0.21) and is 1 of 14 contrasts, so it does
  not clear Bonferroni. **Suggestive, not established [A].**
- **Binder length: untestable here.** 75.1 % of designs are exactly 65 aa; 8/12 targets have
  a single length. Length's own macro-AUC is 0.4914 with inconsistent sign. This says nothing
  about other libraries.
- **Engine agreement: flat null.** Median-split delta −0.006/+0.005 against a random-split
  null of ±0.018 (p = 0.71/0.81). `agreement_count` scores 0.532 with **87.2 %** of designs
  tied at zero **[A]**.
- **Target identity is the only real stratum** (FGFR2 0.741, PDGFR 0.702, then a cliff to
  0.564; 5/12 at or below chance) — but **0 of 21 measurable target properties predict it**,
  so it is not knowable in advance and therefore not actionable **[A]**.
- **No a-priori-definable subset reaches 0.70.** Best of 46 label-free rules: 0.648 **[A]**.

## 8. What this means for reading our reports

| target | designs-per-hit, unranked | top decile by `af3_pae_iptm` |
|---|---|---|
| FGFR2 | 8.98 | **2.13** |
| InsulinR | 67.6 | 21.2 |
| PDGFR | 303 | 92.5 |
| TrkA | 27.7 | **30.5** ← worse |
| Tie2 | 2500 | **4724** ← worse |

Macro fold-enrichment **1.88×** (median 1.58×), and the top decile beats a random ranking on
only **6 of 12 targets** **[A]**.

**Blunt version: on a near-miss pool from a single design tool, the ranking is worth roughly
1.5–2× enrichment on average, ~4× on a good target, and nothing or negative on a third of
targets. It is a triage filter, not a decision procedure.** A report that ranks 200
same-length designs against one target and presents the top 10 as "the best" over-sells by a
wide margin. The report's methodology blurb and CLAUDE.md now say so.

## 9. Struck claims — do not rediscover these

Eleven claims produced during the run were refuted by adversarial verifiers and re-checked.
Recorded so they are not re-derived **[✗]**:

- *"Target difficulty is driven by label quality, r = +0.897"* — `AUC_all = f·AUC_two +
  (1−f)·AUC_one` holds exactly (max residual 1.1e-16) with `AUC_one` near-constant. It is an
  algebraic identity, not a discovery. With the natural library fraction, ρ falls
  0.804 → 0.333 (p = 0.29).
- *"Boltz-2's deficit is uniform across targets"* — FGFR2 + PDGFR supply **58.2 %** of the
  total AF3−Boltz delta. Dropping both: +0.0162, CI [−0.0036, +0.0339], **p = 0.109**.
- *"Variance mis-alignment explains the engine gap (5×)"* — η² on a within-target z-score is
  the squared point-biserial, monotone in AUC. It restates the gap.
- *"AF3 is worst on Adaptyv, so drop Boltz-2"* — built on a non-comparable legacy table
  (5 targets, native not PAE-recomputed columns, mismatched design pools).
- *"Lower `min_engines` to 2"* — MCAR-only; positive under 5 reseeds.
- *"The leaderboard is mostly noise (split-half ρ +0.18)"* — that split *targets*, conflating
  noise with real between-target heterogeneity. Splitting **designs**: Cao **+0.658**
  (Spearman-Brown 0.794). The ordering is reproducible; which *targets* are separable is not.
- *"Shipped policy beats LOO selection"* — `consensus_iptm_mean` was itself selected on
  Adaptyv (`f1bc405`); removing Adaptyv flips the sign.
- *"The de novo 0.91 does not reproduce"* — it does; it is a Simpson artifact (§6.3).
- *"LOO top-decile effect, z = +3.7, p < 0.0001"* — null assumed engine independence; real
  engines correlate 0.34–0.44. Corrected: **+0.07…+0.10, p ≈ 0.005–0.015**.
- Plus 2 further over-claims on enrichment arithmetic and an engine "inversion" that compared
  a 12-target screening macro against a 1-target affinity result.

## 10. Settled, open, and where the data lives

**SETTLED — do not re-investigate:**

- Metric/combination search on a labelled benchmark. Closed.
- Whether the shipped consensus leaves accuracy on the table. It does not (≤ 0.005).
- Whether Stage-1 did anything. It did not.
- Affinity ranking from structure confidence. Closed on 4 independent datasets.
- Scaffold family as a driver of screen performance (permutation p = 0.42).
- Engine-disagreement stratification (flat null).
- Cao's 0.56 ceiling is label censoring.

**GENUINELY OPEN:**

- **Why is Boltz-2 last on Cao?** Scaffold, length and target identity are excluded; the
  mechanism is unknown. Worth one focused look — Boltz-2 is our cheapest engine.
- **Does the label-cleaning effect generalise?** Adaptyv was never checked for the analogous
  assay-quality confound, and its ESMFold2 ipTM predicts *expression* at macro 0.680 —
  essentially equal to its binder AUC. That is an uncontrolled confound on our main
  comparator.
- **HEEH scaffolds screening worse within-target** — cheap to re-test on an independent set.
- **The LOO top-decile re-ranking effect** (+0.07…+0.10) — the only stratum that survived any
  null. Whether a re-ranking pass is worth it is untested.
- **Whether the screen holds at the top of a ranking** — the top-50 analysis had ~10 % power.
  Not disproved, untested.

**Data location.** `runs/` is gitignored, so nothing here is in the repo. Archived to MUNI at
`Project-01-BINDMASTER/EVALUATOR/cao_partU_2026-07/` — the merged table, the per-engine
augmented CSVs, `cao_lib.py`, every analysis script, and the assembled 654k-design master.
Deliberately **not** archived: the 2.4 GB of ESMFold2 structures and the 234 MB source
tarball (re-downloadable from the URL in §2).
