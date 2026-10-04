# Evaluation backlog — defects and contradictions

**Internal working list, not reference material.** The reference is
[ranking.md](ranking.md) + [metrics.md](metrics.md); this is what deriving them turned up.

Kept because the items are real and most are still open. The four CRITICAL contradictions were
fixed on 2026-10-03 and are marked; rows 5–17 are not. Both §1 defects are known and unfixed.

## 9. Defects found while deriving this — NOT YET FIXED

**9.1 A blank `pae_file` silently drops an engine from the gate.** `n_unresolved`
increments only when the path is *named but missing*; a **blank** path warns nobody
(`scoring.py:424-428`). A blank `pae_file` is exactly what `refold_af3.py:_empty_row` and
`refold_esmfold2.py` write for a **failed** design. So a failed design quietly loses its
engine, fails a gate of 3, and `evaluate.sh`'s `check_engine_rows` guard counts *rows* not
populated rows, so it passes. Verified: two blanks → **zero warnings**. This is the silent
-failure class 1.0.3 was meant to close.

**9.2 `compute_statistics` runs before any consensus column exists.** `report.py:385` vs
`:405-412`. So `summary.json` and `metrics_zscore.csv` can **never** contain
`consensus_iptm_mean`, `consensus_iptm_n`, `agreement_count`, `quality_tier` or `rank` —
the per-tool statistics table omits the metric the pipeline ranks on. It also computes a
30-metric ranking table (`statistics.py:31`) that is never read, written or rendered.

**9.3 Neither PAE warning reaches `report.html`** — both are `warnings.warn` to stderr. And
the merger's banner counts `{engine}_iptm` (self-reported) while the gate counts
`{engine}_pae_iptm`, so the two can disagree.

---

---

## 10. Doc/code contradictions to fix — 50 found, 4 critical

> **The four CRITICAL rows are FIXED as of 2026-10-03** (plus two strings that described
> `annotate_wetlab_recommended` and went stale when `agreement_count` moved to notes).
> Pinned by `tests/test_ranking_metric_is_not_misnamed.py`, which was mutation-tested
> against all four reversions plus the "delete every mention instead" escape. Verified by
> rendering a real `report.html`, not by grepping the source — see the note under row 2.
> Rows 5–17 are still open.

| # | file | says | severity |
|---|---|---|---|
| 1 | `…/references/evaluation.md:124` | **told the agent to rank by `agreement_count`** | **FIXED** — replaced with the real gate+sort, and the tier table now carries the measured-inversion warning |
| 2 | `visualization/report.py:3072` | **every `report.html` glossary called `ipsae_min` the primary ranking metric** | **FIXED** — now states it is a diagnostic and names `consensus_iptm_mean`. Worth knowing *why* this one mattered most: `_METRIC_DESCRIPTION` renders only for metrics in the `summary` dict, and per defect §9.2 that dict is built before the consensus columns exist — so the shipped per-tool table shows `ipsae_min` and **never shows `consensus_iptm_mean` at all**. The glossary was the operator's only statement of what ranks, and it named the wrong column |
| 3 | `Evaluator/docs/pipeline_reference.md:72` | named `ipsae_min` as primary and omitted the real metric — **and CLAUDE.md cites this file as the metrics reference** | **FIXED** — metrics table rebuilt with a ROLE column and the gate+sort stated above it |
| 4 | `…/SKILL.md:382` (§6.3) | said the final campaign ranking is "ipSAE agreement" | **FIXED** — names `consensus_iptm_mean` and the `--min-engines` gate, and says explicitly that neither `ipsae_min` nor `agreement_count` ranks |
| 5 | `visualization/report.py:2639` | ships the Cao "73.4 % is not the metric's fault" claim withdrawn 2026-10-03 | HIGH |
| 6 | `cli/report.py:1390` | `--primary-engine` help says it selects the ranking metric — three lines above the Part U note correcting it | HIGH |
| 7 | `Evaluator/README.md:23,207` | "Primary metric: `ipsae_min`" | HIGH |
| 8 | `Evaluator/README.md:216` | calls `consensus_iptm` "Stage-1 screen", `_mean` "Stage-2 rank" — Part U deleted both stages | HIGH |
| 9 | `top30_slim.py:289` | subtitle "Ranked by **two-stage** cross-engine iPTM · intercalators excluded" — both halves wrong | HIGH |
| 10 | `CLAUDE.md` | "`consensus_iptm` … **does not rank**" — it is sort key #4 | MED |
| 11 | `README.md:480` | "Diagnostic columns — these never rank, filter or gate" lists `agreement_count`, which gates `wetlab_recommended` | MED |
| 12 | `cli/report.py:557` | requests `pae_bt_mean` / `pae_tb_mean` — **columns that have never existed** | MED |
| 13 | `evaluate.sh:53` vs `:256` vs `:296` | contradicts itself on AF3's memory three times in one file | MED |
| 14 | `CLAUDE.md` | "22 subcommands" — it is 23 (or 34 per README) | LOW |
| 15 | `core/schema.py` `StandardisedMetrics` | presented as the column contract; **nothing constructs it** — dead | LOW |
| 16 | `CLAUDE.md` | "longer binders score lower on `ipsae_min` (r ≈ −0.78)" — does not reproduce on either pool | MED |
| 17 | `cli/refold_boltz2.py:59` | "run in `binder-eval-boltz2` conda env" — an env that has never existed | LOW |

---

---

## 12. Open questions for you

**12.1 `agreement_count` blocking `wetlab_recommended` — DONE 2026-10-03.** It moved from
`reasons` to `notes`, exactly as SoluProt did on 2026-09-28, so it still prints in
`wetlab_reason` (as `agreement 1 < 2 (note only)`) without withholding the recommendation.
What changed with it: the function docstring, the stale "could not be assessed and was NOT
applied to wetlab_recommended" warning, and the two user-facing strings that still
advertised the old criteria — `report.html`'s glossary and the `cli/report.py` comment. The
`report.html` one had *also* been wrong about SoluProt since 2026-09-28.

Two tests changed sign (`test_wetlab_still_blocks_real_disagreement` →
`test_wetlab_notes_low_agreement_but_does_not_block_on_it`, and phase4's
`test_wetlab_recommended_flags_soluprot_fail`), and a third was added so the pair cannot be
satisfied by never blocking anything: `test_wetlab_blocks_on_plddt_even_when_agreement_is_fine`.
Mutation-tested — restoring the `reasons[i].append` fails both. Verified on a rendered
report: a design with SoluProt False **and** agreement 1 now comes out
`wetlab_recommended=True` with both signals named in the reason column.

**One consequence to be aware of:** `README.md:480` claims the diagnostic columns "never
rank, filter or gate" and lists `agreement_count`. That sentence was false before this
change and is true now — nothing to edit, but it is the first place this contradiction was
written down, so it is worth knowing it was right about the intent and wrong about the code.

**12.2 — ANSWERED, re-measured 2026-10-03.** The "flat null" figure (0.532, 87.2 % tied) is a
**Cao** result carried into CLAUDE.md *and* into the benchmark's own README without being
re-measured. On the all-3-engine labelled subset it is **0.6295**, 70.5 % tied. My earlier
0.669 here was also wrong (different subsetting).

**It is monotone then saturates** — binder rate 0.378 → 0.567 → **0.778** → 0.758. The signal is
in *some vs none*; **2-vs-3 is indistinguishable**, so a gate at 3 would be unjustified. Real
signal, weaker than the mean, warning-shaped.

On a different dataset: none exists externally (the README states `adaptyv_662` and
`proteinbase_175` are two refold batches over **one** dataset, 75.6 % overlap; `promera_partT` is
a 5th-*engine* run). On our own CBG panel it is **0.4627** with a flat binder rate
(0.082 / 0.091 / 0.000 / 0.095) — it **tracks the mean**, informative where the mean is and at
chance where the mean is. Not an independent second opinion that rescues a hard target.

So §8's removal of `adaptyv_rank` stands, but its stated reason should be restated: not "a flat
null" — weaker than the mean, and saturating above 2.

**12.3 — WITHDRAWN, and replaced with what you asked for.** The 13/13 rescue figure came from a
BM2 scratch script deleted during cleanup and is **not reproducible from anything saved**, so it
is withdrawn rather than built on. What is measurable argues against shipping it anyway: 3/3 is
not separable from 2/3 (§12.2), and on CBG a 3/3 design binds at 0.095 against a 0.073 pool rate.

Implemented instead, as "how many engines are confident" with the denominator it was missing:
**`agreement_denom`**. `(vals > thr).fillna(False)` counted *engine never ran* as *engine said
no*, so `agreement_count = 1` could not distinguish two engines doubting a design from two never
scoring it — and **99 labelled benchmark designs are capped at 2** and can never reach 3. The note
now reads `agreement 1 of 3 engines`, and stays **silent** where the bar is unreachable.

The veto/rescue measurements that remain standing: requiring unanimity as a *gate* adds +0.000 at
four of eight cuts (the eye-catching "+0.18" compared a 26-design cell against an 80-design list),
while outside the top-20, 2-of-3 designs bind at **0.689** vs **0.397** for 0-or-1 (Fisher
p=0.00022). "Two should not kill it" holds; "three must agree" as a gate does not.

**12.4 — DECIDED: no normalisation.** Recorded here so it is not rediscovered as novel.
Two unvalidated candidates, not proposed: Rank-normalising per
engine before averaging scored **+0.125** precision@top-20 with all four leave-one-target-out
folds positive; `boltz+esm` scored **+0.175** on the same pool. Both are single-pool, and
`mean(af3,esm)` looked just as good a week before reversing on the second pool. Recorded
here so they are not re-discovered as novel.

**12.5 — DONE.** All four CRITICAL items are fixed, pinned and mutation-tested (see §10's
banner); §9's defects are logged, not fixed; rows 5–17 of §10 remain open. Original question
kept for the record: The four CRITICAL items in §10 are code and skill edits,
not documentation — an agent is currently instructed to rank by `agreement_count`. Do you
want those fixed in the same pass as the doc split, and are the §9 defects in scope now or
logged?
