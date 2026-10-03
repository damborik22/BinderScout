# Does more engines mean less wrong? — measured on Cao 2022

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

## 3. The only statistically significant engine-set result points at REMOVING an engine

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

1. **Keep the gate and keep the 3-engine mean.** The premise holds about errors, the mean
   rescues 73 % of binders buried by one engine, and nothing measured here beats it by
   enough to justify a ranking change against Part U's bar.
2. **Do not ship shrinkage.** §5.0 is retracted; the cliff it was meant to fix does not
   occur on observed data.
3. **`mean(af3, esm)` vs `mean(all 3)` is the one live question** — significant on clean
   Cao, contradicted on Adaptyv by Part T §5. Settle it on a second pool before touching
   anything.
4. **Correct Part U's two sentences** so the next reader does not inherit them.
