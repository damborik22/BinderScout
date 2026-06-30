---
name: bindmaster-wetlab
description: Use this skill to take ranked binder designs out of silico — generate the experimental handoff and plan the next computational round from results. It builds a wet-lab plan (gene synthesis + codon optimization, expression conditions, testing via Adaptyv with a BLI / SPR / FIDA panel, controls, FASTA with biophysical properties) via `binder-compare wetlab`, and after binding data comes back it chooses the next maturation strategy (partial diffusion / MPNN redesign / mutation scan / done) and the parents to carry forward via `binder-compare mature`. Triggers include "prepare the wet-lab plan", "what should we order / test", "generate the gene FASTA", "we got Kd / BLI / SPR results — what next", "plan the next maturation round", "should we mature these", "close the loop". It emits the plan and the maturation spec; the actual maturation design round is handed back to `bindmaster-orchestrator`.
---

# BindMaster Wet-Lab Advisor — SKILL base

**Audience:** an AI agent at the in-silico → wet-lab boundary, and back. **Job:** turn the
evaluator's shortlist into an orderable/expressable/assayable plan, then turn binding results
into the next computational round — closing the campaign loop.

**What this skill is NOT:** not a design runner (emits the `mature` spec → orchestrator); not a
LIMS; vendor/cost defaults are lab-overridable, not authority.

---

## 1. Wet-lab plan  →  see `references/assays.md`, `references/synthesis.md`

```bash
binder-compare wetlab --designs report/top30_candidates.csv -o wetlab_plan.md \
    --top 20 --budget 8000 --tag His6-TEV
```
Sections: gene synthesis (codon-opt, tag), expression, **testing via Adaptyv** (BLI quick yes/no
→ SPR + FIDA on leads — see `assays.md`), controls, FASTA + biophysics. `--budget` sets how many
designs to submit to Adaptyv (every submission gets BLI; leads get SPR + FIDA).

## 2. Maturation — the next round  →  see `references/maturation.md`

```bash
binder-compare mature --designs results.csv --affinity-col kd_nM \
    --round 2 --target-affinity 10 -o maturation_round.json
```
Kd (or the `affinity` composite as a pre-experimental proxy) → strategy: weak >500 nM →
partial diffusion; moderate >50 nM → MPNN redesign; strong → mutation scan; meets target → done.
`TODO:` thresholds per program; how the `mature` JSON becomes an orchestrator kickoff.

## 3. Handoff
→ **`bindmaster-orchestrator`**: the `mature` spec (strategy + parent ids) seeds a new DESIGNING
round (RFD3 partial-diffusion / ProteinMPNN), looping back into autosize → evaluator → wetlab.

## 4. References
- `references/assays.md`, `references/maturation.md`, `references/synthesis.md`
- CLI: `binder-compare {wetlab,mature}`; cores `comparison/wetlab.py`, `comparison/maturation.py`.
- Siblings: `bindmaster-evaluator` (supplies the shortlist), `bindmaster-orchestrator` (runs the round).
