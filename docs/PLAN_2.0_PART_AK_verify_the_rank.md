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

## 0. Why this is needed — one number, two denominators

Our own wet-lab figure and the external benchmark figure are **both correct and are not the
same measurement**, and nothing records which is which at the point of use.

`CALCA_SPOC.csv` holds **125** designs: 99 with a numeric `KD`, 26 blank. Blank means *binding
not detected* **or** *not expressed* — two different outcomes sharing one empty cell. The diary
and the EuRosettaCon poster use **114** designs, stated as *99 binders, 15 non-binders*. So the
26 blanks split 15 / 11, and the exclusion criterion is **expression**, not score:

| label set | what it asks | within-target AUC |
|---|---|---|
| **114** — expressed only (99 binders vs 15 expressed non-binders) | can the metric rank binding among proteins that exist? | **~0.71** |
| **125** — full panel, non-expressed counted as non-binders | will a top pick yield a usable hit? | **0.4835** |

The second is the campaign question — a design scoring 0.9 that does not express is a failed
pick — so both belong in the record, each with its denominator.

**The external benchmark uses the same convention, and this was verified rather than assumed.**
`00_source_data/master_designs.csv` carries an `expressed` flag. On the all-3-engine labelled
subset, 20 of 563 designs are `expressed=False` and **all 20 are labelled non-binders** — the
identical conflation. Excluding them moves `consensus_iptm_mean` **0.7113 → 0.7093**, i.e.
**−0.002**. So the filter is the same; only the leverage differs. On Adaptyv it removes 6.6 % of
the negative class, on CALCA **42 %** (11 of 26). That is the whole explanation for why 0.711 is
robust and the CALCA figure moves by 0.22, and it is a property of negative-class size, not of
method.

**What is actually broken is provenance, not the number.** The 114 cannot be recomputed from
`CALCA_SPOC.csv` — that file has no expressed/tested column, so the poster's n exists only in the
poster and in the lab diary. This is the same class as the 662-vs-563 error caught on 2026-09-10,
and that entry's wording rule extends to it: **report *expressed* and *tested* separately whenever
an n sits next to an AUC**, exactly as *labelled* and *scored* already are.

CBG is insensitive either way (127 negatives) and reproduces: 0.4595 measured against the
recorded 0.496.

### What this does and does not say

It does **not** say either figure is wrong, and it does not touch the 0.711. It says the two have
different denominators, only one of which is written down where it is used, and that the
campaign-relevant reading is the stricter one. Verification is therefore about making the
denominator explicit and widening the evidence — not about replacing the metric.

## 1. Step AK0 — free, blocking, do before any GPU time

**Make CALCA's expressed flag recoverable.** Neither `CALCA_SPOC.csv` nor `CBG_SPOC_NEW.csv`
carries the column that distinguishes *expressed, no binding detected* from *not expressed* —
`master_designs.csv` has `expressed`, but that is the Adaptyv data, not ours. So the poster's
114-design split (99 / 15) cannot be reproduced from the file we share, and the two AUCs cannot
be reported side by side with their denominators. Add the column to the panel; both numbers then
follow from one file and neither needs explaining.

Also drop the 3 CBG rows marked `Duplicated, exclude` in its `Note` column — they were left in
today's 136-row figure. Too few to move it, but they should not be in a final table.

**Cost:** zero GPU. **Blocker:** needs the lab sheet or the operator, not compute.

## 2. Step AK1 — the GPU verification, staged so nothing big runs unattended first

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
