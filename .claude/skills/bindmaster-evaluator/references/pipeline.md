# Evaluation pipeline — canonical recipe

The cross-engine refold + ranking, run **locally on the eval host** (Spark / any >100 GB-memory
box) as library code, not cluster jobs. Promotes + updates the orchestrator's `evaluation.md` to
the current engine set (ESMFold2 default, two-stage ranking, + affinity/monomer).

## Engines (per step → conda env)

| Step | Command | Env | Notes |
|---|---|---|---|
| extract | `binder-compare extract --<tool> DIR … -o seqs.fasta` | `binder-eval` | one extractor per tool; writes a native-metrics sidecar |
| refold Boltz-2 | `binder-compare refold-boltz2 --sequences … --target-seq SEQ -o boltz2.csv` | **Mosaic venv** (`Mosaic/.venv`) | default; native `[binder\|target]` PAE, pLDDT [0,1] |
| refold AF3 | `binder-compare refold-af3 …` | `binder-eval-af3` | canonical 2nd engine; >100 GB memory; pLDDT 0–100 → rescaled; PAE transposed |
| refold ESMFold2 | `binder-compare refold-esmfold2 … --model full` | `binder-eval-esmfold2` | **default**, lightweight; the `chain_iptm_interface` gate |
| refold Protenix | `binder-compare refold-protenix …` | `bindmaster_pxdesign` | **only optional** engine; 24 GB-friendly |
| report | `binder-compare report --boltz2-results … --af3-results … --esmfold2-results … --rank-by two_stage -o report/` | `binder-eval` | two-stage ranking; HTML + `metrics.csv` |
| affinity | `binder-compare affinity --metrics report/metrics.csv --structures-dir … --run-rosetta -o affinity.csv` | `BindCraft` (PyRosetta) | Part N — see `affinity.md` |
| monomer | `binder-compare monomer --complex-dir … --monomer-dir … -o monomer.csv` | refold env | fold-robustness QC — see `qc.md` |

**One-shot:** `bindmaster evaluate run …` / `Evaluator/evaluate.sh` auto-detects installed engines
(`--skip-<engine>`) and drives extract → refold → two-stage report. Drop to individual subcommands
for partial re-runs.

## Pre-flight

1. All tool tarballs staged + untarred under `~/eval_workdir/<TARGET>/` (per-tool subdirs).
2. Each tool's **source-of-truth CSV** is parseable (BindCraft `final_design_stats.csv`, Mosaic
   `designs.csv` `is_top=1`, PH `summary_high_iptm.csv`, PXDesign `summary.csv`, BoltzGen
   `final_designs_metrics_*.csv`, PC analysis CSV, RFD3 `.cif.gz` + MPNN `.fa`). See the worker
   tool playbooks.
3. Boltz-2 cache at `~/.boltz/` populated (incl. `mols/` ~45k `.pkl`).
4. `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` on Ampere with mixed batch sizes.
5. Target MSA reused from the `get_target_msa` cache (AF3/ESMFold2 read it).

## Resume / partial reruns
`refold-*` append to their CSV and support `--resume` (skip already-folded binders) — safe after a
crash; check for duplicate `run_id`s. Re-run `report` any time from the existing per-engine CSVs.

## If an engine is missing
2-engine evaluation is fine, but **`agreement_count` denominator shrinks** — a `2/2` is not a
`2/3`. Note it in the ranking. ESMFold2 is default and cheap, so prefer keeping it in.

`TODO:` env var details (PROTENIX_DATA_ROOT_DIR, AF3 db/model paths) — see `Evaluator/docs/pipeline_reference.md`.
