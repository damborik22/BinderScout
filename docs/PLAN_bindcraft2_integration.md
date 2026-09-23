# PLAN — BindCraft 2 as the eighth design tool

## Why

BindCraft 1 has been the only AF2-hallucination designer in the pipeline, and it
carries the heaviest dependency stack in it: PyRosetta plus conda `jaxlib`.
(Both do in fact work on aarch64 — measured on BM5, jaxlib 0.4.34 on the GPU
and pyrosetta importing — so this is a maintenance burden, not a platform
block.) BindCraft 2 is a full rewrite of the same
lab's method — JAX only, no PyRosetta, no conda, Python ≥3.12, pip wheels —
and it ships modalities BindCraft 1 has no equivalent for (scaffolded VHH /
ARP / scFv / Fab, cyclic peptides, induced-fit and fold-switch objectives).

Two BindCraft 2 design sets have already been delivered to us externally and
evaluated by hand (CBG/2VDY and CALCA, 50 designs each). They were ingested
through `--tool-csv` with a one-off script that dropped 55–57 of the 62 native
columns — including `i_pDAE`, the metric BindCraft 2 actually ranks on. This
plan replaces that hand path with a first-class tool: installed, configured,
run, extracted and reported like the other seven.

**BindCraft 2 does not replace BindCraft 1.** They coexist as separate tools
with separate environments, separate run scripts and separate extractors, so
every archived BindCraft 1 campaign stays reproducible and the two can be
compared head-to-head inside one report.

## What BindCraft 2 is

Upstream package name `bindcraft`, version `1.0.0`, from the Pacesa Lab
(University of Zurich). It layers AlphaFold 2 sequence optimisation with
ProteinMPNN redesign, then validates candidates with held-out AlphaFold
models and structural filters.

Differences from BindCraft 1 that drive this plan:

| | BindCraft 1 | BindCraft 2 |
|---|---|---|
| Environment | conda, PyRosetta, conda `jaxlib` | `.venv`, editable, pip `jax[cuda12\|cuda13]` |
| Python | 3.10 | ≥3.12 |
| Input | three JSON files (target / filters / advanced) | one layered campaign JSON |
| Output | `final_designs.csv` + PDBs | `3_Ranked/!_Ranked.csv` + mmCIF |
| Native rank | i_pTM | **`i_pDAE`**, descending, higher is better |
| Budget | attempts | **accepted-design quota, no timeout** |
| aarch64 | blocked (PyRosetta, conda jaxlib) | plausible; wheels exist for both arches |

### Four facts that shape everything below

1. **It ranks on `i_pDAE`, not i_pTM, and it is not a composite.**
   `RANKING_METRIC = 'i_pDAE'`; the `rank` column is the 1-based position
   after a plain descending sort on that one metric, with no tie-breaker.
   Verified against all 100 rows of the delivered CBG and CALCA exports. The
   `native_metric_interpretation` text committed in `tool_classification.py`
   says "composite Rank" and is wrong.

   `i_pDAE` **is higher-is-better** despite reading like an error term — it
   is a TM-score analogue bounded 0–1, and upstream's `LOWER_IS_BETTER_METRICS`
   pointedly omits it. Register it that way or every downstream plot inverts.

   Ties are pervasive: the delivered values are rounded to two decimals, giving
   a 17-way tie in CALCA and a 13-way tie in CBG. Rank *within* a tie block is
   acceptance order, not quality order. This is a second reason never to
   recompute rank.

2. **Two output schemas exist in the wild.** The delivered CBG/CALCA data came
   from a pre-1.0 build: TitleCase `Rank` / `Design` / `Sequence` in a flat
   `<target>_ranked.csv`, with a `Protocol` settings tier and a `miniprotein`
   modality that v1.0.0 does not have. Version 1.0.0 writes lowercase
   `rank` / `design` / `Binder_Sequence` into `3_Ranked/!_Ranked.csv`. The
   rename is broad: percentage columns became `*_Fraction` on a 0–1 scale,
   `InterfaceResidues` split in two, four timing columns collapsed into one.
   An extractor written against the current docs alone cannot read our archive.

3. **A campaign has no time limit.** `number_of_final_designs` is a quota of
   *accepted* designs, not an attempt budget, and `max_trajectories` is the
   only cap in the package — grepping the whole tree for a wall-clock setting
   finds only a 60 s socket timeout on the weight download. Left unset, a
   campaign runs until it fills the quota. Every other tool in BinderScout is
   bounded by attempts.

4. **The ranked table is rewritten, and it can shrink.** `3_Ranked/!_Ranked.csv`
   is rebuilt after every acceptance, and at campaign close a reconcile pass
   drops any row whose structure is no longer on disk. A mid-run snapshot can
   be superseded by a *smaller* one — so the `--tool-csv` snapshot must be
   taken after the campaign closes, or we re-enter the known
   stale-`tool_csvs` failure mode.

## Acquisition and licensing

| Component | Source | License |
|---|---|---|
| BindCraft 2 source | lab share, `DEV/BindCraft2.zip` (path in `CLAUDE.local.md`) | BindCraft2 Source-Available (Hosting-Restricted) |
| AlphaFold 2 code inside it | vendored by upstream | Apache-2.0 |
| ProteinMPNN / HyperMPNN weights | bundled in the wheel (~77 MB) | MIT |
| AlphaFold 2 parameters | reuse an existing cache — see Install step 3 | DeepMind terms |

**The licence permits redistribution.** It explicitly allows "redistribution
of source code or binaries for others to run themselves", including
commercially, and explicitly names "execution directed by your own automated
or agentic tooling" as internal use. The restrictions are (a) offering it to
third parties as a hosted/managed/API/SaaS service, and (b) using the
BindCraft2 name to market a derivative as if official. Nothing BinderScout
does touches either.

**The constraint is an embargo, not the licence.** The upstream repository is
not published yet — checked, and it 404s. Its location is deliberately not named
here either: this repository is public, so naming an unreleased project's path
is itself a small disclosure. Therefore:

- `BindCraft2/` is **gitignored and never committed**, in `.gitignore` and
  `.dockerignore` both. It is not listed in `THIRD_PARTY_NOTICES.md` section 1
  ("vendored"); if it is acknowledged at all it follows the USEARCH precedent
  in section 2 — obtained at install time, not in the tree.
- **No upstream URL in a committed file** until the repo is public. The
  installer reads `BINDCRAFT2_SOURCE` (a zip, a directory, or later a git URL).
  This also means the `_TOOL_LINKS` defect is fixed by **removing** the
  `bindcraft2` entry so the tool renders unlinked — not by substituting a URL.
- **No patch files, and no edits to their source.** A unified diff embeds it,
  and the licence requires a prominent modification notice inside any modified
  copy. Every fix in this plan is expressed through documented *settings*, so
  nothing is modified and the notice never becomes due.
- **No preset values copied.** Modality and property *identifiers* are
  interface facts and may be named (the licence permits accurate
  compatibility statements); their tuned numeric contents may not be
  reproduced in our config generator.
- **No BindCraft 2 prose, images or logo** pasted into our docs.

Even after the embargo lifts, **clone, never vendor** — BinderScout's root
licence is MIT and BindCraft 2 is source-available and non-OSI.

## Where it fits in the pipeline

An eighth design tool, immediately after `bindcraft` in the three ordered
registries that need a new entry:

| Registry | File | Status |
|---|---|---|
| `TOOL_SEQUENCE` (4-tuples) | `configurator/configurator.py:173` | needs entry |
| `TOOL_SEQUENCE` (3-tuples) | `tui/app.py:35` | needs entry |
| `TOOL_FLAGS` | `Evaluator/binder_comparison/cli/_tool_args.py:20` | needs entry |
| `CANONICAL_TOOL_ORDER` | `comparison/candidates.py:97` | already present (`407aa27`, in this branch's ancestry) |

```
  Mosaic · BoltzGen · BindCraft · BindCraft 2 · PXDesign
  Proteina-Complexa · Protein-Hunter · RFD3
      ↓
  Evaluator: extract → SoluProt → Boltz-2 → AF3 → ESMFold2 → rank → report
```

It changes nothing about evaluation. BindCraft 2 optimises AF2-multimer
i_pTM during hallucination and validates with held-out AF2 models, so **its
confidence is design-time-biased exactly as BindCraft 1's is**, and its
internal validation is still AF2-family — not an independent engine. Its
metrics are a native block only; they never enter `consensus_iptm_mean`, and
its designs pass the same ≥3-engine gate as everything else.

## Architecture

### Environment — BindCraft 2's own `.venv`, created by us

```
BindCraft2/          ← staged from the lab-share zip, gitignored
  .venv/             ← WE create it with uv, then hand BC2 its interpreter
  bindcraft/         ← installed EDITABLE: the clone is the installation
```

It cannot share an environment with anything we have: it needs `jax>=0.11,<0.12`
while Mosaic is on 0.9.2, and it installs editable so the directory must be
permanent.

**Our installer creates `.venv` itself and passes `BINDCRAFT_PYTHON`.** Left to
itself, BindCraft 2's `install.sh` installs into whatever environment is
already active whenever `CONDA_PREFIX` or `VIRTUAL_ENV` is set — and our own
installer activates conda for almost everything. That would put `jax>=0.11`
into an unrelated env and leave no `.venv` for `detect_installs()` to find.
Creating the venv ourselves also removes upstream's conda fallback path, so
`BindCraft2/.venv/bin/python` is the one true detection marker. Invoke with
`env -u CONDA_PREFIX -u VIRTUAL_ENV` as well, belt and braces.

**Do not reuse, upgrade or repoint the `BindCraft` conda env.** `binder-compare
affinity` and `qc-annotate` run PyRosetta through `conda run -n BindCraft`;
breaking it silently breaks Part N.

### Install

`install_bindcraft2()` in `install/install.sh`:

1. Resolve `BINDCRAFT2_SOURCE` (zip → extract; directory → copy; git URL →
   clone at `BINDCRAFT2_COMMIT`). **Unresolvable under `--tool all`: warn and
   skip, exit 0.** Unresolvable under an explicit `--tool bindcraft2`: fail
   with an instruction. Without that split, `--tool all` breaks CI and the
   Docker build on every machine without the lab share.
2. Stage to `BindCraft2/`, stripping `__MACOSX/` and `.DS_Store`.
3. Resolve AF2 parameters in this order, and export the first that exists:
   `$BINDCRAFT2_AF2_PARAMS` → `BindCraft/params/` → the machine's existing AF2
   cache (`bindcraft-tools/af2_params`) → **none found: drop `--no-weights`**
   and let BindCraft 2 fetch its own 5.3 GB. BindCraft 1 is aarch64-blocked, so
   `BindCraft/params/` will not exist on Spark, and BindCraft 2's own selfcheck
   *exits 1* rather than warning when `--no-weights` was passed with no params
   — making this chain load-bearing, not a nicety. On BM5 today the
   `bindcraft-tools` cache holds all seven required checkpoints.
4. `env -u CONDA_PREFIX -u VIRTUAL_ENV BINDCRAFT_PYTHON=BindCraft2/.venv/bin/python
   bash install.sh [accelerator] [--no-weights]`.
   **Omit the accelerator argument** unless `BINDCRAFT2_ACCELERATOR` is set:
   BindCraft 2 reads the driver's CUDA version and already downgrades to
   `cuda12` for any card below compute capability 7.5. Deriving it from our
   `CUDA_VERSION` would be wrong — that variable is a pip wheel-index version,
   not a driver version — and passing it explicitly bypasses the downgrade.
5. Smoke test with `BindCraft2/.venv/bin/bindcraft --help`, then
   `BindCraft2/.venv/bin/python -c "import jax; ..."`. A non-GPU backend
   **fails the install on x86** and **warns on aarch64**, where GPU
   initialisation is the open question slice 7 exists to answer.
6. Shortcut `bin/bindcraft2`, uninstall arm, `--tool all` membership on x86.

Disk: upstream quotes ~20 GB, of which roughly half is the AlphaFold parameter
archive plus its unpacked copy — reusing an existing cache removes that. The
"~60 GB free" figure in `CLAUDE.md` needs revisiting either way.

### aarch64 / Spark — the crash, and the two settings that avoid it

`design_gpu_memory_gb()` calls `float()` on `nvidia-smi`'s card-level memory
reading and catches only `OSError` / `CalledProcessError`. GB10 returns
`[N/A]` for that query — our documented Spark quirk — so it raises
`ValueError`. Reproduced live on BM5 during this investigation.

**It has two call sites, and one setting only covers one of them.**
`auto_multi_gpu: false` short-circuits the worker fan-out, but the campaign
then reaches `campaign_subbatch_size`, which probes card memory again whenever
`subbatch_size` is at its shipped default of `"auto"`. Both must be set:

```json
{ "auto_multi_gpu": false, "subbatch_size": null }
```

(`null` disables subbatching; an integer chunks instead. Upstream's own auto
rule is 4 above 384 residues.) Neither needs a patch.

**The guard is applied at launch time, not configure time.** In this lab
configs are generated on BM5 (aarch64) and frequently *run* on BM1/BM2/BM4
(x86). Writing the key at configure time would disable multi-GPU packing on
x86 whenever BM5 generated the config, and would still crash on Spark whenever
an x86 box generated it. So the generated `run_bindcraft2.sh` inspects
`uname -m` on the **executing** host and injects the two keys only on aarch64.

Ship it **opt-in, not in `--tool all`** on aarch64, the same posture RFD3
has.

**The aarch64 unknowns are now answered** (measured on BM5, ahead of slice 7):
`jax-cuda13` 0.11.1 initialises sm_121 and reports `backend: gpu` with
`CudaDevice(id=0)`; `biotraj` 1.2.2 — the one source build in the tree —
compiles; the install completes and the CLI runs. With the two guard settings a
campaign runs to completion. What remains for slice 7 is only the throughput
question, and the first measurement is not encouraging (see Notes). It joins
BindCraft 1 there rather than replacing it — that tool also runs on Spark, which
an earlier draft of this plan got wrong.

### Per-worker memory, and what a 24 GB card actually holds

Per-worker budget is roughly `2 × (3.4 GB + 38 kB × N²)` with 4 GB subtracted
as headroom first — about 11.8 GB at 256 residues and 26.7 GB at 512. On a
24 GB 3090 that is **one** worker at 256 residues, not two: two would need
~27.6 GB free.

Past ~512 residues BindCraft 2 **does not refuse** — it floors the plan at one
worker per card, runs single-process and OOMs at prediction time. The wizard's
length guidance must say so, because nothing upstream catches it.

### Configurator

`write_run_bindcraft2()` emits two files:

- `runs/<name>/bindcraft2/campaign.json` — our own campaign file.
- `runs/<name>/run_bindcraft2.sh` from a new
  `binderscout_examples/run_bindcraft2.sh.template`, carrying the mandatory
  `settings.json` provenance block **before** the design step, per the per-run
  convention in `CLAUDE.md`.

**Write every path absolute.** Only two campaign-JSON keys are re-based
against the JSON's own directory (`targets[].target_path` and
`binder_scaffold`, and only before `--set` overrides are applied).
`project_folder` is never re-based and resolves against the caller's cwd, so
a relative value would nest.

Campaign settings the wizard writes:

| Key | Handling |
|---|---|
| `modality` | **Always written explicitly.** No modality layer is applied when none is named — the CLI help's "(default: binder)" is misleading. Worse, the resulting null `binder_lengths` surfaces as a raw `TypeError` traceback rather than a clean refusal. Wizard default `binder`. |
| `binder_lengths` | Written for `binder` / `large_binder` / `peptide`; **omitted for every scaffolded modality** (see table below) — the scaffold sets the length. `large_binder` requires it. |
| `max_trajectories` | **Prompted every time**, with an explicit warning that leaving it unset lets the campaign run unbounded. Unbounded remains selectable (it is upstream's own default), but it must be a deliberate choice, never a forgotten prompt. |
| `number_of_final_designs` | Prompted; labelled as an *accepted-design quota*, not an attempt count. |
| `targets[].hotspots` | Maps 1:1 onto our existing hotspot prompts; same `A54,A56,B12-16` syntax. |
| `project_folder` | Absolute path to `runs/<name>/bindcraft2`. |
| `resume` | Left on (upstream default), so a budget-exhausted or killed run continues on relaunch. **Each parameter set gets its own versioned `project_folder`** (`bindcraft2/`, `bindcraft2_v2/`) — that is how resume and our supersede-vs-extend convention coexist without two parameter sets sharing one directory and overwriting each other's `settings.json`. |
| `core` | Prompt `Reproducible run (fixes the seed, disables autotuning and the desperation ladder)? [Y/n]`, default **yes** → writes `core: benchmark`. Answering no omits the key entirely. `benchmark` is the only selectable profile. Mandatory for any A/B comparison — the desperation ladder silently loosens validation after 750 fruitless trajectories and stamps an `autotuned` column when it does. |
| `auto_multi_gpu`, `subbatch_size` | Not written by the wizard — injected by the run script on aarch64 hosts only (see above). |

Wizard scope is **the de novo formats only**. Full identifier set, so the counts
are checkable and the `--config` path has a contract:

| Modality | Wizard | Scaffolded (omit `binder_lengths`) |
|---|---|---|
| `binder` | ✅ default | |
| `large_binder` | ✅ | |
| `peptide` | ✅ | |
| `VHH` | | ✅ |
| `cyclic_peptide` | | |
| `homo_oligomer` | | |
| `multidomain` | | |
| `ARP` | | ✅ |
| `scFv` | | ✅ |
| `Fab` | | ✅ |
| `induced_fit` | | |
| `fold_switch` | | |

Properties — `forced_targeting`, `humanize`, `termini_accessible` in the
wizard; `bigbang`, `disulfide_staple`, `initial_guess`, `mixed_topology`,
`protease_stable`, `termini_together` via `--config`. So: 12 modalities, 3
exposed, 9 via `--config`; 9 properties, 3 exposed, 6 via `--config`.

**The scaffolded antibody formats are out of the wizard deliberately**, not by
omission: `VHH`, `scFv` and `Fab` all belong to the separate nano effort, which
is where antibody-format design and its scoring will be dealt with together.
(`ARP` is an ankyrin-repeat scaffold rather than an antibody fragment, but it is
scaffolded and equally unexercised here, so it sits on the same side of the
line.)

For VHH there is a measured reason on top of the scope one: our ranking cannot
score nanobodies at all — a validated 6.8 nM VHH scores 0.21 through it, with no
binder/non-binder separation for the class — so a wizard-driven VHH campaign
would produce a pool the report cannot rank. **That evidence is specific to
nanobodies and is not assumed to carry to `scFv` or `Fab`**; those are deferred
on scope, not on measurement.

All four stay reachable through `--config`, and the scaffolded set still
suppresses `binder_lengths` on that path, so no capability is removed — only the
invitation.

Wizard-side conflict validation (so a bad combination is caught before a run
script is written): scaffold ↔ {cyclize, `copies`>1, fold_switch,
mixed_topology}; `copies`>1 ↔ multidomain; FASTA target ↔ {forced_targeting,
coldspots}; induced_fit ↔ any detarget target.

Run-script environment: export the resolved `BINDCRAFT_AF2_PARAMS`, and set
`JAX_COMPILATION_CACHE_DIR` to a **per-machine, per-card** path —
`$HOME/.cache/binderscout/bc2_xla/<sanitised card name>`.

Measured, not assumed: left unset, `use_campaign_compile_cache` puts the cache
at `<project_folder>/compile_cache/<card>`, which is **per campaign**, so every
new run re-pays ~60 s per prediction shape from cold. Observed directly on the
first calibration run, which reported
`compiled graphs cached in .../out_noguard/compile_cache/NVIDIA_GB10`.

But an operator-set `JAX_COMPILATION_CACHE_DIR` is returned **verbatim, with no
per-card subdirectory appended** — the function short-circuits on it before the
card is ever consulted. A compiled executable is not portable across GPU
models, so *we* must add the card segment ourselves, matching BindCraft 2's own
sanitisation (non-alphanumeric runs collapse to `_`, then strip leading and
trailing `_`; `NVIDIA GB10` → `NVIDIA_GB10`). Getting this wrong on a mixed-GPU
host silently feeds one card's executables to another.

Do not re-export BindCraft 2's `XLA_*` variables —
it sets `XLA_PYTHON_CLIENT_PREALLOCATE` and appends its own `XLA_FLAGS`.
Separately, never export an **empty** `BINDCRAFT_*` override: an exported-but-
empty variable counts as a value and fails on `int('')` rather than falling
back.

Because there is no in-package wall-clock bound, the run script wraps the
campaign in `timeout` when a wall clock is supplied, and uses Slurm `--time`
on Clara (with `--mem-per-gpu`, per the standing rule).

### Extractor — dual schema

`Evaluator/binder_comparison/extractors/bindcraft2.py`. Resolution: **probe the
patterns in order and let the first pattern that matches win; within a single
pattern, more than one match is an error** via the existing
`resolve_single_match()`.

```
1.  3_Ranked/!_Ranked.csv      v1.0.0 layout
2.  ranked.csv                 pre-1.0 flat layout
3.  <target>_ranked.csv        pre-1.0, as delivered to us
```

**Never resolve to `accepted.csv`, `ranked_by_*.csv` or `filtered.csv`.**
`accepted.csv` is the append-only unranked table and has no `rank` column at
all; `ranked_by_*.csv` is a user re-sort on a different metric;
`filtered.csv` is a post-filter. Any of them would silently violate the
native-rank rule. The same exclusions belong in the `discover_tool_csvs.py`
globs, where a naive `*ranked*.csv` would match `ranked_by_*.csv`.

Identity alias map:

| Field | v1.0.0 | pre-1.0 |
|---|---|---|
| sequence | `Binder_Sequence` | `Sequence` |
| design id | `design` | `Design` |
| native rank | `rank` | `Rank` |
| target names | `targets` | `Targets` |
| target weights | `target_weights` | `Target_Weights` |

Native metrics — the columns that **keep the same spelling in both schemas**,
ingested as typed `bindcraft2_*` fields:

`i_pDAE` (→ `bindcraft2_ipdae`, 0–1, **higher better**, the native rank key),
`i_pTM`, `pTM`, `pLDDT`, `i_pAE`, `Target_pLDDT`, `SS_pLDDT`,
`Backbone_Clashes`, `Interface_Residues`, `Interface_BuriedArea`,
`Interface_Hydrophobicity`, `Surface_Hydrophobicity`, `Binder_RMSD`,
`Target_RMSD`.

Columns that were **renamed and rescaled** between schemas are normalised to
0–1 on ingest or they must not share a field: `Binder_Helix%` /
`Binder_BetaSheet%` / `Binder_Loop%` / `Interface_BuriedArea%` /
`Hotspot_Contact%` (pre-1.0, 0–100) became `*_Fraction` (v1.0.0, 0–1).

Rules the extractor must hold to:

- **Native rank from the tool's raw file.** Sort by the rank column ascending,
  assert the result equals `1..N`, and abort naming the file and the offending
  values if not. File order is then rank order by construction. Do **not**
  assert monotonic `i_pDAE` — ties are pervasive.
- `binder_id = f"bindcraft2_{design}"` — the ID every existing downstream
  artifact for the delivered pools already keys on.
- **Refuse a multi-target export by reading the targets column** and splitting
  it on `;`, refusing when more than one name results. Do **not** scan all
  cells for `;`: the free-text `Notes` column legitimately contains semicolons
  in both delivered files, and a whole-row check would reject both.
- **Refuse a multi-chain binder** (`/` in the sequence). This is a deliberate
  divergence from upstream, which simply strips the separator — we refuse
  because a single-chain refold of a concatenated multi-chain binder is wrong.
- Never extract from `1_Trajectories/!_Trajectories.csv`: its `Binder_Sequence`
  is the pre-ProteinMPNN hallucinated sequence. Never extract
  `outcome == 'rejected'` rows from `2_Refolded/!_Refolded.csv`.
- Tolerate a campaign-dependent column set. The delivered CBG export has 62
  columns and CALCA 60 — a metric column only exists if the campaign set a
  threshold for it. Every native read is optional.
- **Parse with a real CSV reader.** The files are CRLF, may lack a trailing
  newline, and five columns carry quoted commas — one holds a Python dict
  literal. A naive `split(',')` yields 149 fields against a 62-column header.
- Strip/upper the sequence, skip `NaN` before `str()`, and call
  `disambiguate_ids()` before returning — the four ingestion invariants from
  the F44 hardening.

Scale traps for the docstring: `pLDDT` and `i_pTM` are **already 0–1** (no
rescale, unlike AF3); `Binder_pLDDT` is **0–100** and is also upstream's
ranking fallback when `i_pDAE` is absent; `i_pAE` is PAE ÷ 31 Å, not Ångströms;
mmCIF B-factors are 0–100.

Structure lookup caveat: v1.0.0 writes `3_Ranked/<design>_seq<n>.cif`, but the
**delivered** archives are `<Rank>_<Design>.cif` under folders that do not even
agree with each other (`CBG_ranked/` vs `CALCA_binders/`). `binder_id` will not
join to the archived structures without a rank-prefix-aware resolver, so
structure-consuming steps find nothing on those two pools. Recorded, not fixed
here.

### Report — re-add the registration, without the first attempt's three defects

Slice 1 reverts `407aa27` off master, so the thirteen per-tool lookups lose
their `bindcraft2` key entirely and 1.0.0 ships clean. Slice 8 puts it back on
the 1.1.0 line — this time without the three defects the first attempt carried,
each verified present in the shipped CALCA report before the revert:

1. `.tool-bindcraft2` was emitted nine times in the HTML with **no CSS rule
   defined**. Add the rule.
2. `tool_classification.py` — `native_metric_interpretation` claimed a
   "composite Rank" (it is a plain `i_pDAE` sort) and `source_csv_default` was
   `<target>_ranked.csv` alone. Name `i_pDAE` as the rank key and both accepted
   layouts.
3. `_TOOL_LINKS["bindcraft2"]` pointed at BindCraft 1's repository. **Do not
   re-add the entry at all** — the tool renders unlinked, since substituting
   the real URL is forbidden while the repo is pre-publication.

Also: `pool_pre_filtered_default` is `False`, but the delivered pools are
pre-ranked top-50 slices of 200–300-design campaigns, so their metric means
are not comparable to an unfiltered pool. Make it settable per run.

Plus a **registry-completeness test** asserting every key in
`CANONICAL_TOOL_ORDER` appears in all thirteen per-tool lookups *and* has a
`.tool-<key>` CSS rule:

| # | Module | Symbol |
|---|---|---|
| 1–2 | `comparison/candidates.py` | `TOOL_DISPLAY_NAMES`, `CANONICAL_TOOL_ORDER` |
| 3 | `comparison/hits.py` | `TOOL_CODE_SLUGS` |
| 4 | `comparison/tool_classification.py` | `TOOL_CLASSIFICATION` |
| 5 | `core/schema.py` | `SourceTool` |
| 6–8 | `visualization/plots.py` | `TOOL_COLOURS`, `_TOOL_DISPLAY`, `_ENGINE_BAR_LABEL` |
| 9–10 | `visualization/report.py` | `_TOOL_LINKS`, `_TOOL_COLOURS_NGL` |
| 11 | `visualization/top30_slim.py` | `_TOOLCOL` |
| 12–13 | `cli/report.py` | `_TOOL_COLOURS_PYMOL`, `_TOOL_DISPLAY_PYMOL` |
| + | `visualization/report.py` | `.tool-<key>` rules in `_HTML_TEMPLATE` |

(`_TOOL_LINKS` is the one exemption, since `bindcraft2` is deliberately left
out of it while upstream is pre-publication — the test must allow that and say
why, so the exemption is visible rather than looking like the same omission
that produced defect 1.)

Finally, a `_seq\d+$` collapse rule in `scoring.py` so sibling sequences from
one backbone share a `design_group`. It is **inferred from the ID shape**, not
from observed siblings — both delivered pools are pre-collapsed top-50 exports
where every backbone hash appears once, and BindCraft 2's default keeps one
sequence per trajectory. Confirm it against a full campaign (slice 4); until
then it is inert.

## Versioning

> **Nothing in this plan touches `master`.** Master is frozen as
> **BinderScout 1.0.0** — no cherry-pick, no revert, no tag, no commit. All
> work happens on `eight_tool`, which becomes **1.1.0**.

**One thing to state honestly rather than claim otherwise.** `407aa27`
("Register bindcraft2 as a first-class tool in the report") was pushed to
`origin/master` on 2026-09-16 and touches eight files in `Evaluator/`. Because
master is frozen, **1.0.0 does contain that registration** — a `bindcraft2`
key in thirteen per-tool lookups, with no extractor, no installer and no way
to produce a bindcraft2 design. It is inert: a pool without `bindcraft2` rows
renders byte-identically, which is what that commit's own message claims and
what makes freezing it harmless.

It is not, however, defect-free (see the Report section), so nothing downstream
should treat 1.0.0's registration as authoritative. Every correction lands on
the 1.1.0 line.

Branch topology:

```
master ──── frozen at 1.0.0, contains the dormant registration
   └── eight_tool ──── 1.1.0: everything in this plan
```

`eight_tool` already descends from `407aa27`, so the registration is **present
and corrected in place** (slice 8) rather than re-added. `c5c7dcc` (the
ESMFold2 revision pin) is likewise already in this branch's ancestry and simply
ships in 1.1.0.

Version mechanics:

All of these land on `eight_tool`:

- `CHANGELOG.md` — master's `[Unreleased]` body is retitled
  `## [1.0.0] — 2026-09-17` **on this branch only**, recording what master
  already shipped, and a fresh `[Unreleased]` opens above it for 1.1.0. Master's
  own CHANGELOG is left alone.
- `binderscout.__version__ = "1.1.0"` is the **product** version — the repo has
  had no version constant at all — surfaced as `binderscout --version` beside
  the existing `--help` branch, and consumed by every run's `settings.json`
  provenance block.
- `binder-comparison` keeps **independent** SemVer. Its three unlinked `0.1.0`
  literals (`Evaluator/pyproject.toml`, `binder_comparison/__init__.py`,
  `binder_comparison/main.py`) are collapsed into one: the package version is
  declared in `pyproject.toml` and the other two read
  `importlib.metadata.version("binder-comparison")`. It stays `0.1.0`;
  `binderscout --version` and `binder-compare --version` legitimately differ,
  and the docs say so.
- The prose `v0.7.0` markers in `CLAUDE.md`, `docs/completed_plans.md` and
  four skill reference files become `1.1.0`.
- `REFOLD_CODE_TOKEN = "BinderScout"` is **not** touched — historical design
  codes like `CALCA-BinderScout-16` parse against it. Nor is
  `binder-compare hits --version`, which stays a free-text operator field.

**Tagging is deferred.** No tag is created while master is frozen and this
branch is unmerged; `v1.1.0` is cut when `eight_tool` lands, which is a
separate decision outside this plan.

## Acceptance criteria

1. `binderscout --version` prints `1.1.0` on `eight_tool`, and every generated
   run's `settings.json` records it. Master is untouched: `origin/master`
   still points at `60115d0` when this branch is done, and no commit on it is
   authored by this work. (Local `master` is two commits stale and stays that
   way — it is not fast-forwarded either.)
2. `binderscout install --tool bindcraft2 --yes` succeeds on x86 and is
   idempotent on a second run; `--uninstall --tool bindcraft2 --yes` leaves
   `runs/` intact; and `--tool all` on a machine with no `BINDCRAFT2_SOURCE`
   warns, skips BindCraft 2, and exits 0.
3. A shipped-example campaign completes end-to-end and writes a non-empty
   `3_Ranked/!_Ranked.csv` with matching mmCIF structures. Its
   trajectories-per-accepted-design ratio and wall clock are recorded — nothing
   upstream quantifies either.
4. `binderscout configure` generates a `run_bindcraft2.sh` that passes
   `tests/configurator/test_settings_json_convention.py`, and a `campaign.json`
   from which a campaign reaches trajectory 1 and is then cancelled.
5. The extractor parses **both** real delivered files — CBG (62 columns, with
   `Target_RMSD` and `Hotspot_Contact%`) and CALCA (60 columns, without) —
   preserving `Rank` 1..50, yielding 50 unique `binder_id`s each, and emitting
   `native_bindcraft2_ipdae` for all 50 rows of each into
   `sequences_native_metrics.csv`. Neither file is rejected by the multi-target
   or multi-chain guard.
6. A regenerated BC2 report has no unmatched `.tool-*` class, names BindCraft 2's
   native metric as `i_pDAE`, and renders the tool name without a link.
7. `git status` is clean of BindCraft 2 source after install;
   `git check-ignore -v BindCraft2/` confirms the ignore. No BindCraft 2
   *source file* is ever tracked on any branch — only our own code that talks
   to it.
8. `ruff check`, `ruff format --check`, `shellcheck` over the CI file list, and
   `pytest` pass **at every slice boundary** — the tool-count assertions are
   updated in the same commit that first changes the count.
9. Either (a) a Spark campaign completes and BindCraft 2 joins `--tool all` on
   aarch64, or (b) `docs/PLAN_bindcraft2_integration.md` records the reproduced
   failure with the exact command, traceback and `nvidia-smi` output, and the
   aarch64 arm stays opt-in.
10. `CLAUDE.md` says "eight", lists BindCraft 2 in the tool and environment
    tables, and carries the sentence distinguishing BindCraft 2 (a design tool)
    from BindMaster 2 (`docs/bindmaster2_grafts.md`).

## Decisions already taken

| Decision | Choice |
|---|---|
| Source distribution | Staged from the lab share into a gitignored `BindCraft2/`; `BINDCRAFT2_SOURCE` accepts zip, directory or (later) git URL |
| BindCraft 1 | Coexists; BindCraft 2 is tool #8 |
| Master | **Frozen at 1.0.0 — nothing touches it.** No cherry-pick, no revert, no tag, no commit |
| This work | All on `eight_tool`, which becomes 1.1.0; `__version__` introduced there; tagging deferred until merge |
| 1.0.0 contents | Includes the dormant `bindcraft2` registration from `407aa27`, already published. Inert, but not defect-free — corrected on the 1.1.0 line, never back-fitted into 1.0.0 |
| Platforms | x86 in `--tool all`; aarch64 opt-in pending a Spark validation run |
| Environment | `BindCraft2/.venv`, created by our installer, not a conda env |
| Trajectory budget | Prompted every time, with a warning; unbounded stays selectable |
| Extractor schema | Both layouts, via an explicit column-alias map |
| Wizard scope | De novo core + VHH; the other 8 modalities and 6 properties via `--config` |
| aarch64 guard | Injected by the run script from `uname -m` at launch, not baked in at configure time |
| Tool link | `bindcraft2` removed from `_TOOL_LINKS` while upstream is pre-publication |

## Out of scope for the first cut

- The eight modalities and six properties not in the wizard (reachable via
  `--config`).
- Multi-target campaigns — refused with a clear message rather than parsed.
- Multi-chain binders — refused rather than concatenated.
- A rank-prefix-aware structure resolver for the two delivered archives.
- Harvesting `2_Refolded/!_Refolded.csv` (roughly 10× more already-validated
  sequences that BindCraft 2 discards). An `--all-bindcraft2-designs` flag
  analogous to `--all-mosaic-designs` is a later campaign-strategy decision.
- A CIF-fallback extractor path. Every delivered mmCIF embeds the full record,
  so the pool is reconstructable from structures alone — worth having, but not
  needed while the raw CSVs are archived.
- Invoking `bindcraft rank` / `bindcraft filter` for pool triage.
- Finishing the BinderScout → BinderScout rename.

## Implementation slices

Each slice is one commit, **green at its own boundary**. The ordering below is
deliberate: the extractor's CLI flag lands before the configurator emits it,
and the campaign-JSON writer lands before the Spark validation that needs it.

1. **Open 1.1.0 on `eight_tool`** — `binderscout.__version__ = "1.1.0"`,
   `binderscout --version`, Evaluator version collapse, CHANGELOG retitle plus a
   fresh `[Unreleased]`, v0.7.0 prose markers. Master untouched.
2. **Ignore and stage** — `.gitignore` + `.dockerignore` for `BindCraft2/`;
   `BINDCRAFT2_SOURCE` resolution helper; verify nothing is tracked.
3. **Installer (x86)** — `install_bindcraft2()`, AF2-params fallback chain,
   uninstall arm, flags, help, menu, preflight estimate, `tui/app.py`
   `TOOL_SEQUENCE` entry, **and the `tests/tui/` tool-count update in the same
   commit**. Shellcheck; add any new script to the CI file list.
4. **Example run** — shipped example campaign on x86. Record wall clock and
   accepted-per-trajectory yield; confirm whether `_seq<n>` siblings occur.
5. **Extractor** — `bindcraft2.py` dual-schema, `_tool_args.py`, `extract.py`,
   `NativeMetrics.bindcraft2_*`, `discover_tool_csvs.py` globs (excluding
   `ranked_by_*` / `filtered` / `accepted`), `scoring.py` collapse, fixtures cut
   from the real CBG and CALCA exports, **and the
   `tests/binder_comparison/test_cli_tool_args.py` count update**.
6. **Configurator** — `TOOL_SEQUENCE`, `REQUIRED_CFG_KEYS`, `detect_installs`
   (one key spelling across all four), Step 5/6h/7 prompts, conflict
   validation, `write_run_bindcraft2`, campaign.json writer,
   `run_bindcraft2.sh.template` with the `uname -m` guard, `--bindcraft2` in
   `write_run_evaluate`, `cmd_status` probe, **and the
   `tests/configurator/` count and `_WRITERS` updates**.
7. **Installer (aarch64) + Spark validation** — opt-in arm, a campaign
   generated by slice 6, go/no-go on `--tool all`, and criterion 9's artifact
   either way.
8. **Report registration (re-added, corrected)** — the thirteen per-tool
   lookups minus `_TOOL_LINKS`, the `.tool-bindcraft2` CSS rule, `i_pDAE` named
   as the rank key, both layouts in `source_csv_default`, per-run
   `pool_pre_filtered`, registry-completeness test.
9. **Docs and skills** — `CLAUDE.md`, `README.md`, `CONTRIBUTING.md`,
   `Evaluator/docs/pipeline_reference.md`, orchestrator / worker / evaluator
   skill trees, and the BindCraft 2 vs BindMaster 2 disambiguation.
10. **Close 1.1.0** — final CHANGELOG entry. Tagging and the merge to master
    are a separate decision, taken when this branch lands.

## Notes recorded during investigation

- The only copy of the raw delivered exports (`CBG_ranked.csv`,
  `CALCA_ranked.csv`) was in a temporary scratchpad — `bc2_archive.sh` archived
  the structures but never the ranked CSVs. Both, plus the 50 as-delivered
  mmCIFs per target and a provenance README, are now archived under each
  target's `RAW/bindcraft2_2026-09-16_bindcraft2/native_ranked_csv/`.
- Upstream's only published timing is a 40-trajectory campaign on a GH200:
  3620 s at one worker, 2021 s at seven. Modality, binder length and target
  size are unstated, so it does not transfer to an RTX 3090 or to a large
  target.

- **Measured head-to-head (slices 4 and 7).** Same campaign both sides: shipped
  hPDL1 target (115 residues), `binder` modality, `binder_lengths` [60,60],
  `max_trajectories` 2, `core: benchmark`.

  | | per trajectory | design workers | 2 trajectories | peak RSS |
  |---|---|---|---|---|
  | BM5 — GB10, aarch64 | 343 s warm, 413 s cold | **1** (guard disables fan-out) | 14 m 44 s | 5.9 GB |
  | BM1 — RTX 3090, x86 | 328 s / 339 s cold | **2** packed @ 9.6 GB | 7 m 26 s | 5.4 GB |

  **Per trajectory the two platforms are equal.** The GB10 is not slow: 343 s
  against 328 s is noise. The entire 2× throughput gap is worker fan-out — the
  3090 packs two workers on one card, the GB10 runs one, because the guard that
  avoids the `[N/A]` crash sets `auto_multi_gpu: false` and that is what fan-out
  is gated on.

  This corrects an earlier claim in this plan, which read total wall clock over
  two trajectories including a cold compile as "~7.4 min per trajectory" and
  then compared it to upstream's ~90 s GH200 figure to conclude that aarch64 is
  slow. Both halves were wrong: the real figure is ~5.7 min, our x86 box is
  ~5.5 min, and neither is near 90 s — that number belongs to a much larger
  card, not to x86 versus aarch64.

  **Follow-up worth taking.** The fan-out loss is ours to recover, and the prize
  is larger on Spark than anywhere else: 121 GB of unified memory could hold far
  more than the two workers a 24 GB card fits. It is not reachable today —
  `plan_design_workers` probes card memory *unconditionally*, before
  `BINDCRAFT_DESIGN_WORKERS` or `workers_per_gpu` is consulted, so every route to
  fan-out runs through the call that raises on `[N/A]`. The only openings are a
  change upstream, or presenting a corrected `nvidia-smi` to that process. The
  second is environment rather than source, so it stays inside this plan's
  no-patching rule, but it redirects every other memory query in the tree and
  should not be done casually.

- **The v1.0.0 output tree is exactly as this plan predicted**, confirmed
  against that campaign: `3_Ranked/!_Ranked.csv` with lowercase
  `rank`/`design`/`Binder_Sequence`, `i_pDAE` leading the confidence block,
  accepted structures as `<design>_seq<n>.cif` with a 0-based index, and
  `1_Trajectories/` / `2_Refolded/{Complexes,BinderMonomer}/` beside it. Its
  own closing line reads `campaign done: … ranked by i_pDAE`.
- The delivered pre-1.0 modality value is `miniprotein`, which v1.0.0 does not
  ship. The schema divergence extends to settings *values*, not only column
  names — relevant if we ever replay a delivered campaign's settings.
