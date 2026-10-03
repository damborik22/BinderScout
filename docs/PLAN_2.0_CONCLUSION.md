# BinderScout 2.0 — state of the plan

A self-contained handoff. Everything needed to pick 2.0 up without reading the
diary first; pointers are given where the detail lives.

| | |
|---|---|
| **Branch** | `v2.0.x` (all 2.0 work; `master` is frozen at 1.0.3, `v1.1.x` is the BindCraft 2 line) |
| **HEAD** | `5fb9d99`, clean, pushed, CI green |
| **Tests** | 887 passing, 7 skipped; ruff + shellcheck clean |
| **Version** | **2.0.0** — decided 2026-09-28. `binderscout.py:32` carries it; **not yet tagged**. Newest tag in the repo is `v1.1.1`, and HEAD is 84 commits past it, so `git describe` still reports `v1.1.1-84-g…` until `v2.0.0` is cut |
| **Changelog** | 2.0 work sits under `[Unreleased]` |

Companions: [NEXT_STAGES.md](NEXT_STAGES.md) (stage detail),
[MORNING_DECISIONS.md](MORNING_DECISIONS.md) (the open decisions in full),
[REPO_DIARY.md](REPO_DIARY.md) (how each finding was reached),
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
`hits.py` holdout. **Blocked on decision §5.1** (pre-filtered pools) and, for
its stated gate ("holdout passes a KS test vs the pool"), on a real campaign
with a genuine generation order.

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
code. Its real prerequisite is **two archived pools with all three engine
CSVs**, to measure recall at the keep-fraction — this box has none.

One correction to carry: Z's stated gate ("`rank` byte-identical with and
without `--stage1-results`") **tests the wrong thing.** That flag only attaches
advisory columns; the ranking change comes from the *missing refolds*. A staged
run and a full run cannot have identical `rank`. **Restate the gate as a recall
bound.**

### Stage 6 — the GPU-memory pass, and it goes LAST
By decision: a reading taken against an unfinished pipeline is stale by the time
it ships. Memory, not speed, decides whether a step runs at all.

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

## 5. Open decisions — these are the user's, not the code's

### 5.0 The cross-engine gate should degrade gracefully, not switch off — **identified 2026-10-03, not implemented**

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


### 5.1 Does the discovery-rank metric accept a pre-filtered pool? **(the big one)**
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

### 5.2 Which labelled pools go into the registry first? — DEFERRED
Bookkeeping rather than compute (all four are already refolded through our
engines), but **73.4% of Cao's binder labels are one-sided Kd**, and excluding
them moves macro-AUC 0.53 → 0.73. The subset choice changes every number
computed from it.

### 5.3 The aarch64 `dssp` build path — minor
`tools/aarch64/dssp` carries a `/home/<account>` baked in at compile time.
Recorded and pinned by a test. **Rebuild next time someone is on Spark anyway.**

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
| **AF3 on BM2** | One re-run recording which `AF3_COMMIT` was used, to settle §6 |
| **One ESMFold2 fold** | On a card that holds ~12 GB of weights, to close the loop on the pin fix (the *load* is confirmed; a completed fold is not) |
| **Proteina-Complexa throughput** | Installable on aarch64 again since 2026-09-26; the MCTS timing question is unmeasured. Run a short MCTS on Spark and time it before planning a campaign |
| **Stage 4 validation** | Two archived pools with all three engine CSVs |
| **Shadow-mode promotion** | Wet-lab outcome labels |

---

## 8. How to confirm this state

```bash
git -C . rev-parse --short HEAD          # expect 5fb9d99 (or later on v2.0.x)
git status --short                       # expect empty
./conda/envs/binder-eval/bin/python -m pytest tests/ -q     # 887 passed, 7 skipped
uvx ruff check . && uvx ruff format --check .
shellcheck --shell=bash --severity=warning install/install.sh install/install_aarch.sh Evaluator/evaluate.sh
./install/install.sh --tool all --verify # audits what is actually on disk
```

**House rules that produced the above, worth keeping:** write the guard as a
test, then **mutate the code and confirm the test goes red** — and assert the
mutation applied, because a mutation that silently fails to apply leaves a green
test proving nothing. Both happened here; both were caught only by checking.
