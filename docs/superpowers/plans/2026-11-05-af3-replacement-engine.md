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

## Part 2: the switch (owner approved 2026-11-07; registers Protenix only)

Owner decisions that bind this part: success = similar `consensus_iptm_mean` AUC; **no increase in GPU demand** (ceiling = a 24 GB card, as AF3 and ESMFold2 already need), so RF3 (33.5-36.8 GiB without proprietary ops) is out and Chai-1 failed target PD-L1; **Protenix v1.x is the only engine registered** (measured 21.3 GiB peak on a 779-token complex on a 24 GB card). The registry is still engine-agnostic: adding another engine later is one registry row plus an adapter, no edits to scoring.

Part 2 rulings (the owner may overturn any):
- R1. One registry, `Evaluator/binder_comparison/core/engines.py`. Three slots: `boltz` (primary anchor), `second` (`af3` default, or `protenix`), `esmfold2`. A panel is exactly these three; a four-engine panel cannot be expressed.
- R2. Column prefix = the real engine name (`protenix_pae_iptm`, `protenix_ipsae_min`, `protenix_pdb`...). AF3 names are untouched.
- R3. Slot selection: explicit `--second-engine {af3,protenix}` wins. With no flag, `evaluate.sh` uses AF3 if its env and weights are present; otherwise, if exactly one other registered engine is installed, it uses that one and prints a notice naming the panel. Columns of the engine NOT in the slot are ignored with a notice, never averaged.
- R4. The panel is recorded: `metrics.csv` gets constant columns `panel` (e.g. `boltz+protenix+esmfold2`) and `second_engine`; the HTML report prints "Boltz-2 + Protenix + ESMFold2; AF3 not used" and that scores from different panels are not on one scale.
- R5. Protenix always runs with the torch kernels and torch layernorm (no proprietary NVIDIA ops at runtime); the installer still pulls the cuEquivariance wheels as a hard dependency of `protenix`, and says so in the licence text it prints.
- R6. Installer: `--second-engine protenix` (both installers). Opt-in, NOT in `--tool all`, off by default. Prints the licence text and its source before any download, asks y/N unless `--yes`, records text + date in `.install_state/`, downloads the weights only after acceptance, needs no AF3 weights. Declining downloads nothing, writes no marker, exits non-zero.

### Task 13: Engine registry

**Files:** Create `Evaluator/binder_comparison/core/engines.py`; Test `tests/binder_comparison/test_engine_registry.py`.

**Interfaces:**
- Produces: frozen dataclass `Engine(name, display, prefix, refold_dir, results_csv, iptm_col, ipsae_col, pdb_cols, binder_chain, default_threshold)` and `Panel(boltz, second, esmfold2)` with `.engines`, `.iptm_cols`, `.ipsae_cols`, `.label` (`"Boltz-2 + Protenix + ESMFold2"`), `.slug` (`"boltz+protenix+esmfold2"`). `SECOND_ENGINES = ("af3", "protenix")`. `resolve_panel(second: str = "af3") -> Panel` raises `ValueError` naming the valid values for anything else (including `"boltz"`, `"esmfold2"`, `""`). `engine(name) -> Engine`.
- The `af3` row reproduces today's literals exactly: iptm `af3_pae_iptm`, ipsae `af3_ipsae_min`, pdb cols `("af3_pdb","af3_cif")`, dir `refold_af3`, csv `af3_results.csv`, chain B, threshold 0.61. `boltz` ipsae col is `boltz_pae_ipsae_min` (not the af3-style name).
- [ ] Tests: `resolve_panel()` default equals the current `_ENGINE_IPTM_COLS` list order; `resolve_panel("protenix").iptm_cols == ["boltz_pae_iptm","protenix_pae_iptm","esmfold2_pae_iptm"]`; unknown name error text; no panel has 4 engines or a duplicate prefix.
- [ ] Commit: `Part 2: engine registry`.

### Task 14: Scoring reads the panel

**Files:** Modify `Evaluator/binder_comparison/comparison/scoring.py` (sites: `_ENGINE_OUTPUT_DIRS` ~204, path remap ~351, `DEFAULT_ENGINE_THRESHOLDS`/`_ENGINE_IPSAE_COLS` ~657-671, `apply_screening_thresholds` ~676, agreement_count ~959, `_ENGINE_IPTM_COLS` ~1006, `compute_consensus_iptm` ~1039, `compute_consensus_ipsae` ~1093, `rank_designs` ~1124), `comparison/confidence_gate.py:60`, `comparison/self_consistency.py:152`, `comparison/foldseek.py:91`; Test `tests/binder_comparison/test_scoring_panel.py`.

**Interfaces:** Consumes Task 13. Produces: `compute_consensus_iptm(df, panel=None)`, `rank_designs(df, min_engines=MIN_ENGINES_DEFAULT, panel=None)`, `apply_screening_thresholds(..., panel=None)`; `panel=None` means `resolve_panel("af3")` and MUST reproduce today's behaviour byte for byte. The module-level `_ENGINE_IPTM_COLS` name stays (tests monkeypatch it) and is derived from the default panel.
- [ ] Tests: (1) the same synthetic pool with its `af3_*` columns renamed `protenix_*` and `panel=resolve_panel("protenix")` gives identical `rank`, `consensus_iptm_mean`, `consensus_iptm_n`, `passes_engine_gate`; (2) a frame holding BOTH `af3_pae_iptm` and `protenix_pae_iptm` with the protenix panel averages only boltz/protenix/esmfold2 (`consensus_iptm_n` never exceeds 3); (3) default-panel call unchanged; (4) `agreement_count` and the ipsae thresholds follow the panel.
- [ ] `tests/integration/test_ranking_is_pinned.py` passes UNMODIFIED. Commit: `Part 2: scoring reads the engine panel`.

### Task 15: Merger and schema

**Files:** Modify `Evaluator/binder_comparison/comparison/merger.py` (`merge_refold_results`, `_load_engine`), `core/schema.py` (af3 field block ~194-205, ~307-309, ~359-367); Test `tests/binder_comparison/test_merger_second_engine.py`.

**Interfaces:** `merge_refold_results(boltz2_csv, sequences_fasta=None, *, af3_csv=None, esmfold2_csv=None, second_csv=None, second_engine="af3")`. `second_csv` with `second_engine="protenix"` prefixes columns `protenix_`; `af3_csv` keeps working and is the same slot as `second_csv` when `second_engine="af3"`. Passing BOTH `af3_csv` and `second_csv` with different engines refuses (one slot). Schema: engine-prefixed columns for registered second engines are generated from the registry, AF3's remain exactly as they are.
- [ ] Tests: protenix merge yields `protenix_iptm` etc. and no `af3_*`; the target-mismatch guard and the one-row-per-design guarantee still hold for the protenix slot; `af3_csv`-only call unchanged; both slots filled refuses naming both.
- [ ] Commit: `Part 2: merger and schema take the second-engine slot`.

### Task 16: `binder-compare report` and the record of the panel

**Files:** Modify `Evaluator/binder_comparison/cli/report.py` (sites ~243-306, 477-489, 514, 529-601, 703-722, 1177-1191, 1430-1432, 1545-1592), `visualization/report.py` (~55-61, 209, 288), `visualization/plots.py` (~106-108, 294-319, 427, 618, 1025), `cli/hits.py:38`; Test `tests/binder_comparison/test_report_second_engine.py`.

**Interfaces:** new `--second-engine {af3,protenix}` (default `af3`) and `--second-results CSV`; `--af3-results`, `--threshold-af3` keep working and apply to the AF3 slot; `--primary-engine` choices come from the registry (`boltz`, the second engine's name, `esmfold2`; the literal `af3` stays valid while AF3 is the slot). If `--af3-results` is given while `--second-engine protenix` (or the reverse) the report prints a notice and ignores the other-slot CSV (R3). `metrics.csv` gains constant `panel` and `second_engine` columns; the HTML shows the panel line and the not-on-one-scale sentence (R4); plot labels and legends use `Panel.label`/display names. AF3 reports must differ from today's only by the two new columns and the panel line.
- [ ] Tests: end-to-end on the synthetic pool with protenix results: `metrics.csv` carries `protenix_pae_iptm`, `panel == "boltz+protenix+esmfold2"`, no `af3_*` ranking input, HTML contains "AF3 not used"; the AF3 path's `rank` order equals the pre-change order; wrong-slot CSV notice.
- [ ] Commit: `Part 2: report records the panel and the second engine`.

### Task 17: Protenix refold wired into `binder-compare`

**Files:** Create `Evaluator/binder_comparison/cli/refold_protenix.py` (thin: runs `Evaluator/scripts/refold_protenix_v1.py` in the Protenix env with `--trimul-kernel torch --triatt-kernel torch --layernorm-type torch`, `--output-dir refold_protenix`, writes `protenix_results.csv`, same exit codes as `refold-af3`: 3 on partial failure), register in `main.py`/`cli/__init__.py`; Test `tests/binder_comparison/test_refold_protenix_cli.py`.

**Interfaces:** `binder-compare refold-protenix --sequences F --target-seq S -o CSV --output-dir D [--model-dir D] [--env NAME] [--resume]`; default env `binder-eval-protenix`; `$PROTENIX_MODEL_DIR` default for `--model-dir`. The CSV header equals the shared refold header; structure stems are `<binder_id>_protenix`.
- [ ] Tests: argument forwarding (kernel flags always present), exit 3 on partial failure, refuses an unlicensed model name, `--resume` passthrough (mock the subprocess).
- [ ] Commit: `Part 2: refold-protenix subcommand`.

### Task 18: `evaluate.sh`

**Files:** Modify `Evaluator/evaluate.sh` (sites listed by `git grep -n -i af3 Evaluator/evaluate.sh`: flags ~20-54, defaults ~246-268, arg parsing ~287-329, env/weights detection ~398-447, CSV/engine count ~566-588, `engine_af3` ~795, engine lookup ~875, launch ~943-990, report call ~1015-1072, binder chain ~1085); Test `tests/evaluator/test_evaluate_sh_second_engine.py` (dry-run style like `tests/evaluator/test_evaluate_sh_flags.py`).

**Interfaces:** `--second-engine {af3,protenix}`, `--protenix-env NAME`, `--gpu-cap-protenix GiB`, `--skip-second` (and `--skip-af3` keeps meaning "skip the AF3 slot"). Selection per R3. A generic `engine_second()` dispatches to `refold-af3` or `refold-protenix`; the report gets `--second-engine` and `--second-results`. Skipped/absent second engine keeps today's wording (gate unmet, `--min-engines 2` hint) and names the engine.
- [ ] Tests: slot selection matrix (flag wins; no flag + AF3 ready -> AF3; no flag + only Protenix ready -> Protenix with notice; neither -> skipped by name), `--skip-af3` unchanged, existing `tests/test_shell_evaluate_*` stay green, shellcheck clean.
- [ ] Commit: `Part 2: evaluate.sh drives the chosen second engine`.

### Task 19: Installers

**Files:** Modify `install/install.sh` and `install/install_aarch.sh` identically in shape (registry row `DO_PROTENIX|Protenix|install_protenix|false` so it is not in `all`; `--second-engine NAME` maps `protenix` to that row and rejects `af3` with "use --tool af3"); new function `install_protenix()` in each; Test `tests/test_installer_protenix.py` (plus keep `tests/test_installers_do_not_drift.py`, `tests/test_installer_tool_registry.py`, `tests/test_referenced_conda_envs_exist.py` green; add `binder-eval-protenix` wherever the last one needs).

**Interfaces:** `install_protenix` creates env `binder-eval-protenix` (Python 3.12; torch 2.7.1 from the `cu128` index; `protenix==1.1.0`; `pip install -e 'Evaluator[report]'`); refuses up front, naming the fix, when no C compiler is found (a dependency, `scikit-learn-extra`, builds from source); prints the licence text and its source from `Evaluator/docs/second_engine_licences.md` (Apache-2.0 code and v1.x parameters, v2 weights proprietary and never used, the weight host, the cuEquivariance wheels installed but unused), prompts y/N unless `--yes`, writes `.install_state/protenix` with the text and the date only after the weights (checkpoint 1,475,950,125 bytes) are on disk, and does not need AF3 weights. Smoke: import `protenix`, `torch.cuda.is_available()` NOT asserted (login nodes), `binder-compare refold-protenix --help` works in the env.
- [ ] Tests: declining downloads nothing and writes no marker (mock the prompt); `--yes` prints the licence block before the first download line; registry row not in `--tool all`; the licence text printed equals the record's text (read from the doc, not retyped); `--tool all` output unchanged.
- [ ] Commit: `Part 2: opt-in Protenix installer option`.

### Task 20: Configurator, headless replay, skills

**Files:** Modify `configurator/configurator.py` (~373, 5295-5335, 6405-6480, 6529-6580, 7059), `tools/make_config_builder.py`/`docs/config-builder.html` if the config builder lists engines, `.claude/skills/binderscout-*` and `.claude/agents/invariant-auditor.md` (I5 -> "Exactly three refold engines: Boltz-2, ESMFold2 and one second engine, AF3 by default"); Test `tests/configurator/test_configurator_second_engine.py`.

**Interfaces:** config key `second_engine` (default `"af3"`); the wizard offers Protenix only when `binder-eval-protenix` exists; `run_evaluate.sh` carries `--second-engine`; headless replay of an old config without the key behaves as before.
- [ ] Tests: generated `run_evaluate.sh` for `second_engine: protenix` has `--second-engine protenix` and no `--skip-af3`-driven surprise; old configs unchanged; `tests/configurator/test_headless_configs_are_reconciled.py` green.
- [ ] Commit: `Part 2: configurator chooses the second engine`.

### Task 21: End to end, pins and docs

**Files:** Test `tests/integration/test_second_engine_panel_pinned.py` (golden synthetic pool re-slotted to protenix gives the same `rank` order and the right `panel`); modify `CHANGELOG.md` (Unreleased: the option, the registry, the benchmark result with its caveats), `CLAUDE.md` (engine line-up, "exactly three engines" statements, the Protenix env row, the 24 GB measurement), `Evaluator/docs/pipeline_reference.md`, `Evaluator/docs/evaluation/ranking.md` (panels are not on one scale). Run one live check on a 24 GB card: `evaluate.sh --second-engine protenix` on a 2-design pool, `metrics.csv` has `protenix_pae_iptm` for both designs and `panel`.
- [ ] Gate: the full suite incl. `tests/integration`, ruff, shellcheck, anonymity tests.
- [ ] Commit: `Part 2: docs, pins and live check`.
