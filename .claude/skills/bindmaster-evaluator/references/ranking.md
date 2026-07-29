# Reading the ranking

**There is ONE ranking and no way to choose another** (Part U, 2026-07-28). It produces a single
`rank` column. `--rank-by` and `--screen-metric` were **removed**, not deprecated — passing either
exits 2.

- **Stage 0 — cross-engine gate.** A design must have been refolded by at least `--min-engines`
  independent engines (**default 3** = Boltz-2 / AF3 / ESMFold2; floor 2). Without it a
  single-engine design's mean *is* that engine's score, competing against 3-engine means on an
  incomparable scale — and for Mosaic / Protein-Hunter that engine is the one that designed it.
  Designs failing the gate rank **last, not dropped** (`passes_engine_gate` records it).
- **Rank — `consensus_iptm_mean`**, the mean engine iPTM. Ties break on `consensus_iptm_n` (more
  engines behind an equal mean wins), then `consensus_iptm`, then binder pLDDT.

`consensus_iptm` (max across engines) survives as a **diagnostic column only — it does not rank.**
Max-ranking loses to mean-ranking (precision@top-10% 0.79 vs 0.92).

## Calibrate the reader before showing a top-N

**It is a triage filter, not a decision procedure.** On the Cao 2022 near-miss pool (4,442 designs,
12 targets — the closest analogue to a real campaign: hundreds of same-tool, same-length designs
against one target) the whole 72-metric field spans macro-AUC **0.471–0.560**, and the top decile is
worth ~**1.9×** enrichment (FGFR2 8.98 → 2.13 designs per hit) — but it beats a random ordering on
only **6 of 12 targets**, and on TrkA and Tie2 it is *worse than not ranking at all*.

Ranking looks much stronger on easier pools: Adaptyv **0.68–0.72**, de novo BindCraft **0.72–0.78**
macro, and Cao itself rises to **0.73** once one-sided-Kd "binders" are excluded (73.4% of its binder
labels are one-sided and are experimentally indistinguishable from non-binders on Cao's own binary
assay). Presenting a top-10 as "the best" without this framing over-sells by a wide margin.

## Key signals

- **`chain_iptm_interface`** (ESMFold2 chain-pair interface iPTM) — a strong binder screen
  (macro AUC ≈ **0.69** on the full Adaptyv batch; an earlier 0.745 was a subset figure and is
  inflated — do not quote it), and the `autosize` gate. Surfaced as a column.
- **Same-model bias** — never accept a design on the engine it was *designed against*: BoltzGen /
  Mosaic / Protein-Hunter game `boltz_iptm`; PXDesign games Protenix. AF3 is independent of every
  design tool. (Matrix: `bindmaster-orchestrator/references/tools/README.md`.) The mean across
  independent engines is what resists this — a design one engine loves and another rejects is
  demoted by the mean.
- **`ipsae_min`** and the quality tiers (High > 0.80 / Medium 0.61–0.80 / Low 0.40–0.61 / Reject
  ≤ 0.40) — **diagnostic**, not the sort key.
- **`agreement_count`** — diagnostic only. **Do not gate or stratify on it:** macro-AUC 0.532 with
  87.2% of designs tied at zero, and splitting the pool at the median engine spread moves AUC by
  less than a random-split null (p = 0.71/0.81).

## Do not re-open these

Metric and combination search on labelled data is **closed**. Honest nested selection over 72
metrics scores **0.517**, worse than the **0.555** of the shipped metric (p = 0.0014, 8/12 targets);
the best of 2,489 searched combinations sits inside the permutation null. The Stage-1 max screen
removed 0 designs from the top decile on 12/12 targets and was retired. Affinity ranking from
structure confidence is closed as negative on four independent datasets.
Full write-up: `docs/INVESTIGATION_partU_cao_benchmark.md`.

## The one caveat to state out loud

The ranking orders **binder-vs-non-binder**, *not affinity among binders*. The head of the list is
"most likely to bind at all", not "tightest". Rank affinity with `affinity.md` (Part N) on the
shortlist — and note Part N landed as a negative result, so that ranker is **advisory**, not
validated.

## Explaining a ranking to a human

Lead with: rank, the three engine iPTMs (show the spread — agreement vs one-engine spike),
`consensus_iptm_n`, and whether an *independent* engine backs the score. Say plainly when engines
disagree rather than hiding it, and state the enrichment the ranking is actually worth.
