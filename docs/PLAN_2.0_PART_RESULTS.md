# BinderScout 2.0 — result for every part

One row per lettered part of [PLAN_binderscout_v2.md](PLAN_binderscout_v2.md), with
what was actually established. **A "result" here is not always "done"** — for the
parts blocked on a model, on labels, on GPU-hours or on archived pools, the result
is a verdict with the evidence behind it, which is what lets the next person decide
rather than re-derive.

Companion to [PLAN_2.0_CONCLUSION.md](PLAN_2.0_CONCLUSION.md) (the narrative
state). As of `v2.0.x`, 893 tests, ruff + shellcheck clean.

---

## Summary

| part | subject | result |
|---|---|---|
| **AD** | discovery rank / `generation_index` | **Half shipped.** Extraction + provenance done across 5 tools; the metric is blocked on a decision |
| **Y** | private label registry | **Shipped as a library.** One naming collision to settle before anything consumes it |
| **AA** | cheap pre-GPU screens | **3 of 6 shipped.** Two need models, one closed, promotion needs labels |
| **AB** | diversity | **Not built — but now measured, and the measurement says build it** |
| **AC** | seed aggregation | **DONE.** The hazard was live; fixed and guarded |
| **Z** | staged cheap-filter | **Not started.** Buildable; not validatable here |
| **AE** | tool racing | **Verdict: defer.** Needs the fleet; no evidence it is the bottleneck |
| **AF** | fourth engine (Chai-1) | **Verdict: reopen — its original rationale is dead, a stronger new one is live** |
| **AG** | fleet/Clara benchmark consumer | **Not started.** Blocked on Y's naming + GPU-hours |
| **AH** | BindPred | **Not started.** Needs the model; shares one runner with AA's A1 |
| **AI** | tune Mosaic's design loss | **Verdict: defer**, and it conflicts with a measured result |
| **AJ** | MD reverse check | **Verdict: do not build now.** No tooling, and the premise is weak |

**2½ of 12 complete.** Four (AE, AF, AI, AJ) had *zero* prior coverage; they now
have verdicts rather than silence.

---

## AC — seed aggregation · **DONE, and it was a live defect**

The plan listed this as a hazard already running in production (item G10). It was.

`merge_refold_results` joined the engine CSVs with
`pd.merge(..., on="sequence", how="outer")` — many-to-many. K duplicate rows for
one sequence in each of N engines produced **K^N** rows for that one design.
Measured on the 6-design golden pool, duplicating a single shared sequence:

| duplicates | total rows (should be 6) | that design occupies |
|---|---|---|
| 2 in boltz2 only | 7 | 2 |
| 2 in boltz2 + af3 | 9 | 4 |
| 2 in all three | 13 | **8** |
| 3 in all three | 32 | **27** |

Not cosmetic: percentiles, top-N, per-tool means, z-scores and `rank` are all
pool-relative, and the merger's own banner reported the inflated count as "unique
sequences".

**Reachability, checked rather than assumed.** `extract` deduplicates by sequence,
so two tools emitting the same binder cannot trigger it; AF3 collapses its seeds
into one row. What remains is the documented append path — CLAUDE.md: *"refold_
boltz2.py appends to CSV. If rerun after partial failure, check for duplicate
`run_id` entries."*

**Fixed** by deduplicating in `_load_engine` with a warning that names the engine,
the count and the likely cause, plus `validate="1:1"` on the join so a regression
errors instead of inflating — mirroring the guard `cli/report.py:729` already used.
Six tests, written red first, both mutations verified.

---

## AB — diversity · **not built, but the case for it is now measured**

Two corrections to the plan, both confirmed:

1. **Diversity already runs inline** in `report` (`cli/report.py:28`, used at
   `:428`), with `--diversity-results` as a sidecar override and `--no-diversity`
   to opt out. The plan treats it as a subcommand to add, so a flag on
   `cli/diversity.py` alone would be a **silent no-op**.
2. **Foldseek and MMseqs2 exist but are misplaced**, not missing — both sit in
   `Proteina-Complexa/.venv/bin/`, x86 only. `mkdssp` is absent entirely on this
   box; `beta_intercalation.py` already degrades to `(-1, -1, 0)` without it.

**The new measurement.** On the same 6 real BindCraft 2 designs:

| | result |
|---|---|
| Sequence clustering (`cluster_sequences_df`, threshold 0.7, k=4) | **6 families, every one a singleton** (`family_size=1`) |
| Structural clustering (Foldseek `easy-cluster --min-seq-id 0 -c 0.8`) | **1 family** — all 6 binders |

Sequence diversity calls these designs maximally diverse; structurally they are
one fold. **That is the exact failure AB exists to fix, and it appears within a
single tool** — AB's stated gate ("a cross-tool pair in different `family_id`,
same structural family") is a stronger form of a problem already present in the
weaker case.

**Caveats, stated because the number is small:** 6 designs, one tool, one target,
one threshold pair. The target chains unexpectedly stayed singleton under the same
Foldseek call, which suggests the invocation is not yet the right one and should be
re-derived before the number is quoted.

**Gate status: cannot be evaluated on this box.** It needs a cross-tool pool with
structures; the only structured pool here is 6 designs from one tool.

---

## AD — discovery rank · **half shipped**

**Done:** `generation_index` + `generation_index_source` across five tools, with
`unavailable` as a first-class value for the three that genuinely cannot report.
Per-tool verdicts in
[INVESTIGATION_generation_index_2026-09-24.md](INVESTIGATION_generation_index_2026-09-24.md).
Verified end to end through the real CLI — all five reporting routes correct.

**Remaining:** `hits.py` holdout. **Blocked on decision §1** of
[MORNING_DECISIONS.md](MORNING_DECISIONS.md) — most extractor inputs are already
downstream of a quality filter, so a discovery rank over them is conditioned on
survival. Its stated gate ("holdout passes a KS test vs the pool") additionally
needs a campaign with a real generation order.

---

## Y — label registry · **shipped as a library**

Public `MANIFEST.json`, private rows resolved by checksum; the `.gitignore` leak
guard landed on Day 0, so the irreversible half is done. Imported by nothing that
ships.

**One thing to settle first:** Y specifies `binder_comparison/benchmarks.py` while
AG additionally specifies `comparison/benchmark.py`. **One module, decided before
either starts** — this blocks AG and AH.

---

## AA — cheap pre-GPU screens · **3 of 6**

| item | result |
|---|---|
| **D7** ProtParam panel | Shipped |
| **D8** composition gate | Shipped, **shadow mode** |
| **D1** TmProt | Shipped end to end, both platforms |
| **A1** BindPred | Needs the model. Build the runner **once** — AH consumes the same one |
| **D3** AggreProt | Reduction + decorrelation harness built and validated; needs the model or one real per-residue export |
| **P5** ESM plausibility | **CLOSED — deliberately not built** |

**Promotion out of shadow mode is blocked harder than "no labels yet".** The
composition gate flags **6 of 6 real BindCraft 2 designs**, including the rank-1
design at `consensus_iptm_mean` 0.918: `min_hydrophobic_frac` ≥ 0.40 sits *above*
that pool's mean (0.363), and `max_glu_arg_frac` ≤ 0.36 sits *at* it (0.347).
`max_ala_frac` and `max_pro_gly_frac` transfer fine. The thresholds came from
RFD3, whose failure mode is a Pro/Gly coil, while BindCraft 2 makes charged
helices. **This needs per-tool calibration, not a nudged global pair.** Pinned by
`tests/test_composition_gate_stays_advisory.py`.

---

## Z — staged cheap-filter · **not started, buildable**

AA's one load-bearing prerequisite (the ESMFold2 full/fast default) is already
closed in code. **Its real prerequisite is two archived pools carrying all three
engine CSVs**, to measure recall at the keep-fraction — this box has none, and the
6-design golden fixture is far too small.

**Correction to carry:** Z's stated gate — "`rank` byte-identical with and without
`--stage1-results`" — **tests the wrong thing.** That flag only attaches advisory
columns; the ranking change comes from the *missing refolds*. A staged run and a
full run cannot have identical `rank`. **Restate the gate as a recall bound**
(the plan's own target: loses ≤1 of the full run's top 30 and **0 of the top 10**).

---

## AE — tool racing · **verdict: defer**

Run several design tools concurrently and cut the losers early.

- **Needs the fleet**, not this box. Not preparable beyond a dispatcher stub.
- **No evidence it is the bottleneck.** Nothing in 2.0 measured per-tool
  time-to-first-good-design, which is the quantity racing would exploit.
- **It interacts with AB.** Killing a tool early prunes whatever *structural*
  diversity it alone contributes — and AB's measurement above shows sequence
  diversity cannot currently detect that. Racing before AB lands risks optimising
  throughput by silently narrowing the fold space.

**Recommendation:** measure per-tool time-to-first-good-design on an existing
archived campaign before writing any of it. That is a day of analysis and it
decides whether AE is worth weeks.

---

## AF — fourth refold engine (Chai-1) · **verdict: reopen, for a new reason**

There is already a plan: [PLAN_chai_and_designers.md](PLAN_chai_and_designers.md),
"Part O — Chai-1 as 4th refold engine". **`chai_lab` is installed** in
`binderscout_protein_hunter`.

**Its original rationale is dead.** The doc justifies Chai-1 as strengthening
consensus by raising the `agreement_count` denominator, "alongside Boltz-2,
Protenix, AF3". Two things happened since:

- **Protenix refolding was removed** (Part J reverted), so the engine list in that
  doc is wrong.
- **`agreement_count` was measured as a flat null** — macro-AUC 0.532 with 87.2%
  of designs tied at zero (Part U). CLAUDE.md now forbids gating or stratifying on
  it. So "raises the agreement denominator" is not a benefit.

**A stronger rationale is now live, and it did not exist when that doc was
written.** Measured 2026-09-27: **AF3 cannot run on consumer Ampere/Ada at all** —
its tokamax Pallas/Triton kernels need 110,592 bytes of shared memory per block
against the 101,376 that sm_86/sm_89 expose. That is architectural, not VRAM. So
on a large part of the fleet the canonical 3-engine gate is unreachable, and the
default `--min-engines 3` fails every design. **A fourth engine that runs on
consumer cards would restore the gate where AF3 cannot.**

**Recommendation:** re-scope AF around *portability*, not consensus width. The
question to answer first is cheap: does Chai-1 run on sm_86 within 12 GB? If yes,
AF becomes the highest-value unstarted part on this list.

---

## AG — fleet/Clara benchmark consumer · **not started**

Consumes Y's registry. ~6 days plus ~50–95 GPU-hours; not runnable here.
**Blocked on Y's module-naming decision** — AG and Y currently specify different
module paths for the same thing.

---

## AH — BindPred · **not started**

Needs the model. **AA's A1 and AH both create the BindPred runner, CLI and env** —
the plan says "build it once", and that remains right. Whoever starts either one
builds the shared runner.

---

## AI — tune Mosaic's design loss · **verdict: defer, and it conflicts with a measured result**

Needs Mosaic GPU runs, so not startable here.

**More importantly, it runs against Part U.** Mosaic *is* Boltz-2 gradient
hallucination, so tuning its design loss tunes it against the same model the
Evaluator refolds with. CLAUDE.md is explicit that Mosaic games `boltz_iptm` by
construction and that its native metric ≈ Boltz-2 self-confidence ≈ Boltz-2 refold
confidence is "a tautology". **Tuning the loss to improve a Boltz-2-measured score
optimises the tautology, not the designs.**

**Recommendation:** if AI is attempted, its success criterion must be measured on
an engine Mosaic did *not* design against — AF3 or ESMFold2 — never on Boltz-2.
Without that constraint the part will report a win that means nothing.

---

## AJ — MD reverse check · **verdict: do not build now**

Molecular-dynamics validation of designed complexes.

- **No tooling.** Neither GROMACS (`gmx`) nor OpenMM is installed anywhere in this
  repo's environments.
- **Expensive.** MD on a pool is orders of magnitude beyond a refold.
- **The premise is weak given what 2.0 measured.** Part N closed
  affinity-from-structure-confidence as a negative result, and Part U found that
  searching over 72 metrics scored *worse* than `consensus_iptm_mean` alone
  (0.5170 vs 0.5552). AJ proposes yet another expensive scorer, with no evidence
  that the ranking's ceiling is a *scoring* problem rather than a label problem.
- **The actual bottleneck is labels**, which is what blocks promoting four
  already-shipped shadow columns.

**Recommendation:** spend the effort on outcome labels instead. If AJ is revisited,
it should be as a *stability filter on a handful of finalists* before synthesis —
not as a pool-wide ranker.

---

## What would move the most, next

1. **Decide §1** (pre-filtered pools) — unblocks finishing AD, the largest
   half-done part.
2. **Answer AF's cheap question** — does Chai-1 run on sm_86 in 12 GB? If yes it
   is the highest-value unstarted part, because it restores the gate on hardware
   where AF3 is impossible.
3. **Settle Y vs AG's module name** — one line, unblocks two parts.
4. **Re-derive AB's Foldseek invocation** and re-run on a cross-tool pool. The
   6-design result above is suggestive, not sufficient.
