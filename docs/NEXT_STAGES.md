# Next stages

Where 2.0 stands after the 2026-09-23/24 session, and what to pick up next.
Companion to [PLAN_binderscout_v2.md](PLAN_binderscout_v2.md) (the plan) and
[PLAN_binderscout_v2_corrections.md](PLAN_binderscout_v2_corrections.md) (where
its facts were wrong).

---

## Done

| | |
|---|---|
| **Day 0** | `rank` corruption from four unguarded joins · benchmark-label leak guard · CI on release branches |
| **Prerequisite** | Mutation-tested ranking suite (synthetic) **and** a golden fixture from a real CALCA campaign |
| **AD step 4** | Mosaic records `generation_index` — the only item with an external clock |
| **AA core** | ProtParam panel (D7) · per-sequence composition gate in shadow mode (D8) · **TmProt end to end** (D1) |
| **Scoped** | D4 foldability · D3 AggreProt — both were "scope first", not build orders |
| **Infrastructure** | Installer `--verify` / `--repair` / retries · one tool registry · 12-tool menu · a worked example |

Everything above is on `v2.0.x`, 728 tests, ruff and shellcheck clean.

---

## Stage 1 — AD's Evaluator half, **redesigned**

The plan says the extractors gain `generation_index` and `generated_at`, and
calls it "one line each" because every extractor globs its tool's outputs so
`stat()` gives a real generation time.

**That premise is wrong, and it is the whole difficulty.** Seven of the eight
extractors resolve ONE aggregate CSV and iterate its rows —
`bindcraft.py:64,90` (`final_design_stats.csv`), `boltzgen.py:59,71`,
`mosaic.py:68,108`, `proteina_complexa.py:173,201` — each a `read_csv` then an
`iterrows`, with `rglob` used only to re-find a structure file. A file mtime
gives **one timestamp for the entire pool**, not one per design. And BindCraft
2's `!_Ranked.csv` is rewritten on every acceptance, so even its row order is
acceptance order rather than generation order.

So the work is not plumbing, it is establishing **per tool** what generation
order can honestly be recovered.

### Done — the extraction half

The per-tool investigation is
[INVESTIGATION_generation_index_2026-09-24.md](INVESTIGATION_generation_index_2026-09-24.md).
`ExtractedBinder` now carries `generation_index` and `generation_index_source`,
and the value reaches `metrics.csv` through the existing native-metrics sidecar.

**Row position is not used for any tool** — not one. Where a file happens to be
in generation order the extractor re-sorts before iterating; where it does not,
the order is a quality sort.

| source | tools |
|---|---|
| `explicit` (a counter the tool wrote) | Mosaic, Protein-Hunter |
| `joined` (a counter in another of its tables) | BindCraft 2 — `trajectory`, joined on `hash` |
| `parsed` (an ordinal inside an identifier) | BoltzGen, RFD3 |
| `unavailable` | PXDesign, Proteina-Complexa, BindCraft 1 |

`unavailable` is a real answer, and for Proteina-Complexa it is the *correct*
one: under MCTS the pool is a flattened tree, so a scalar index has no
consistent meaning. Those three are pinned by tests that no production code
makes pass — the tempting "fix" for each is a fall-back to row position, which
for all three is a quality sort.

### Remaining — the metric itself

`hits.py` holdout, and the decision below.

**The pool-filtering problem is unresolved, and may matter more than ordering.**
Most extractor inputs are already downstream of a quality filter, so a discovery
rank computed on them is conditioned on survival — the denominator has been
deleted. Protein-Hunter's default CSV is gated at iPTM 0.8, Mosaic's at the top
~5%, BoltzGen's at roughly 700 rows of 10,000. Before the metric ships it needs
to either refuse a pre-filtered pool or carry the fact; `pool_pre_filtered`
already exists in `tool_classification.py` to say so.

---

## Stage 2 — Y, the private label registry

Library only, imported by nothing that ships, so it is the lowest-risk part in
the plan. Its `.gitignore` guard already landed on Day 0, so the irreversible
half is done.

Two corrections from the investigation carry into it:

- The plan says the labelled pools live only under gitignored `runs/`. That is
  **wrong for three of the four named pools**; they sit in at least four
  different roots, and `runs/` does not exist on this box at all.
- Y and AG both specify `binder_comparison/benchmarks.py`, and AG additionally
  specifies `comparison/benchmark.py`. One module, decided before either starts.

Unblocks AG and AH, which cannot begin without it.

---

## Stage 3 — AA's remaining items

| item | state |
|---|---|
| **P5** ESM Cambrian plausibility | **Buildable now.** ESM-2 650M fits this box (2–5 GB). Shadow mode, like every pre-GPU filter |
| **A1** BindPred | Needs the model. Build the runner **once** — AH consumes the same one |
| **D3** AggreProt | Reduction + decorrelation harness are **built and validated**; needs the model or one real per-residue export |
| **promotion** out of shadow mode | Needs outcome labels (which designs expressed and bound), not more refolds |

The decorrelation harness is the leverage here: 439 designs already carry
SoluProt scores, so any new screen's redundancy question is minutes of CPU once
its scores exist.

---

## Stage 4 — Z, the staged cheap-filter mode

Depends on AA, **not** in the way the plan says. AA's one load-bearing item for
Z — the ESMFold2 full/fast default — is already closed in code; only a docstring
was stale. Z can start whenever.

Its real prerequisite is **two archived pools with all three engine CSVs**, to
measure recall at the chosen keep-fraction. The RAW archive now supplies that
shape of data.

One correction: Z's stated gate ("`rank` byte-identical with and without
`--stage1-results`") tests the wrong thing. That flag only attaches advisory
columns; the ranking change comes from the *missing refolds*. A staged run and a
full run **cannot** have identical `rank`, and the gate needs restating as a
recall bound.

---

## Stage 5 — the static config-builder page

The audit produced the exact `--config` schema, which was the blocker. It is
worth building because `configurator.py` is ~4,600 lines driving a linear
wizard, and a form is a form.

Constraints that must hold:

- **Static HTML, no server.** A second surface listing tools and flags is
  exactly the drift this codebase already struggles with; a page that only emits
  JSON cannot drift into a second source of truth.
- Generate the form from `REQUIRED_CFG_KEYS` and the defaults in
  `configurator.py`, not from a hand-written copy.
- Emit a **relative** `run_dir` — now safe, since `load_run_config` resolves it.
- `examples/CALCA/smoke.json` is the reference output and is pinned by tests.

Traps the audit found, all of which a hand-written page would hit: the
`tools_enabled` key is `pxdesign_local`, not `pxdesign` (a config with the
latter enables nothing and exits 1); `use_boltz`/`use_af3`/`primary_engine` look
like `tools_enabled` keys in every wizard-written config but are read from
`cfg`; and `target_sequence` must match the structure's chain or RFD3 refuses.

---

## Stage 6 — the GPU-memory pass, and it goes LAST

A pass over every pipeline step to optimise GPU memory consumption. It is the
final step of 2.0 by decision (2026-09-24), not an opportunistic thing to do
while implementing the stages above: a reading taken against an unfinished
pipeline is stale by the time it ships.

Memory, not speed, is what decides whether a step runs at all on a given card,
and the measured profile is very uneven. From the 2.0 benchmark:

| engine | peak | shape |
|---|---|---|
| Boltz-2 | ~139.6 GB @ 900 tokens | memory-dominant, scales hard |
| ESMFold2 | ~14 GB floor @ 150 tokens | a floor, not a slope — why a 12 GB card cannot run it at any size |
| AF3 | ~5.2 GB | nearly flat across our size regime |

Two traps this repo has already paid for, both of which look like "needs a
bigger card" and are not:

- `XLA_PYTHON_CLIENT_PREALLOCATE` reserves a fraction of the pool *regardless
  of the working set*. The false ">=100 GB AF3" requirement came from exactly
  this — a 4.4 GB working set reserving ~22 GB on a 3090.
- PyTorch fragmentation, which needs
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` rather than more VRAM.

On BM5 (GB10) the GPU pool *is* system RAM, so an uncapped job reboots the box
rather than raising OOM. Measure there through `tools/gpurun --cap`.

---

## Blocked on someone else

| | needs |
|---|---|
| **AggreProt** (D3) | The model, or one real per-residue export. `parse_profile_csv` is written against the published *description* and is marked unvalidated |
| **Foldability** (D4) | Which method "Kohout" names. It is not a public tool |
| **AA promotion** | Wet-lab outcome labels |
| **CI** | A push. Nothing has reached origin, so the branch-filter fix has not taken effect |

---

## Two loose ends worth naming

**The repo still contains absolute `/home/<user>` paths**, in `CHANGELOG.md`,
`Evaluator/docs/plans/`, `docs/INVESTIGATION_RANKING_DISCREPANCY.md` and others,
although CLAUDE.md states they were "scrubbed from tree and history
2026-09-22". They are already on `origin/master` and `origin/v1.1.x`, so this is
pre-existing rather than newly published — but the claim in CLAUDE.md is not
true and someone relying on it would be wrong.

**The golden fixture cannot exercise the cross-engine gate.** All six real
designs are 3-engine, so `MIN_ENGINES 3→2` leaves it green. Gate demotion is
pinned by the synthetic pool instead. If a future archive happens to contain a
1-engine design, the two fixtures could collapse into one — but manufacturing
one would make the golden order no longer the order the campaign produced.
