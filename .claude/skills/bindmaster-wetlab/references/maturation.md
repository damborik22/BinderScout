# Maturation strategy

After binding data comes back (or, pre-experimentally, from the `affinity` composite as a Kd
proxy), choose the next computational round and the parents to carry forward.

```bash
binder-compare mature --designs results.csv --affinity-col kd_nM \
    --round 2 --target-affinity 10 -o maturation_round.json
```

## Decision tree (`comparison/maturation.decide_maturation_strategy`)
Best affinity seen (lower nM = tighter) → strategy:

| Best affinity | Strategy | Expected | Why |
|---|---|---|---|
| meets `--target-affinity` | **done** | — | stop; ship to the lab |
| > 500 nM (weak) | **partial_diffusion** | 2–10× | explore *backbone* space — the fold may be wrong |
| > 50 nM (moderate) | **mpnn_redesign** | 2–5× | keep the backbone, optimize the *sequence* |
| ≤ 50 nM (strong) | **mutation_scan** | 1.2–2× | fine-tune individual residues |
| no measurement | mpnn_redesign | — | cheapest backbone-preserving default |

Thresholds (`--partial-threshold` / `--mpnn-threshold`) are program-overridable.

## Parents
- backbone / sequence rounds: the **top-k tightest** binders (`--top-k`, default 5).
- mutation scan: the **single best**.
- done: none.

## Seeding the next round (→ orchestrator / worker)
The `mature` JSON (strategy + parent ids) becomes a new DESIGNING assignment:
- **partial_diffusion** → RFD3 with a *partial* noise schedule seeded from each parent backbone
  (re-noise + re-denoise locally), then ProteinMPNN → autosize gate. `TODO:` pin the RFD3
  partial-diffusion flags (worker `new-run-types.md`).
- **mpnn_redesign** → ProteinMPNN on the fixed parent backbones (best-of-N), then refold.
- **mutation_scan** → enumerate point mutants of the single best; refold + score.

Then the loop re-enters `autosize → evaluator → wetlab`.

## Stop criteria
Stop when the best meets `--target-affinity`, or improvement per round flattens (< ~1.5× over the
prior round), or the wet-lab gate is reached. Don't mature forever — each round is GPU + (often) a
new assay.
