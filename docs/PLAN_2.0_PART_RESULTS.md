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
| **Y** | private label registry | **Shipped as a library**, and its naming collision with AG is now settled |
| **AA** | cheap pre-GPU screens | **3 of 6 shipped.** Two need models, one closed, promotion needs labels |
| **AB** | diversity | **Not built — but now measured, and the measurement says build it** |
| **AC** | seed aggregation | **DONE.** The hazard was live; fixed and guarded |
| **Z** | staged cheap-filter | **Not started.** Buildable; not validatable here |
| **AE** | tool racing | **Verdict: defer.** Needs the fleet; no evidence it is the bottleneck |
| **AF** | fourth engine (Chai-1) | **Reopen as an ADDITION.** Source analysis says no sm_86 wall, favourable memory design, outputs match our schema. Unverified by execution |
| **AG** | fleet/Clara benchmark consumer | **Not started, now unblocked.** Naming settled; only GPU-hours remain |
| **AH** | BindPred | **Obtained and REJECTED** — benchmarked blind on our SPOC data, ranks backwards |
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

**The naming question is settled (2026-09-28) — see AG below.** Y's
`benchmarks.py` is the sole registry; AG imports it and puts its scoring in
`label_scoring.py`. Guarded by `tests/test_one_benchmark_registry.py`. Original
wording of the conflict: Y specifies `binder_comparison/benchmarks.py` while
AG additionally specifies `comparison/benchmark.py`. **One module, decided before
either starts** — this blocks AG and AH.

---

## AA — cheap pre-GPU screens · **3 of 6**

| item | result |
|---|---|
| **D7** ProtParam panel | Shipped |
| **D8** composition gate | Shipped, **shadow mode** |
| **D1** TmProt | Shipped end to end, both platforms |
| **A1** BindPred | **REJECTED 2026-09-28** — obtained and benchmarked blind; see the AH section |
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

**A second rationale looked live on 2026-09-27 and is now in doubt.** AF3 failed
on an RTX 3060 with a 110,592-vs-101,376-byte shared-memory error, and I concluded
AF3 "cannot run on consumer Ampere/Ada at all". **That conclusion was wrong** — see
the AF3 correction in CLAUDE.md. AF3 demonstrably ran on BM2, an RTX 3090 (sm_86),
in August, with the same `tokamax==0.0.11` already present; the variable that
differed was the **token bucket** (60 vs 258), which our own code sets with no
lower bound while AF3's stock buckets start at 256.

So AF should be justified on its own merits — an independent fourth opinion, and
an engine with no custom-kernel dependency at all — **not** on AF3 being
unavailable, until that hypothesis is tested.

**Re-scope AF around *portability*, not consensus width** — and as an **addition**,
not a substitution: the three current engines are verified and none is being
replaced.

### Source analysis, 2026-09-28 (no fold was run — see the limit at the end)

**1. No sm_86 architectural wall.** This is the decisive difference from AF3.
`chai_lab` 0.6.1 contains **no** `triton`, `pallas`, `flash_attn`, `xformers`,
`deepspeed` or `cutlass` anywhere in its 101 source files. It is TorchScript JIT
modules plus PyTorch SDPA — its ESM embedder is literally
`traced_sdpa_esm2_t36_3B_UR50D_fp16.pt`. SDPA selects among backends and falls
back automatically, so there is no fixed >99 KB shared-memory request of the kind
that aborts AF3 on sm_86. **Nothing in the source predicts an architectural
refusal on either a 3090 (sm_86) or GB10 (sm_121).**

**2. The memory design is unusually favourable.** `chai1.py:153-165`
(`_component_moved_to`) caches each JIT component in **host RAM** and moves it to
the GPU only for the duration of its use, then straight back:

```python
component.jit_module.to(device)
yield component
component.jit_module.to("cpu")  # returned, not retained
```

So **peak VRAM ≈ largest single component + activations, not the sum of the
trunk.** `low_memory=True` (the default) separately returns intermediates on CPU
(`return_on_cpu=low_memory`). I had assumed the opposite before reading it.

**3. The one large optional cost** is `use_esm_embeddings=True` (default), which
pulls ESM2-3B in fp16 — roughly **6 GB of weights**. It is a flag, so it can be
disabled, but it is a real input feature and turning it off is an accuracy change,
not a free saving.

**4. Its outputs match `StandardisedMetrics` cleanly** — this is what makes
integration cheap rather than speculative:

| Chai-1 provides | our need |
|---|---|
| `PTMScores.interface_ptm` | iPTM — the ranking input |
| `PTMScores.per_chain_pair_iptm` | binder↔target iPTM specifically |
| `complex_ptm`, `per_chain_ptm` | pTM columns |
| `PLDDTScores` complex / per-chain / per-atom | pLDDT columns |
| `pae_logits [... n n bins]` + `pae_bin_centers` | the PAE matrix, by expectation over bins |

**5. Two risks the source does not settle.**

- **Throughput.** Moving components CPU↔GPU on every call is PCIe-bound. That is
  the price of the low peak in (2), and over a pool of hundreds of designs it
  could dominate wall-clock. **Must be measured before adopting.**
- **Packaging.** `chai_lab` currently lives inside `binderscout_protein_hunter`
  (a *design* tool's env, torch 2.5.1+cu121). A refold engine needs its own env,
  as `binder-eval-af3` and `binder-eval-esmfold2` do.

### What adding a fourth engine costs elsewhere

Because it is an addition, two things downstream change and neither is automatic:

- **`--min-engines 3` stops meaning "all three" and starts meaning "3 of 4".**
  That is a different gate, and on sm_86 hardware it becomes satisfiable
  (Boltz-2 + ESMFold2 + Chai-1) where today it is not.
- **`consensus_iptm_mean` was validated on three engines** (Part U). A mean over
  four is not automatically the same metric and needs re-checking against the
  labelled pools, not assumed.

### Limit of this result

**Entirely from source. No Chai-1 fold was executed** — the GPU was in use, and
this box is a 12 GB RTX 3060 kept for development. The prediction to test on a
3090 or GB10 is: Chai-1 loads and folds without an architectural error, at a peak
well under the sum of its components. **Correction, 2026-09-28: AF3 is probably not blocked on sm_86 at all — see below.**

---

## AG — fleet/Clara benchmark consumer · **not started, but unblocked**

Consumes Y's registry. ~6 days plus ~50–95 GPU-hours; not runnable here.

**The module-naming blocker is settled, 2026-09-28.** Reading what each part
actually needs narrowed the conflict the plan recorded (§159-160):

* Only **`benchmarks.py` was ever duplicated**, and Y shipped it — so precedence
  decides that one. AG **imports** it rather than recreating it, and
  `load_labels()` already returns a checksum-verified DataFrame, which is exactly
  the shape AG needs to join a ranking against.
* AG's `comparison/benchmark.py` is **not a duplicate at all.** There is no
  label-based scoring anywhere in the shipped tree — no `roc_auc`, no `macro_auc`,
  no precision-at-k over labels — so Part U's numbers came from analysis that never
  landed as library code. AG writing the first of it is genuinely new work.

So the rule is **one registry**, not one module: keep `benchmarks.py` as the sole
source of truth for which pools exist, and give the scoring a name that cannot be
mistaken for it. `comparison/benchmark.py` is refused purely on that ground — one
character and one directory from `benchmarks.py` is how a reader imports the wrong
one. Use `label_scoring.py`.

Pinned by `tests/test_one_benchmark_registry.py`, which fails if the confusable
name appears, if any second module re-declares the registry's surface, or if the
registry loses a function AG and AH depend on. Three mutations verified.

**Remaining blocker is only the GPU-hours.**

---

## A1 / AH — BindPred · **obtained, benchmarked blind, REJECTED**

**Result, 2026-09-28: do not integrate, not even as a shadow column.**

The model was located and obtained: [`hbp5181/BindPred`](https://huggingface.co/hbp5181/BindPred),
MIT, [Bioinformatics 2026](https://doi.org/10.1093/bioinformatics/btag309). It lives in
the gitignored `weights/bindpred/`. So "needs the model" is no longer the blocker — the
blocker is that it does not work for us.

**Interface (resolved from its source, since the model card omits it).** Sequence-only,
no structure: 2560 features = `[ligand_emb(1280) ‖ receptor_emb(1280)]`, mean-pooled
`facebook/esm2_t33_650M_UR50D` layer 33, ordering per `train.py:38`. Output is
**log10(Kd) in molar** (`train.py:52`), lower = tighter. The shipped `.cbm` is the
embeddings-only variant — no PyRosetta or BindCraft features, despite the repo shipping
those embedding sets too. Runs on **CPU** in minutes for ~125 designs.

Because it needs no structure it would have belonged in the **pre-GPU screen panel**
alongside SoluProt/TmProt, not in the ranking path.

**Why rejected.** Benchmarked blind against our internal SPOC results — predictions
written by one script that never reads the affinity column, scored by another, with both
input orderings reported so the ordering could not be chosen after seeing the scores.
**It ranks our designs in the wrong direction**, in both orderings, so it is not an
ordering artifact. The mechanism is under-dispersion: its predicted range is far
narrower than the measured spread, which is gradient-boosted-tree regression toward the
training mean applied off-distribution. Its top-10 selection is worse than not ranking
at all.

This is **consistent with BindPred's own shipped evidence**, not contrary to it: as a
cross-target *discriminator* it works (macro-AUC 0.651 vs 0.512 for a BindCraft energy
baseline on its own 212-design set), but its affinity evidence rests on 20 measured Kd
values with one target at n ≥ 4, and that one is negative. The paper's headline r = 0.86
is a between-complex spread over 11,919 diverse complexes — a different problem from
ranking designs against one fixed target, which it does not claim to solve.

**Part N is confirmed, not overturned.**

**If revisited**, the route is recalibration on our own regime (isotonic/linear fit on
one campaign, tested on another) — which addresses the observed failure directly — or
use as a discriminator only. Do **not** add it as another ranking column; Part U
measured that searching over more metrics scored *worse* than `consensus_iptm_mean`
alone.

> Numbers, per-design predictions and the reproduction scripts are deliberately **not in
> this repository** — it is public and the SPOC results are unpublished. They are in the
> internal `Claude outputs/BindPred_blind_benchmark_2026-09-28/` folder
> (`CONCLUSION.md` + `BindPred_blind_benchmark_REPORT.md`).

### The finding worth acting on, which came out of the same run

`ipsae_min` **did not track affinity on that pool**, and was *below* chance at
separating designs with a measured affinity from those without — while `Mean_ipTM` was
positive and useful. **Binder length is a strong baseline** that rivals `Mean_ipTM` on
the raw correlation — though controlling for length, `Mean_ipTM` keeps real residual
signal, so it is not a length proxy (an earlier wording of this said it was; corrected).
Yet `ipsae_min` is
the basis of `passes_affinity_gate` (`ipsae_min ≥ 0.61`) and of all four quality tiers
(High/Medium/Low/Reject). On a short-helix target those tiers may be sorting noise.
**Investigated 2026-09-28, and it is worse than a correlation problem.** On *both*
targets we hold experimental results for, the shipped gate `passes_affinity_gate`
(`ipsae_min ≥ 0.61`) keeps the **weaker** binders: the designs it rejects bind several
times more tightly than the ones it passes, with no better binder rate. The four quality
tiers do not order by affinity either — on one target the tier ranked "Low" binds
tighter than "Medium", and on the other the **"Reject"** tier holds the majority of
confirmed binders and the tightest median. The **"High"** tier fires 0 and 2 times
across the two pools, with **zero** binders — `ipsae_min` never reaches its threshold on
a short-helix target, so the top tier is effectively unreachable.

The stated explanation in CLAUDE.md — *"longer binders tend to score lower on
`ipsae_min` (r ≈ −0.78)"* — **does not reproduce** on either pool (near zero, and
positive). So the gate is not a disguised length filter; `ipsae_min` simply carries no
affinity information there, and removing length changes nothing. It is also highly
redundant with `Mean_ipTM` (ρ > 0.7 on both) while being the weaker of the two.

**Recommendation: demote `ipsae_min` to a diagnostic column — keep computing it, stop
gating and tiering on it** — which is exactly how `agreement_count` was handled after
Part U. Re-basing the gate on `Mean_ipTM` is the more ambitious option but needs a
second well-powered target first, because ipTM's own sign flips on the weaker pool.

Caveats: two targets, only one well-powered, and CALCA is a 32-aa helix — precisely the
regime the 2026-05-16 diary entry already flagged as mis-calibrating ipSAE. That entry
recorded the problem for AF2 ipSAE; it evidently survives into the merged metric. A
large structured target is the obvious next test.

Full numbers in the internal `Claude outputs/ipsae_min_gate_investigation_2026-09-28/`
folder. **Not yet changed in code** — this is a shipped default with a public gate, and
it should be changed deliberately rather than mid-investigation.

---

## AH — original entry · **superseded by the above**

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
