# Part AK — Verify the ranking (do not change its scope)

> Named **AK** because 2.0's parts run Y, Z, AA…**AJ**, and `V` is already spoken for:
> `docs/INVESTIGATION_partT_promera.md:203` reserves it for a Promera follow-up, and
> `PLAN_ranking_and_engines_roadmap.md` has its own Part X.

**Status:** planned, nothing launched. **Brief:** *"We do not want to change scope of our rank,
just verify it."* So: no new metric, no new engine, no re-weighting, no gate change. Same
`consensus_iptm_mean` behind the same `--min-engines` gate, measured on more labelled data than
it has been measured on so far.

Written 2026-10-03, after re-measuring `agreement_count` (draft §12.2) turned up a label problem
that matters more than the GPU work.

---

## 0. Why this is needed — one corroborating target, at n = 114 with a wide interval

**Corrected 2026-10-04.** This section twice asserted that both of our own wet-lab targets
measure at chance. That was wrong, and the error was mine: I labelled rows that were **never
ordered** as measured non-binders.

Both SPOC sheets carry a divider — below it, designs were not ordered, because of duplication.
On CALCA the `No` column simply restarts (…112, 113, 114, then 87, 89, 92…), and every row past
the restart has an empty `KD` and sits at the **top** of the pool by `Mean_ipTM` (0.938, 0.936,
0.929). They have no experimental outcome, so they cannot be non-binders.

| panel | n | split | AUC | 95 % CI (Hanley–McNeil) |
|---|---|---|---|---|
| **CALCA, as ordered and tested** | **114** | 99 / 15 | **0.7061** | **[0.581, 0.831]** |
| ~~CALCA, 11 never-ordered rows as y = 0~~ | ~~125~~ | ~~99 / 26~~ | ~~0.4835~~ | — |
| **CBG / 2VDY, as ordered and tested** | **114** | 10 / 104 | **0.4957** | **[0.308, 0.683]** |
| ~~CBG, 23 never-ordered rows as y = 0~~ | ~~137~~ | ~~10 / 127~~ | ~~0.4579~~ | — |
| curated Adaptyv/ProteinBase (unaffected) | 563 | 258 / 305 | 0.7113 | [0.668, 0.754] |

**CALCA's interval overlaps the benchmark's**, so our own wet-lab data *corroborates* 0.711
rather than contradicting it. The caveat that survives is **sample size, not sign**: 0.7061 rests
on **15** non-binders. Quote it with the interval.

**The diagnostic, worth keeping as a routine check on any label import.** Eleven rows cannot move
a 114-design AUC from 0.706 to 0.4835 unless they sit at the top of the ranking — and they do:
the CALCA 11 outrank **81 %** of the 99 confirmed binders (median ipTM 0.923 against the binders'
0.903). A supposed negative that outranks four fifths of the positives is far more likely to be
*unmeasured* than *negative*. That signature is visible without the divider.

**Two mechanisms produced the error, and the second is the instructive one.**

1. On CALCA I treated an empty `KD` as "tested, did not bind". The divider was already in the
   sheet; no inference about expression was ever required, and I did not look for one.
2. On CBG the sheet **did** distinguish the two cases — `N/A` for tested-and-not-bound, empty for
   never-ordered — and **`pd.read_csv` silently converts `"N/A"` to `NaN` by default**, collapsing
   104 real negatives into the same bucket as 20 unordered rows. Reading with
   `keep_default_na=False` recovers the distinction and reproduces 0.4957 exactly. A default that
   destroys the distinction being tested is the quietest kind of data loss.

### The label rule, restated

The boundary is **outcome availability**, not Kd presence:

> A design is labelled only if it has an experimental outcome.
> Ordered and tested, no binding detected → `not_bound`.
> Not ordered, or ordered with no result returned → **excluded** from binding AUCs, and
> reported as a separate count beside every *n*.

This supersedes the 2026-10-03 convention ("no measured Kd = not bound"), which was adopted on my
incorrect description of what the blanks were. The Adaptyv benchmark is unaffected either way: its
labels carry an explicit expression flag and all 223 `expressed = False` rows already carry y = 0.

**So AK survives, with a different motivation.** Not "both our targets are at chance" but: *one
corroborating target at n = 114 with a [0.581, 0.831] interval, and we want more.* AK1's sizing is
untouched — that was always about benchmark coverage, never about our panels.

## 1. Step AK0 — free, do first (no longer blocking)

**Done 2026-10-04 as part of the §0 correction.** Both panels are restated at **n = 114**, with
the never-ordered rows recorded as a separate count beside each *n* rather than folded into the
negatives:

| panel | n tested | binders | non-binders | excluded (never ordered) | AUC [95 % CI] |
|---|---|---|---|---|---|
| CALCA | 114 | 99 | 15 | **11** | 0.7061 [0.581, 0.831] |
| CBG / 2VDY | 114 | 10 | 104 | **23** (20 unordered + 3 flagged duplicates) | 0.4957 [0.308, 0.683] |

The 3 CBG rows marked `Duplicated, exclude` in the `Note` column are **outside** the 114 —
confirmed, they fall among the blanks, so no recompute is needed on their account.

**Remaining, and cheap:** the poster's claim is *comparative* — consensus 0.706 against the design
tools' own native score on the same 114 designs. Only the consensus side has been recomputed here,
so the native-score AUC should be redone at n = 114 to make the comparison reproducible from the
registry rather than from the poster.

**Expression is no longer the open question it looked like.** It never needed inferring: the
divider records what was ordered. If per-design expression data ever arrives it is worth reporting
beside these figures, not instead of them.

**Cost:** zero GPU, no external input.

## 2. Step AK1 — **DEFERRED, do not start** (operator: "nothing big", and no benchmark work now)

Kept here because the sizing is done and correct, not because it is queued. Nothing below runs
until it is explicitly asked for. The GPU being idle is not a reason to start it — AK0 above and
Part AF below are both ahead of it, and AF is cheap.

### Sizing, for when it is wanted

The external benchmark's own bottleneck is engine **coverage**, not labels. Of **2,018** labelled
designs, only **563** have all three engines:

| coverage | designs |
|---|---|
| 3 engines | 563 |
| 2 engines | 99 |
| **0 engines** | **1,356** |

And the gap is entirely in two targets — the two that score worst:

| target | labelled | binders | all-3 now | refolds to complete |
|---|---|---|---|---|
| egfr | 826 | 128 | 190 | 1,788 |
| nipah | 1,030 | 103 | 211 | 2,379 |
| il7r | 96 | 60 | 96 | **0 — complete** |
| pd-l1 | 66 | 32 | 66 | **0 — complete** |

**4,167 single-engine refolds** takes the verification set from 563 → 2,018 (3.6×), egfr from
190 → 826 (4.3×) and nipah from 211 → 1,030 (4.9×). Same metric, same gate; strictly more
evidence. It also removes the 99 two-engine rows that today cannot reach `agreement_count = 3`.

### AK1a — pilot (~1 GPU-hour, run attended)

1. **Reproducibility control first.** Re-refold **20 designs that already have all three
   scores** and confirm the new values match the stored ones. This is the step that earns the
   right to spend the rest: 4,167 refolds from an unvalidated harness are worth nothing, and a
   drifted env or a changed model revision would be invisible in the aggregate.
2. Then ~60 uncovered nipah designs × 3 engines = 180 refolds, to **measure** per-design wall
   time and VRAM per engine. The only cost figure available is "~30 GPU-h per 500-design
   3-engine pool" from the benchmark README, which implies ~83 GPU-h for 4,167 — replace it with
   a measurement before committing.
3. Confirm each engine's `--buckets` floor behaviour on these lengths (`AF3_MIN_BUCKET = 256`).

### AK1b — the unattended run

Shard by target: **egfr on one machine, nipah on the other.** They are independent, there is no
cross-target join, and a failure on one leaves the other's output usable.

- **BM5 (GB10): size by query, never by a copied number.** The GPU pool is system RAM there, so
  an uncapped job reboots the box. `ssh bm5 'bash -lc "~/dev/BinderScout/tools/gpurun --max"'`
  and dispatch through `tools/gpurun --cap` for a driver-enforced ceiling.
- **Clara:** check node-hogging etiquette — there is a prior incident on record (`1ebc73e`).
- Append-mode CSVs: `refold_boltz2.py` appends, so a resumed run can duplicate `run_id`. Use
  `--resume` and de-duplicate before analysis.
- The target MSA is cached per target by SHA-256 and shared by all three engines, so pre-warm
  once per target and no engine re-queries ColabFold.

## 3. What AK1 verifies, stated so it can fail

Pre-registered, with today's 563-design values as the prediction. **No metric is being selected
here** — each is a pass/fail on an existing claim:

| claim | now (n=563) | verified if | refuted if |
|---|---|---|---|
| `consensus_iptm_mean` ranks | macro-AUC 0.7113 | **≥ 0.681** at n=2,018 | **< 0.681** |
| egfr is the weak target, not a small-sample artifact | 0.6478 (n=190) | stays < 0.70 at n=826 | ≥ 0.70 |
| nipah holds up | 0.7261 (n=211) | stays > 0.68 at n=1,030 | ≤ 0.68 |
| **the 3-engine mean beats the BEST single engine out of fold** | **+0.0026, p=0.69** | a positive effect that keeps its sign on 4/4 LOTO folds | anything less |
| (weak form, recorded only) 3-mean beats the *average* single engine | +0.047, p=0.0002 | — | — |
| `agreement_count` is informative but saturates | 0.6295; rate 0.378/0.567/0.778/0.758 | 2-vs-3 still indistinguishable | 3 > 2 by a margin that survives LOTO |
| the gate's rescue gradient | 92.9 % / 25.0 % / 0 % | monotone, 1-engine rescue > 80 % | non-monotone |

**One threshold, not two (D2, 2026-10-04).** An earlier draft said "holds within ±0.03" *and*
"below ~0.65 is the finding", which left **0.65–0.681 in neither bucket** — and since benchmark
coverage was never random, that gap is exactly where a coverage-selection effect would land. The
rule is now a single cut at **0.681**: at or above it the 563-design result survives the 3.6×
expansion; below it, the result was a coverage artifact, because the 563 are precisely the designs
that already got three engines.

**The ensemble row is the strong form now (D4, 2026-10-04).** It previously read "beats the
*average* single engine, +0.047, p=0.0002" — which §7 of this same document already reports as the
weak form: the 3-mean does **not** beat the *best* single engine out of fold (+0.0026, p=0.69) and
`mean(boltz, esm)` out-scores it (0.7279 vs 0.7231). As written the row could pass while the thing
worth knowing failed. The weak form is kept on its own line, marked as recorded-only.

## 4. Explicitly out of scope

- No new ranking metric, no re-weighting, no normalisation (operator decision, draft §12.4), no
  engine added or dropped, no gate threshold change.
- No unanimity "rescue" flag (draft §12.3 withdrawn — its evidence is unreproducible, and 3/3 is
  not separable from 2/3 on the data we have).
- No search over metrics. Part U measured that honest nested selection over 72 metrics scores
  **0.5170** against **0.5552** for `consensus_iptm_mean` alone. Verification only.


---

## 5. Parked — benchmark *expansion* is not part of this, and not wanted now

Recorded so the measurement is not repeated, and flagged as **acquisition, not verification** —
which is why it is out of scope here. It came up while sizing AK1 and was pushed the wrong way
before being corrected.

`00_source_data/master_designs.csv` carries **2,517 labelled designs across 24 targets**, but
target sequences exist for only **4 names** (`egfr`, `il7r`, `nipah`, `pd-l1`) in
`01_refold_inputs/*/target_seqs.json`:

| | targets | labelled designs |
|---|---|---|
| target sequence available | 4 (3 usable — see nipah below) | 988 |
| **no target sequence** | **17** | **1,529** |

Several of the unavailable ones are far better balanced than what we use today — spcas9 70 %
binders, human-insulin-receptor 60 %, human-pdgfr-beta 60 %, human-mzb1-perp1 50 %, human-phyh
50 %, against EGFR's 15.7 % — so a 17-target macro-AUC would be a much stronger basis than a
3-target one. **That is a reason it would be valuable later, not a reason to do it now:** it means
sourcing 17 target sequences and refolding ~1,529 new designs, which is new benchmark data, not a
check on the ranking we already ship.

### One data-integrity problem to settle before *any* future use of this table

`master_designs.csv` has **`nipah-glycoprotein-g`: 927 designs, 1 binder (0.1 %)**, while the
merged 3-engine table has **`nipah`: 1,030 labelled, 103 binders (10 %)**. Similar names,
incompatible label sets, and almost certainly two different sources — there is a separate
`00_source_data/proteinbase_collection_nipah-binder-competition-results.csv`. Nipah is the single
largest block in both tables, so this is not a rounding difference and it must be resolved before
either number is cited. Four further targets (human-serum-albumin 103, human-tnfa 35, human-orm2
30, human-gm2a 30) have **zero** binders and cannot contribute a within-target AUC at all, though
they are usable as negative controls.

## 6. Where AK1 runs — **Clara, dispatched by BM4** (operator, 2026-10-04)

AK1 is Clara's job, orchestrated by BM4 as fleet manager. The readiness notes below are kept
because they were measured, not because BM2 is the target.

**Readiness means *executes one design end to end*, not *installed*.** This is the plan's own
lesson — verify the real interface, not a proxy — and an earlier version of this table broke it by
marking BM2 ready on "env present and weights present". Two separate things on this fleet have
already hidden behind that: BM5's `binder-eval-af3` and `binder-eval-esmfold2` were
editable-installed against a **different checkout** and so were not running `AF3_MIN_BUCKET` at
all, and Protein-Hunter's env on BM5 is a ~198 MB empty shell. Both passed "installed".

| machine | state, 2026-10-04 |
|---|---|
| **Clara** | AK1's target. Readiness **not yet verified by execution** — do that first |
| BM2 (RTX 3090, sm_86) | on `v2.0.x`; all four envs verified against the repo path; **AF3 executes here** — `iptm 0.88, ptm 0.85` on a real 258-token complex, and a 60-vs-256 bucket pair confirms the `AF3_MIN_BUCKET = 256` floor is what made it work. Currently running the Part AF Chai-1 study |
| BM5 (GB10, aarch64) | on `v2.0.x`; sweep 24 pass / 1 fail (the fail is PH's empty env shell); the two mis-pointed eval envs re-pointed |
| BM3 (RTX 3060, 12 GB) | **engineering/CI box — must never produce authoritative refolds.** ESMFold2 cannot run at any size here (14.2 GB floor), and Boltz-2 fails outright at 600 and 900 tokens on 24 GB, let alone 12 |

**A claim that must not be reintroduced:** "no 3090, 4090 or 3060 can run AF3 regardless of
tokens, because tokamax requests 110,592 bytes of shared memory against sm_86's 101,376." That was
believed on 2026-09-27 and is **false** — it was our own missing bucket floor. `refold_af3.py`
computed `bucket = len(target) + max(len(binder))` with no lower bound, so a 60-token pool asked
AF3 for a shape its stock ladder never produces. With `AF3_MIN_BUCKET = 256` the same input runs.
The shared-memory figure is real; the conclusion drawn from it was not.

## 7. Part AF follow-on — pre-registration for the Chai-1 adoption study

**Written before the data exists, deliberately.** The question is "could Chai-1 be our fourth
engine", which is an adoption decision, and CLAUDE.md already records the trap: *"Do NOT
re-litigate the engine set on one pool… Four single-pool effects were retracted in the week of
2026-09-29. Treat a single-pool effect as a hypothesis, not a result."* Fixing the criteria first
is the only thing that makes a single-pool answer worth having.

### MSA parity is mandatory, and the pilot proves why

Our three engines read a cached target MSA; the binder is `use_msa=False`. Chai-1 accepts
`msa_directory` holding `.aligned.pqt` files keyed by `expected_basename(sequence)`, so converting
our cached a3m with `a3m_to_aligned_dataframe` reproduces that arrangement exactly — target
aligned, binder single-sequence (the run log confirms `No MSA found for sequence: SKLEEIKRL…`,
which is the binder).

**Measured on one design, and it changes the conclusion of the first AF run:**

| | iPTM on a **confirmed non-binder** |
|---|---|
| Boltz-2 | 0.905 |
| ESMFold2 | 0.827 |
| **Chai-1, MSA parity** | **0.818** |
| AF3 | 0.52 |
| Chai-1, MSA-free | **0.285** |

The first AF run's striking result — Chai-1 alone rejecting a non-binder that two of our engines
rank highly — was **an artifact of running it MSA-free**. With parity it behaves like Boltz-2 and
ESMFold2 and makes the same mistake. This is the calibration confound flagged in the AF write-up,
confirmed in one shot: a uniformly less-confident engine rejects binders and non-binders alike.
**Had the 563-design study been run MSA-free it would have produced a false positive for
adoption.**

Cost also revises down: **118 s per design** with MSA (the 346 s in the AF run included cold model
load), so 563 designs ≈ **18.5 GPU-h**, not the 48–54 estimated.

### Criteria, fixed in advance

Chai-1 is worth adopting only if **both** hold:

1. **It carries incremental signal.** Partial Spearman of `chai_iptm` against binding, conditioning
   on the other three engines' iPTM. The standing precedent on this pool is Boltz-2 **+0.314** and
   ESMFold2 **+0.213**, both p<1e-4. **Pass: |partial| ≥ 0.15 with p < 0.01.** A high solo AUC with
   a near-zero partial means it is a fourth copy of an opinion we already have, which costs
   GPU-hours and buys nothing.
2. **The effect keeps its sign across all four leave-one-target-out folds.** This is the test that
   killed `mean(af3,esm)`, which looked good on exactly this pool and reversed on the next.

Reported alongside, not as criteria: solo macro-AUC against the other three; whether Chai-1
rescues true binders that all three of ours bury (the adversarial rationale); and per-target
breakdown.

### Explicitly NOT a criterion

**"`mean(4)` beats `mean(3)` on this pool" does not justify adoption.** On this very benchmark the
3-engine mean does not beat the best single engine out of fold (+0.0026, p=0.69) and
`mean(boltz,esm)` out-scores it (0.7279 vs 0.7231). A 4-mean improvement here would be the same
class of evidence as effects already retracted, so it is recorded and not acted on.

### If it passes

Adoption is still a second step, because a fourth engine **re-scopes the rank**: `--min-engines 3`
silently becomes "3 of 4", and `consensus_iptm_mean` over four engines is not the metric Part U
validated. Both need re-deriving against the labelled pool before any default changes.
