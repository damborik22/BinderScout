# Evaluation pipeline — canonical recipe

> **Scaffold.** `TODO:` consolidate the working recipe from
> `bindmaster-orchestrator/references/evaluation.md` and extend with affinity + monomer.

- Step order, the conda env per step (binder-eval / Mosaic venv / binder-eval-af3 /
  binder-eval-esmfold2 / BindCraft for Rosetta), `--resume` semantics, ESMFold2 fast-vs-full.
- The one-shot path: `bindmaster evaluate run …` / `Evaluator/evaluate.sh`.
- `TODO:` partial-rerun recipes after a refold crash.
