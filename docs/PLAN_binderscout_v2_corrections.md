# Corrections and scoping notes for the 2.0 plan

The 2.0 plan and its item assessment live on a OneDrive share outside this tree,
so a correction found while implementing has nowhere to land and the next reader
re-derives it. This file is that place. It is not a second plan — see
[PLAN_binderscout_v2.md](PLAN_binderscout_v2.md) for the implementation plan.

Two kinds of entry:

* **Corrections** — an anchoring fact in the plan that does not match the code.
* **Scoping notes** — the deliverable for an item whose verdict was
  "scope it first" or "test before building". These items were never build
  orders, and closing them means answering a question, not writing a runner.

---

## Scoping note — D4, "Foldability (Kohout)"

**Verdict on record:** *scope it first.* **Why:** *needs a statement of what it
adds over `fold_robust` + monomer pLDDT.* **Proceed when:** *that delta is
established.*

### The delta cannot be established yet, for a reason the item did not anticipate

**The tool is not identifiable from outside.** "Foldability (Kohout)" names
Pavel Kohout, a researcher at Loschmidt Laboratories (the group behind SoluProt
and TmProt), not a published tool. A search finds his work on protein evolution
and successor-sequence prediction but no foldability predictor released under
that name. Before D4 can be scoped at all, someone with internal context has to
answer: **which method is this, is it available, and what does it output —
a score, a class, a per-residue profile?** Everything below is conditional on
that answer.

### What the repository already measures, precisely

`comparison/monomer.py` answers *"does the binder hold its fold without the
target?"* — and it is worth being exact, because the overlap the item suspects
is real but narrower than "foldability".

* `kabsch_rmsd()` (`monomer.py:16`) — Cα RMSD after optimal rigid
  superposition, reflection-corrected so the rotation is proper.
* `classify_fold_robustness()` (`monomer.py:41`) — a boolean at
  `CONTEXT_DEPENDENT_RMSD = 3.0` Å.
* The comparison is **binder refolded alone vs the binder's conformation inside
  the complex**. It is structural, comparative, and requires a GPU refold of the
  binder on its own.

So `fold_robust` measures **context dependence**: a fold that only exists
because the target holds it in place. That is a specific expression and
behaviour risk, not foldability in general.

**Monomer pLDDT**, which comes free from that same binder-only refold, is the
closer overlap. A confidently-predicted monomer is the model asserting the
sequence folds on its own.

### What a sequence-only foldability score could add

Only one thing structurally: **timing.** Both existing signals are
*post-refold*. A sequence-only score is available *before any GPU time*, which
is exactly the pre-GPU cascade Part Z is built around. That is a real saving
and not an information gain.

It becomes an information gain only where it **disagrees** with monomer pLDDT.

### The test that would close this item

On an archived pool that has monomer refolds, compute against every design:

1. Spearman ρ of the foldability score vs **monomer pLDDT**.
2. Spearman ρ of the foldability score vs **Cα RMSD** (`fold_robust`'s input).
3. Whether it separates designs that failed expression, where such labels exist.

**Decision rule.** If |ρ| against monomer pLDDT is high, the item closes as
"adds speed, not signal" — worth having only inside Part Z's staged mode, and
never as a new column of its own. If |ρ| is low **and** it tracks a real
outcome, it is a genuinely new signal and proceeds under the shadow-mode rule
like every other pre-GPU filter.

**Blocked on:** the tool's identity (above), and an archived pool with monomer
refolds — the same transfer that gates the golden pool, Part AA's measurements,
AB and Z.

---

## Scoping note — D3, "Aggregation by AggreProt"

**Verdict on record:** *test before building.* **Why:** *same
hydrophobicity/charge signal as SoluProt.* **Proceed when:** *rank correlation
vs `soluprot_score` is low AND it separates expression failures.*

No work is needed to start this beyond the same archived pool. The test is
already fully specified by the verdict, and it is cheap: SoluProt scores exist
for any pool that has been through `evaluate.sh`, so the decorrelation check
needs no new environment and no GPU — only AggreProt scores for the same
sequences.

**Do the correlation before standing up the environment**, not after. The
verdict's phrasing is deliberate: the environment is the expensive half
(~2 d + 1 env by the assessment's own estimate), and it is wasted if the signal
is a restatement of a screen we already run.

---

## Correction — D1, "TmProt", was more than "partly shipped"

**Status on record:** *"Partly shipped (report `--tmprot-results`); no
evaluate.sh step."*

Accurate but it understates the gap. The consumer was wired through the entire
display layer — `_attach_tmprot_results` in `cli/report.py`, the slim decision
table (`visualization/top30_slim.py:48`), the multimetric radar
(`visualization/plots.py:1071`) and the column tooltip
(`visualization/report.py:2139`) all read `native_tmprot_tm`. What was missing
was not a step in `evaluate.sh` but **any way at all to produce the CSV**: no
runner, no subcommand, no installer arm, no environment. The flag pointed at a
file a human had to build by hand with an external tool.

Closed: see the `screen-tmprot` slice. The missing-`evaluate.sh`-step framing
would have led someone to add a step that invoked nothing.

---

## Correction — the radar reads Tm, and that is fine

`plot_multimetric_radar` (`visualization/plots.py:1063-1071`) normalises
`native_tmprot_tm` onto a 0–1 axis. That looks at first like a violation of
D1's *"never a ranking term"*, and it is not: the function draws one polygon per
tool for display. It does not feed `rank_designs()`. Recorded here because the
next person to grep for `native_tmprot_tm` will have the same moment of alarm.

The same function also reads `agreement_count`, which Part U retired as a
ranking input (macro-AUC 0.532, 87.2 % of designs tied at zero). Also
display-only, also fine, also worth knowing before someone "fixes" it.

---

## Correction — item C2 is routed to Part AD but appears in none of its steps

The assessment routes C2 ("predict target difficulty and size the campaign") to
AD, and AD's ten steps do not mention it. Meanwhile
`comparison/target_analysis.py:46-84` already ships `difficulty_score()`,
`classify_difficulty()` and `suggest_campaign()` — returning `n_target` of
250/100/50 by band — on **unvalidated constants**. So the item is neither
unbuilt nor done: it is built and uncalibrated, which is the case the verdict
("proceed — calibrate the existing heuristic") actually describes. Whoever picks
up AD should treat C2 as a calibration task against AD's own yield curve, not as
a feature.

---

## Measurement — D1's gate PASSES on a real pool (2026-09-24)

D1 said proceed *"when Tm spread on an archived pool exceeds predictor error."*
That gate can now be closed: the 2VDY/CBG archive
(`RESULTS and REPORTS/2VDY_combined_2026-07-22/`) carries `tmprot_fresh.csv`,
439 designs already scored.

| | |
|---|---|
| range | 48.53 – 83.68 °C (35.15 °C) |
| mean ± sd | 66.93 ± **12.31** °C |
| IQR | 54.52 – 79.56 (**25.05** °C wide) |
| 5–95 pct | 51.46 – 83.21 (31.75 °C wide) |
| below 60 °C | **189 / 439 (43.1 %)** |

Sequence-based Tm predictors carry roughly 8–10 °C RMSE. A 12.3 °C standard
deviation and a 25 °C interquartile width clear that comfortably, and the screen
splits the pool rather than calling every de novo binder hyperstable — which was
the specific worry behind *"out of domain on hyperstable de novo miniproteins"*.

**Gate passes. TmProt is informative on real binder pools.**

## Measurement — TmProt is NOT redundant with SoluProt

The same archive has `soluprot_fresh.csv` for the same 439 designs, so the
redundancy question the assessment raises for this whole family of Loschmidt
screens can be answered directly. On 436 deduplicated designs:

* Spearman ρ = **−0.090**
* Pearson r = **−0.031**

Essentially uncorrelated. The concern that these screens all restate one
hydrophobicity/charge signal is **empirically false for TmProt**. It does not
settle the same question for AggreProt (D3) — but it does mean the shared
premise behind both verdicts should not be assumed, only measured.

## Measurement — the rank bug was live in a shipped campaign, and escaped on luck

`tmprot_fresh.csv` and `soluprot_fresh.csv` each contain **3 duplicated
sequences** (439 rows, 436 distinct). An inner join on `sequence` inflates
439 → **445 rows**. That is exactly the row multiplication that corrupted
`rank` before `_merge_by_sequence` (commit `3d0c7a9`), in a real campaign that
shipped a gene order.

It did not damage that report: none of the 3 duplicated sequences survived into
the 350 designs in `metrics.csv`, so the inflation had nothing to bite on. The
join carried no guard either way — this campaign escaped on the composition of
its pool, not on anything defensive. Two conclusions worth keeping:

1. Duplicate sequences in real screen outputs are **normal**, not pathological.
   Two tools emitting the same binder is the ordinary case.
2. A defect that depends on pool composition will look absent for a long time
   and then not be.

## Note — what the OneDrive archive can and cannot unblock

`RESULTS and REPORTS/` holds seven completed campaigns (2VDY/CBG and CALCA,
including the Part U re-runs). Present: `metrics.csv`, `metrics_zscore.csv`,
`candidates.csv`, per-tool native CSVs, the screen outputs, ~100 structures,
and the HTML reports.

**Absent: per-engine refold CSVs and PAE `.npy` — zero of each.** So this
archive supports *measurement* work (AA's false-negative rate, D3's
decorrelation, AB's structural work) but cannot rebuild a real-data golden
fixture, which needs the report's inputs rather than its outputs. That fixture
still needs a small fetch from a fleet machine; the synthetic pool in
`tests/integration/` already covers the mutation guarantee in the meantime.
