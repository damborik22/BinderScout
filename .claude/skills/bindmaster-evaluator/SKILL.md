---
name: bindmaster-evaluator
description: Use this skill to evaluate, rank, and quality-check a pool of designed binders. It runs the cross-engine refold (Boltz-2 + AF3 + ESMFold2), produces the cross-engine iPTM ranking (engine gate, then `consensus_iptm_mean`) and HTML/CSV report, ranks affinity among binders via the interface-energy composite (Part N, Rosetta in the BindCraft env), and flags context-dependent folds (monomer validation). It also owns the ESMFold2 `chain_iptm_interface` gate used by the autosize loop. Triggers include "evaluate the pool", "rank the designs", "which are the best", "run the cross-engine refold", "score affinity", "Part N", "check the folds / monomer", "generate the report", "merge the results". It interprets the metrics (the ranking vs ipsae_min, same-model bias, consensus) but does NOT run design tools — it consumes their outputs. Hands the top candidates to `bindmaster-wetlab`.
---

# BindMaster Evaluator — SKILL base

**Audience:** an AI agent turning a pool of designs into a ranked, quality-checked shortlist.
**Job:** extract → refold → rank → affinity → QC → report.

**What this skill is NOT:** not a design runner; not a strategy/allocation brain (orchestrator);
not the final affinity word (no metric ranks affinity perfectly — see `affinity.md`).

---

## 1. The pipeline  →  see `references/pipeline.md`

```bash
binder-compare extract  --<tool> DIR …            -o seqs.fasta
binder-compare refold-boltz2   --sequences seqs.fasta --target-seq SEQ -o boltz2.csv   # Mosaic venv
binder-compare refold-af3      … -o af3.csv        # binder-eval-af3, big-VRAM
binder-compare refold-esmfold2 … -o esmfold2.csv   # default, lightweight; also the autosize gate
binder-compare report   --boltz2-results … --af3-results … --esmfold2-results … -o report/
binder-compare affinity --metrics report/metrics.csv --structures-dir … --run-rosetta -o affinity.csv
binder-compare monomer  --complex-dir … --monomer-dir … -o monomer.csv
```
`TODO:` which conda env hosts which step; resume semantics; ESMFold2 fast-vs-full.

## 2. Reading the ranking  →  see `references/ranking.md`
ONE ranking: cross-engine gate → `consensus_iptm_mean` (`--rank-by` / `--screen-metric` were
removed and now exit 2). `chain_iptm_interface` as a strong screen, the same-model bias matrix,
`ipsae_min` / `agreement_count` as diagnostics only. **Say what the ranking is worth** — ~1.9×
enrichment on a campaign-like pool, beating random on 6 of 12 benchmark targets: a triage filter,
not a decision procedure.

## 3. Affinity among binders (Part N)  →  see `references/affinity.md`
`|dG/dSASA|` energy density, gated by `ipsae_min` (not multiplied — it carries no affinity signal);
Rosetta runs in the **BindCraft** env (cross-platform, incl. aarch64).
`TODO:` when the extra Rosetta cost is worth it.

## 4. Quality control  →  see `references/qc.md`
Monomer-vs-complex Cα RMSD > 3 Å = context-dependent fold (risk). `TODO:` how to act on it.

## 5. Handoff
→ `bindmaster-wetlab` with the top candidates (ranked + affinity + QC).

## 6. References
- `references/pipeline.md`, `references/ranking.md`, `references/affinity.md`, `references/qc.md`
- CLI: `binder-compare {extract,refold-*,report,affinity,monomer,autosize}`
- Sibling: `bindmaster-orchestrator` (its `evaluation.md` is the seed for `pipeline.md`).
