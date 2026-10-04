# How BinderScout ranks designs

**As of 2026-10-04.** There is one ranking and no way to select another. This file is the *why*
and the *what it is worth*; the per-column catalogue is in [metrics.md](metrics.md).

Every figure here is measured, with its pool and sample size named. Where a claim was retracted,
the retraction is stated rather than the claim removed — several were.

## 1. The answer, in one paragraph

There is **one** ranking and no way to select another. A design must have been refolded by
at least `--min-engines` independent engines (**default 3**: Boltz-2, AF3, ESMFold2); the
survivors are sorted by **`consensus_iptm_mean`**, the mean of the three engines'
**PAE-recomputed** ipTM. Designs failing the gate are ranked **last, not dropped**. The
output is a single `rank` column. Everything else the evaluator produces either feeds that
number, flags a caution for a human, or is reported for inspection — and the catalogue in
§6 says which, per column.

---

---

## 2. Why three engines — the Roman principle

**No single engine can put a design on a pedestal, or cast it into Tartarus.**

That is the design rationale, and it is **adversarial**, not statistical. It is not "three
measurements average out noise". It is that **any one engine can be confidently and
systematically wrong about an entire class of designs**, and you cannot know in advance
which engine or which class. The mean denies a lone engine the power to decide in either
direction: a single enthusiast is dragged down by the other two, and a single detractor is
outvoted by them.

### The mechanism is the mean itself

`consensus_iptm_mean` **is** the agreement rule — it is not an approximation of one, and a
vote count would be worse. A high mean requires all three scores high, so three must
effectively agree to promote. One dissenter drags the mean down **proportionally rather
than fatally** — the design survives, demoted. Two dissenters drag it under.

Measured on the canonical labelled pool, against real experimental labels — of true binders
buried in an engine's own within-target bottom quartile:

| buried by | rescued by the mean |
|---|---|
| exactly **one** engine (n=70) | **92.9 %** |
| **two** engines (n=20) | **25.0 %** |
| **three** engines (n=8) | **0 %** |

That gradient *is* "two will not kill it completely; three decide".

### The evidence for the no-veto half

**A single engine demonstrably buries a whole class of real binders.** AF3 scored the
`protrl` EGFR designs at a mean ipTM of **0.129** — Boltz-2 gave 0.911, ESMFold2 0.749 —
while **35 of those 44 designs bind experimentally**. Permutation p=0.0002, surviving
length adjustment; AF3's in-cell AUC 0.562 against ESMFold2's 0.752.

Two further instances exist **with a different engine at fault each time** (Boltz-2 on
bindcraft/EGFR, ESMFold2 on dsm-synteract/pd-L1), and **the worst engine changes on every
one of the four targets**:

| target | worst engine | 3-mean advantage over it |
|---|---|---|
| EGFR | AF3 | **+0.256** |
| IL7R | **Boltz-2** | +0.063 |
| Nipah | AF3 | +0.190 |
| pd-L1 | **ESMFold2** | +0.118 |

The 3-mean is **never worst**, on 4/4 targets. Each engine's *deviation from the other two*
also carries genuine incremental signal (partial Spearman vs binding, conditioning on the
other two: Boltz-2 **+0.314**, ESMFold2 **+0.213**, both p<1e-4).

### What this argument is NOT

**Three engines do not beat one or two on average on that pool** — `boltz+esm` 0.734 >
all-three 0.726 > `boltz` alone 0.720. Where three wins is **the worst case**. The value is
insurance, which is exactly why AF3 stays despite being weakest on average: on IL7R the
villain was Boltz-2.

**Two caveats on the rationale, both measured:**
- The variance half is **real but bounded**. One engine buries a true binder **5.69×** more
  often than all three together (CI [3.27, 18.39]; 11.4× at a bottom-decile cut) — but a
  random-ordering null gives **17.2×** (p=0.0008), so the engines are *not* independent
  votes. Error correlation within target and within class is ρ ≈ 0.39: **effective n =
  1.6–1.7 of 3**.
- Joint burial is **length-linked**: mean binder length 84.5 aa when no engine buries a
  true binder, **119.9 aa** when two do. That is the shared failure mode.
- **The design-time gaming does NOT transfer to refold time, measured.** Mosaic *is*
  Boltz-2 gradient hallucination, so its design-time objective is Boltz-2 confidence — but
  on the labelled pool Boltz-2 ranks Mosaic's designs **lower** than AF3 or ESMFold2 do
  (rel_boltz −0.0346, wrong sign on 2/2 targets), and the pre-specified gaming contrast
  fails overall (p(>0)=0.29). A refold is a fresh fold from sequence with an MSA. **Keep
  the no-veto argument; drop the "designers inflate their own engine's refold score" one.**
  *(The pedestal direction of the Roman principle is sound by the same arithmetic as the
  Tartarus direction, but has not been measured directly. Recorded as a gap, not a claim.)*

---

---

## 3. What the ranking is worth, and where it is blind

**This section belongs near the top of the final doc.** It is what decides whether a top-N
list should be trusted.

**Label convention (operator decision, 2026-10-03): a design with no measured Kd is scored
`not bound`** — not "untested", not "not expressed" — unless there is evidence of an expression
failure for that design. Our panels record a Kd or a blank and nothing else, so any
expression-based exclusion would be an unsupported assumption. The convention is deliberately
conservative: if some blanks were expression failures, they are unmeasured for binding and
counting them as non-binders adds noise that *deflates* AUC, biasing against our own predictor.

| pool | n | binders | within-target AUC |
|---|---|---|---|
| CALCA (our SPOC panel) | 125 | 99 | **0.4835** |
| CBG / 2VDY (our SPOC panel) | 136 scored | 10 | **0.4595** |
| curated Adaptyv/ProteinBase, 4 targets | 563 | 258 | **0.7113** |

The benchmark's labels already follow this convention — all 223 of its `expressed=False` rows are
`y = 0` — so 0.7113 is its full-panel figure and is unchanged by the decision. Only CALCA moves:
the diary and the EuRosettaCon poster use 114 designs (99 binders / 15 non-binders), excluding 11
blanks, and those 11 are non-binders here. CBG barely moves because its negative class is 127.

**Both of our own targets therefore measure at chance, while the external benchmark holds at
0.711.** The 0.711 is not thereby wrong — it was verified independently, including against its own
expression flag (−0.002) — but we have **no own-data corroboration** of it, and the figure we had
been citing as such does not survive this convention. Part AK exists for that reason.

**On a hard target the ranking measured at chance, and that part is unchanged.** On CBG the
`>= 0.85` slice bound at **6.8 %** against **10.0 %** below it (Fisher p=0.74) — the lever ran
backwards. Confirmed
to be our metric and not a proxy: the panel's `Mean_iPTM` matches `consensus_iptm_mean` on
135/137 designs to the decimal.

**The correct reading, from `docs/REPO_DIARY.md`:** pool mean ipTM tells you **the target
is tractable**, not **which design on a hard target will bind**. A between-target signal,
on n=2 targets. Conflating the two is the trap.

Corroboration that CBG is a *target* problem rather than a sampling-depth one: BoltzGen with
identical filters over ~10k designs per target gives `pass_filter_rmsd` ("folds as
intended") **80.3 % CALCA vs 5.2 % CBG**, while every composition filter behaves the same
on both. The collapse is structural.

**So: the ranking is a triage filter, not a decision procedure.** Expect ~1.5–2× enrichment
on a tractable target and nothing on a hard one. Nothing in the pipeline currently predicts
which kind of target you have before you spend the GPU — that is an open gap.

---

---

## 4. The pipeline, in execution order

```
  per-tool outputs                      extract (one extractor per tool)
         │                                      │
         ▼                                      ▼
   designs.csv / native CSVs            sequences.fasta + *_native_metrics.csv
                                                │
          ┌─────────────────────────────────────┼──────────────────────────────┐
          ▼                   ▼                 ▼                              │
      Boltz-2             AF3 v3.0.2        ESMFold2        (SoluProt / TmProt: label only,
   (Mosaic venv)       (binder-eval-af3) (binder-eval-esmfold2)  run BEFORE refolding)
          │                   │                 │
          └──── per-engine CSV + PAE .npy + structures ────┐
                                                           ▼
                                               binder-compare report
                                                           │
   merge on `sequence` (1:1 validated) → native metrics → shadow annotations →
   PAE loaded, ipTM + ipSAE RECOMPUTED per engine → agreement_count →
   consensus_iptm / _mean / _n → rank_designs → wetlab → metrics.csv + report.html
```

Engine detection is by **conda env name only** (`evaluate.sh:253-290`); nothing checks the
env can import its engine, so an empty env shell counts as installed. Boltz-2 is the
exception — it is resolved from `Evaluator/envs/mosaic_venv_path` and the run is **refused**
if its `binder-compare` is absent (`:228-241`).

**`--skip-<engine>` is not symmetric** (`evaluate.sh:561-643`): `--skip-boltz2` means
*reuse the existing CSV* and still passes it to the report; `--skip-af3` and
`--skip-esmfold2` mean *drop the engine entirely*, so an existing CSV is **not** passed —
and at the default gate of 3 every design then fails `passes_engine_gate`.

The exact `report.py` call order is load-bearing (a block placed before `rank` existed was a
real bug): `compute_statistics` runs at `report.py:385` while the consensus columns are added at
405–412, so `summary.json` and `metrics_zscore.csv` cannot contain `consensus_iptm_mean`,
`consensus_iptm_n`, `agreement_count`, `quality_tier` or `rank`. The per-tool statistics table
therefore omits the metric the pipeline ranks on. Known, not yet fixed.

---

---

## 5. The ranking itself

`rank_designs` (`scoring.py:828-936`):

1. **Refuses** `min_engines < 2` (`MIN_ENGINES_FLOOR`).
2. **Gate:** `consensus_iptm_mean.notna() & (consensus_iptm_n >= min_engines)`. Recorded in
   `passes_engine_gate`. Failures rank **last**, not dropped.
3. **Sort:** `passes_engine_gate` desc, then `consensus_iptm_mean` desc, then
   `consensus_iptm_n` desc (more engines behind an equal mean wins), then `consensus_iptm`
   (the **max**) desc, then binder pLDDT desc.
4. **When nothing clears the gate**, `passes_engine_gate` goes constant and stops
   discriminating, so the order becomes `consensus_iptm_mean` alone — and a design scored
   by **one** engine can outrank one scored by three. This is warned about loudly
   (`scoring.py:893-923`), because it is the single-engine failure the gate exists to
   prevent. The warning is **stderr only** and does not reach `report.html`.

**What is averaged:** `_ENGINE_IPTM_COLS` = `boltz_pae_iptm`, `af3_pae_iptm`,
`esmfold2_pae_iptm` — all **recomputed from the `.npy` PAE matrices** by
`add_iptm_from_pae_files` / `compute_iptm_from_pae` (`scoring.py:391-444`, `:600-663`),
*not* the engines' self-reported `*_iptm`, which are reported only. The kernel is
max(bt,tb) of `max_i[mean_j 1/(1+(PAE_ij/d0)²)]` with a global
`d0 = max(1.0, 1.24·∛(L−15) − 1.8)` and **no PAE cutoff** — deliberately different from the
ipSAE kernel, which uses a 10 Å cutoff and a per-residue d0.

**An engine contributes nothing unless its column name is in `_ENGINE_IPTM_COLS`.** The gate
counts list membership, not data: a populated `newengine_pae_iptm` left out of that list is
invisible (measured — `consensus_iptm_n` stayed 2; adding the name moved it to 3).

**The gate measures COVERAGE, not AGREEMENT** — how many engines produced a score. On every
labelled pool we own, coverage is 100 % constant, so the gate is **exactly inert** there
(within-target Spearman 1.000 between `min_engines` 2 and 3). Its value is entirely about
*missing* engines.

---

---

## 8. Removed — do not re-add

| removed | evidence |
|---|---|
| `--rank-by`, `active_rank` | honest nested selection over 72 metrics scored **0.5170** vs **0.5552** for `consensus_iptm_mean` alone (p=0.0014) |
| `--screen-metric`, stage-1 max screen, `passes_max_screen` | removed **0 designs** from the top-5/10/20/50 on 12/12 targets; the `max` default was documented as lenient and was the opposite |
| `adaptyv_rank` | `agreement_count` ranked ahead of the mean. Removal stands, but the stated reason does not: the "flat null" (0.532, 87.2 % tied) is a **Cao** figure, and on the registered pool it is **0.6295** — real signal, still below `consensus_iptm_mean`'s 0.711, and saturating above 2 |
| `consensus_rank` (max-ipTM) | max-ranking loses to mean-ranking, precision@top-10 % 0.79 vs 0.92 |
| `--soluprot-filter` | at its own default threshold it discarded several of the tightest measured binders; no threshold above 0.0 met the recall bar |
| AF2 refolding | Part I; BindCraft / PXDesign still use AF2 internally |
| Protenix refolding | Part J reverted; AF3 covers the independent cross-check |
| shrinkage on the gate | +0.0003…0.0006 macro AUC, CIs straddling zero, `k` unidentifiable — and coverage never varies, so it fixes a failure mode that does not occur |
| `mean(af3, esm)` | reversed with significance on a second pool (−0.0210, p<0.0001, 0/4 targets) |

---
