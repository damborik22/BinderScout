# DRAFT — Evaluation reference: how BinderScout ranks designs

> **STATUS: DRAFT FOR REVIEW, 2026-10-03.** Everything here is derived from the code
> (file:line given throughout) and from measurements on labelled pools. Nothing else in the
> repo has been changed. Once reviewed this is intended to split into
> `ranking.md` (how and why) and `metrics.md` (the column catalogue) in this directory,
> with the ~40 other files that currently carry pieces of this pointing here.
>
> **Sections 9–12 are not reference material** — they are the defect and contradiction
> lists this derivation produced, and the open questions I need decided. They come out of
> the final doc.

---

## 1. The answer, in one paragraph

There is **one** ranking and no way to select another. A design must have been refolded by
at least `--min-engines` independent engines (**default 3**: Boltz-2, AF3, ESMFold2); the
survivors are sorted by **`consensus_iptm_mean`**, the mean of the three engines'
**PAE-recomputed** ipTM. Designs failing the gate are ranked **last, not dropped**. The
output is a single `rank` column. Everything else the evaluator produces either feeds that
number, flags a caution for a human, or is reported for inspection — and the catalogue in
§6 says which, per column.

---

## 2. Why three engines — the Roman principle

**No single engine can put a design on a pedestal, or cast it into Tartarus.**

That is the design rationale, and it is **adversarial**, not statistical. It is not "three
measurements average out noise". It is that **any one engine can be confidently and
systematically wrong about an entire class of designs**, and you cannot know in advance
which engine or which class. The mean denies a lone engine the power to decide in either
direction: a single enthusiast is dragged down by the other two, and a single detractor is
outvoted by them.

### The mechanism is the mean itself

`consensus_iptm_mean` **is** the agreement rule — it is not an approximation of one, and a
vote count would be worse. A high mean requires all three scores high, so three must
effectively agree to promote. One dissenter drags the mean down **proportionally rather
than fatally** — the design survives, demoted. Two dissenters drag it under.

Measured on the canonical labelled pool, against real experimental labels — of true binders
buried in an engine's own within-target bottom quartile:

| buried by | rescued by the mean |
|---|---|
| exactly **one** engine (n=70) | **92.9 %** |
| **two** engines (n=20) | **25.0 %** |
| **three** engines (n=8) | **0 %** |

That gradient *is* "two will not kill it completely; three decide".

### The evidence for the no-veto half

**A single engine demonstrably buries a whole class of real binders.** AF3 scored the
`protrl` EGFR designs at a mean ipTM of **0.129** — Boltz-2 gave 0.911, ESMFold2 0.749 —
while **35 of those 44 designs bind experimentally**. Permutation p=0.0002, surviving
length adjustment; AF3's in-cell AUC 0.562 against ESMFold2's 0.752.

Two further instances exist **with a different engine at fault each time** (Boltz-2 on
bindcraft/EGFR, ESMFold2 on dsm-synteract/pd-L1), and **the worst engine changes on every
one of the four targets**:

| target | worst engine | 3-mean advantage over it |
|---|---|---|
| EGFR | AF3 | **+0.256** |
| IL7R | **Boltz-2** | +0.063 |
| Nipah | AF3 | +0.190 |
| pd-L1 | **ESMFold2** | +0.118 |

The 3-mean is **never worst**, on 4/4 targets. Each engine's *deviation from the other two*
also carries genuine incremental signal (partial Spearman vs binding, conditioning on the
other two: Boltz-2 **+0.314**, ESMFold2 **+0.213**, both p<1e-4).

### What this argument is NOT

**Three engines do not beat one or two on average on that pool** — `boltz+esm` 0.734 >
all-three 0.726 > `boltz` alone 0.720. Where three wins is **the worst case**. The value is
insurance, which is exactly why AF3 stays despite being weakest on average: on IL7R the
villain was Boltz-2.

**Two caveats on the rationale, both measured:**
- The variance half is **real but bounded**. One engine buries a true binder **5.69×** more
  often than all three together (CI [3.27, 18.39]; 11.4× at a bottom-decile cut) — but a
  random-ordering null gives **17.2×** (p=0.0008), so the engines are *not* independent
  votes. Error correlation within target and within class is ρ ≈ 0.39: **effective n =
  1.6–1.7 of 3**.
- Joint burial is **length-linked**: mean binder length 84.5 aa when no engine buries a
  true binder, **119.9 aa** when two do. That is the shared failure mode.
- **The design-time gaming does NOT transfer to refold time, measured.** Mosaic *is*
  Boltz-2 gradient hallucination, so its design-time objective is Boltz-2 confidence — but
  on the labelled pool Boltz-2 ranks Mosaic's designs **lower** than AF3 or ESMFold2 do
  (rel_boltz −0.0346, wrong sign on 2/2 targets), and the pre-specified gaming contrast
  fails overall (p(>0)=0.29). A refold is a fresh fold from sequence with an MSA. **Keep
  the no-veto argument; drop the "designers inflate their own engine's refold score" one.**
  *(The pedestal direction of the Roman principle is sound by the same arithmetic as the
  Tartarus direction, but has not been measured directly — flagged as a gap, not a claim.)*

---

## 3. What the ranking is worth, and where it is blind

**This section belongs near the top of the final doc.** It is what decides whether a top-N
list should be trusted.

| pool | binders | `consensus_iptm_mean` within-target AUC |
|---|---|---|
| CALCA, **expressed only** (114 of 125) | 99 vs 15 | **~0.706** |
| CALCA, **full panel** (125) | 99 vs 26 | **0.4835** |
| CBG / 2VDY (full panel, 136 scored) | 10 (7.3 %) | **0.4595** (0.496 recorded) |
| curated Adaptyv/ProteinBase (563, 4 targets) | 258 (45.8 %) | **0.7113** |
| …same, expressed only (543) | 258 vs 285 | 0.7093 (**−0.002**) |

**Always state the denominator.** A blank `KD` on our panel means *binding not detected* **or**
*not expressed*; the 114 figure excludes the 11 non-expressed, which is a principled filter and
the same one Adaptyv uses. The filter is near-free there (6.6 % of the negative class, −0.002)
and decisive on CALCA (42 % of it, ~0.22) purely because CALCA has 26 negatives. Expressed-only
asks *can the metric rank binding among proteins that exist*; the full panel asks *will a top
pick yield a usable hit* — the campaign question. Neither is wrong; quoting one without its
denominator is. Note `CALCA_SPOC.csv` has no expressed column, so the 114 cannot be recomputed
from it (Part AK, step AK0).

**On a hard target the ranking measured at chance.** On CBG the `>= 0.85` slice bound at
**6.8 %** against **10.0 %** below it (Fisher p=0.74) — the lever ran backwards. Confirmed
to be our metric and not a proxy: the panel's `Mean_iPTM` matches `consensus_iptm_mean` on
135/137 designs to the decimal.

**The correct reading, from `docs/REPO_DIARY.md`:** pool mean ipTM tells you **the target
is tractable**, not **which design on a hard target will bind**. A between-target signal,
on n=2 targets. Conflating the two is the trap.

Corroboration that CBG is a *target* problem rather than a sampling-depth one: BoltzGen with
identical filters over ~10k designs per target gives `pass_filter_rmsd` ("folds as
intended") **80.3 % CALCA vs 5.2 % CBG**, while every composition filter behaves the same
on both. The collapse is structural.

**So: the ranking is a triage filter, not a decision procedure.** Expect ~1.5–2× enrichment
on a tractable target and nothing on a hard one. Nothing in the pipeline currently predicts
which kind of target you have before you spend the GPU — that is an open gap.

---

## 4. The pipeline, in execution order

```
  per-tool outputs                      extract (one extractor per tool)
         │                                      │
         ▼                                      ▼
   designs.csv / native CSVs            sequences.fasta + *_native_metrics.csv
                                                │
          ┌─────────────────────────────────────┼──────────────────────────────┐
          ▼                   ▼                 ▼                              │
      Boltz-2             AF3 v3.0.2        ESMFold2        (SoluProt / TmProt: label only,
   (Mosaic venv)       (binder-eval-af3) (binder-eval-esmfold2)  run BEFORE refolding)
          │                   │                 │
          └──── per-engine CSV + PAE .npy + structures ────┐
                                                           ▼
                                               binder-compare report
                                                           │
   merge on `sequence` (1:1 validated) → native metrics → shadow annotations →
   PAE loaded, ipTM + ipSAE RECOMPUTED per engine → agreement_count →
   consensus_iptm / _mean / _n → rank_designs → wetlab → metrics.csv + report.html
```

Engine detection is by **conda env name only** (`evaluate.sh:253-290`); nothing checks the
env can import its engine, so an empty env shell counts as installed. Boltz-2 is the
exception — it is resolved from `Evaluator/envs/mosaic_venv_path` and the run is **refused**
if its `binder-compare` is absent (`:228-241`).

**`--skip-<engine>` is not symmetric** (`evaluate.sh:561-643`): `--skip-boltz2` means
*reuse the existing CSV* and still passes it to the report; `--skip-af3` and
`--skip-esmfold2` mean *drop the engine entirely*, so an existing CSV is **not** passed —
and at the default gate of 3 every design then fails `passes_engine_gate`.

The exact `report.py` call order is load-bearing (a block placed before `rank` existed was a
real bug) and is listed in §9.2.

---

## 5. The ranking itself

`rank_designs` (`scoring.py:828-936`):

1. **Refuses** `min_engines < 2` (`MIN_ENGINES_FLOOR`).
2. **Gate:** `consensus_iptm_mean.notna() & (consensus_iptm_n >= min_engines)`. Recorded in
   `passes_engine_gate`. Failures rank **last**, not dropped.
3. **Sort:** `passes_engine_gate` desc, then `consensus_iptm_mean` desc, then
   `consensus_iptm_n` desc (more engines behind an equal mean wins), then `consensus_iptm`
   (the **max**) desc, then binder pLDDT desc.
4. **When nothing clears the gate**, `passes_engine_gate` goes constant and stops
   discriminating, so the order becomes `consensus_iptm_mean` alone — and a design scored
   by **one** engine can outrank one scored by three. This is warned about loudly
   (`scoring.py:893-923`), because it is the single-engine failure the gate exists to
   prevent. The warning is **stderr only** and does not reach `report.html`.

**What is averaged:** `_ENGINE_IPTM_COLS` = `boltz_pae_iptm`, `af3_pae_iptm`,
`esmfold2_pae_iptm` — all **recomputed from the `.npy` PAE matrices** by
`add_iptm_from_pae_files` / `compute_iptm_from_pae` (`scoring.py:391-444`, `:600-663`),
*not* the engines' self-reported `*_iptm`, which are reported only. The kernel is
max(bt,tb) of `max_i[mean_j 1/(1+(PAE_ij/d0)²)]` with a global
`d0 = max(1.0, 1.24·∛(L−15) − 1.8)` and **no PAE cutoff** — deliberately different from the
ipSAE kernel, which uses a 10 Å cutoff and a per-residue d0.

**An engine contributes nothing unless its column name is in `_ENGINE_IPTM_COLS`.** The gate
counts list membership, not data: a populated `newengine_pae_iptm` left out of that list is
invisible (measured — `consensus_iptm_n` stayed 2; adding the name moved it to 3).

**The gate measures COVERAGE, not AGREEMENT** — how many engines produced a score. On every
labelled pool we own, coverage is 100 % constant, so the gate is **exactly inert** there
(within-target Spearman 1.000 between `min_engines` 2 and 3). Its value is entirely about
*missing* engines.

---

## 6. Metric catalogue

**ROLE** is the field that was missing everywhere: `RANKS` feeds `rank` · `GATES` can
exclude or demote · `WARNS` is a per-design caution for a human · `REPORTS` is emitted for
inspection only · `NATIVE` is a design tool's own metric carried through untouched.

| column | what it is | dir | ROLE | validation |
|---|---|---|---|---|
| `consensus_iptm_mean` | mean of the three PAE-recomputed ipTMs | ↑ | **RANKS** (key 2) | 0.706 CALCA / 0.496 CBG / 0.723 Adaptyv |
| `passes_engine_gate` | cleared `--min-engines` | ↑ | **RANKS** (key 1) + GATES | gate inert at 100 % coverage |
| `consensus_iptm_n` | how many engines scored it (0–4) | ↑ | **RANKS** (key 3) | — |
| `consensus_iptm` | **max** ipTM across engines | ↑ | **RANKS** (key 4) | max-ranking loses to mean-ranking (Part U) |
| `plddt_binder_mean/min` | binder fold confidence | ↑ | **RANKS** (key 5, min) | — |
| `rank` | the single output ordering | ↓ | the result | — |
| `agreement_count` | engines over an **absolute ipSAE 0.61** — **a different quantity from ipTM** | ↑ | **WARNS** (and see §12.1) | macro-AUC **0.669** on our pool (0.532 on Cao) |
| `*_pae_iptm` | per-engine ipTM recomputed from PAE | ↑ | **RANKS** (via the mean) | — |
| `*_iptm` | engine's **self-reported** ipTM | ↑ | REPORTS | scales differ sharply between engines |
| `ipsae_min` | min(bt,tb) iPSAE, DunbrackLab 2025 | ↑ | REPORTS + GATES (affinity) | **measured INVERTED** on our SPOC data |
| quality tiers (High/Medium/Low/Reject) | bands on `ipsae_min` | — | REPORTS | **measured INVERTED** — "Reject" held 6/10 CBG binders; "High" fired on none |
| `passes_affinity_gate` | `ipsae_min >= 0.61` | ↑ | GATES (`affinity` only) | **measured INVERTED** |
| `*_pae_*`, `ipae` | PAE block statistics | ↓ | REPORTS | |
| `ranking_loss` | Mosaic's design-stage loss | ↓ | NATIVE | gameable: Mosaic's own objective |
| `self_consistency_rmsd`, `passes_self_consistency` | target-aligned RMSD between refolds | ↓ / ↑ | REPORTS (shadow) | unvalidated |
| `passes_confidence_gate`, `confidence_fail_reasons` | BindCraft's filters, ported exactly | ↑ | REPORTS (shadow) | unvalidated |
| `would_exclude_*` | what each shadow gate *would* have removed | — | REPORTS | — |
| `seq_family_*` | near-duplicate sequences, k-mer Jaccard ≥ 0.20 | — | REPORTS | all observed near-dupes were same-tool |
| `struct_family_*` | shared fold, Foldseek TM ≥ 0.5, binder chain only | — | REPORTS | max pairwise sequence Jaccard 0.298 over 114 designs — folds are invisible to sequence methods |
| `generation_index`, `_source` | where a design fell in generation order | — | REPORTS | 5 of 8 tools can report; `unavailable` is first-class |
| `soluprot_*` | sequence-only solubility | ↑ | REPORTS (label only) | best available predictor of *expression*; filter mode removed |
| `tmprot_*` | predicted melting temperature | ↑ | REPORTS (label only) | advisory; must not grow a filter |
| `wetlab_recommended`, `wetlab_reason` | blockers + informational notes | ↑ | GATES (advisory) | see §12.1 |
| `epitope_match_fraction` | contact overlap with intended hotspots | ↑ | REPORTS | — |
| `native_*` | a tool's own metrics, prefixed | — | NATIVE | each gameable by its own tool |

---

## 7. Conventions that have caused real bugs

1. **pLDDT scale.** Boltz-2 returns [0,1]; AF3 is native [0,100] and is rescaled on ingest.
   **BindCraft 2's `bindcraft2_plddt` and `_iptm` arrive on [0,1] and must NOT be rescaled**
   — dividing again silently flattens the pool. `bindcraft2_ipae` is interface PAE **÷ 31**
   and is **not in ångströms**, so it is not comparable with `pae_*`.
2. **PAE ordering.** Boltz-2 is native `[binder|target]`. AF3 is token-order, so the target
   goes first in the input JSON and the matrix is **permuted** (an `np.block`
   rearrangement, not a transpose). A new engine must declare its ordering.
3. **Column registration.** See §5 — membership of `_ENGINE_IPTM_COLS` is the gate's actual
   mechanism.
4. **Gameability map.** Never read a tool's own engine as an independent opinion about that
   tool's designs: Mosaic ↔ Boltz-2 (it *is* Boltz-2 gradient hallucination), BindCraft and
   BindCraft 2 ↔ AF2 i_pTM, PXDesign ↔ its internal Protenix, Protein-Hunter ↔ Boltz-2 /
   Chai-1. Note §2's finding that this bias is **not** observed at refold time.
5. **AF3 bucket floor.** `AF3_MIN_BUCKET = 256`, AF3's own smallest compilable shape. Below
   it, tokamax's kernels request 110,592 bytes of shared memory against sm_86's 101,376 and
   the refold aborts. Measured both ways on an RTX 3090.
6. **The target MSA is fetched once per target** and shared by all three engines via a
   SHA-256-keyed disk cache. This is what defeats the ColabFold rate limit across sessions.

---

## 8. Removed — do not re-add

| removed | evidence |
|---|---|
| `--rank-by`, `active_rank` | honest nested selection over 72 metrics scored **0.5170** vs **0.5552** for `consensus_iptm_mean` alone (p=0.0014) |
| `--screen-metric`, stage-1 max screen, `passes_max_screen` | removed **0 designs** from the top-5/10/20/50 on 12/12 targets; the `max` default was documented as lenient and was the opposite |
| `adaptyv_rank` | `agreement_count` as a *screen* was a flat null **on Cao** (see §12.2) |
| `consensus_rank` (max-ipTM) | max-ranking loses to mean-ranking, precision@top-10 % 0.79 vs 0.92 |
| `--soluprot-filter` | at its own default threshold it discarded several of the tightest measured binders; no threshold above 0.0 met the recall bar |
| AF2 refolding | Part I; BindCraft / PXDesign still use AF2 internally |
| Protenix refolding | Part J reverted; AF3 covers the independent cross-check |
| shrinkage on the gate | +0.0003…0.0006 macro AUC, CIs straddling zero, `k` unidentifiable — and coverage never varies, so it fixes a failure mode that does not occur |
| `mean(af3, esm)` | reversed with significance on a second pool (−0.0210, p<0.0001, 0/4 targets) |

---

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

## 11. Orphans that must survive the unification

Knowledge existing in exactly **one** file (35 found; these are the ones I would most hate
to lose):

- **AF3 weights licensing** (`Evaluator/README.md`) — the ToU bars commercial use of
  outputs and release of raw scores/structures for training, which conflicts with
  publishing our scores. The only record of *why* the engine line-up is what it is on legal
  grounds.
- **The cross-method bias matrix** — 8 design tools × 3 refold engines, clean/correlated per
  cell (`skills/binderscout-orchestrator/references/tools/README.md`). The evaluator skill
  names that file as its authority, so it cannot simply be deleted.
- **The measured GPU-memory table** (`README.md`) — AF3 2.3–5.2 GB flat; **ESMFold2's
  14.2 GB floor at 150 tokens, so a 12 GB card cannot run it at any size**, and it writes an
  empty row and exits 0 on CUDA OOM; Boltz-2 139.6 GB at 900 tokens.
- **`chain_iptm_interface` macro-AUC 0.69** on the *full* Adaptyv batch, with the explicit
  instruction not to quote the inflated 0.745 subset figure.
- **BindCraft 2 native scales** (`pipeline_reference.md`) — see §7.1.
- **The iPSAE directional formula in prose** and the 10 Å uniform-cutoff rationale
  (`references/evaluation.md`), plus wall-time budgets (~30 GPU-h per 500-design 3-engine
  pool).
- **The Stage-1 inertness counterexample** (`CLAUDE.md`) — A=(.5,.5,.5) vs B=(.9,.1,.1)
  shows elementwise `mean ≤ max` does not imply rank preservation.

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
