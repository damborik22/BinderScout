# Reading the ranking

The report's default is **two-stage cross-engine iPTM** (`--rank-by two_stage`), benchmark-validated
on ProteinBase (4 targets). Two stages because the metric that best *screens* binders isn't the one
that best *orders* the survivors:

- **Stage 1 — screen (recall):** `consensus_iptm` = the **max** engine iPTM across Boltz-2 / AF3 /
  ESMFold2. Keep the top 50% (`passes_max_screen`). The most-predictive engine flips per target, so
  "trust whichever is most confident" gives the best binder-vs-non-binder AUC (~0.755).
- **Stage 2 — rank (precision):** order survivors by `consensus_iptm_mean` = the **mean** engine
  iPTM. At the sharp end you want designs *all* engines agree on (precision@top-10% 0.92 vs 0.79 for
  max alone). `two_stage_rank` is the column; nothing is dropped (the screen is a flag + ordering).

## Key signals
- **`chain_iptm_interface`** (ESMFold2 chain-pair interface iPTM) — the **single strongest** binder
  screen on the benchmark (macro AUC ≈ 0.745), and the `autosize` gate. Surfaced as a column.
- **Same-model bias** — never accept a design on the engine it was *designed against*: BoltzGen /
  Mosaic / Protein-Hunter game `boltz_iptm`; PXDesign games Protenix. Require an *independent*
  engine in `agreement_count`. AF3 is independent of every design tool. (Matrix:
  `bindmaster-orchestrator/references/tools/README.md`.)
- **`ipsae_min`**, **`agreement_count`** (engines past ipsae_min > 0.61), **quality tiers** —
  secondary / diagnostic columns; `adaptyv_rank` and `consensus_rank` coexist for comparison.

## The one caveat to state out loud
Two-stage ranks **binder-vs-non-binder**, *not affinity among binders*. The head of the list is
"most likely to bind at all", not "tightest". Rank affinity with `affinity.md` (Part N) on the
shortlist.

## Explaining a ranking to a human
Lead with: rank, the three engine iPTMs (show the spread — agreement vs one-engine spike),
`agreement_count`, and whether the top metric came from an *independent* engine. A design one engine
loves but another rejects is demoted by the mean — say so rather than hiding the disagreement
(disagreement is signal, especially for short ~60 aa binders).
