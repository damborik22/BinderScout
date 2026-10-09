# BinderScout 2.0 — state of the plan

A self-contained handoff. Everything needed to pick 2.0 up without reading the
diary first; pointers are given where the detail lives.

| | |
|---|---|
| **Branch** | `v2.0.x` (all 2.0 work; `master` is frozen at 1.0.3, `v1.1.x` is the BindCraft 2 line) |
| **HEAD** | The `v2.0.0` tag was **re-cut six times after release** (2026-10-04 to 10-09, with the owner's say-so) to carry the audit fixes, the Boltz-2 output-dir fix, the ESMFold2 loader fix, the AF3 full-precision installer patch and this session's records. It sits at the tip of `v2.0.x`; further fixes go into `v2.0.1`. Anything that recorded the original `d6ed96b` is stale. Clean, pushed |
| **Tests** | **1109 passing**, 7 skipped; ruff + shellcheck clean |
| **Version** | **`v2.0.0`, TAGGED 2026-10-04** on `v2.0.x` — 158 commits past `v1.1.1`. Fleet only: not published, and **not merged to `master`** by decision. **This row previously read "the tag waits on §3's GPU-memory pass" — the operator overrode that on 2026-10-04**, and the reasoning inverts cleanly: the memory pass goes last *because a reading taken against an unfinished pipeline is stale*, which means the pipeline must ship first for the reading to be worth taking. Stage 6 is now post-2.0.0 work, not a tag blocker |
| **Fleet** | All five sites (BM1, BM2, BM4, BM5, Clara) were pinned to the tag on 2026-10-09 after the last re-cut. A moved tag is **not** updated by a plain `git fetch`: use `git fetch --tags --force`, and measure `behind` only after a forced fetch. Checkout path is `~/dev/BindMaster` on the BM boxes and `~/BindMaster` on Clara; `tools/fleet.sh` resolves either. **Do not switch a checkout under a running job**: the eval envs are editable installs of it |
| **As of** | 2026-10-09 (about 10:00 UTC). In flight at that moment, and recorded as such below: the Clara rerun of 85 nipah designs, the GuideFlip refolds, and the muni-disk archive |
| **Changelog** | released as `## [2.0.0] — 2026-10-04`; `[Unreleased]` is now empty |

Companions: [NEXT_STAGES.md](NEXT_STAGES.md) (stage detail),
[MORNING_DECISIONS.md](MORNING_DECISIONS.md) (the open decisions in full),
[../2.0/DIARY_2.0.md](../2.0/DIARY_2.0.md) (**how each finding was reached, wrong turns
included — the 2.0 diary**; `REPO_DIARY.md` is the *historical* diary and is not where 2.0 work
goes),
[PLAN_binderscout_v2.md](PLAN_binderscout_v2.md) (the original plan) and
[PLAN_binderscout_v2_corrections.md](PLAN_binderscout_v2_corrections.md) (where
its facts were wrong).

---

## 1. What 2.0 set out to do, and what it became

The plan was a set of lettered items (AD, Y, AA, Z, …) adding provenance,
cheap pre-GPU screens and a discovery metric to the Evaluator.

**What it actually became was a correctness pass.** Roughly two thirds of the
work turned out to be *connecting or verifying things that already existed*
rather than building new ones. That is the single most useful thing to carry
forward: this repo's characteristic defect is not missing code, it is code that
is present, looks complete, and is either unwired or unverified.

Two failure modes recurred, each many times:

1. **Built and never connected.** `--tool-csv`, `--collect-structures`,
   `tools/rfd3_gate.py`, `binder-compare prefilter` and the whole Rosetta
   interface panel each shipped doing nothing while looking finished.
2. **Checked by a proxy that cannot fail.** Five installer verifiers passed
   environments that could not run; five test guards passed mutations they were
   written to catch.

Both are now guarded by tests, and the guards are mutation-tested.

---

## 2. Done

| area | state |
|---|---|
| **Day 0** | `rank` corruption from four unguarded joins · benchmark-label leak guard · CI on release branches |
| **Fixtures** | Mutation-tested ranking suite (synthetic) **and** a golden fixture from a real CALCA campaign |
| **Stage 1 (AD), extraction half** | `generation_index` + `generation_index_source` across five tools; `unavailable` pinned as a first-class value for the three that cannot report. Per-tool verdicts: [INVESTIGATION_generation_index_2026-09-24.md](INVESTIGATION_generation_index_2026-09-24.md) |
| **Stage 2 (Y)** | Private label registry — public `MANIFEST.json`, private rows resolved by checksum. Library only, imported by nothing that ships |
| **Stage 3 (AA) core** | ProtParam panel (D7) · per-sequence composition gate (D8, shadow) · TmProt end to end (D1) |
| **Stage 5** | Static config-builder page, generated from `REQUIRED_CFG_KEYS` so it cannot drift |
| **Confidence gate** | BindCraft's no-Rosetta filters ported (i_pAE ≤ 10.85 Å, pLDDT ≥ 0.8, interface i_pTM ≥ 0.5), shadow mode |
| **Self-consistency** | Target-aligned design-vs-refold RMSD, shadow mode |
| **Rosetta panel** | Three stacked silent bugs fixed — it had never emitted a value |
| **RFD3 wiring** | Geometry gate before MPNN · fold-back ranking via `prefilter --only-tool` |
| **Provenance** | PXDesign collector reads the CSV that exists · every run keeps each tool's native CSV **and** the design structures |
| **Installer** | `--verify` / `--repair` / retries · one tool registry · 12-tool menu · aarch64 parity (TmProt, Proteina-Complexa) · drift guarded by test |
| **Hygiene** | Usernames scrubbed tree-wide and enforced · optional-import guard · several false CLAUDE.md claims corrected |

### Added 2026-10-03 / 10-04

| area | state |
|---|---|
| **Ranking is described correctly** | Four surfaces named the wrong metric as the rank — including a skill file that told an **agent** to sort on `agreement_count`, and `report.html`'s own glossary. `rank_designs()` was correct throughout; only the labels had drifted. Pinned by `tests/test_ranking_metric_is_not_misnamed.py`, mutation-tested against all four reversions **and** against the "delete every mention instead" escape |
| **`agreement_count` is a note, not a gate** | It was appending to the blocking `reasons` list. Now reported in `wetlab_reason` without withholding the recommendation, and it carries **`agreement_denom`** — `(vals > thr).fillna(False)` had made "engine never ran" indistinguishable from "engine said no", and 99 labelled benchmark designs are capped at 2 of 3 |
| **Label registry has its first pool (Y)** | `adaptyv`: 2,018 labelled designs, 4 targets. Manifest public, rows private and checksum-verified. Labels rebuilt from the exports' `evaluations` — **2,018/2,018 verified**, 2 corrected, expression corrected 1,795/223 → 1,810/208. `list_benchmarks()` no longer returns `[]` |
| **A reward that cannot be computed must not be 0.0** | `install/patches/` + both installers. PC caught every reward exception, reported it with `warnings.warn`, and its CLI runs python with `-W ignore` — so an unusable AF2 reward produced a completed search full of zeros that exited 0 |
| **1.1.x parity** | Two commits were missing, one a **rollout blocker**: `f596509` pins ESMFold2's nested ESMC-6B encoder, without which it loads random weights and still exits 0 (300/300 binders lost, four days to spot); `bd2d112` stops a skipped engine's existing CSV being dropped from the report |
| **Proteina-Complexa installs and runs on aarch64** | First time. Six defects fixed, five of them ours — `uv venv --clear`, the editable install's index strategy, the bf16 smoke test blaming XLA for an OOM kill, missing `openbabel`, and the installer shadowing PC's vendored ColabDesign fork |

### Added 2026-10-07 / 10-09

| area | state |
|---|---|
| **Post-release audit** | 27 bugs confirmed by two adversarial reviewers each, fixed; 24 issues then raised against the fixes (3 blockers, 21 items), all closed. The headline: `run_logged` backgrounds its command and `conda run` does not forward stdin, so every heredoc-fed PXDesign patch **executed nothing and printed a green check** (7 sites across both installers). Patch bodies are now files passed as an argument, with an assertion on the result. See §4.10 |
| **ESMFold2 was broken by the 2.0 pin** | The engine runs on the **biohub fork** of transformers, not PyPI. `transformers>=5.16` plus the default revision `69869f737bef` disabled the *default* refold engine while the env still verified clean. Reverted to `8fc3ff471022`; the loader now refuses a class without `load_esmc`; neither installer pins 5.x or installs over a present fork; the pin test was rewritten. See §4.9 |
| **Boltz-2 output directory leak** | `engine_boltz2` was the only engine without `--output-dir`, so `--resume` read another run's CSV: a fresh 20-design run published 260 foreign rows and the guard printed `ok -- 260 new row(s)`. Scoped to `$OUTPUT/refold_boltz2`. See §4.11 |
| **AF3 full precision** | Upstream rounds confidence scores to two decimals (81 distinct iPTM values over 563 designs, against 563 for each other engine). `install/patches/af3_full_precision.py`, run by both installers after the build; `--verify` re-checks it through `--check`. Mutation-tested. See §4.12 |
| **Part AK1 executed** | 2,033 designs x 3 engines on 4 targets = 6,099 folds, 50 chunks, 4 sites, **zero failures**. Result and its limits in §4.16 |
| **AK1 integrity audit** | Five independent read-only auditors (identity, labels, engine outputs, run provenance, statistics). No identity or output defect; one stale label; one cross-site software difference (BM5); and interpretation claims that did not survive. See §4.13, §4.16, §4.17 |
| **Part AF adjudicated** | Chai-1 on 563/563 designs, 0 errors. Partial Spearman **+0.116** (p = 0.006) against a pre-registered bar of 0.15: **not adopted**. Criterion 2 (sign stable across folds) passes |
| **GuideFlip external set** | Labelled data extracted from the preprint's supplementary tables (the repository holds code only): 88 designs, 71 measured, 30 binders. Alpha-synuclein and RBX1 arms folding; the nanobody arm is done and **set aside as BinderScout nano work** |
| **OpenBind assessed, dropped** | Wrong direction for this toolkit (fixed protein, varying ligand). Its affinity task reproduces the June numbers; AF3 accepts a SMILES ligand input (verified by hand, not yet in the refolder). See §5.5 |

### Verified end to end (2026-09-27)

The whole pipeline was run as an operator would — install → configure →
simulated 8-tool run → extract → refold → evaluate → report — and again on real
refold data. What is now demonstrated rather than assumed:

- **Extraction**: 8/8 tools, provenance correct on all five reporting routes.
- **Shared target MSA**: cold fetch → cache → hit; one file serves all three
  engines, no re-query.
- **Cross-engine gate**: a design with the pool's *best* `consensus_iptm_mean`
  but only 2 engines ranked **last and was not dropped**; `--min-engines 2`
  promoted it to first. Gate failures now also explain themselves in the
  operator-facing notes.
- **Self-consistency**: identical → 0.000; whole complex rotated and translated
  → **0.000** (proving the superposition is *target*-aligned); binder alone
  displaced 10 Å → **10.000**.
- **Orchestrator**: `evaluate.sh` end to end, exit 0, full report from real
  Boltz-2 output.
- **Failures are loud**: every engine that cannot run exits non-zero and writes
  no empty rows; `check_engine_rows` refuses to report a partial pool.

---

## 3. Remaining work

> **Per-part results — all twelve lettered parts — are in
> [PLAN_2.0_PART_RESULTS.md](PLAN_2.0_PART_RESULTS.md).** This section is
> organised by Stage 1–6, which covers only about half of them; AB, AC, AE, AF,
> AI and AJ appear only in that file.


### Stage 1 (AD) — the metric itself
`hits.py` holdout. §5.1 was **decided on 2026-10-04** (so the old "blocked on §5.1" is stale); what remains is, for its stated gate ("holdout passes a KS test vs the pool"), a real campaign with a genuine generation order.

### Stage 2 (Y) — one decision before anything consumes it
Y and AG both specify `binder_comparison/benchmarks.py`; AG additionally
specifies `comparison/benchmark.py`. **One module, decided before either
starts.** Unblocks AG and AH.

### Stage 3 (AA) — remaining items
| item | state |
|---|---|
| ~~**P5** ESM plausibility~~ | **CLOSED — not built.** SoluProt + TmProt suffice; four shadow columns already ship unvalidated, and Part U measured that extra metrics score *worse* than `consensus_iptm_mean` alone |
| **A1** BindPred | Needs the model. Build the runner **once** — AH consumes the same one |
| **D3** AggreProt | Reduction + decorrelation harness built and validated; needs the model or one real per-residue export |
| **promotion** out of shadow mode | Needs wet-lab outcome labels, not more refolds — **and see §4.1, which makes this stronger than "not yet"** |

### Stage 4 (Z) — staged cheap-filter mode
Can start whenever; AA's one load-bearing prerequisite is already closed in
code. Its real prerequisite was **two archived pools with all three engine
CSVs**, to measure recall at the keep-fraction. **That is now met (2026-10-09):** AK1 produced complete three-engine pools for egfr (826 designs, 128 binders) and nipah (1,045, 111), plus il7r and pd-l1, archived on muni-disk. What is not done is the recall measurement itself.

One correction to carry: Z's stated gate ("`rank` byte-identical with and
without `--stage1-results`") **tests the wrong thing.** That flag only attaches
advisory columns; the ranking change comes from the *missing refolds*. A staged
run and a full run cannot have identical `rank`. **Restate the gate as a recall
bound.**

### Stage 6 — the GPU-memory pass, and it goes LAST
By decision: a reading taken against an unfinished pipeline is stale by the time
it ships. Memory, not speed, decides whether a step runs at all.

**Inputs measured on 2026-10-07/09, so the pass starts from facts** (details in §4.14): the `--gpu-cap-*` flags set only the driver limit and never the JAX pool; `refold_boltz2.py` hardcodes 24 GiB; on GB10 the memory guard and `gpurun --max` disagree about what is safe; Boltz-2 on GB10 needs about 1.5x a discrete card, so designs of roughly 840+ tokens cannot be folded there at a safe size; and chunk wall time follows the number of **distinct lengths**, not the number of designs (§4.15).

### Opened 2026-10-09 (not yet staged)

| item | state |
|---|---|
| **`--gpu-cap-*` flags do nothing for JAX** | Either wire the cap into `<ENGINE>_XLA_MEM_FRACTION` or remove the flags. Decision in §5.6 |
| **Clara rerun of nipah c24-c26** | 85 designs (all non-binders, the shortest binders) were folded on BM5 with an older AF3 build and an ESMFold2 env that had xformers. Being refolded on Clara so every site matches. When it lands: replace them in the consolidated table and **measure the BM5-vs-Clara site effect directly** (the only clean measurement; the audit could only bound it) |
| **Archive read-back** | Everything is streamed to muni-disk as tarballs with a checksum taken in the same pass. **Nothing has been read back and compared yet**, and the rerun needs its own archive |
| **Ligand mode in the evaluator** | The three refolders take protein sequences only. AF3 accepts a ligand entry in the JSON it already builds; Boltz-2 (Mosaic JAX port) and ESMFold2 are unverified. Needed for any small-molecule target; blocked on §5.5 |
| **Record the AF3 build in every run** | `settings.json` should carry the AF3 commit and the ESMFold2 attention backend, so a cross-site difference is a lookup and not an audit |
| ~~Re-cut the tag~~ | Done 2026-10-09 after the Clara rerun; fleet re-pinned with `git fetch --tags --force` |

---

## 4. Findings that must not be relearned

These cost real time to establish. Each is measured, not inferred.

### 4.1 The composition gate would delete a validated pool
It flags **6 of 6 real BindCraft 2 designs** in the golden pool, including the
rank-1 design at `consensus_iptm_mean` 0.918.

| threshold | value | observed | verdict |
|---|---|---|---|
| `min_hydrophobic_frac` | ≥ 0.40 | 0.320–0.410 | floor sits **above** the pool mean (0.363) |
| `max_glu_arg_frac` | ≤ 0.36 | 0.222–0.411 | ceiling sits **at** the pool mean (0.347) |
| `max_ala_frac` | ≤ 0.20 | 0.038–0.111 | transfers fine |
| `max_pro_gly_frac` | ≤ 0.12 | 0.028–0.087 | transfers fine |

The two that fail are the two carried over from `tools/rfd3_gate.py`. The cause
is a tool mismatch, not a bad constant: RFD3's failure mode is a Pro/Gly coil,
while BindCraft 2 hallucinates against AF2 and produces charged, helical,
hydrophobic-poor sequences *by construction*. **This needs per-tool calibration,
not a nudged global pair.** Pinned by `tests/test_composition_gate_stays_advisory.py`.

**Measured against labels, 2026-10-04, and it is worse than "needs calibration".** The registry
(§2) made it possible to judge the shipped shadow column against real outcomes for the first
time. Over all **2,018** labelled Adaptyv designs, `would_exclude_composition`:

| | |
|---|---|
| flagged for exclusion | **1,512 (74.9 %)** |
| true binders it would remove | **271 of 325 (83.4 %)** |
| binder rate among **kept** | **0.107** |
| binder rate among **excluded** | **0.179** |

Lift **0.663× — inverted.** The designs it discards bind at a *higher* rate than those it keeps,
and it survives the obvious confounds: inverted in **4 of 5** length bands and on both large
targets (egfr 0.062 vs 0.171, nipah 0.065 vs 0.119). No individual feature carries signal —
every one scores **0.462–0.547** AUC, with `comp_pro_gly_frac` at 0.462, i.e. pointing the wrong
way.

So the diagnosis above is right about the cause (thresholds calibrated on RFD3's Pro/Gly-coil
failure mode do not transfer to a de novo pool, and flagging 75 % of one is the symptom) and too
generous about the remedy. **`would_exclude_composition` must not be promoted out of shadow
mode.** The two targets pointing the right way are n=96 and n=66 at 0.64/0.48 prevalence.

### 4.2 Ranking expectations
The ranking is a **triage filter, not a decision procedure**. On the Cao
near-miss pool the whole 72-metric field spans macro-AUC 0.471–0.560; the top
decile is worth ~1.5–2× enrichment but beats random on only **6/12 targets**.
Do not present a top-N as "the best" without this caveat. (Part U.)

### 4.3 Verify the real interface, not a proxy
`evaluate.sh` drives every evaluator step through the `binder-compare` console
script, so `import <engine>` was never evidence of anything. Five verifiers
passed unusable environments on that basis. The verify test now **parses the env
list out of `evaluate.sh`** rather than hardcoding it, so a new step in a new env
fails until its verifier follows.

Corollary learned one layer deeper: covering *most* of an interface still passes
a broken one. A verifier that checked two of a script's three imports reported
the default refold engine usable with a model class that did not exist.

### 4.4 A pinned artifact needs a pinned loader
1.0.2 pinned the ESMFold2 model revision and left `transformers` unbounded. The
two halves drifted apart via a renamed config key (`distogram_bins` →
`num_distogram_bins`) and the pinned checkpoint became unloadable by any
installable transformers — breaking the **default** refold engine on every fresh
install. Both halves are now pinned, guarded by
`tests/test_esmfold2_pin_is_two_sided.py`.

### 4.5 Downloaders that check existence, not integrity
`boltz.main.download_boltz2` decides what to fetch by whether a path exists. An
interrupted download is therefore permanently sticky: re-running the documented
bootstrap prints its normal banner, skips every incomplete artifact and reports
success. Found with a checkpoint at 0.21 of 2.3 GB and `mols/` holding 2,949 of
45,227 entries — ALA absent, GLU present. `refold_boltz2` now refuses such a
cache and gives the deletion step.

### 4.6 Completed work must be published as it is produced
Boltz-2 folded 8 designs correctly, then XLA aborted in allocator teardown
(`bfc_allocator.cc: Check failed: central_gap_ == kInvalidChunkHandle`). Because
the results were copied to the caller's path only *after* the fold function
returned, all 8 were stranded. `--resume` did not help — it hit the same abort,
2 runs of 2 — and `try/finally` cannot, because a C++ `CHECK` raises SIGABRT.
Now published **before** folding as well as after.

---

### 4.7 A measurement needs its numerator checked, not just its denominator

The sharpest self-inflicted error of 2.0. A Proteina-Complexa MCTS was timed at 112.3 s for
"9 AF2 reward evaluations" → ~12.5 s per call → a 25× speedup over the CPU figure the tool's
deprecation rests on. **It was published and retracted within the hour.** Every reward was
`0.0`; AF2 never executed; the GPU and CPU control runs produced byte-identical sequences. What
had been timed was MCTS lookahead against a null reward.

`total_reward` was sitting in the rewards CSV **one column from the row count used to derive
"9 AF2 calls"**. The denominator was read and the numerator was not. The CPU control caught it
only because it came back *identical* (111.5 s vs 112.3 s) — and that control had been run to
remove a *target* confound, not to test whether the reward fired. Had it returned ~3,000 s it
would have been taken as confirmation.

Two durable consequences: wall-clock is a **proxy** for "the expensive thing ran", never
evidence of it; and §4.3's rule now extends to measurements, not just interfaces. The swallowing
that allowed it is fixed (§2).

### 4.8 Three of four claims failed on *identity*, with the evidence in the same artefact

Across 2026-10-03/04, the pattern was not missing information but unread information:

- the installer reported Proteina-Complexa "installable" while its own log showed it had
  **never re-installed** (`uv venv` refuses when a venv exists);
- `CLAUDE.md` argued PC inherits BindCraft's jax fix because its reward "**is** the same
  ColabDesign" — in a sentence that gave **two different version numbers** (1.1.1.1 vs 1.1.3).
  The version gap is the blocker: 93 `jax.tree_map` call sites against 0;
- Chai-1 appeared to be the only engine rejecting a true non-binder (0.285 where Boltz-2 said
  0.905) — an artefact of running **MSA-free**. At parity it scores 0.818 and makes the same
  mistake. Had the 563-design study run that way it would have produced a **false positive for
  adoption**.

The lesson that generalises: when a document asserts two things are *the same*, check the
identifiers it cites in the same breath.

### 4.9 The default refold engine runs on a fork, and a pin can disable it while everything verifies

ESMFold2 produced the CALCA and CBG pools and the 563-design benchmark, and 2.0 stopped it from folding anywhere that was installed or upgraded under the new pin. The engine runs on **`github.com/Biohub/transformers` at `3a8956fb`**, which *reports* version 4.57.6 and is the only build whose class is `ESMFold2Model` **with `load_esmc`**, the method the fold calls. PyPI transformers 5.16.1, 5.17.0 and 5.18.0 were each checked: all expose `EsmFold2Model` with `__init__(self, config)` and no `load_esmc`. So `transformers>=5.16` plus the default revision `69869f737bef` (authored against the 5.16.0.dev0 pre-release) replaced a working loader with one that raises `TypeError: unexpected keyword argument 'load_esmc'`, while the env still verified clean. The 2026-09-27 reasoning that `8fc3ff471022` "cannot be loaded by any installable transformers" was true of PyPI and irrelevant: this engine does not run on PyPI transformers. **The class name is not the contract; the method is.** The fork's git URL now 404s, so an env without it must be mirrored from one that has it (pure Python, so it crosses architectures), with `tokenizers==0.22.2`, `safetensors==0.8.0`, `huggingface-hub==0.36.2`. The loader refuses with those instructions rather than failing mid-run. pip itself recorded the truth: `esm 3.3.0 requires transformers @ git+...Biohub/transformers.git@3a8956fb`.

### 4.10 A patch that is not a file is not a patch

`conda run` does not forward stdin, and `run_logged` launches its command with `&` (bash then redirects an async command's stdin from `/dev/null`). A heredoc fed to `python` under either executes nothing and exits 0, so `run_logged` printed a green check over a no-op. Seven PXDesign patch sites were skipped this way, and a May install whose log said all four applied had none of them. The rule for every patch: **a script file passed as an argument, then an assertion on what is on disk**, never the return code. Mutation-check it: put the heredoc back and confirm a test goes red.

### 4.11 Scope every engine's output directory to the run

A default that is relative to the current directory is shared state. `refold-boltz2` defaulted `--output-dir` to `./refold_boltz2`; `--resume` then read whatever an earlier run left there. A fresh 20-design run logged "skipping 86 already-completed binders", folded nothing, and reported **260 new rows** (other runs'), because the guard counts non-empty iPTM and all 260 had one. **The guard added in 2.0 catches an engine that writes nothing; it cannot catch one that publishes someone else's rows.** AF3 and ESMFold2 already scoped theirs.

### 4.12 A patch to installed software dies on reinstall

Upstream AF3 rounds iPTM, pTM and ranking_score to two decimals, which left AF3 with 81 distinct iPTM values against 563 for every other engine and understated it in every rank metric. The fix edits the installed package, so it vanished the moment BM5's AF3 was rebuilt. It now lives in the installers (`install/patches/af3_full_precision.py`), runs after every build, and `--verify` can see a loss. Without the `--check` path nothing could: `import alphafold3` and the CCD check both pass on a rounded build. Only some builds also round PAE to one decimal, so that edit is optional; an *unrecognised* source fails loudly.

### 4.13 Compare engines across sites only after auditing the software at each

BM5 ran nipah c24-c26 (85 designs, every one a non-binder, the shortest binders) on **AF3 3.0.2 from April** while every other site ran the pinned July build (`fd39d2c5`), and its ESMFold2 env had **xformers 0.0.35 on torch 2.12+cu130** where the x86 sites fall back to PyTorch attention. Because chunks were sorted by length, the site boundary *is* a length boundary, so the effect cannot be separated from length with this data; dropping those designs moves nipah ESMFold2 AUC 0.669 to 0.655 (a bound, not an estimate). BM5 is now rebuilt to the pin (`3.0.4.dev14+gfd39d2c5d`) and xformers is removed. Six test folds against BM2: AF3 mean |delta iPTM| 0.006 (max 0.015); ESMFold2 four of six within 0.007 but two moved by 0.06 and 0.19, which is the size of ordinary run-to-run spread but proves nothing at n = 6. **The Clara rerun is the test.** Everything else matched across sites: identical ESMFold2 revision, identical Boltz-2 and AF3 settings, byte-identical target MSAs (sha256), one git commit.

**Result of the Clara rerun (2026-10-09, all 85 designs, same sequences, 3 engines).** Mean |delta iPTM| Clara vs BM5, rank correlation, designs moving more than 0.15:

| engine | mean abs delta | Spearman | > 0.15 |
|---|---|---|---|
| ESMFold2 | 0.022 | 0.89 | 1 |
| AF3 | 0.068 | 0.66 | 7 |
| Boltz-2 | 0.108 | 0.76 | 23 |

Read it carefully. ESMFold2, the engine with the xformers difference, agrees closely, so attention backend was not a large effect. AF3 moved more, but Boltz-2 moved *most* although its software and settings were identical at both sites. That makes the Boltz-2 figure a floor for run-to-run spread (diffusion sampling, GPU model, memory pool) and means the AF3 gap is **not clearly a software effect**: it sits below that floor. No same-site repeat exists, so the floor is inferred, not measured. Consequence: nipah per-design iPTM from BM5 carries roughly this much noise per engine; the nipah AUCs above stand as bounds, not corrected values. Short (<=30 aa) and longer binders differ little for AF3 and ESMFold2; Boltz-2 is noisier on the short ones (0.129 vs 0.099).

### 4.14 GPU memory: the cap flags are not what they look like

`evaluate.sh --gpu-cap-boltz2/-af3/-esmfold2` set `CUDA_MPS_PINNED_DEVICE_MEM_LIMIT` only. The JAX pool is set elsewhere: `refold_boltz2.py` hardcodes a 24 GiB target, and only `<ENGINE>_XLA_MEM_FRACTION` overrides it. Three BM5 runs failed identically (a 53.75 GiB single allocation) because the "48G" and "85G" caps never reached JAX. On GB10 the pool is system RAM and `gb10-guard` SIGKILLs at `MemFree` below 24 GiB, **unregistered jobs first**; an 85 GiB pool left 15.9 GiB and was killed although `gpurun --max` advertised 91 GiB. A job launched through `gpurun --cap N` registers a declared budget; 70 GiB left 33 GiB and ran. And **Boltz-2 on GB10 needs about 1.5x a discrete card**: the same nipah designs fit a 70 GiB pool on an H200 but not on GB10 (845-token complexes), so the longest designs belong on Clara. Query the live ceiling, never quote it.

### 4.15 Chunk time follows distinct lengths, not designs

JAX recompiles for every new input shape and there is no persistent compile cache for Boltz-2. egfr c01 (40 designs, **1** distinct length) took 25 minutes in Boltz-2; c02 (40 designs, **13** lengths) took 101. About 6 minutes per distinct length on an H200, against 0.6 minutes to fold. Chunks sorted by length share few shapes with their neighbours, so a cache would not have helped much. Plan runs by distinct-length count. BM5 spends roughly 5 minutes per design per engine on compilation alone.

### 4.16 AK1: what the full-scale refold shows, with the claims it does not support

2,033 designs, labels corrected (one stale label, il7r `bright-panther-frost` 0 to 1; effect <= 0.004):

| solo AUC | egfr | il7r | nipah | pd-l1 | macro, equal | macro, by n |
|---|---|---|---|---|---|---|
| Boltz-2 | 0.687 | 0.671 | 0.543 | 0.820 | 0.680 | 0.617 |
| AF3 | 0.498 | 0.709 | 0.589 | 0.771 | 0.642 | 0.563 |
| ESMFold2 | 0.621 | 0.712 | 0.669 | 0.686 | 0.672 | 0.652 |
| mean of three | 0.629 | 0.737 | 0.636 | 0.805 | **0.702** | 0.643 |

**Supported:** no engine wins on every target (Boltz-2 on egfr and pd-l1, ESMFold2 on il7r and nipah); the mean is never the worst and is within 0.06 of the best everywhere; it beats AF3 by 0.060 [+0.030, +0.090]. **Not supported, and previously stated:** that the mean is *better* than the best single engine. Its macro edge is +0.021, 95% CI [-0.011, +0.039], indistinguishable from zero, and it reverses under n-weighting (ESMFold2 0.652 vs 0.643). On egfr alone the mean is *worse* than Boltz-2 by 0.058 [-0.092, -0.025]. Dropping AF3 does not help (0.696). "No signal from AF3 on egfr" is also too strong: AF3 returns a collapsed binder (pLDDT < 0.5) for 352/826 egfr and 324/1045 nipah designs and for none in il7r or pd-l1. Chai-1, adjudicated separately, is not adopted. **The mean is a defensible hedge, not a demonstrated improvement.**

### 4.17 Label denominators, again

215 of 2,033 designs (10.6%; egfr 69, nipah 146) did not express and are labelled non-binders by documented convention, so the AUCs partly measure expression (dropping them moves macro mean3 by 0.006). State the denominator beside any number. The GuideFlip supplement says the same thing in its own words, "an undetermined affinity does not imply absence of binding", and marks `dnRB7` as "not classified as a binding negative"; 17 of its 88 designs were never assayed and are kept out of the labels. The historical failure (never-ordered rows read as negatives) has now been met three times.

### 4.18 Do not generalise a noise estimate from one target

Refolding the same designs moved Boltz-2's pd-l1 AUC from 0.717 to 0.820 (n = 66) and the same engine on il7r (n = 96) by under 0.01, with per-design movement independent across engines and unbiased in both. Individual designs move by 0.15 to 0.5 in a few percent of cases; what that does to an AUC depends on how many designs there are to dilute it.

---

## 5. Open decisions — these are the user's, not the code's

### 5.0 ~~The cross-engine gate should degrade gracefully~~ — **RETRACTED the same day, measured**

> **Tested and withdrawn 2026-10-03.** See
> [INVESTIGATION_coverage_premise_2026-10-03.md](INVESTIGATION_coverage_premise_2026-10-03.md).
> Shrinkage gains **+0.0003 … +0.0006** macro AUC over the raw mean with every CI
> straddling zero, is **worse** on precision@top-10 % in 8/8 regimes, and `k` is
> unidentifiable (the objective spans 0.0013 across the whole grid; the leave-one-target-out
> fit selects both k=0 and k→∞ in every configuration).
>
> **And the premise behind the proposal was wrong.** Coverage is 100 % constant on every
> labelled set we own (Cao 4,442/4,442, denovo 110/110, Adaptyv 563/563). In the only
> missingness mode we have evidence of — an engine's env absent, or PAE files unresolvable,
> where 50 Adaptyv rows lost *all three* engines at once — coverage is constant and the
> gate, the raw mean and shrinkage at any k are **provably the same within-target ranking**.
> The regime where they differ, per-design heterogeneous coverage, has never been observed.
>
> What survives from the reasoning below: the user's premise is **true about errors**
> (one engine buries a true binder 5.2× more often than all three together, 7.6× on clean
> labels), and the mean rescues **73.2 %** of binders buried by exactly one engine. The
> error-correlation estimate is ρ ≈ 0.382 measured within target and within class, not the
> ρ = 0.52 quoted below, which was computed on the engines' native ipTM rather than the
> PAE-recomputed columns the ranking averages.
>
> The reasoning is kept because the retraction is the useful part: a principled estimator
> with a fittable parameter is still worth nothing if the failure mode it addresses does
> not occur.

### 5.0 (superseded) The cross-engine gate should degrade gracefully, not switch off

**The argument, which is the gate's own justification sharpened.** A 3-engine mean can of
course be worse than a single engine on any given design. But P(one engine wrong) must be
much larger than P(three engines wrong together) — so coverage is informative, and that is
exactly why the gate prefers it.

**How much it is worth depends on error correlation, and that is now measured.** On the 64
ss_bias designs scored by both AF3 and ESMFold2 (2026-10-03): Pearson **r = +0.52**,
Spearman 0.51 — only **27 % shared variance**, so 73 % of each engine's signal is its own.
A two-engine mean therefore cuts sd by ×0.872 against ×0.707 for perfect independence and
×1.0 for redundancy. The engines are weakly correlated, so extra opinions buy real
information and the premise holds.
*Two caveats:* this is **agreement, not accuracy** (no labels in that pool), and it is
computed on the engines' **native** `iptm`, whereas the ranking averages the
PAE-recomputed `*_pae_iptm` under a common TM kernel. The native scales differ sharply
(AF3 0.625 vs ESMFold2 0.339), which is *why* the pipeline recomputes — so the operative
correlation may well differ, and re-measuring on `*_pae_iptm` needs the PAE `.npy` files.

**The live defect this exposes.** When nothing clears the gate, `passes_engine_gate` goes
constant, the order becomes `consensus_iptm_mean` alone, and a 1-engine design outranks a
3-engine one (measured). As of `92e415b` the warning says so loudly — but the *ordering*
still discards coverage at exactly the moment coverage matters most.

**The form the fix should take, and why not either obvious one.** Pure coverage-first is
also wrong: a 3-engine design at 0.30 should not beat a 1-engine design at 0.99 —
confidently mediocre losing to possibly excellent. The correct form is **shrinkage**:
pull each design's mean toward the pool mean in proportion to its uncertainty, so a
1-engine estimate moves a lot and a 3-engine estimate barely moves. That subsumes both the
cliff-gate and the raw mean as limiting cases and has one free parameter.

**Why it is not implemented.** It is a ranking change, and Part U measured that searching
for a better ranking on our data made it *worse* (0.5170 vs 0.5552, p=0.0014). Unlike
metric search, though, this is a *principled* estimator with a fittable parameter, so the
objection is about validation rather than about the idea. **The test:** fit the shrinkage
constant on one labelled pool and check precision@top-10 % on a held-out one, against both
the current cliff-gate and the raw mean. Part T §5.1 is the cautionary precedent — a
within-target "free win" there reversed sign on independent data.

**Blocked on:** the labelled pools (Adaptyv 2,515 / Cao 4,442) are not on this box or BM2,
and `Evaluator/benchmarks/` is Part Y's empty registry. This is the same access gap that
blocks promoting four shadow columns.


### 5.1 ~~Does the discovery-rank metric accept a pre-filtered pool?~~ — **DECIDED 2026-10-04: (b), uniformly**

Carry the caveat: emit the rank with `pool_pre_filtered=True` alongside, for **all eight tools
with no exceptions**. The operator's reasoning is the stronger one — a discovery rank meaning
"earliest among survivors" for five tools and "earliest overall" for three, in one table, is the
same incomparability the cross-engine gate exists to prevent. The "(c) where it is cheap"
half was explicitly declined for that reason.

**Still blocked on data, not on this decision:** AD's validating gate is "holdout passes a KS
test vs the pool", which needs a campaign with a real generation order. This box has none, so
(b) ships a column that cannot yet be checked. Not built pending that.

### 5.1 (original wording) Does the discovery-rank metric accept a pre-filtered pool? **(the big one)**
**Blocks: finishing Stage 1.** Everything else in it is built.

Most extractor inputs are already downstream of a quality filter, so a discovery
rank computed over them is conditioned on survival — the denominator has been
deleted:

| tool | what the extractor sees |
|---|---|
| Protein-Hunter | iPTM > 0.8 **and** pLDDT > 0.8 **and** Ala ≤ 20% |
| Mosaic | `is_top=1` — top ~5% |
| BoltzGen | ~700 rows of ~10,000 |
| Proteina-Complexa | `top_samples`, then only survivors |
| BindCraft | accepted designs only |

Options: **(a)** refuse (honest, near-useless for five of eight tools);
**(b)** carry `pool_pre_filtered=True`, which `tool_classification.py` already
tracks; **(c)** require the complete pool — Mosaic and Protein-Hunter both have
one behind a single CLI flag each.

**Standing recommendation: (b) now, (c) where it is cheap.**

### 5.2 ~~Which labelled pools go into the registry first?~~ — **DECIDED 2026-10-04: Adaptyv only**

`adaptyv` registered (2,018 designs, 4 targets). Our own SPOC panels are deliberately **not**
registered yet — operator decision, on the grounds that we are not sharing our data. Noted at the
time: Part Y's design means registering a pool does *not* publish its labels (the manifest carries
provenance and a checksum; rows stay in a private store), and CALCA/CBG/2VDY are already named
throughout the public repo — so the constraint is narrower than it looks if that changes.

### 5.2 (original wording) Which labelled pools go into the registry first? — DEFERRED
Bookkeeping rather than compute (all four are already refolded through our
engines), but **73.4% of Cao's binder labels are one-sided Kd**, and excluding
them moves macro-AUC 0.53 → 0.73. The subset choice changes every number
computed from it.

### 5.3 The aarch64 `dssp` build path — minor
`tools/aarch64/dssp` carries a `/home/<account>` baked in at compile time.
Recorded and pinned by a test. **Rebuild next time someone is on Spark anyway.**

### 5.4 How AK1-style numbers are reported (proposed, not decided)

Report macro AUC **both** equal-weighted and n-weighted, state the expressed/unexpressed denominator, and give a paired bootstrap interval for any claim that one ranking beats another. The equal-weighted ordering of the mean over the best single engine does not survive n-weighting (§4.16); the audit found no defect in the arithmetic, only in what was claimed from it.

### 5.5 Which small molecule? **(the user's)**

The goal stated on 2026-10-09 is designing proteins that bind a small organic compound, which is the inverse of OpenBind (fixed protein, varying ligand). Public experimental data for that task is tiny (RFdiffusion All-Atom digoxigenin: 17 designs, 2 binders; the Kortemme steroid set: 26 designs, 4 binders, licence not stated), so a benchmark of the AK1 kind cannot come from public sources and has to come from the first ordered designs. Our design tools that take a ligand target are RFD3, Protein-Hunter and BoltzGen. Nothing about the evaluator's ligand mode is worth building until a target is chosen. If none is, digoxigenin is the calibration case: published designs, crystal structures, a purchasable ligand.

### 5.6 The `--gpu-cap-*` flags

Wire them to the JAX pool fraction, or remove them (§4.14). Today they promise a ceiling they do not set.

---

## 6. Platform reality — engines, and where they actually run

Measured 2026-09-27 on a 12 GB RTX 3060 (sm_86). This matters because several
documented claims did not survive contact.

| engine | status |
|---|---|
| **Boltz-2** | Runs. Folded 8 CALCA designs, ipTM 0.4855–0.9007 |
| **AF3** | **Cannot run on consumer Ampere/Ada at all.** Its tokamax Pallas/Triton kernels request **110,592 bytes of shared memory per block**; sm_86/sm_89 expose **101,376**. This is a per-SM architectural limit, not VRAM — unaffected by the memory fraction, by a larger card of the same generation, by `--flash_attention_implementation=xla`, by `--xla_gpu_enable_triton_gemm=false`, or by a cold compile cache. A100 gives 164 KB; H100/GB10 228 KB |
| **ESMFold2** | Loader now correct (weight load produces **zero** mismatches), but OOMs moving ~12 GB of weights onto the card. **`--model fast` hits the same wall.** Confirms the "~14 GB floor, a floor not a slope" note |

**Consequence for the fleet, needing action:** CLAUDE.md's "AF3 runs fleet-wide
(BM1/BM2/BM4)" rests on a 2026-08-14 measurement on **BM2, an RTX 3090 — also
sm_86, the same 101,376-byte limit**. That result cannot be reproducible on a
commit using these kernels. The likely explanation is that `AF3_COMMIT` has
moved since (tokamax is new in AF3 3.0.x), which would leave the 4.4 GB VRAM
finding true and the *card list* stale. Marked **in doubt** in CLAUDE.md; both
measurements kept.

**Also worth knowing:** `--tool all` installs **two** refold engines, not three.
AF3's weights are gated behind a Google DeepMind request so it cannot be in
`all`, which means a fresh install faces the default `--min-engines 3` with two
engines and every design fails the gate. The report says so loudly and names the
shortfall; it is now documented in CLAUDE.md.

---

## 7. Needs a machine this one is not

| | what |
|---|---|
| ~~AF3 on BM2~~ | **CLOSED 2026-10-09.** The audit read the commit at every site: Clara, BM2 and BM4 run `fd39d2c5`; BM5 ran `f6a5aec` and has been rebuilt to the pin |
| ~~One ESMFold2 fold~~ | **CLOSED, and bigger than asked.** 2,033 ESMFold2 folds completed in AK1; the question also surfaced the fork regression (§4.9) |
| **Proteina-Complexa throughput** | Installable on aarch64 again since 2026-09-26; the MCTS timing question is unmeasured. Run a short MCTS on Spark and time it before planning a campaign |
| **Stage 4 validation** | Pools now exist (§3, Stage 4). Needs someone to run the recall-bound measurement |
| **Shadow-mode promotion** | Wet-lab outcome labels. The GuideFlip alpha-synuclein and RBX1 sets (about 48 measured designs, 12 binders) are a possible small source; they cannot discriminate between rankings |
| **BM5 site effect** | Needs the Clara rerun of nipah c24-c26 to finish (§3, Opened 2026-10-09) |

---

## 8. How to confirm this state

```bash
git -C . describe --tags                 # expect v2.0.0 (the tag is at the tip of v2.0.x)
git status --short                       # expect empty
./conda/envs/binder-eval/bin/python -m pytest tests/ -q     # 1109 passed, 7 skipped
uvx ruff check . && uvx ruff format --check .
shellcheck --shell=bash --severity=warning install/install.sh install/install_aarch.sh Evaluator/evaluate.sh
./install/install.sh --tool all --verify # audits what is actually on disk
```

**House rules that produced the above, worth keeping:** write the guard as a
test, then **mutate the code and confirm the test goes red** — and assert the
mutation applied, because a mutation that silently fails to apply leaves a green
test proving nothing. Both happened here; both were caught only by checking.
