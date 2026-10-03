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

## 0. Why this is needed — under the adopted label convention, both of our own targets are at chance

**Label convention, operator decision 2026-10-03: a design with no measured Kd is scored
`not bound`.** Not "untested", not "not expressed" — *not bound*, on both SPOC panels, unless and
until there is evidence of an expression failure for that design. The panels record a Kd or a
blank cell and nothing else, so an expression-based exclusion would be an assumption we cannot
support from the data we hold. This is deliberately the **conservative** direction: if some blanks
really were expression failures, they are unmeasured for binding and calling them non-binders adds
label noise that *deflates* AUC. The bias therefore runs against our own predictor, which is the
correct way round for a claim about it.

Applying it:

| pool | n | binders | within-target AUC |
|---|---|---|---|
| CALCA, full panel | 125 | 99 | **0.4835** |
| CBG / 2VDY, full panel | 136 scored | 10 | **0.4595** |
| curated Adaptyv/ProteinBase | 563 | 258 | **0.7113** |

**The external benchmark is unaffected, because its labels already follow this convention.** All
223 `expressed=False` rows in `master_designs.csv` carry `y = 0`. The 0.7113 we have always quoted
*is* the full-panel number; 0.7093 was the expressed-only variant, and the −0.002 gap between them
is simply how little the question matters when the negative class is large.

**What changes is CALCA.** The diary and the EuRosettaCon poster use **114** designs, stated as
*99 binders, 15 non-binders* — i.e. 11 of the 26 blanks excluded. Under the adopted convention
those 11 are non-binders, the panel is 125, and the figure is **0.4835** rather than ~0.706. CBG
barely moves (0.4595 against the recorded 0.496) because its negative class is 127, so a handful
of rows changes nothing. The leverage is entirely negative-class size: 11 of 26 is 42 % of CALCA's
negatives against 20 of 305, or 6.6 %, on Adaptyv.

**So: both of our own wet-lab targets measure at chance, while the external benchmark holds at
0.711.** That is the honest picture and it is the reason this part exists. It does not make the
0.711 wrong — it was verified independently here — but it does mean we have no *own-data*
corroboration of it, and that the one figure we had been citing as such does not survive the
convention we have now chosen.

### Consequences to carry forward

- **`docs/REPO_DIARY.md`'s 2026-09-10 entry** records "AUC 0.496 on CBG versus 0.706 on CALCA" and
  builds a between-target reading on the contrast ("pool mean iPTM tells you the target is
  tractable"). Under this convention the contrast is 0.4595 vs 0.4835 — **there is no contrast**,
  and that reading loses its support. A dated correction is appended to that entry rather than
  rewriting it.
- **The EuRosettaCon poster printed n = 114 with 99 binders / 15 non-binders.** That number is
  superseded, not merely re-derived. Worth knowing before the panel is cited again.
- **The wording rule from the 2026-09-10 Adaptyv *n* correction still applies** — report
  *labelled* and *scored* separately whenever an n sits next to an AUC — and now extends to the
  binder/non-binder rule itself: state that blanks are scored as non-binders.

## 1. Step AK0 — free, do first (no longer blocking)

**Re-state the SPOC figures under the adopted convention, and drop the 114-design split.**
No new data needed: CALCA is 0.4835 on 125 designs and CBG is 0.4595 on 136. Also drop the 3 CBG
rows marked `Duplicated, exclude` in its `Note` column, which were left in today's figure — too
few to move a 136-row AUC, but they should not be in a final table.

**Expression stays an open question, not a blocking one.** If expression data ever arrives for the
panel, the expressed-only figure becomes computable and worth reporting *beside* the full-panel
one; until then there is nothing to recover and no choice to make. This step is bookkeeping, not a
dependency — which is a change from this plan's first draft, where it was the blocker.

Also drop the 3 CBG rows marked `Duplicated, exclude` in its `Note` column — they were left in
today's 136-row figure. Too few to move it, but they should not be in a final table.

**Cost:** zero GPU, and no external input required.

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

| claim | now (n=563) | verified if |
|---|---|---|
| `consensus_iptm_mean` ranks | macro-AUC 0.7113 | holds within ±0.03 at n=2,018 |
| egfr is the weak target, not a small-sample artifact | 0.6478 (n=190) | stays < 0.70 at n=826 |
| nipah holds up | 0.7261 (n=211) | stays > 0.68 at n=1,030 |
| the 3-engine mean beats the average single engine | +0.047, p=0.0002 | sign holds on 4/4 targets |
| `agreement_count` is informative but saturates | 0.6295; rate 0.378/0.567/0.778/0.758 | 2-vs-3 still indistinguishable |
| the gate's rescue gradient | 92.9 % / 25.0 % / 0 % | monotone, 1-engine rescue > 80 % |

**If `consensus_iptm_mean` drops below ~0.65 at n=2,018, that is the finding** — and it would
mean the 563-design result was a coverage artifact, since coverage was never random: the 563 are
the designs that already got three engines.

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

## 6. Machine readiness, as measured 2026-10-03

Verified on BM2 so it does not need re-discovering:

| | status |
|---|---|
| GPU | RTX 3090, 24 576 MiB, **23 MiB used — idle** |
| Boltz-2 | `Mosaic/.venv/bin/binder-compare` present |
| AF3 | env present **and weights present** (`~/.alphafold3/models/af3.bin`) |
| ESMFold2 | env present, console script works |
| disk | ample (~1.5 GB of PAE for the whole of AK1) |

**One gap:** BM2's checkout is on `v1.1.x`, and all four envs are editable-installed against it,
so they predate `AF3_MIN_BUCKET`, `agreement_denom` and the `<binder_id>_<engine>` structure
naming. Any GPU work there needs `git checkout v2.0.x` plus `pip install -e 'Evaluator[report]'`
in all four — the `[report]` extra, **never** `--no-deps`, which leaves `binder-compare` unable to
start at all.

**BM5 and Clara could not be reached** from this session or from BM2 (neither resolves), so their
readiness is unverified.
