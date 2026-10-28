# BindMaster Orchestrator — Tool Reference Database

Static knowledge base for the `bindmaster-orchestrator` skill. Each file describes one tool used in BindMaster (seven design tools, three refolding/evaluation engines), focused on **orchestration decisions** rather than encyclopedic facts.

## Philosophy

This database documents what each tool produces, in the tool's own terms.

The BindMaster evaluator adds `ipsae_min` (DunbrackLab 2025 iPSAE, uniform 10 Å PAE cutoff) as a **method-agnostic cross-method comparator** over the merged design pool. The evaluator sits *alongside* each tool's native ranking — it doesn't override it. Native metrics from each tool (Mosaic's `ranking_loss`, BindCraft's iPTM + Rosetta battery, PXDesign's composite, etc.) are preserved and used as orchestration signals.

Cross-method ranking in `metrics.csv` (**THE** ranking, Part U — `comparison.scoring.rank_designs`):
1. **Cross-engine gate** — only designs refolded by `consensus_iptm_n >= --min-engines`
   (default 3, floor 2) are eligible. Ineligible rows are ranked last, never dropped
   (`passes_engine_gate`).
2. **`consensus_iptm_mean` descending** — the mean refold iPTM across available engines.
   Ties break on `consensus_iptm_n`, then `consensus_iptm`, then binder pLDDT.

The result is the `rank` column (1 = best).

**Do not rank by `agreement_count`.** The ranking this file used to prescribe — it first,
then `ipsae_min` — matched no default the evaluator ever shipped; pre-Part-U the default
was `two_stage`, already keyed on `consensus_iptm_mean`. Part U removed `agreement_count`
as a sort key outright: on Cao 2022 (4,442 designs / 12 targets / all three engines) it is
a flat null — macro-AUC 0.532 with 87.2% of designs tied at zero. It survives in
`metrics.csv` as a diagnostic column only. `adaptyv_rank` and `consensus_rank` (max-iptm)
went with it; mean-ranking beats max-ranking at precision@top-10% 0.92 vs 0.79.

**This ranks binder-vs-non-binder confidence, not affinity among binders.** Affinity
ranking from structure confidence is closed as negative across four datasets — see
`comparison.affinity` for the advisory gate-then-density ranker.

Tier classification (4-level, from CLAUDE.md `Evaluation metrics`):
- **High:** `ipsae_min > 0.80`
- **Medium:** `0.61 < ipsae_min ≤ 0.80`
- **Low:** `0.40 < ipsae_min ≤ 0.61`
- **Reject:** `ipsae_min ≤ 0.40`

Threshold 0.61 is the agreement threshold (the per-engine "pass" cutoff used in `agreement_count`).

## File index

### Design tools (`*_design.md` equivalent)

| File | One-line summary | Engine | Same-model bias to flag |
|---|---|---|---|
| `bindcraft.md` | AF2 backprop hallucination + MPNN + PyRosetta filtering. Turnkey reference, internal AF2 cross-val. | AF2-multimer / AF2-ptm | Independent of Boltz-2, AF3, ESMFold2 |
| `boltzgen.md` | Diffusion → inverse-folding → Boltz-2 refold pipeline. Two-checkpoint ensemble, diversity-aware filter. | Boltz-2 internally | **Boltz-2 refold is correlated** |
| `mosaic.md` | JAX gradient hallucination over 8 structure predictors. Composable losses, framework not turnkey. | Boltz-2, AF3, AF2 (composable) | **Boltz-2 refold is correlated** |
| `protein-hunter.md` | Iterative structure-hallucination-within-diffusion. Multi-modal, all-X initial sequence. | Boltz-2 (or Chai-1) | **Boltz-2 refold is correlated** |
| `proteina-complexa.md` | NVIDIA flow matching + inference-time search. Atom + sidechain + sequence in one pass. | Flow matching (AF2/RF3 rewards) | Independent of Boltz-2, AF3, ESMFold2 |
| `pxdesign.md` | ByteDance diffusion + Protenix + AF2-IG. 17–82% nanomolar hits across 6/7 therapeutic targets. | Protenix internally | **AF3 refold is correlated** (Protenix reimplements AF3); clean vs Boltz-2 + ESMFold2 |
| `rfd3.md` | All-atom diffusion (RFdiffusion3). Atom-level conditioning, side-chain aware, batch generation. | RFD3 (Baker lab) | Independent of Boltz-2, AF3, ESMFold2 |

### Evaluation / refolding tools

| File | One-line summary | Status | Independence from design pool |
|---|---|---|---|
| `boltz2.md` | Primary refolder. AF3-class diffusion + affinity head. Native `[binder\|target]` ordering, pLDDT `[0,1]`. | Stable, default | Correlated with Mosaic / BoltzGen / Protein-Hunter |
| `protenix.md` | **Retired as a refolder** (Part J reverted 2026-07-26). Background only — PXDesign's internal engine. | Not a refolder | n/a |
| `alphafold3.md` | **Canonical 2nd refolder** (Part K, landed). DeepMind native AF3 v3.0.2. Any CUDA host — ~4.4 GiB peak for 258-391 tokens, so a 24 GB card is enough. | Stable; `--tool af3` (gated weights) | Independent of every design tool **except PXDesign** (Protenix internally) |
| `esmfold2.md` | **The default refolder**, installed by `--tool all`. Lightweight, no gated weights. Also the source of the `chain_iptm_interface` gate `autosize` uses. | Stable, default | Independent of every design tool |

## Entry template

Every tool file follows the same structure:

```
# <Tool Name>

**Engine:** <core model / method, one line>
**Role:** design | refolding | both
**Status:** stable | in-progress | opt-in (gated weights)
**Environment:** <conda env / venv name>

## Principle
<2–4 paragraphs: how it actually works, mechanistically — not marketing>

## Strengths
- <orchestration-relevant strength>

## Weaknesses
- <failure modes and known limits>

## Pick when         (design tools)
## When this engine's signal is most important   (refolders)
- <concrete trigger conditions for the orchestrator>

## Avoid when         (design tools)
## When this engine's signal should be weighted down   (refolders)
- <when a sibling tool is better, with the sibling named>

## Outputs the evaluator parses
- <file format, column names, conventions (PAE ordering, pLDDT scale), parser quirks>

## Key knobs
- <only orchestration-relevant params with typical values, not the full config surface>

## Sources
- Paper, repo, lineage, BindMaster integration notes
```

## Cross-method bias matrix

Same-model bias to watch for when interpreting any per-engine refold column, and when
a design clears the cross-engine gate on fewer than three engines:

|  | Boltz-2 refold | AF3 refold | ESMFold2 refold |
|---|---|---|---|
| BindCraft outputs | clean | clean | clean |
| BoltzGen outputs | **correlated** | clean | clean |
| Mosaic outputs | **correlated** | clean | clean |
| Protein-Hunter outputs | **correlated** | clean | clean |
| Proteina-Complexa outputs | clean | clean | clean |
| PXDesign outputs | clean | **correlated** | clean |
| RFD3 outputs | clean | clean | clean |

"Clean" means the refold engine isn't used by that tool during design, so refold signal is structurally independent. "Correlated" means same-model self-judging applies — the refold can't be the only cross-check.

Practical consequence: **ESMFold2 is clean against all seven design tools; AF3 is clean against all but PXDesign** (PXDesign's internal engine is Protenix, an AF3 reimplementation). Boltz-2 is the correlated one, against three tools. No engine is a "tiebreaker" — the ranking's tiebreak chain is `consensus_iptm_n` → `consensus_iptm` → binder pLDDT (`comparison/scoring.py`), not any one engine's opinion. AF3 is the slowest of the three and its weights are gated, but it runs on any CUDA host (~4.4 GiB peak in our size regime), not aarch64 only.

## Companion content (not in this folder)

This database is the *static* knowledge layer of the orchestrator skill. Two companions live elsewhere:

- **`learnings.md`** — Dynamic experience log from previous Claude Code orchestrator rounds (CBG ground truth, BoltzGen-zero-expression, BLI-vs-SPR, stability ≠ binding, CALCA flexible-target findings). Updated as the lab runs more campaigns.
- **`SKILL.md`** — The orchestration decision logic that consumes this database + learnings. Defines target-classification, tool dispatch, and result-merging logic.

## Sources of truth

- Repo: https://github.com/damborik22/BindMaster
- CLAUDE.md (orchestration context): `BindMaster/CLAUDE.md` in the repo
- iPSAE formula: DunbrackLab 2025 `d0_res` variant; uniform 10 Å PAE cutoff
- Cross-method ranking philosophy: CLAUDE.md `Critical domain facts` ("engine disagreement is signal, not noise")
- Overall design philosophy: each tool's metrics are preserved; the evaluator is an unbiased judge across methods, not a replacement for any tool's native ranking
