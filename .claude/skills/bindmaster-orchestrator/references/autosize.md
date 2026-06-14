# Autosize — the adaptive sampling loop

> **Scaffold (extension to the orchestrator skill).** `TODO:` flesh out + cross-link from SKILL.md §6.

The `binder-compare autosize` controller decides "do we have N *independent* good designs yet?"
and sizes the next batch — so the orchestrator no longer guesses per-tool counts.

- **Equal-N across tools** — every tool driven to the same `--n-target`; per-tool `--budget-cap`
  lets hard tools settle for fewer. Harder targets → smaller N (from the dossier difficulty band).
- **Gate** — ESMFold2 `chain_iptm_interface`, tier-aware (`--tier permissive|default|strict`).
- **Independence** — counts backbones (design groups), not sequences.
- **Modes** — single-shot verdict, or `--loop` (generate → refold → decide); local closed loop
  now, distributed PROGRESS.md signal later.
- `TODO:` how the target-analyst dossier sets `n_target`/`tier`/`tools`; calibration of the gate
  threshold on batch 1; how this replaces the old manual "BindCraft 50 / BoltzGen 10k" math.

**Position in the loop:** target-analyst (upstream) → orchestrator + autosize → worker → evaluator.
