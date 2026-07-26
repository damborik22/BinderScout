# PLAN — Ranking Calibration & New Engines Roadmap (Parts T · U · O · V · W · X)

> **Status:** Evaluated, not started. Each part is **investigate-first** — read current
> `master`, confirm findings against the actual codebase (the older PLAN docs are stale),
> propose a concrete implementation plan with its validation gate, and **wait for approval
> before writing code.**
>
> **Anchoring facts verified 2026-07-23 (`master` @ post-`5769064`):**
> - Analysis modules that exist today in `Evaluator/binder_comparison/comparison/`:
>   `affinity.py`, `diversity.py`, `monomer.py`, `wetlab.py`, `maturation.py`,
>   `epitope.py`, `epitope_map.py`, `candidates.py`, `ensemble.py`, `statistics.py`,
>   `target_analysis.py`, `scoring.py`. Report renderers:
>   `visualization/{report.py, plots.py, top30_slim.py}`. → **Part X premise is real.**
> - `Protein-Hunter/chai_ph/` (chai-lab) is already vendored. → **Part O install cost is low.**
> - Related **completed** plan: **Part N** (`docs/completed_plans.md`) — Rosetta interface-ΔG.
>   Landed 2026-06-16 **with a negative result**: ΔG, `|dG/dSASA|`, PRODIGY and the BindCraft
>   14-metric panel do not rank affinity among binders (best pooled |ρ| ≈ 0.34 on 2/4
>   targets; corroborated on OpenBind + SKEMPI). Part T (iCS) attacks the same gap, so it
>   **inherits Part N's bar**: beat the incumbent on labelled data, or document the negative
>   and stop.

---

## Why this roadmap exists (the framing that orders it)

The just-finished **ApoE4 isoform-selectivity campaign** produced 44 AF3-selective
candidates but exposed the real bottleneck: **it's ranking quality, not design volume.**
No structure-confidence metric we ship (`ipsae_min`, `consensus_iptm[_mean]`) ranks
*affinity* or *selectivity* **among** binders — only binder-vs-non-binder
(`ipsae_min` measured ≈ 0 correlation with experimental Kd on the Adaptyv set).

Therefore the roadmap front-loads the **evaluation layer** (X, T, U) and defers new
*designers* (V, W). We should not spend weeks on a new design tool before we know
whether the metric that selects its output is even the right one.

**Recommended order: X → T → U → O → V → W.**

---

## Benefit / cost summary

| # | Task | Benefit | Cost | Campaign relevance | Do when |
|---|---|---|---|---|---|
| **X** | Report gap audit | Highest ROI — unblocks honest reads of every report | ~1 day | Direct (we pick wet-lab designs from these reports) | **Now** |
| **T** | Promera 5th refold engine + **iCS** metric | Could be the affinity/selectivity ranker `ipsae_min` isn't | ~1 wk | Direct (core ranking weakness) | **Now, after X** |
| **U** | ProtDBench calibration harness | Objective, data-driven metric comparison (enables T's decision) | ~few days | Direct (makes metric choices provable) | **Now, with T** |
| **O** | Chai-1 refold engine | 4th independent engine hardens anti-gaming consensus | ~days (vendored) | Indirect (consensus robustness) | Spare slot |
| **V** | OpenGerminal (Ab/Nb designer) | New capability; removes aarch64 PyRosetta blocker | ~1 wk | Future (no current Ab campaign) | On demand |
| **W** | RFD2-MI (small-mol/PTM designer) | Enables ligand/PTM targets (pairs with Boltz-2 affinity head) | ~1 wk | Future (no current ligand target) | On demand |

---

## Part X — Report gap audit  *(do first)*

**Goal.** Determine which analysis modules actually **surface in the HTML report** vs.
being CLI-only, sidecar-CSV-only, or effectively dead code. If `affinity.py` /
`diversity.py` / `monomer.py` / `wetlab.py` compute signal that never reaches the report
a human reads, wet-lab picks are being made blind.

**Investigate-first checklist (no code):**
- [ ] X1. For each module in `comparison/` (list above), trace whether
      `visualization/report.py` (and `top30_slim.py`) actually calls it / renders its
      output. Build a table: `module → computed? → in CLI? → in HTML? → dead?`.
- [ ] X2. Note columns that exist in the CSV but not the HTML (and vice-versa).
- [ ] X3. Flag the highest-value gaps for the *current* campaigns first:
      selectivity/epitope (ApoE4), diversity (dedup wet-lab picks), monomer (fold
      stability), affinity/maturation (the ranking gap).
- [ ] X4. Report findings + a **surgical** fix plan (wire the missing high-value panels
      into the HTML); wait for approval.

**Validation gate:** none needed to *investigate*; the fix itself is verified by
regenerating a report on an existing run and confirming the new panels render with
correct numbers.

---

## Part T — Promera as 5th refold engine + iCS ranking metric

**Goal.** Evaluate whether **Promera**'s interface scores — ipSAE and **iCS (interface
Contact Score)** — rank binders better than our incumbent `ipsae_min`, and only then wire
Promera into `evaluate.sh` as a 5th engine.

**Investigate-first checklist:**
- [ ] T1. Confirm Promera availability/licensing, weights, and GPU footprint on our
      hardware (Spark / H200 / 24 GB). Can it run in a dedicated conda env like AF3?
- [ ] T2. Refold two labelled sets through Promera: **CBG r2 pool** + the **Adaptyv
      4-target benchmark** (experimental Kd available).
- [ ] T3. Compute macro-AUC of `iCS` and Promera-`ipSAE` for binder-vs-non-binder, and —
      the real prize — check any *rank correlation with Kd among binders*.
- [ ] T4. Read **Part N**'s negative result first (`docs/completed_plans.md`) — it already
      ruled out ΔG, `|dG/dSASA|`, PRODIGY and the BindCraft panel as affinity rankers, and
      documents the traps (length confound, Simpson's-paradox "screen-then-invert"). iCS
      must clear that bar, and must be tested against the same labelled sets.

**Validation gate (hard):** wire Promera into the pipeline **only if `iCS` (or
Promera-ipSAE) beats the incumbent** `ipsae_min` macro-AUC (~0.71 Adaptyv / ~0.755
ProteinBase). If it doesn't beat it, document the negative result and stop.

---

## Part U — ProtDBench calibration harness

**Goal.** Stand up a reproducible harness that scores our ranking layer against
**ProtDBench** (arXiv 2605.04118) so every metric decision — `ipsae_min` vs `iCS` vs
`consensus_iptm[_mean]` vs future metrics — is data-driven rather than anecdotal. This is
the *infrastructure* that lets Part T's decision be provable.

**Investigate-first checklist:**
- [ ] U1. Read arXiv 2605.04118. Confirm the benchmark's **targets, hotspots, and crops
      are reproducible** inside our pipeline before building anything.
- [ ] U2. Identify the ground-truth labels (binder/non-binder, or affinity) and the exact
      metric-of-record the paper uses, so our AUC/rank numbers are comparable.
- [ ] U3. Sketch a `binder-compare calibrate` (or a script) that ingests our refold CSVs +
      the benchmark labels and emits an AUC/precision table per candidate metric.

**Validation gate:** the harness must reproduce at least one published number from the
paper on a shared metric before we trust its verdicts on our own metrics.

---

## Part O — Chai-1 as a refold engine

**Goal.** Add Chai-1 as a 4th independent refold engine to harden cross-engine consensus
(we've seen PH and Mosaic *game* Boltz-2's iPTM by construction; more independent voters
resist that). `chai_ph` is already vendored, so install cost should be low.

**Investigate-first checklist:**
- [ ] O1. Verify the vendored `Protein-Hunter/chai_ph/` can be driven for **refold**
      (complex prediction from sequence), not just PH's design loop — and whether it needs
      its own `binder-eval-chai` env or can reuse `bindmaster_protein_hunter`.
- [ ] O2. Confirm the older "Part O plan (O1–O13)" the task list references still matches
      reality (it may be stale) — reconcile before adopting it.
- [ ] O3. Map Chai-1 output → `StandardisedMetrics` (`chai_*` column prefix, pLDDT scale,
      PAE binder/target ordering) exactly as AF3/Protenix were mapped.

**Validation gate:** Chai-1 columns must agree with Boltz-2/AF3 on a sanity set (known
good + known bad complex) before it's allowed to move the consensus. Weigh the marginal
value — 4th engine on top of Boltz-2 + AF3 + ESMFold2 has diminishing returns.

---

## Part V — OpenGerminal (antibody / nanobody designer)  *(future capability)*

**Goal.** Evaluate OpenGerminal as a de-novo **antibody/nanobody** design tool. Apache-2.0,
no PyRosetta/IgLM dependency → cheaper to integrate than Part P (RFantibody) **and** it
would work on aarch64 (removes the DGX-Spark PyRosetta blocker that stops RFantibody /
Protein-Hunter there).

**Investigate-first checklist:**
- [ ] V1. Confirm license, weights, deps, and aarch64 viability.
- [ ] V2. Scope the configurator + extractor work (new `OpenGerminalExtractor`, run-script
      template, `settings.json` block) — mirror the RFD3/Protein-Hunter integration.
- [ ] V3. Confirm there is an actual antibody/nanobody campaign that needs it before
      building — this is orthogonal to the current de-novo mini-binder work.

**Validation gate:** reproduce a known antibody/nanobody binder before trusting it in a
campaign. **Defer until a campaign requires antibodies.**

---

## Part W — RFD2-MI (small-molecule / PTM designer)  *(future capability)*

**Goal.** Evaluate RFdiffusion2 multi-input for **small-molecule / PTM-conditioned**
binder design (targets our current protein-only tools can't address). Rankings would come
from the **Boltz-2 affinity head**, not `ipsae_min`.

**Investigate-first checklist:**
- [ ] W1. Confirm license, weights, deps; relationship to the RFD3/foundry stack already
      installed (`bindmaster_rfd3`).
- [ ] W2. Scope configurator + extractor + affinity-head scoring path.
- [ ] W3. Confirm a real small-molecule/PTM target exists before building.

**Validation gate (hard):** reproduce a **known small-molecule binder (testosterone)**
end-to-end before trusting RFD2-MI output. **Defer until a ligand/PTM target is on deck.**

---

## Process discipline (applies to every part)

1. **Read current `master` first.** The older PLAN docs (`PLAN_refactor_af3_rfd3.md`,
   `plans.md` Parts I/N, etc.) are stale — verify against the code, not the doc.
2. **Investigate → report findings → propose plan + validation gate → wait for approval.**
   No implementation code until the specific part is approved.
3. **Negative results are deliverables.** If iCS doesn't beat `ipsae_min` (T), or Chai-1
   adds no consensus signal (O), that verdict — documented — is the win.
4. **Surgical changes.** New engines mirror the AF3/Protenix/RFD3 integration patterns
   already in the tree; don't refactor the evaluator to add one.
