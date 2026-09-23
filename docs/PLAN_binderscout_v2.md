# PLAN — BinderScout 2.0 implementation

**Status:** planning only. No v2.0 code has been written. Every part below is
**investigate-first** per the source plan's own rule: confirm the anchoring
facts, propose the implementation with its validation gate, and wait for
approval before writing code.

**Source documents** (they live outside the tree, on a OneDrive share):
`PLAN_binderscout2_integration.md` (12 lettered parts),
`BinderScout_2.0_item_assessment.csv` (44 items → parts),
`standalone_dev_box_assessment.md` (this box as the engineering machine).

**How this was produced.** Nine agents, 510 tool calls: seven investigated one
part each against the actual code, two critiqued the result for completeness
and for ranking risk. Roughly **50 of the source plan's anchoring facts are
stale, wrong or unverifiable** — several load-bearing. Those corrections are
the most valuable output here and are listed per part.

**The one rule everything is measured against** (from the source plan):
`rank_designs()` = cross-engine gate (`--min-engines`, default 3, floor 2) →
`consensus_iptm_mean`. *Nothing in 2.0 changes the ranking. Every new signal
lands as an advisory column.*

§2 is about the ways that rule is **not automatically true**.

---

## 1. Day 0 — three things before any v2.0 code

### 1.1 `rank` is corrupted today by four unguarded joins (**live bug, reproduced**)

Four sequence-joined attaches in `Evaluator/binder_comparison/cli/report.py`
merge with neither `drop_duplicates` nor `validate="m:1"`:

| line | function |
|---|---|
| `703` | `_attach_native_metrics` |
| `733` | `_attach_native_metrics_sidecar` |
| `764` | `_attach_soluprot_results` |
| `799` | `_attach_tmprot_results` |

Every **`binder_id`**-joined attach *is* guarded — `828`, `863`, `1012`,
`1052`, `1083`, `1130` all carry `validate="m:1"`. `comparison/merger.py:139`
carries it too, while the outer join at `merger.py:63` does not. So the
codebase knows the idiom; the sequence joins simply never got it.

`_attach_native_metrics_sidecar` is **not opt-in**: `report.py:186-187` calls
it whenever `--sequences` is passed, which `evaluate.sh` always does.

Reproduced in `binder-eval` (pandas 2.3.3) on this branch — 3 designs joined to
a table with one duplicated `sequence`:

```
3 designs in → 4 rows out        (no warning, no exception)

binder_id  consensus_iptm_mean  rank
        a                  0.9     1
        a                  0.9     2     ← one design, two ranks
        b                  0.8     3
        c                  0.7     4     ← shifted from 3
```

Duplicate sequences are not hypothetical: two tools can emit the same binder,
and CLAUDE.md already records that `refold_boltz2.py` appends to its CSV and can
carry duplicate `run_id`s after a partial failure.

**Fix first, on its own, with a regression test** — before the golden pool is
captured. Capturing first would bake the multiplied rows into the expectations
and the new test would certify the defect.

### 1.2 The benchmark-label leak guard (Y step 4)

`git check-ignore -v Evaluator/benchmarks/cao2022/labels.csv` returns nothing
today. The repo is public. Part Y creates that directory. This is ~10 lines of
`.gitignore` (ignore `Evaluator/benchmarks/**/*.{csv,parquet,tsv}`, negate
`MANIFEST.json` and `SCHEMA.json`) and it is **the only irreversible failure in
the plan** — it must exist before the directory does.

### 1.3 CI does not run on this branch

`.github/workflows/ci.yml:4-7` fires on `master` only, for both `push` and
`pull_request`. The branch is `v2.0.x`. For the whole of v2.0 development,
neither the golden regression test nor the leak guard runs anywhere. The
prerequisite's gate explicitly requires "green in the existing CI job" — which
cannot happen. Widen the filter or accept that the guard is local-only, but
decide it deliberately.

---

## 2. Ranking-risk register — why "advisory columns only" is not free

The source plan treats "adds a column" as inherently safe. It is not, and these
are the mechanisms. Each was verified in the code.

| # | Mechanism | Evidence |
|---|---|---|
| **G1** | The unguarded join is **four** sites, not the three the plan names — and the omitted one runs on every report | `report.py:733`, called at `:186-187` |
| **G2** | Row multiplication is silent; rank damage is invisible | measured — §1.1 |
| **G3** | `rank` is **tie-order-dependent** and no part says so. `scoring.py:899-900` sorts on a key list, pandas resolves ties by stable lexsort, so tied rows keep *input* order. Reversing input reverses their ranks | measured |
| **G4** | `annotate_wetlab_recommended()` has two **pool-relative** terms the plan treats as per-row: `n_engines = counts.max()` (`scoring.py:1011-1016`) decides whether the agreement criterion applies *to every row*; `tool_means` (`:1033-1049`) is a per-tool mean | `scoring.py` |
| **G8** | `visualization/top30_slim.py:159` `_full_table` emits **every** column not explicitly dropped — so every advisory column churns that output | `top30_slim.py` |
| **G9** | Composites fire **by column name**: `compute_composite_scores` (`scoring.py:546-570`) triggers on the mere presence of `native_dG` + `native_dSASA`, or `native_shape_complementarity` | `scoring.py` |
| **G10** | `merger.py:63` is unvalidated too, which is Part AC's seed hazard already live | `merger.py` |

**Consequence for every part:** "I only added a column" must be *proved* by the
golden test, not asserted. And a new column must not be named into G9's
patterns by accident.

---

## 3. Order to implement

The source plan's order (AD → Y → AA → Z → AC → AB → AG → AH → AI → AJ → AE →
AF) is ordered by benefit. The dependencies allow a different one, and both
critics converged on it independently.

| # | Item | Why here |
|---|---|---|
| 0 | **Fix the four joins** (§1.1) + leak guard (§1.2) + CI call (§1.3) | Bug fix on master; must precede the fixture |
| 1 | **Golden pool** (prerequisite) | Turns "nothing may change `rank`" into a job. Owned by the prerequisite **only** |
| 2 | **AD step 4 — the Mosaic template** | The *only* item with an external clock: it must land before the next Mosaic campaign or that cycle yields no discovery data. Touches `binderscout_examples/`, zero coupling |
| 3 | **AD (Evaluator half)** | Its own gate *is* the golden test; running it earlier means hand-diffing |
| 4 | **Y** | Library only, imported by nothing shipping. Unblocks AG/AH |
| 5 | **AA**, split: the two-line fixes first, screen bank after | Its step 2 moved to position 0; the rest is additive |
| 6 | **AB** | After AA for report-surface coordination only; no code dependency |
| 7 | **Z — last of the column-adding parts** | The only part that changes *which rows exist*. Every pool-relative computation (G4, G7) must be pinned by a golden before Z moves the pool |
| 8 | AC / AG / AH / AI / AJ / AE / AF | Fleet or Clara. Preparable here, not runnable |

**Z does not depend on AA**, contrary to the plan: AA's one load-bearing item
for Z (the ESMFold2 full/fast default) is already closed in code —
`esmfold2_runner.py:36`, `cli/refold_esmfold2.py:81`,
`scripts/refold_esmfold2.py:604` and `evaluate.sh:113` all default to `full`.
Only a docstring is stale.

---

## 4. Cross-part collisions

Twelve were found. These are the ones that cause real rework:

1. **One fixture, three paths, three assertion sets.** The prerequisite,
   AA step 3 and AB step 1 each specify a golden pool at a different path.
   Built independently that is three committed megabytes of `.npy` that can
   never agree. **Resolution:** `tests/integration/golden_pool/` with the
   prerequisite's tiered tests; strike the other two and replace with "consume
   `tests/integration/`". The prerequisite's T2 (`assert_frame_equal` over the
   whole `metrics.csv`) subsumes both.
2. **Five parts insert into `report.py` `run()` lines 164-241** — AC's seed
   collapse, AD's sidecar filter, AA's annotate pass, Z's stage-1 attach, AB's
   novelty join. Sequence them or they conflict every time.
3. **Three parts clone the defect a fourth is fixing.** Z step 6 and AB step 8
   are both instructed to model their new attach "line-for-line on
   `_attach_tmprot_results`" — one of the four unguarded joins. If they land in
   the plan's order, each ships a fresh copy of §1.1.
4. **Two ESMFold2 residues claimed by three parts** (`esmfold2_runner.py:54`,
   `scripts/refold_esmfold2.py:428`). Two lines, three checklists.
5. **Three parts edit the same `evaluate.sh` flag parser, step counter and
   `REPORT_ARGS`** (AA's TmProt step, Z's staged mode, AC's `--rank-seeds`).
6. **Two parts both create `binder_comparison/benchmarks.py`**, and one also
   creates `comparison/benchmark.py` (Y step 7 vs AG steps 10/11).
7. **Three parts extend `hits.py` `HITS_COLUMNS`/`_CARRY`** — hand-maintained
   lists with no registry; a column added to `_CARRY` but not `HITS_COLUMNS` is
   silently dropped at `hits.py:195`.
8. **AA and AH both create the BindPred runner, CLI and env.** AH says "build
   once, shared with AA"; AA does not reciprocate.
9. **The Overath pool has two ids and two doc filenames**, and `pool_id` is a
   path component in Y's design — so `load_pool('overath')` and
   `load_pool('overath2025')` are different pools.
10. **The CA-only fixture sanitisation is incompatible with AB's DSSP panel** —
    `mkdssp` needs backbone N/CA/C/O, and `beta_intercalation.py:41` swallows
    the failure into `(-1,-1,0)`.

---

## 5. What the source plan gets wrong

Per part, the load-bearing corrections. Full detail in the per-part sections.

- **AD — the core premise is wrong.** The plan says each extractor `glob`s its
  tool's outputs so `stat()` on the source file gives a real generation time,
  "one line each". In fact **7 of 8 extractors resolve one aggregate CSV and
  iterate its rows** (`bindcraft.py:115-125`, `bindcraft2.py:189-200`,
  `boltzgen.py:111-119`, `mosaic.py:129-138`, `proteina_complexa.py:314-341`,
  …), so mtime yields **one timestamp for the entire pool**. The plan's split
  into "one-file-per-design tools give a real time / summary-table tools give
  order only" does not survive: all four of its named per-design tools read an
  aggregate CSV. And BindCraft 2's `!_Ranked.csv` is rewritten on *every*
  acceptance, so even the order claim fails.
- **Prerequisite — the spec names a file that does not exist.** `hits.csv`
  appears **nowhere in the repo** (0 grep hits). `Evaluator/tests/` does not
  exist (tests are at repo root; `pytest.ini` sets `testpaths = tests`). There
  are **zero non-`.py` files** anywhere under `tests/`, so there is no fixture
  convention to reuse.
- **Y — the data premise is wrong for 3 of 4 named pools.** They are not only
  under gitignored `runs/`; they live in at least four different roots. And
  `runs/` does not exist on this box at all.
- **AA — `_attach_tmprot_results` is the wrong template.** It is one of the four
  unguarded joins (§1.1). Also D8, the composition gate, is not "code movement"
  from `tools/rfd3_gate.py`: `check_composition()` there is **pool-level**, not
  per-sequence.
- **AB — diversity already runs inline** in `report` by default
  (`cli/report.py:26`, called at `:403`); the plan treats it as a sidecar
  subcommand, so a flag on `cli/diversity.py` alone is a silent no-op. There is
  also **no reusable DSSP parser** in `beta_intercalation.py`, and
  MMseqs2/Foldseek are installed **only inside Proteina-Complexa, on x86**.
- **AC — seed aggregation is placed downstream of the wrong merge.** The plan
  puts it in `scoring.py`, but `merger.py:63` joins on `sequence`, so multiple
  seeds of one design collide there first.

---

## 6. Per-part summary

| Part | BM3 | Effort | Gate (short) |
|---|---|---|---|
| **Prereq — golden pool** | develop + run | ~2 d | Five tiered tests; **all four ranking mutations turn T1 red**, an additive column turns only the column-list assertion red |
| **AD** — discovery-rank | develop + run | ~3 d + 1 campaign | `rank`/`passes_engine_gate`/`consensus_iptm_mean` diff empty; holdout passes a KS test vs the pool |
| **Y** — label registry | develop + run | ~3 d here + ~1 d off-box | `load_pool("cao2022")` re-derives Part U's macro-AUC 0.5552 / 0.5170 |
| **AA** — screen bank | develop + run | ~4 d core, ~8-9 d full | `rank` byte-identical with the full column set vs none |
| **AB** — diversity | develop + run | ~7 d (plan says 5) | A named cross-tool pair in different `family_id`, same structural family |
| **Z** — staged filter | develop only | ~4-5 d | Loses ≤1 of the full run's top 30 and **0 of the top 10** |
| **AC / AG / AH** | develop only | AC ~5 d + 1 GPU-day · AG ~6 d + ~50-95 GPU-h · AH 1 d–2 wk | Shared: `rank` byte-identical on a pinned pool |

**Not investigated — 4 of 12 parts have no coverage:** AE (tool racing), AF
(fourth engine / Chai-1), AI (tune Mosaic's design loss), AJ (MD reverse
check), plus AH-prime. That is 8 assessment rows (S1b, S4, S5, A2, A5b, C1, C6,
C7, C8) with zero investigation.

**BM3 reality:** everything above marked "develop + run" is sequence-only or
CPU. This box **cannot refold** — ESMFold2 peaks at 14,248 MiB at 150 tokens,
above the 12 GB card at the smallest benchmarked size, and it **writes an empty
row and exits 0 on CUDA OOM**, which would produce a complete-looking
`metrics.csv` in which designs were demoted for a hardware reason. Every
measurement step therefore blocks on one archived, fully-refolded pool being
copied here — the longest-lead item in the plan.

---

## 7. Open decisions

1. **Who owns correcting the source plan?** ~50 wrong facts, and the plan lives
   on a share outside the tree, so there is nowhere for a correction to land.
   Proposal: `docs/PLAN_binderscout_v2_corrections.md` in-repo.
2. **Item C2** ("predict target difficulty, size the campaign") is routed to AD
   and appears in none of AD's ten steps —
   `comparison/target_analysis.py:46-84` already ships unvalidated constants.
3. **C4's SPOC half** is uncovered by any part.
4. **Part Z has no row in the assessment CSV.** Its natural item, P4, is routed
   to "AA, AB". The largest-compute-saving part has no provenance.
5. **Y's S7** (weekly dataset watch) has `plan_part=Y` but no deliverable in
   Y's section — in or out?
6. **Version/branch story**: CLAUDE.md says master is frozen at 1.0.3 with
   active work on `v1.1.x`; tags run to `v1.1.1`; the plan anchors to `v1.1.1`;
   the branch is `v2.0.x`; `[Unreleased]` holds the rename. Four accounts.
7. **The install-defect workstream is unassigned** —
   `docs/INVESTIGATION_install_bare_box_2026-09-23.md` records B1-B15, four of
   them false-success defects, one (B14) reproduced live during this session's
   install. No part owns them.
