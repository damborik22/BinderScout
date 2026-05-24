# BindMaster Orchestrator — Tool Reference Database

Static knowledge base for the `bindmaster-orchestrator` skill. Each file describes one tool used in BindMaster (six design tools, three refolding/evaluation engines), focused on **orchestration decisions** rather than encyclopedic facts.

## Philosophy

This database documents what each tool produces, in the tool's own terms.

The BindMaster evaluator adds `ipsae_min` (DunbrackLab 2025 iPSAE, uniform 10 Å PAE cutoff) as a **method-agnostic cross-method comparator** over the merged design pool. The evaluator sits *alongside* each tool's native ranking — it doesn't override it. Native metrics from each tool (Mosaic's `ranking_loss`, BindCraft's iPTM + Rosetta battery, PXDesign's composite, etc.) are preserved and used as orchestration signals.

Cross-method ranking in `summary.csv`:
1. **`agreement_count`** (how many engines say `ipsae_min > 0.61`) — primary sort
2. **`ipsae_min` descending** — secondary sort

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
| `bindcraft.md` | AF2 backprop hallucination + MPNN + PyRosetta filtering. Turnkey reference, internal AF2 cross-val. | AF2-multimer / AF2-ptm | Independent of Boltz-2, Protenix, AF3 |
| `boltzgen.md` | Diffusion → inverse-folding → Boltz-2 refold pipeline. Two-checkpoint ensemble, diversity-aware filter. | Boltz-2 internally | **Boltz-2 refold is correlated** |
| `mosaic.md` | JAX gradient hallucination over 8 structure predictors. Composable losses, framework not turnkey. | Boltz-2, Protenix, AF2 (composable) | **Boltz-2 refold is correlated** |
| `protein-hunter.md` | Iterative structure-hallucination-within-diffusion. Multi-modal, all-X initial sequence. | Boltz-2 (or Chai-1) | **Boltz-2 refold is correlated** |
| `proteina-complexa.md` | NVIDIA flow matching + inference-time search. Atom + sidechain + sequence in one pass. | Flow matching (AF2/RF3 rewards) | Independent of Boltz-2, Protenix, AF3 |
| `pxdesign.md` | ByteDance diffusion + Protenix + AF2-IG. 17–82% nanomolar hits across 6/7 therapeutic targets. | Protenix internally | **Protenix refold is correlated** |
| `rfd3.md` | All-atom diffusion (RFdiffusion3). Atom-level conditioning, side-chain aware, batch generation. | RFD3 (Baker lab) | Independent of Boltz-2, Protenix, AF3 |

### Evaluation / refolding tools

| File | One-line summary | Status | Independence from design pool |
|---|---|---|---|
| `boltz2.md` | Primary refolder. AF3-class diffusion + affinity head. Native `[binder\|target]` ordering, pLDDT `[0,1]`. | Stable, default | Correlated with Mosaic / BoltzGen / Protein-Hunter |
| `protenix.md` | Second refolder (Part J in progress). ByteDance AF3 reimplementation, 4 checkpoint tiers, Apache 2.0. | In progress | Correlated with PXDesign |
| `alphafold3.md` | Third refolder (Part K in progress). DeepMind native AF3 v3.0.2, aarch64 / DGX Spark only. | In progress, aarch64 only | **Fully independent of every design tool** |

## Entry template

Every tool file follows the same structure:

```
# <Tool Name>

**Engine:** <core model / method, one line>
**Role:** design | refolding | both
**Status:** stable | in-progress | aarch64-only
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

Same-model bias to watch for when interpreting `agreement_count`:

|  | Boltz-2 refold | Protenix refold | AF3 refold |
|---|---|---|---|
| BindCraft outputs | clean | clean | clean |
| BoltzGen outputs | **correlated** | clean | clean |
| Mosaic outputs | **correlated** | clean | clean |
| Protein-Hunter outputs | **correlated** | clean | clean |
| Proteina-Complexa outputs | clean | clean | clean |
| PXDesign outputs | clean | **correlated** | clean |
| RFD3 outputs | clean | clean | clean |

"Clean" means the refold engine isn't used by that tool during design, so refold signal is structurally independent. "Correlated" means same-model self-judging applies — the refold can't be the only cross-check.

Practical consequence: **AF3 is the only refolder fully independent of every design tool in the pool**, which is why CLAUDE.md positions it as the gold-standard tiebreaker — even though it's aarch64-only and slowest.

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
