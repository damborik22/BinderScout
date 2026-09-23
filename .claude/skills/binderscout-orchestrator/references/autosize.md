# Autosize — the adaptive sampling loop

Extension to the orchestrator skill. `binder-compare autosize` answers "do we have **N
independent** good designs yet?" and sizes the next batch — so the orchestrator no longer hand-does
the "BindCraft 50 / BoltzGen 10 000" yield math.

## What it does
- **Equal-N across tools** — every tool is driven to the same `--n-target`; a per-tool
  `--budget-cap` (GPU-h) lets a hard tool settle for fewer rather than burning forever. No overshoot
  (it stops at N).
- **Gate** — ESMFold2 `chain_iptm_interface` (the strongest single binder screen), tier-aware:
  `--tier permissive|default|strict` (0.70 / 0.75 / 0.80), or an explicit `--threshold`.
- **Independence** — counts **backbones** (`design_group`), not sequences, so MPNN/cycle variants
  of one trajectory collapse to one design.
- **Next batch** — `ceil((N − have) / yield × margin)` from the running yield; cold start explores
  `MIN_PROBE`; stops with `budget` if the cap is hit (reports the shortfall — that's signal, not failure).

## Modes
- **Single-shot verdict** — score the current pool, print the JSON verdict.
- **`--loop`** — generate → refold (ESMFold2) → decide, until complete / budget / max-rounds.
  Local closed loop today; the **distributed** mode runs autosize on returned tarballs and, on
  `continue`, writes "tool X needs ~M more" into PROGRESS.md for the worker (same core, swap the
  `generate` hook).

## From the target-analyst dossier → autosize
The dossier's JSON sidecar maps straight onto per-tool autosize invocations:

| Dossier field | → autosize |
|---|---|
| `n_target` (from difficulty band) | `--n-target` (same value for every tool — equal-N) |
| `gate_tier` | `--tier` |
| `tools` | which tools the orchestrator runs the loop for |
| `hotspots`, `binder_length` | each tool's design config (not autosize itself) |

Harder target → smaller `n_target`, more permissive `tier`, more diverse `tools` (see
`comparison/target_analysis.suggest_campaign`).

## Calibrate the gate on batch 1
The tier defaults are conventional, but the `chain_iptm_interface` distribution shifts per target.
On the first batch, run the **full** cross-engine refold alongside ESMFold2 and pick the threshold
that hits your precision target (benchmark top-20% ≈ 0.88 precision); thereafter the loop gates on
ESMFold2 alone. `TODO:` wire a one-shot calibration helper.

**Position in the loop:** target-analyst → orchestrator + autosize → worker → evaluator.
