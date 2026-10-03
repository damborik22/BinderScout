# Does more engines mean less wrong? — measured on Cao 2022

> ## ⚠️ POOL SUPERSEDED, 2026-10-03
> **Cao 2022 is not to be used as a benchmark** (operator decision, same day, for the
> reason this investigation independently measured: its Kd labels are too censored).
> 73.4 % of its binder labels are one-sided, 94.2 % across the full library, `kd_ok` keeps
> ~495 designs, and **8 of 12 targets sit at the random-ordering noise floor**.
>
> **Everything in §1 and §2 below was computed on Cao and is therefore PROVISIONAL.** The
> §3 retraction is unaffected — it retracted a Cao claim *using* the Adaptyv benchmark,
> which is the right direction.
>
> **RE-MEASURED on the canonical pool the same day — §1 REPLICATES.** 8 of 9 numbers
> reproduce within noise and none reverses: premise ratio **5.69×** CI [3.27, 18.39]
> (Cao 5.2×, sitting mid-CI), bottom-decile 11.44× (Cao 10.5×), error correlation
> **ρ 0.389 Spearman** (Cao 0.382), effective n **1.63–1.69** of 3 (Cao 1.70), rescue
> 92.9 % / 25.0 % / 0 % for binders buried by 1 / 2 / 3 engines (Cao 73.2 / 27.5 / 0 — the
> mean works *better* here). A label-permutation null confirms these are genuinely errors
> (burial 0.175 vs 0.247 for arbitrary designs, p<0.0001). See §6.
>
> The canonical benchmark is the curated **Adaptyv/ProteinBase** set under
> `EVALUATOR/Benchmark/` on the MUNI share (563 designs with the full PAE panel, 4 targets,
> replicated binding calls). The premise numbers below — the 5.2×, the ρ ≈ 0.382, the
> 73.2 % rescue rate — **need re-measuring there.** Nothing should be built on them until
> that is done.

**Date:** 2026-10-03 · **Pool:** `cao_merged.csv`, 4,442 designs, 12 targets, 2,042 binders
(`kd_lb < 1000 nM`), 100 % three-engine coverage. Aggregates only; no per-design data.

The question, as put: *"There is always a chance that the 3-engine mean is worse than 1
engine. But the chance that 1 engine is wrong has to be much bigger than 3."*

That had never been measured on our own data. It now has, and it splits cleanly into a
claim about **errors** (true) and a claim about **ranking** (not true).

---

## 1. The premise is TRUE, about errors

Define "badly wrong" as burying a true binder in an engine's own within-target bottom
quartile.

| | P(one engine buries it) | P(all three bury it) | ratio |
|---|---|---|---|
| all labels (2,042 binders) | 0.224 | 0.044 | **5.2×** |
| clean labels (543 binders) | 0.124 | 0.016 | **7.6×** |

Robust to the cut, and the ratio *grows* as it sharpens: bottom-10 % → **10.5×**,
bottom-25 % → 5.2×, bottom-50 % → 2.3×. It holds in the false-alarm direction too — one
engine spuriously tops a non-binder 3.8× more often than all three do.

**How independent are they, really?** Perfect independence would give 19.9× (all labels) /
65.5× (clean); identical engines 1.0×. Observed sits roughly halfway on a log scale — the
three engines are *genuinely partly independent*, not redundant. Error correlation measured
**within target and within class** (so neither target difficulty nor the binary signal
inflates it) is **ρ ≈ 0.382**, giving a variance-reduction factor of 0.588 at k=3 —
**effective n = 1.70 of a possible 3.00**.

**What the mean demonstrably rescues**, which is the gate's real measurable benefit:

| true binders buried by… | n | rescued by the 3-engine mean |
|---|---|---|
| exactly one engine | 557 | **73.2 %** |
| two engines | 273 | 27.5 % |
| all three | 97 | 0 % |

## 2. But it does NOT translate into a better ranking

| claim | result |
|---|---|
| 3-mean beats the **average** single engine | **TRUE** +0.0088 macro AUC (clean +0.0167); vs Boltz-2 +0.0271, p=0.0052, 11/12 targets |
| 3-mean beats the **best** single engine | **FALSE** −0.0052, p=0.449 (clean −0.0224, p=0.070). AF3 alone: 0.5603 vs the mean's 0.5552 |

The best engine is AF3, and the out-of-fold pick is AF3 on **12/12** leave-one-target-out
folds — so this is not a selection artifact.

**Why the premise does not carry over.** Variance reduction assumes *equal error variance*.
Boltz-2 breaks that: it is simultaneously the most decorrelated engine (ρ 0.34) and the
weakest (macro AUC 0.528). Averaging it in buys independence and pays in noise. The
3-mean's own burial rate (0.2211) sits *inside* the engine-to-engine spread
(0.2128 … 0.2399), i.e. the mean is not less often wrong than a good single engine.

A per-target counterexample worth keeping: on Tie2 (clean) the engines score 0.312 / 0.462
/ 0.579 and the 3-mean lands at **0.336** — worse than two of the three it averages. The
raw mean inherits a failing engine rather than outvoting it.

## 3. ~~The only significant engine-set result points at REMOVING an engine~~ — **RETRACTED 2026-10-03, replication**

> **It does not replicate. It reverses, with significance, and the originating effect does
> not survive Cao's own label-quality flag. Three independent failures:**
>
> **(a) It dies on Cao's own flag.** My "label-clean" slice was *positives with a finite
> `kd_ub_num`*. Cao ships `kd_ok` — `kd_lb<1000 & ~avid_doesnt_agree & ~low_conf &
> kd_ub/kd_lb ∈ [1,10]` — and **Part U's own archived script uses it**. On `kd_ok` the
> effect is **−0.0097, p=0.673 — a sign flip**. The 48 designs separating the two
> definitions *all* have `kd_lb_num == 0.0`: a Kd interval of [0, X], an upper bound with a
> degenerate lower bound, not a two-sided measurement. They are concentrated — H3 22 of its
> 24, Tie2 4 of 4 — and **Tie2 exists as a 12th target only because of them** while
> carrying the largest per-target delta (+0.1275 on 4 positives). Dropping Tie2 halves the
> effect to +0.0113.
>
> **(b) I bundled two different slices.** The "+0.153 enrichment, p=0.031" and "3-mean wins
> only 3/12" are the **all-labels** numbers. On the slice that carries the AUC effect,
> enrichment delta is **+0.0000 (p=2.0, 0/12 wins)**. The effect and its stated
> corroboration came from different label definitions, and I reported them as one finding.
>
> **(c) Adaptyv is the exact mirror image.** On the curated benchmark (563 designs, 4
> targets, 100 % coverage): **−0.0210, CI [−0.0309, −0.0095], p<0.0001, af3+esm wins 0/4
> targets**, under *both* metric panels. It independently reproduces the benchmark's own
> prior measurement (−0.0190, p<0.001, 0/4).
>
> **And the mechanism inverts.** My stated reason was "Boltz-2 is simultaneously the most
> decorrelated and the weakest". On Adaptyv Boltz-2 is the **strongest** engine
> (0.7204 vs AF3 0.6134, ESMFold2 0.6933) while being *equally* decorrelated (within-target
> Spearman 0.380 Cao / 0.384 Adaptyv). So there the independence is bought without paying
> noise — which is precisely why the sign reverses. The proposed change would have **dropped
> the strongest engine on the benchmark the shipped metric was validated against.**
>
> Context that should have been in the original: on Cao's all-labels slice **8 of 12 targets
> sit at the random-ordering noise floor**, so the question was being settled on 4
> informative targets. And the denovo holdout cannot adjudicate — its minimum detectable
> effect is ±0.133, **6.3× larger** than the 0.021 in question, and `mean(all 3)` at 0.6709
> falls *inside* the null interval [0.335, 0.670].
>
> **Conclusion: keep all three engines and the shipped `consensus_iptm_mean`.** Part T §5's
> "every engine earns its slot" stands; my AUC argument against it was a single-pool,
> single-slice artifact.

### (superseded) The claim as originally reported

**`mean(af3, esmfold2)` beats `mean(all three)`:** clean labels **+0.0210 macro AUC,
95 % CI [+0.0040, +0.0440], p=0.0078**, with the 3-mean winning only 3/12 targets;
top-5 % enrichment +0.153, p=0.031. On all labels +0.0064 (p=0.338).

That is the opposite direction from Part AF, which asks whether to add a fourth.

**Do not act on it yet.** One pool; the clean subset keeps 6 of 12 targets and 543 of 2,042
positives, with FGFR2 alone holding 225 of them; and Part T §5 measured that dropping
Boltz-2 loses uniquely-caught binders on a *different* pool (Adaptyv). Part T §5.1 is the
standing warning: a within-pool "free win" there reversed sign on independent data.

Also checked and null: z-scoring each engine before averaging changes nothing
(+0.0010, p=0.54), so the shipped raw mean is not losing anything to scale mismatch.

## 4. Shrinkage: NULL, and the question is mostly moot

Proposed on 2026-10-03 (conclusion §5.0) as the principled fix for the empty-gate cliff.
Tested: `(n·mean + k·pool_mean)/(n + k)`, k fitted leave-one-target-out.

- vs the raw mean: ΔmacroAUC **+0.0003 … +0.0006**, every CI straddling zero, and **worse**
  on precision@top-10 % in **8/8** regimes (significantly in 3).
- `k` is **unidentifiable**: the objective spans 0.0013 across the entire k grid, and the
  LOTO fit selects both k=0 and k→∞ in every configuration.
- Whatever it gains over the *current* rule comes from **having no gate**, which the raw
  mean does for free.

**And the premise behind my own proposal was wrong.** Coverage is **100 % constant on every
labelled set we own** — Cao 4,442/4,442, denovo 110/110, Adaptyv 563/563. In the only
missingness mode we have real evidence of (an engine's env absent, or a pool's PAE files
unresolvable — 50 Adaptyv rows lost *all three* engines at once), coverage is constant and
the gate, the raw mean and shrinkage at any k are **provably the same within-target
ranking**. The regime where the three rules differ — per-design heterogeneous coverage —
has never been observed on labelled data. The strand had to simulate it.

## 5. Two of Part U's supporting claims must be withdrawn

Part U's headline survives: the 73.41 % one-sided-Kd figure reproduces **exactly**, and the
0.5552 → 0.7228 lift on label-clean positives reproduces to four decimals. "Cao's ceiling
is mostly label censoring" stands. (On the full 654,716-design library the censoring is
**94.21 %**.)

Two supporting sentences do not:

1. **"This is not circular reasoning from the same Kd fit" — wrong.** `binder_4000_nm` is
   predicted by `kd_ub < 4000` at MCC 0.819 / κ 0.807, with 490 disagreements in 654,716
   rows (0.075 %). Two-sidedness *alone* predicts it at 47.5 % vs 0.032 % — a 1,490× ratio
   — irrespective of the binder label. The contrast and its corroborator are both functions
   of whether the titration produced an upper bound. (Residual independent signal does
   exist: 0.900 vs 0.332 within two-sided designs, and 41 library-wide designs pass at
   4 µM with no Kd bound at all.)
2. **"Experimentally indistinguishable from non-binders" — false.** One-sided Kd-binders
   pass `binder_4000_nm` at **8.7×** the rate of Kd-non-binders (p=4.2e-62), and **32×** at
   400 nM (p=3.5e-09). They are weaker, not indistinguishable.

Consequence for method: Cao can answer "3 engines vs an *arbitrary* single engine", and
must not be used for "3 engines vs the *best* single engine" without this caveat attached.

## 6. What to do

1. **Keep the gate, the 3-engine mean, and all three engines.** §3 is retracted: the
   engine-set change reverses with significance on Adaptyv and does not survive Cao's own
   `kd_ok` flag.
1. ~~Keep the gate and keep the 3-engine mean.~~ The premise holds about errors, the mean
   rescues 73 % of binders buried by one engine, and nothing measured here beats it by
   enough to justify a ranking change against Part U's bar.
2. **Do not ship shrinkage.** §5.0 is retracted; the cliff it was meant to fix does not
   occur on observed data.
3. ~~`mean(af3, esm)` vs `mean(all 3)` is the one live question.~~ **SETTLED, negative** —
   see the retraction in §3. It was settled on the second pool, and the answer is no.
4. **Correct Part U's two sentences** so the next reader does not inherit them.


---

## 6. Re-measured on the canonical Adaptyv benchmark (563 designs, 4 targets, 258 binders)

Cao excluded per the operator decision. 100 % three-engine coverage;
`compute_consensus_iptm` reproduced from the shipped code to 2.2e-16.

### 6.1 The premise replicates — and is bounded by correlation

Covered in the banner above. Two additions beyond replication:

**The gate's benefit is capped by how correlated the engines are.** Observed ratio 5.69×
against a **random-ordering null of 17.19×** (null 95 % [7.84, 80.50], p=0.0008). Perfectly
independent engines would give ~17×; correlation costs roughly two thirds of the achievable
ratio. So "three engines protect you 5.7× better than one" is right, and "they are
independent votes" is not.

**Joint burial is length-linked**, which names the shared failure mode instead of leaving it
as noise. Mean binder length of true binders by number of engines burying them: k=0 **84.5
aa**, k=1 94.7, k=2 **119.9**, k=3 113.4. Consistent with the long-binder penalty already
recorded against `ipsae_min`.

Not resolved on this pool: the **false-alarm** direction fails its null (p=0.071), so only
the binder-burial half of the premise is established here.

### 6.2 The engine panel — and why we still change nothing

| scorer | macro AUC | 95 % CI |
|---|---|---|
| max of 3 | 0.7361 | [0.686, 0.784] |
| mean(boltz, esm) | **0.7279** | [0.677, 0.776] |
| **mean of 3 (shipped)** | **0.7231** | [0.673, 0.771] |
| boltz-2 | 0.7204 | [0.670, 0.769] |
| mean(boltz, af3) | 0.7125 | [0.662, 0.760] |
| mean(af3, esm) | 0.7021 | [0.652, 0.750] |
| esmfold2 | 0.6933 | [0.641, 0.743] |
| af3 | 0.6134 | [0.562, 0.663] |

- **The §3 retraction is confirmed:** `mean(af3,esm)` loses to the 3-mean by exactly
  −0.0210, on 4/4 targets.
- **But the untested direction looks better:** `mean(boltz,esm)` *beats* the 3-mean, and on
  the deployment metric by **+14 binders at top-20 (p=0.0012)** and +17 at top-50 (p=0.0024).
- **AF3 is significantly anti-predictive on one target** — egfr AUC 0.394, P(AUC ≥ 0.5) =
  0.008 — and that single target carries most of the apparent gain from dropping it.

**We change nothing, for four reasons that do not rely on deferring to Part U:**

1. **At the shortlist sizes we actually ship (N = 3–8) the entire panel is within ±4
   binders** — the choice is unmeasurable. The advantage only appears at N ≥ 15, deep in a
   list nobody orders from.
2. **Drop-AF3 does not keep its sign across leave-one-target-out folds of this very pool**
   (−0.017, +0.008, −0.002, +0.030). It fails an out-of-fold test needing no second dataset.
3. **It inverts on the secondary pool**, where dropping Boltz-2 gains +0.071 and dropping
   AF3 gains nothing.
4. **Unique catch — the measure that would have defended the status quo — fails its own
   random-voter null for two of three engines.** It supports neither the change nor the
   default.

### 6.3 Three claims of ours to weaken, not strengthen

1. **"No engine wins everywhere, so keep all three because dropping any one loses uniquely
   caught binders."** Not supported by its own null: the unique-catch measure fails a
   random-voter test for two of three engines. Keep all three — but not for this reason.
2. **The "do not drop Boltz-2" result's p-value.** Recorded as p<0.001; measured here as
   **p=0.035**, with the direction and the 4/4 target split intact. Real, weaker than stated.
3. **The implicit claim that the 3-mean is at least as good as the best single engine is
   false.** Out of fold the 3-mean beats the *average* single engine (+0.0474, p=0.0002) but
   **not the best** (+0.0026, p=0.69).

### 6.4 The caveat that limits all of §6

**`consensus_iptm_mean` was itself selected on this dataset** (the Benchmark's own README
records this as an open item), so §6.2 is **not** an independent validation of the shipped
metric — only a check that it is not beaten by an obvious alternative on the pool it came
from. A genuinely independent engine-set test needs a pool neither the metric nor the
engines were tuned on, and we do not have one.

Also: four targets, macro CIs ±0.05 wide, every target-level sign count out of 4. The gate
itself is **exactly inert** here (within-target Spearman 1.000, max rank difference 0 between
`min_engines` 2 and 3) because coverage never varies — consistent with §4.
