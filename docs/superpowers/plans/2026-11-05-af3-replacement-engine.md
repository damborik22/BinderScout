# AF3 Replacement Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find out which commercially usable structure predictors can fill the AF3 slot without losing ROC AUC on the Adaptyv benchmark, then (gated) make the slot switchable.

**Architecture:** Part 1 is a benchmark that changes no pipeline code: one refold script per candidate writes a CSV in the AF3 refold format with its own column prefix, and a new analysis module compares panels on the 563 labelled designs. Part 2 (engine registry, `--second-engine`, installer option) is specified in the spec and tasked only after Part 1 reports.

**Tech Stack:** Python 3.10+ (pandas, numpy), pytest, ruff 0.17.0, existing `scoring.compute_iptm_from_pae`, `benchmarks.load_labels("adaptyv")`, per-candidate conda/uv envs outside the repo.

**Spec:** `docs/superpowers/specs/2026-11-04-af3-replacement-engine-design.md`

## Global Constraints

- Public repo: no machine names, accounts or paths of ours in tracked files (`tests/test_public_docs_are_anonymous.py`, `tests/test_no_infrastructure_identifiers_in_tree.py` must stay green). Label rows never enter the repo; they are read through `$BINDERSCOUT_BENCHMARK_STORE`.
- PAE is stored `[binder|target]`; `<engine>_pae_iptm` is derived by the shared kernel `scoring.compute_iptm_from_pae`, never taken from an engine's own ipTM.
- Column names carry the real engine name (`openfold3_pae_iptm`, never `af3_*`).
- `rank` / the 3-engine gate / `consensus_iptm_mean` semantics are unchanged; AF3 stays the default.
- Pass rule (spec): macro AUC primary; bootstrap resamples designs WITHIN each target; pass iff (a) paired 95% interval of (macro AUC_k − macro AUC_P0) not wholly below 0, (b) point estimate ≥ −0.02, (c) no target worse than P0 by more than 0.05. Floor panel {Boltz-2, ESMFold2} is reported beside every candidate.
- Candidates, in order: OpenFold3, Protenix v1.x (pin v1; never v2), Chai-1, RF3, IntelliFold-2 (only after its licence line is cleared).
- aarch64 unified-memory host: run only under `tools/gpurun --cap N`, never uncapped.
- Gate for every task: `./conda/envs/binder-eval/bin/python -m pytest -q --ignore=tests/integration`, `uvx ruff@0.17.0 check .` and `format --check .`; env `PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES= JAX_PLATFORMS=cpu`.

## Review Focus

- A design the candidate failed on (OOM, crash) must leave a BLANK row, never 0.0, and must not enter a panel as a score. Test: blank row stays NaN through `panel_consensus`.
- `not_tested` / `excluded:` outcome rows must never become negatives (the 2026-10-03 incident). Test: `load_labels` rows with those outcomes are dropped before AUC.
- A target with one class only has no AUC. Test: `per_target_auc` returns NaN and the report names the target; it is not silently averaged as 0.5.
- A candidate whose PAE is atom-level or the wrong size must be refused, not scored. Test: wrong-sized matrix raises (same guard as `_load_checked_pae`).
- A candidate run with a different target MSA than the baseline is not a like-for-like panel. Test: the refold scripts take the target MSA from `get_target_msa`, and the CSV records `target_msa_mode`.

---

## Part 1: Benchmark

### Task 1: Panel-comparison module

**Files:**
- Create: `Evaluator/binder_comparison/comparison/panel_benchmark.py`
- Test: `tests/binder_comparison/test_panel_benchmark.py`

**Interfaces:**
- Produces:
  - `panel_consensus(df: pd.DataFrame, cols: list[str]) -> pd.Series` (row mean over `cols`, skipna=False so a blank engine blanks the design)
  - `per_target_auc(df: pd.DataFrame, score: pd.Series, *, target_col: str = "target", label_col: str = "binds") -> dict[str, float]` (NaN for a one-class target)
  - `paired_bootstrap_diff(df, score_a, score_b, *, n_boot: int = 2000, seed: int = 0, target_col: str = "target", label_col: str = "binds") -> dict` with keys `macro_diff`, `ci_low`, `ci_high`, `per_target_diff: dict[str, float]` (resamples within each target, same resample for both scores)
  - `passes(result: dict) -> tuple[bool, list[str]]` applying the three-part rule; the list names each failed clause.

- [ ] **Step 1: Write failing tests** in the test file: `test_blank_engine_blanks_the_design`; `test_one_class_target_has_nan_auc_and_is_not_averaged_as_half`; `test_bootstrap_resamples_within_target` (two targets with different sizes; every resample keeps each target's n); `test_passes_requires_all_three_clauses` with three constructed results (interval wholly below 0 → fails clause a; point −0.03 → fails b; one target −0.06 → fails c; each asserts the clause name appears).
- [ ] **Step 2: Run** `pytest tests/binder_comparison/test_panel_benchmark.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the four functions above; AUC via rank statistic (no new dependency).
- [ ] **Step 4: Run** the same command. Expected: PASS. Mutate `passes` (drop clause c) and confirm `test_passes_requires_all_three_clauses` fails; restore from a backup copy, not `git checkout`.
- [ ] **Step 5: Commit** `Part: panel-comparison module for the AF3-replacement benchmark`.

### Task 2: Step 0 — reproduce the current panel's AUC

**Files:**
- Create: `Evaluator/scripts/panel_benchmark.py` (CLI: `--merged CSV --pool adaptyv --panel boltz_pae_iptm,af3_pae_iptm,esmfold2_pae_iptm [--panel ...] --out JSON`)
- Test: `tests/binder_comparison/test_panel_benchmark_cli.py` (synthetic merged CSV plus a fake `$BINDERSCOUT_BENCHMARK_STORE`)

**Interfaces:**
- Consumes: Task 1 functions; `binder_comparison.benchmarks.load_labels("adaptyv")` (the registered pool has 2018 rows, label column `binds`, outcome column `outcome`; the merged CSV is the 563-design curated subset, so the join is on `id` and must find all 563).
- Produces: JSON with `panels: {name: {per_target_auc, macro_auc, median_auc}}` and, per non-baseline panel, the `paired_bootstrap_diff` dict and `passes` verdict against the first `--panel`.

- [ ] **Step 1: Write failing CLI test** on a 2-target synthetic set: expected macro AUC and that a `not_tested` row is absent from the result.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement** the CLI by calling Task 1; keep only `outcome` in (`bound`, `not_bound`) and join the merged CSV to the labels on `id`; refuse (exit 2, name the counts) if any merged id has no label row, or if any design has a blank column in a requested panel; print the joined n per target.
- [ ] **Step 4: Run it.** Expected: PASS.
- [ ] **Step 5: Reproduce on real data** (private store set; merged CSV from the lab share): run the CLI for panels `boltz+af3+esmfold2` and `boltz+esmfold2`. Expected: macro AUCs match the recorded 0.7231 and 0.7279 to within 0.001. If not, STOP and find out why before Task 4. Save the JSON next to the benchmark report.
- [ ] **Step 6: Commit** `Part: panel_benchmark CLI and step-0 reproduction of the AF3 panel`.

### Task 3: Licence record for all candidates, IntelliFold-2 first

**Files:**
- Create: `Evaluator/docs/second_engine_licences.md`

**Interfaces:** Produces a table consumed by Task 9 and by Part 2's installer text: engine, code licence, weights licence, source URL, verbatim quote, date read.

- [ ] **Step 1:** Re-read primary sources (LICENSE files, model cards, announcement pages) for OpenFold3, Protenix v1.x, Chai-1, RF3; fill the table with dated quotes, copying from the spec's candidate table only what was verified.
- [ ] **Step 2:** Resolve IntelliFold-2: read its NOTICE and LICENSE and state whether the "vendors an Apache-2.0 release of AlphaFold 3" line means AF3 code (non-commercial) is inside. Record "cleared", "not cleared" or "unclear". Only "cleared" proceeds to Task 9.
- [ ] **Step 3:** Run the anonymity tests; expected PASS. **Step 4: Commit** `Docs: dated licence record for the AF3-replacement candidates`.

### Task 4: Shared second-engine refold helpers

**Files:**
- Create: `Evaluator/binder_comparison/refolding/second_engine.py`
- Test: `tests/binder_comparison/test_second_engine_helpers.py`

**Interfaces:**
- Produces:
  - `to_binder_target_pae(pae: np.ndarray, n_binder: int, n_target: int, *, order: str) -> np.ndarray` (`order` in `"binder_target"`, `"target_binder"`; swaps blocks, never transposes; raises `ValueError` naming both sizes if `pae.shape != (n_binder+n_target,)*2`)
  - `write_refold_row(csv_path, row: dict, *, prefix: str) -> None` (appends; header identical to `refold_af3.py`'s with `<prefix>_` on engine-specific columns; a failed design is written with blank metric cells and `error` set)
- Consumes: `scoring.compute_iptm_from_pae` for the pinned-ordering test.

- [ ] **Step 1: Write failing tests:** `test_target_first_matrix_is_reblocked_not_transposed` (asymmetric 5x5 fixture, exact block positions asserted); `test_wrong_sized_matrix_is_refused`; `test_failed_design_row_is_blank_not_zero`.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement** both functions. **Step 4: Run.** Expected: PASS, then mutate the block swap into a transpose and confirm the first test fails; restore from backup.
- [ ] **Step 5: Commit** `Part: shared helpers for second-engine refold scripts`.

### Tasks 5–9: One refold script per candidate

Tasks 5 (OpenFold3, `Evaluator/scripts/refold_openfold3.py`), 6 (Protenix v1.x, `refold_protenix_v1.py`), 7 (Chai-1, `refold_chai1.py`), 8 (RF3, `refold_rf3.py`), 9 (IntelliFold-2, `refold_intellifold2.py`, only if Task 3 cleared it) each have the same shape. Per task:

**Files:** Create the script above; Test: `tests/binder_comparison/test_refold_<engine>_script.py`.

**Interfaces:**
- Consumes: Task 4 helpers; `target_msa.get_target_msa(seq)` for the shared target MSA (binder uses no MSA).
- Produces: CLI identical to `refold_af3.py` (`--sequences --target-seq --output --output-dir --resume --no-msa --msa-cache-dir`) plus `--model-dir`; CSV columns per Task 4 with prefix `<engine>`; one PAE `.npy` per design in `[binder|target]` order named `<binder_id>_<engine>_pae.npy`; `target_msa_mode` recorded.

- [ ] **Step 1: Write failing tests** with the model call stubbed: ordering (the engine's native order from its docs is passed to `to_binder_target_pae`, asserted with an asymmetric fixture), `--resume` skips a scored row but re-runs a blank one, a failing design yields a blank row and a non-zero exit with the count, atom-level PAE is refused.
- [ ] **Step 2: Run.** Expected: FAIL. **Step 3: Implement** the script; how the model is invoked (CLI versus Python) and how token-level PAE is obtained are the implementer's call, recorded in the script header with the doc URL. Chai-1: call the model from Python because the CLI does not write PAE. Protenix: pin the v1.x checkpoint by name and refuse `protenix-v2`.
- [ ] **Step 4: Run tests.** Expected: PASS. **Step 5: Live smoke** in the engine's own env on one design (any host that fits it; under `gpurun --cap` on the unified-memory host): the CSV has a non-blank `<engine>_pae_iptm` derived by the kernel, and the PAE shape equals binder+target length. **Step 6: Commit** `Part: <engine> refold script for the AF3-replacement benchmark`.

### Task 10: Run the benchmark and write the report

**Files:**
- Create: `Evaluator/docs/second_engine_benchmark.md` (aggregate numbers only, no label rows)

**Interfaces:** Consumes Tasks 2, 5–9; produces the verdict table Part 2 depends on.

- [ ] **Step 1:** For each candidate, refold the 563 Adaptyv designs per target (sequences from the share's per-engine refold CSVs, same cached target MSA as the baseline) on a host that fits it; each run is resumable; check the row count and the blank-row count after each target.
- [ ] **Step 2:** Merge each candidate's `<engine>_pae_iptm` into the merged CSV by `id`; run `panel_benchmark.py` with panels P0, floor and one per candidate.
- [ ] **Step 3:** Write the report: per-target and macro/median AUC, paired intervals, pass verdicts with failed clauses named, the floor beside each, each candidate's training cutoff, and the sentence the spec requires when a candidate ties the floor. State plainly that four targets make this a hypothesis.
- [ ] **Step 4:** Run the anonymity tests. **Step 5: Commit** `Docs: AF3-replacement benchmark report`.

### Gate: decision on Part 2

Stop and show the owner the Task 10 table. Part 2 starts only for engines that passed, on the owner's word.

---

## Part 2 (gated; broken into tasks after the gate)

Specified in the spec's "Part 2: the switch". Outline only: engine registry replacing `_ENGINE_IPTM_COLS` and the hard-coded engine handling in `schema.py`, `merger.py`, `report.py`, `evaluate.sh` (`--second-engine`, default `af3`, exclusive); panel recorded in `metrics.csv` and the report; installer option that prints the licence text and source before download, records it in the install state, and needs no AF3 weights; tests pinning each engine's ordering and the AF3-unchanged path (`tests/integration/test_ranking_is_pinned.py` must still pass); CHANGELOG and CLAUDE.md updates.
