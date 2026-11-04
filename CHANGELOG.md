# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

> **Note on paths in older entries.** On 2026-10-27 a set of internal lab documents —
> both repository diaries, the `docs/PLAN_*` / `docs/INVESTIGATION_*` planning records,
> `docs/completed_plans.md`, `docs/plans.md`, the two skill deploy playbooks and the
> `tools/fleet.sh` fleet driver — was removed from this repository and archived off-repo
> on the lab share. Entries below still name them, because they record what happened at
> the time; those paths no longer resolve in the tree.

## [Unreleased]

### Fixed

_Nothing yet._

## [2.0.3] — 2026-11-03

Work since `v2.0.2` (137 commits). Nothing here changes the ranking:
`rank` is still the cross-engine gate then `consensus_iptm_mean`, computed exactly as before.

### Behaviour changes you may notice

- **A transplanted pool's structure files are found again, and a remap is announced.** Refold CSVs
  record absolute paths, so a pool reported under another account lost the 3D viewer,
  `top20_structures/` and `view_top20.pml` with exit 0. Structure columns are now resolved against
  each engine's CSV directory (as the PAE columns already were), with one `[structure]` warning per
  column for what is still missing. The remap is **bounded at the engine's own directory**
  (`refold_boltz2` / `refold_af3` / `refold_esmfold2`) and never falls to a bare file name, because
  export names carry no per-run id and an unbounded strip could bind a design to another run's
  same-named file; each column also gets one informational warning saying how many cells were
  `REMAPPED` and which leading prefix was dropped.
- **A refold `--resume` now re-runs blank rows.** A design whose previous row had every metric empty
  (the shape a per-design CUDA OOM leaves behind) used to count as finished, so a retry skipped
  exactly the designs it existed to repair and exited 0. Resume now keys on the binder **sequence**
  and on a non-empty score, for all three engines, and says how many blank rows it is re-running.
- **Merging refold CSVs from different targets is refused.** Engine CSVs whose `target_sequence`
  disagree can no longer merge into one design with `consensus_iptm_n = 3`.
- **A PAE matrix that cannot be what it claims is refused with a named warning, and scores NaN:**
  non-square, non-finite, wrongly sized for `binder_length + target`, or an all-zero interface.
  A one-residue `binder_length` error used to inflate ipTM by up to +0.31 and an all-zero interface
  scored 1.0. Non-finite input now gives NaN rather than `ipsae 0.0` / "Reject".
- **`--json` is pure JSON.** Shortcut notices and the dispatcher banner go to **stderr**; on a fresh
  clone the first `binderscout status --json` used to fail to parse at character 0.
- **`binderscout install --verify` reports tools built against another commit as `STALE`** (still
  usable, so the exit status is unchanged). `--repair --stale` rebuilds them; plain `--repair` does not,
  because one pull of a tool's repository would otherwise mark every tool stale at once.
- **Headless `--config` files are stricter.** An unrecognised key is fatal before anything is written
  (with up to three near-miss suggestions) instead of silently falling back to a default; a run
  folder that is an existing *file* is refused; an enabled tool with no script writer is refused.
- **Generated runs target what you asked for.** Hotspots are no longer replicated onto every target
  chain, RFD3/RFD4 contigs preserve every targeted chain, and tools given a target *sequence* get
  every chain, not the first (see Fixed). A pMHC-style multi-chain target is the case that exposed it.
- **The BoltzGen pool size follows the requested count** (floor 50) instead of a flat 10 000, and
  generation prints the implied cost in hours. A "1 design" smoke test used to run for ~15 hours.
- **`run_all.sh` runs Mosaic** (it used to print "SKIPPED" and run 8 of 9 tools).
- **The `binderscout` shortcut does not exist on a fresh clone**, so the quick start now begins with
  `./binderscout.py install`. A tool is reported `installed` only when the installer's own marker
  exists as well as its probe; checkouts that predate the markers keep working untouched.

### Added

- **`--save-pae-bins` on `refold-boltz2` and `refold-esmfold2`** (opt-in, default off, **not
  validated on a GPU yet**). Stores each design's per-pair PAE bin probabilities as
  `<design>_pae_bins.npz` (about 11.5 MB per design before compression for a 300-token complex, 64
  bins) plus a `pae_bins_file` CSV column, so the gap between our point-PAE ipTM and the engines' own
  can be measured. Boltz-2 pays one extra forward pass per design; ESMFold2 hooks the existing pass.
  Not used for ranking and not in the report. **AF3 has no such flag**: it does not expose the
  distribution without patching AF3 itself. See `Evaluator/docs/pipeline_reference.md`.
- **`binderscout status`** — live campaign state per tool and per machine: designs banked of
  requested, liveness and an ETA. Three signals per arm, not one, because designs land in batches and
  a frozen count does not mean a stalled arm: the count, the process/GPU, and log silence.
  `--hosts`, `--local`, `--json`, `--watch [SECS]`, `--timeout`; hosts come from `$BINDERSCOUT_FLEET`.
  Remote boxes are probed by piping a stdlib-only script into `ssh <alias> python3 -` (no checkout
  needed there). BoltzGen is reported by phase (generating vs analysed) with each phase's own
  denominator, and BindCraft is no longer confused with BindCraft 2. Runs group into campaigns, with
  labels and deadlines from a machine-local file named by `$BINDERSCOUT_CAMPAIGNS`; absolute paths are
  reported relative to `$HOME`.
- **`binderscout status --html FILE`** — a self-contained page any box can regenerate from a timer and
  serve over plain HTTP, so nothing has to push it. It is written beside and renamed (a polling
  browser never sees a half-written page), and its freshness band is recomputed in the browser from
  the page's own stamp, so a dead generator turns the page stale instead of reading "fresh" forever.
- **`*_pae_iptm_pinned` and `consensus_iptm_mean_pinned` — diagnostic columns, rank unchanged.**
  Each design is re-scored with one d0 (the pool-median binder length, or `--d0-binder-length`) so the
  length artifact in ipTM's `L_binder + L_target` d0 is visible per design. Measured on the
  563-design labelled benchmark, ranking on them does **not** help (macro AUC +0.0025, 95% CI
  -0.004..+0.010, signs split 2/2 across targets), so `rank` stays on the per-design d0.
- **`binderscout_paths.find_conda_base()`** — one shared answer to "where is conda?"; the CLI, the TUI
  and the configurator each had a private candidate list. Order: `$BINDERSCOUT_CONDA`, the checkout's `conda/`,
  `$CONDA_EXE`, `$CONDA_PREFIX`, `PATH`, then the usual locations; no subprocess. With conda on `PATH`
  but no checkout-local conda, `binderscout evaluate` used to report "conda not found".
- **RFD4-Proteina is installable on aarch64** (`install_aarch.sh --tool rfd4`), opt-in and not in
  `--tool all`, with a pinned commit and a size + sha256 check on the weights. It is validated by a
  dependency resolve and an install on one GB10, **not** by a design campaign there.
- **Installer hardening (the BUG-xx series from a full campaign run):** the installers stream to
  `install.log` and print a two-minute heartbeat off a TTY (BUG-07); a toolchain preflight names a
  missing compiler before an hour of installing (BUG-08); install markers are written only after a
  tool's install returns 0 (BUG-06); floating dependencies are pinned and verified at the artifact
  the tool needs to run — PyRosetta for BindCraft (BUG-14), `atomworks` in the RFD3 env on both
  platforms (BUG-28), others (BUG-23/24/25); `--repair` is ported to `install_aarch.sh`; the
  optional SoluProt and TmProt screens are skipped with a note, not a traceback, when their binary is
  absent (BUG-10); and the cross-engine gate shortfall is presented as a notice, not a raw warning
  (BUG-12).
- A guard test that documentation and tests name machines only by architecture
  (`tests/test_public_docs_are_anonymous.py`), and one that pins the README, CLAUDE.md and
  THIRD_PARTY_NOTICES facts (`tests/test_docs_state_the_release_facts.py`).

### Fixed

- **A design missing from the first engine kept its identity columns.** The outer join dropped every
  later engine's `binder_length` / `target_sequence` / `run_id`, so such a design lost `binder_length`,
  every PAE slice for it was NaN and it was ranked last with no warning (rank 20 -> 394 on an archived
  pool). Gaps are now filled from the later engine; the first engine's values still win.
- **The merge join key is canonical.** Sequences are stripped and upper-cased on load, so a re-keyed
  CSV cannot split one design into single-engine rows; a CSV pair where only one carries
  `target_sequence` now warns instead of silently skipping the mismatch guard.
- **Resume consolidated.** Six private implementations of "what counts as already done" (three refold
  scripts, three runners) are now one module, `refolding/resume.py`, ported from the `master` line and
  keeping this line's score gate. It fixes the case where a CWD-relative output directory shared with
  other targets made every design look completed (a 65-design pool refolded 0 of 65 and reported
  success), and the AF3 blank-row case above.
- **Configurator structure handling:** the mmCIF-to-PDB writer omitted the altLoc column, shifting
  every later field one column left (BUG-19); expression tags are trimmed from the depositor's own
  annotation rather than guessed (BUG-09); hotspots resolve in author numbering, not label numbering;
  chain ids are case-sensitive; the RFD3 contig comes from the structure's own numbering (BUG-21); the
  prepared structure keeps only the selected chains and is what every tool is pointed at (BUG-16).
- **Proteina-Complexa:** the target is registered through `complexa target add`, not a config key it
  never read; its sequence collector no longer throws away a finished run's results; and it reads
  Complexa's own `self_sequence` column. The generated script parses (the harvest moved to a heredoc).
- **RFD4 needs no root.** The generated script finds Python headers through `sysconfig`, falls back to
  a uv-managed interpreter's headers, and refuses up front with `uv python install <ver>` if neither
  exists, instead of dying inside Triton's JIT on `Python.h`.
- **The configurator asks about the cross-engine gate once** when fewer than three refold engines are
  installed, and records the answer (`min_engines`) in `config.json` as an explicit decision, rather
  than the operator discovering at report time that nothing cleared the gate. The gate is still never
  derived from what happens to be installed; with a single engine it offers nothing, because the floor
  is 2.
- **Protein-Hunter received only the first target chain** when fed a target sequence (400 designs had
  Boltz-2 inputs holding just a 276-aa heavy chain and reported ipTM 0.82 about a complex that was not
  the target). Every chain is now passed; `--contact_residues` stays one group on the first chain.
  Mosaic's template can take only one sequence, so it now refuses and names the chains it would have
  dropped.
- **The machine-names guard no longer fails on its second run.**
  `tests/test_shell_scripts_name_no_machines.py` scanned `tools/__pycache__/*.pyc` as a shell script,
  and a `.pyc` embeds the absolute path of the runner's own account. Its `tools/` lane is now
  tracked files only, with bytecode excluded.
- **The `evaluate.sh` parser test no longer depends on the conda on the machine running it.** Its
  stub `conda` binary lost to the `conda` shell function that `evaluate.sh` sources, so on a host with
  a system conda it ran the real `conda env list` / `conda run` and could outlast its timeout under
  load. It now plants a stub function where the search looks first and asserts that a decoy conda was
  never called.
- **Documentation:** manual `conda run` commands now say to source `conda.sh` first (in standalone
  mode conda is not on `PATH` and they exit 127); the README's `binder-compare run` example goes
  through `binderscout evaluate`; the `examples/` smoke-run text says BoltzGen with a budget of 1 still
  runs a 100-design pool (about 9 minutes for its design step alone); the subcommand count is 23;
  `screen-tmprot` is named as this line's counterpart of `master`'s `filter-tmprot`; the MSA pre-warm
  advice now points at `target_msa_cache_path` (`get_target_msa` returns the a3m text, not a path) and
  says both cache-directory spellings may exist; and CLAUDE.md records the 2026-11-03 measurement that
  `*_pae_iptm` reads well below the engine's own ipTM on small complexes (n=1 and n=3, a hypothesis).

### Changed

- **Documentation.** The README banner, branch and clone instructions, tool counts and a new
  `binderscout status` section now match the repository: tags `v2.0.0`–`v2.0.2` are on the public
  remote, `master` is a separate 1.x line, `v1.1.x` is retired to `archive/v1.1.x`, and there is no
  `aarch64` branch. CLAUDE.md corrects the ancestry statement (the lines share a merge base,
  `602345a`, and have diverged since), records which `master` fixes are ported and which is not (`filter-tmprot`), and states
  what `*_pae_iptm` is and what the rank can resolve (see `Evaluator/docs/evaluation/ranking.md` §1a).
  THIRD_PARTY_NOTICES.md's GPLv3 written offer cites commits that exist after the 2026-10-27 history
  rewrite and adds RFD4-Proteina, TmProt and ESMFold2 rows. CONTRIBUTING.md gains a Releasing section.
  Machine and cluster names were removed from tracked documents and test fixtures.
- Seven project subagents are tracked under `.claude/agents/`; the working-tree clones of two foreign
  tools are gitignored so a stray `git add -A` cannot turn the lint job red.
- `tests/test_version_matches_changelog.py` pins `binderscout.__version__` to the newest numbered
  changelog heading. It is `xfail(strict=True)` until the release commit bumps the version.

### Fixed by the end-to-end demo campaign (2026-11-03)

- **`evaluate.sh` step 0 no longer destroys the design id.** It re-parsed the extract FASTA over itself and
  welded the `source=` / `length=` tags into the id, so `metrics.csv` said `source_tool='unknown'` and every
  structure filename was bloated. `parse-seqs` now keeps tags as tags (idempotent on an extract FASTA) and
  step 0 writes to a temporary file and moves it into place.
- **A finished run can be re-run.** With `--resume` (always passed by the generated script) a complete run
  writes nothing, and the no-new-rows guard reported failure. It now reports "already complete" when every
  pool design carries a scored row **folded against this run's target**; the stale-shared-CSV and
  different-target protections are kept.
- **RFD3:** the geometry gate's "cannot verify" exit no longer kills the script under `set -e` (the documented
  warn-and-continue branch and `RFD3_IGNORE_GATE` were unreachable, so RFD3 produced 0 designs), and a binder
  shorter than the gate's floor is described as too short rather than as having no atoms.
- **`binder-compare extract`:** one empty tool is a named warning and the other tools' designs are still
  written (it used to exit 1 and discard them); exit 1 only when every tool is empty.
- **Configurator:** a copied `--config` with a new `name` gets its own run folder; the BoltzGen script stops its
  whole process group on termination; a headless config can set `trim_construct_tag`; the Protein-Hunter
  collector finds its summaries at either directory level.
- **The CALCA smoke example now reliably produces a design.** Protein-Hunter at 1 design x 1 cycle with the default 0.7 iPTM threshold yielded a usable design about once in 12 tries, so a fresh `examples/CALCA/smoke.json` run usually died at extract. It now uses 3 designs x 3 cycles and an iPTM pass threshold of 0.5 (non-default, smoke only; 4 of 4 trials produced designs). Recorded in `examples/README.md`.
- **Hygiene:** the machine-names guard no longer scans `__pycache__` (the suite failed on its second run), and
  a conda shell function on the host can no longer make the `evaluate.sh` parser test flaky.

### Fixed by the full end-to-end run (2026-11-03)

Every design tool was then run from a configurator-generated script (x86_64: all nine; aarch64: RFD4),
the pool refolded by all three engines and reported.

- **RFD4 hung forever on aarch64.** Upstream's default of four DataLoader workers deadlocked there (ten
  minutes, GPU idle, no output, no error). The generated script now passes `num_workers=0`, which gave 10 of
  10 designs on the same host. The script also checks for a C compiler before starting (Triton's own
  failure arrived 45 s in, after the model had loaded) and records the real interpreter version and the
  target sequence in `settings.json`.
- **`report` exits 1 when PAE files are listed but none can be read** (a refold CSV copied without its PAE
  directory). It used to write a full-looking report with an empty `consensus_iptm_mean` and a `rank`
  column, and exit 0.
- **`report.html` no longer describes the removed Stage-1 max screen as a live stage**; the max-versus-mean
  plot is now labelled as the engine-agreement diagnostic it is. The top tables show `consensus_iptm_n`
  beside the rank, and the per-tool native ranking is wired for PXDesign, Protein-Hunter and
  Proteina-Complexa (it said "no native column available" for tools whose native metrics were present).
- **`extract --collect-structures` names a missing `gemmi`** instead of printing a bare `collected 0/N` for
  every mmCIF-writing tool.
- **RFD3 script:** per-backbone ProteinMPNN logs are kept (they went to `/dev/null`) and the script exits
  non-zero when no backbone yielded a sequence; `settings.json` records the `rc-foundry` version.
- **`binderscout status` (or any query) no longer re-points the account's `binderscout` command** at the
  checkout it was run from; only `install` does that.
- **BindCraft 2** no longer names a rejected-candidates file it did not write.
- **Tests:** the x86_64 installer tests run on an aarch64 host (the installer's refusal is overridden for
  tests only), and one configurator test no longer depends on whether the checkout has installed a tool.

### Ported from `master` (1.0.6-1.0.8), re-applied on this line

- **One NaN guard for every extractor's sequence cell.** An empty CSV cell is NaN and
  `str(nan).strip().upper()` is `"NAN"`, whose letters are all standard residues: a blank cell passed
  validation and the string was folded as a design. Every CSV-reading extractor now goes through
  `SequenceExtractor._sequence_cell`.
- **`merge_refold_results` treats the `--sequences` FASTA as the pool.** Engine rows whose sequence is not
  in the pool are dropped with a named warning before anything is ranked (an engine CSV accumulates
  across runs and may hold more than the pool being reported).
- **`evaluate.sh` checks pool coverage, not a row delta**, and **resolves AF3's weights up front**
  (AF3 is skipped by name when they are missing instead of failing late). **AF3 is now in `--tool all`**
  (the environment only; the gated weights are still yours to request).
- **Proteina-Complexa:** `dm-haiku` is pinned and asserted by importing `colabdesign`; the generated
  harvest keeps the metrics Complexa computed (accepts `binder_sequence`, scans every output directory),
  and a harvest that finds no designs now exits non-zero (PXDesign too).
- **RFD3:** a run with no hotspots is refused at configure time (the previous `infer_ori_strategy:
  hotspots` assertion fired inside RFD3 after the model had loaded). The x86_64 `rc-foundry` pin is now
  load-bearing (one constant in both pip specs).
- **Every script the configurator generates must `bash -n` parse**, enforced by a test.
- **Not ported (known gap):** master's Proteina-Complexa raw-output copy-back and the per-row `structure`
  column that links a design id to its PDB. Tracked for 2.0.4.

### Fixed by the aarch64 full run and the fix lanes (2026-11-04)

- **The RFD3 geometry gate no longer rejects a compact helical short binder, and now looks at 20-24 residue
  binders.** It asked every binder for Rg/expected <= 1.45 and >= 0.80 long-range contacts per residue, which a
  helix cannot satisfy (a helix has no contact between residues 9 or more apart), so it failed good 26-30 aa
  backbones, and it declined to look at anything under 25 residues, so the CALCA smoke example (20-30 aa) never
  exercised it. A helical backbone (its own helix fraction >= 0.40) of up to 60 aa, the longest length measured, is now passed with an explicit "NOT VERIFIED:
  compactness and where the binder sits" note; every other backbone, including any helix longer than 60 aa and any coil mixed into a helical pool, keeps both original criteria; the floor is 20
  (the shortest length measured). The origin gate (`|fixed_com|`) is unchanged. Measured on real RFD3 backbones
  (table in `tests/test_rfd3_gate_helix_aware.py`): against the CALCA helix target the mis-centred runs are
  still helical, so only the origin gate tells them apart, and the geometry gate says so.

- **Protein-Hunter `sequences.csv` design ids are unique.** `summary_high_iptm.csv` has one row per
  passing cycle, and the collector built `ph_<run_id>` from the run id alone, so different designs
  shared an id. The id is now `ph_<run>_c<cycle>` (repeats from cycle-less sources are numbered).
  Nothing joined on the old id: the extractor reads the summary CSV itself.
- **RFD4 no longer preserves the structure's expression tag.** On 5O45 the contig was the chain's
  whole label range `A1-129`, which includes AAALE + His6 (119-129, the depositor's own
  `_struct_ref_seq_dif` rows). The contig now follows `target_sequence` (the wizard's tag-trim offer
  and `trim_construct_tag` both trim it), keeping `label_seq_id` numbering (`A1-118`), says what was
  dropped, and warns when a flagged tag is still inside the contig.
- **`run_rfd4.sh` starts `rfd4-generate` inside its generate dir**, so Hydra's `hydra_outputs/`
  and `runs/` land in the run folder instead of the operator's current directory.
- **Installers no longer take over an account's PATH.** The shortcuts-dir `export PATH=` line is
  appended to `~/.bashrc` only for an interactive install or with the new `--add-to-path`; a `--yes`
  or non-TTY run (CI, a verification clone) prints the line and does not write it. (The `uv` bootstrap's own
  `~/.local/bin` line is a separate append and is not gated; see Known issues.)
- **The "run folder follows the name" note** for a copied config that only changes `name` no longer
  reads as a warning about `run_dir`; it states the resulting folder and that nothing is wrong.
- **A run with design tools but no Evaluator** now prints one line saying how to get
  `run_evaluate.sh`.

- **A fully resumed Boltz-2 refold no longer loads the model to find nothing to do.** `evaluate.sh`
  always passes `--resume`; on a finished run the engine still imported jax/equinox/mosaic, built
  `Boltz2()` and reserved its XLA pool (~19 GB on a 24 GB card, ~9 s) before exiting. `refold-boltz2`
  now checks, before it imports the script, whether every pool design already has a scored row
  (the sequence-plus-score key of `refolding/resume.py`, narrowed by `target_sequence` exactly as
  `evaluate.sh`'s `pool_coverage` does, with a parity test between the two), prints
  `already complete ... model not loaded` and exits 0 after publishing the existing rows. A design with a
  blank or missing score is still folded. A pool whose scores were folded against a DIFFERENT target is now
  refused by the engine itself (exit 1, nothing published) instead of being skipped by sequence and left
  for `evaluate.sh` to catch afterwards. `refold_batch` in `scripts/refold_boltz2.py` also returns before
  the target MSA, the weights and `Boltz2()` when every index is skipped. No score, rank or CSV column changes.
  AF3 and ESMFold2 resume are not changed.

- **Proteina-Complexa: the run directory now keeps its raw output, and each design names its structure.**
  Ported by hand from the 1.x line (the two lines share no ancestry past `v1.0.3`, so nothing could be
  cherry-picked). Complexa writes its PDBs and metrics CSVs inside its own gitignored clone, which
  `install --uninstall` deletes, so an archived run held `sequences.csv` and nothing to inspect. The
  generated harvest now copies the structures to `proteina_complexa/structures/` and every metrics CSV to
  `proteina_complexa/raw/`, and `sequences.csv` gains a `structure` column naming the copy that holds that
  design's binder. Two designs whose PDBs share a file name keep separate copies (the second is prefixed
  with its directory) instead of the second being skipped and its column pointing at the first design's
  structure. The column is a link, not a metric: the extractor reads the same ids, sequences and native
  metrics with or without it, so `rank` and every score are unchanged. This line already carried the
  rest of master's commit (the all-candidates scan, `binder_sequence`, the `evaluation_results` descent,
  de-duplication); the Evaluator extractor needed no change.
- **`run_pxdesign.sh` starts on an aarch64 host.** It forced `CUDA_HOME` to the conda env, whose aarch64 build has
  no `bin/nvcc`, so deepspeed (reached through protenix) raised `FileNotFoundError` 8 s in. It now uses the env's CUDA
  only when it has an nvcc, else the `nvcc` on `PATH`, else `/usr/local/cuda`, and finds the platform's
  `targets/<arch>-linux` directory (it hard-coded `x86_64-linux`). Found by running every tool's script on an aarch64 host.
- **`run_proteina_complexa.sh` no longer dies at 0 s on `SC_EXEC: unbound variable`.** The script is `set -u`;
  `env.sh` reads `${SC_EXEC}` unguarded when the install's `.env` does not define it. `env.sh` is now sourced with
  `set +u`, as the conda blocks already were.
- **PXDesign `binder_length` is the sequence length** when the output directory is not named `outputs_len<N>`
  (it read `?`).
- **The CALCA smoke config fits a 30 minute budget per tool.** It pins `boltzgen_intermediate: 8` (the default pool
  of 100 is folded by Boltz-2 at about 23 s per design on a GB10, well over 50 minutes) and one Mosaic length.
- **Review fixes to the above:** the RFD3 helix exemption is per backbone and capped at 60 aa (a 60-150 aa straight
  helix, and a coil mixed into a helical pool, are still judged); a third Proteina-Complexa PDB with the same file
  and parent-directory name keeps its own copy; `--resume --save-pae-bins` on a finished Boltz-2 pool no longer takes
  the early exit (it used to refuse a CSV without the bins column, and must still).

### Known issues in 2.0.3

- **aarch64 coverage.** On an aarch64 host (GB10, every GPU job under a driver-enforced memory cap) all nine design
  tools were run from configurator-generated scripts. Designs came from seven of them (Protein-Hunter, RFD3, Mosaic,
  BoltzGen, BindCraft, PXDesign, RFD4). The pooled three-engine evaluation of a 10-design CALCA pool (6 tools) and a
  20-design PD-L1 RFD4 pool scored every design with all three engines and passed the gate, and a re-run refolded
  nothing. **BindCraft 2** ran but accepted 0 designs in 3 trajectories (the accepted-design path was not exercised
  there). **Proteina-Complexa is blocked on aarch64**: with the script fixes above, its AF2 reward fails on the removed
  `jax.clear_backends` (ColabDesign 1.1.1.1 on jax 0.6.2) and the tool correctly refuses to continue. Mosaic and
  BoltzGen needed the bounded smoke settings above to fit a 30 minute budget; Mosaic restarts from the first length on
  a re-run instead of resuming. The test suite passed there (2331 at e234cd7).
- The RFD3 geometry gate passes a helical backbone of 20-60 aa without judging compactness (it says so); the origin
  gate (`|fixed_com|`) is what catches a mis-centred run on a helical target. Measured on one 32-aa helix target only.
- Proteina-Complexa registers its target in the shared checkout (`configs/targets/targets_dict.yaml`, `logs/`,
  `inference/`) even when a run fails; a symlinked or read-only checkout is therefore written to.
- RFD3 backbones are collected into `design_structures` by sequence, so a diffusion backbone that does not carry the
  MPNN sequence reports 0 collected.
- `settings.json` records `binderscout_git_branch: HEAD` when run from a detached tag.
- A fresh clone has no `Evaluator/envs/mosaic_venv_path` until the installer runs (the error says so); on one
  aarch64 host the pointer references the `binder-eval-boltz2` env, which has jax and equinox there.
- The installers' own `uv` bootstrap still appends `~/.local/bin` to `~/.bashrc` (the shortcuts-dir line is gated,
  that one is not).
- Only the CALCA smoke example, a PD-L1 contig check and the aarch64 run above were exercised live; the x86_64 demo
  ran on one host (RTX 3090).

### Removed

- **The 16 planning records under `docs/`** (`PLAN_*`, `INVESTIGATION_*`, `REPORT_*`,
  `MORNING_DECISIONS`, `NEXT_STAGES`) left the tree. They were internal, several named machines and
  storage, and the 2.0.2 notes already said they had been removed. They are archived off-repo with the
  diaries; git history is deliberately not rewritten, so older commits and the published tags still
  contain them. What the project needs from them lives in `CLAUDE.md`, this changelog and
  `Evaluator/docs/`. `2.0/README.md` was rewritten as an index of what remains.

## [2.0.2] — 2026-10-27

### Added

- **RFD4-Proteina as the ninth design tool** (IPD x NVIDIA latent-reasoning diffusion), wired
  through all three modules: `install/install.sh --tool rfd4`, a configurator step that generates
  `run_rfd4.sh` from `binderscout_examples/run_rfd4.sh.template`, and an `RFD4Extractor` reachable
  as `binder-compare extract --rfd4`. It produces backbone **and** sequence in one pass, so there
  is no MPNN step. **x86_64 only and opt-in — deliberately not in `--tool all`.** aarch64 is
  refused outright rather than labelled unvalidated, because upstream's own
  `scripts/setup_venv.sh` exits 1 on any non-x86_64 host. The code is BSD-3; **the weights licence
  has not been verified here**, so the installer says so rather than implying it is cleared.
- The configurator derives RFD4's preserved segment from the mmCIF `label_seq_id` column, which is
  what RFD4 resolves contigs against. Author numbering silently names different residues — a stock
  5O45 is `A18-132` by author and `2-116` by label — and that cost two failed jobs before it was
  understood. An mmCIF-less (`.pdb`) target is refused at configure time rather than converted.

### Removed

- **73 files of internal lab material and research data, from the tree *and* from all published
  history** (`git filter-repo`, force-pushed across `master`, `v1.1.x`, `v2.0.x` and all ten
  tags): both repository diaries, the `docs/PLAN_*` / `docs/INVESTIGATION_*` planning records,
  `docs/plans.md`, `docs/completed_plans.md`, the `docs/data/` benchmark sets, the two skill
  deploy playbooks and `tools/fleet.sh`. Several of those carried **unpublished designed binder
  sequences next to their targets**. The diaries were not deleted but moved: they live on the lab
  share (outside this repository), and `.gitignore` now blocks `DIARY_*.md`.
  A rewrite does not undo publication — it only stops future casual access.

### Changed

- `docs/INVESTIGATION_RANKING_DISCREPANCY.md` is republished in sanitized form at the same path:
  statistics, methods and conclusions kept, campaign name, target sequence and run paths removed.
  The path is unchanged on purpose, because `core/schema.py`, `comparison/scoring.py` and
  `extractors/boltzgen.py` cite it as the evidence for the ranking.
- 48 references across 26 surviving files were retired. Where a citation carried the claim a
  reader needs, the claim is now inline and only the pointer is gone. `CHANGELOG.md` and
  `STAGES.md` keep their entries verbatim, with one note at the top, because they are historical
  records.

## [2.0.1] — 2026-10-15

### Fixed

- **A space inside a design id no longer yields mis-named structures with exit 0.** The binder id is a FASTA header's first whitespace token, so `>CALCA-Protein Hunter-01` became `CALCA-Protein` for all twelve such designs; their structures were written as `CALCA-Protein_af3.pdb` and `__2`..`__6` in file order, and none carried its own id (metrics CSVs were unaffected - they join on sequence). The three `refold-*` commands now refuse such a header before any GPU time is spent (`header_binder_id`), and `write_fasta` (so `extract` and `parse-seqs`) writes ids with whitespace replaced by `_`.

## [2.0.0] — 2026-10-04

**Shipped to the fleet only; not published.** *(As written at the time; the `v2.0.0` tag and the
`v2.0.x` branch are now on the public remote.)* 2.0 is an *evaluation* release, not
a feature release: no new design tool, and the three-engine refold pipeline
(Boltz-2 + AF3 + ESMFold2) is the same one 1.1 shipped. What changed is what the
pipeline is allowed to claim.

Three themes, and they are the reason for the major version:

- **One ranking, and no way to choose another** (Part U): a cross-engine gate
  then `consensus_iptm_mean`, producing a single `rank` column. `two_stage_rank`,
  `adaptyv_rank`, `consensus_rank`, `active_rank`, `passes_max_screen`,
  `--rank-by` and `--screen-metric` are **gone with no compatibility shim** —
  searching for a better metric on labelled data measured *worse* than not
  searching (0.5170 vs 0.5552, p=0.0014). This is the breaking change.
- **Silent success is now a failure.** A run that produced nothing, or produced
  blanks, used to exit 0: ESMFold2 loading random weights from an unpinned
  revision, AF3 reserving half a card, a refold engine writing a column of empty
  rows, a reward that could not be computed returning `0.0`, an installer
  declaring an engine ready on a card that cannot run it. Each now refuses and
  names what is wrong.
- **Claims are separated from evidence.** The negative results are recorded as
  loudly as the positive ones, four single-pool effects were retracted rather
  than shipped, and Cao 2022 was withdrawn as a benchmark on label censoring.
  `docs/PLAN_2.0_CONCLUSION.md` §4 is the list that must not be relearned.

Known not-done, by decision: the **GPU-memory pass goes last** (a reading taken
against an unfinished pipeline is stale by the time it ships), and Stages 1–4 of
the plan are feature work, not shipping blockers. See
`docs/PLAN_2.0_CONCLUSION.md` §3.

### Fixed

- **A partial refold failure exited 0, and four separate mechanisms kept it quiet.** Each
  engine already refused when *every* design failed; none refused when *some* did — the
  likelier case, because demand rises with token count, so on a marginal card the long
  binders fail and the short ones pass and the CSV comes back plausible. A failed design
  loses an engine, so its `consensus_iptm_mean` is taken over the survivors and it drops
  below the `>=3`-engine gate — in `metrics.csv` that is indistinguishable from three
  engines having disliked it. Four fixes, because any one alone is defeated by the others:

  - `require_device_memory()` refuses ESMFold2 on a card below **14,248 MiB** *before* the
    MSA fetch and the weight download (measured: 14,248 MiB at 150 tokens on an RTX 3090,
    13,781 on GB10 — a floor rather than a slope, because it is resident-weight cost). This
    is what enforces "a GPU that is too small must never produce authoritative refolds" in code
    rather than in convention. `BINDERSCOUT_ALLOW_SMALL_GPU=1` overrides it and says the output is not
    authoritative. **Boltz-2 and AF3 deliberately get no floor** — Boltz-2's demand is
    card-dependent (8,518 MiB at 150 tokens, 16,712 at 300, failure at 600; GB10 needs
    ~1.5× a discrete card), so a static floor would either refuse a card that can fold a
    60-token complex or pass one that cannot do 300.
  - All three engines now raise `PartialRefoldFailure` and **exit 3** when some designs
    failed — 3, not 1, because the rows that did fold are on disk and the message names the
    failed indices, so a wrapper can tell "re-run these" from "this environment is broken".
    The runners hold the exception until after the publish/absolutise step, which sits
    *after* the call, so re-raising immediately would strand exactly those rows.
  - `--resume` now keys on the **score**, not on `idx`. A failed design's blank row carries
    an `idx`, so resume skipped precisely the designs it existed to retry, reproduced the
    gap exactly and reported success. Fixed in all three runners (the path production uses)
    and in ESMFold2's own entrypoint.
  - `evaluate.sh`'s `csv_rows()` counts rows with a non-empty `iptm`, not rows. A blank row
    is a row, so the guard added specifically to catch "an engine that exits 0 and writes
    nothing" printed `ok -- 50 new row(s)` over 50 blanks. The column is found by **name**,
    since the three engines order their columns differently and a hard-coded index would
    read a different column per engine.

  Both installers now warn at install time when the card is below ESMFold2's floor, rather
  than printing "ESMFold2 refolder installation complete" on a box where the engine can
  never fold — the pattern this project has already paid for with BindCraft 1 and PXDesign,
  both of which reported themselves healthy while being unusable on Spark. It is a warning
  and not a refusal, because installing on a small box is legitimate (CI, development, an
  env destined for another machine), and it reads `ENGINE_MIN_DEVICE_MIB` rather than
  repeating the number, so the installer and the runtime cannot disagree.

  Pinned by `tests/test_a_blank_refold_row_is_not_a_score.py` (50 tests), mutation-tested
  against 19 mutations. Two of those mutations initially passed: commenting the preflight
  out left a substring-based ordering assertion green, and making a runner swallow the
  exception was untested altogether — the runner is the only boundary production crosses,
  since `binder-compare refold-<engine>` never calls the scripts' `main()`.

- **Four surfaces named the wrong metric as the ranking metric, and one of them was an
  agent instruction.** `rank_designs()` has always been correct — gate on `--min-engines`,
  sort on `consensus_iptm_mean`, tie-break on `consensus_iptm_n` → `consensus_iptm` →
  binder pLDDT — so no run produced a wrong order and no test went red. Only the
  descriptions had drifted: `report.html`'s own glossary called `ipsae_min` "the primary
  ranking metric" on the page that ranks by `consensus_iptm_mean`;
  `Evaluator/docs/pipeline_reference.md`, the file CLAUDE.md cites as *the* metrics
  reference, said the same in its metrics table; the orchestrator skill's
  `references/evaluation.md` instructed an agent to sort on `agreement_count`
  **descending** as the primary key; and `SKILL.md` §6.3 said `ipsae_min` agreement
  "unifies them at the campaign's final ranking".

  An agent following the third would have produced a differently-ordered shortlist from
  the report's own, with no mechanism to notice. Pinned by
  `tests/test_ranking_metric_is_not_misnamed.py`, mutation-tested against all four
  reversions **plus** the escape a purely negative test allows — deleting every mention of
  ranking instead of correcting it — so each surface must also name the real metric.
  `pipeline_reference.md`'s table gained a ROLE column
  (RANKS / GATES / WARNS / REPORTS / NATIVE), the distinction whose absence let this drift.

  Verified by rendering a real `report.html`, not by grepping the source, and that
  mattered: `_METRIC_DESCRIPTION` renders only for metrics present in the `summary` dict,
  and because `compute_statistics` runs before the consensus columns exist, the shipped
  per-tool table shows `ipsae_min` and **never shows `consensus_iptm_mean` at all** — so
  that glossary line was the operator's only in-page statement of what ranks.

- **`ss_bias` was a dead knob: two design-loss terms were unreachable in every
  generated run.** `design()` in the Mosaic template took an `ss_bias` argument
  that gated `sp.HelixLoss()` and `sp.DistogramRadiusOfGyration()` — and its sole
  call site never passed it, so both terms sat at the default `"none"` and could
  not fire, while the template advertised helix/compact shaping. The configurator
  injected eight values and this was not one of them, so there was no way to reach
  it through the documented path either.

  Wired end to end: the call site passes it, the configurator injects and validates
  it, and it is a first-class run parameter recorded in the generated script.

  Two things fixed while wiring it. The branch was `if/elif`, which silently made
  `"helix+compact"` mean `"helix"` — the two are different properties and now
  compose. And an unrecognised value was silently ignored, which cost a whole
  campaign running with no bias at all; it now raises.

  Worth having because it moves the RFD3 geometry lesson in-loop. There we learned
  to gate on `Rg/expected <= 1.45` and long-range contacts **after** backbone
  generation, and that a Pro/Gly-rich sequence is a *symptom* of a coil rather than
  an MPNN problem. As a differentiable term the backbone never gets to be a coil.
  Upstream Mosaic independently converged on shipping globularity as a standing
  term in its minibinder recipe — at weight 0.2 against a different 3-term loss, a
  number that does **not** transfer to our 9-term loss, which already carries
  `WithinBinderPAE` and `WithinBinderContact`, both correlated with compactness.
  Our 0.1 is equally unvalidated; it is one of the few single dimensions genuinely
  worth a sweep.

- **AF3 aborted on every small pool, and the cause was ours.** `refold_af3.py`
  computed `bucket = len(target) + max(len(binder))` with **no lower bound**, so a
  60-token pool (CALCA's 32-aa target + a 28-aa binder) asked AF3 for
  `--buckets=60` — a shape AF3's own stock ladder never produces, since that ladder
  starts at 256. Below 256 its tokamax Pallas/Triton attention and gated-linear-unit
  kernels select a tile config requesting 110,592 bytes of shared memory per block
  against the 101,376 that sm_86/sm_89 expose, and the refold died with
  `RESOURCE_EXHAUSTED: Shared memory size limit exceeded`.

  This had been recorded as "AF3 cannot run on consumer Ampere". **It can.** Measured
  on an RTX 3090 (sm_86), one `input.json` reused byte-identically across two arms
  with a cold shared compile cache, only the bucket digits differing:
  `--buckets=60` → rc=1 in 43 s with the abort and no structure; `--buckets=256` →
  rc=0 in 69 s, no error, 2 structures, iptm 0.52. The same card had already
  completed pools at buckets 493, 512 and 568.

  Fixed with `AF3_MIN_BUCKET = 256`, pinned by
  `tests/test_af3_bucket_has_a_floor.py` (3 mutations, all caught). The floor costs
  nothing against AF3's documented behaviour — stock AF3 pads a 60-token complex to
  256 regardless; we were requesting an impossible shape, not saving compute. A pool
  already above 256 is untouched.

  Two doc corrections fall out of the same investigation. The identical 4,430 MiB
  peak recorded at 258 **and** 391 tokens was read as evidence AF3's memory barely
  grows with size; it is one compiled shape measured twice, because neither run
  passed `--buckets` at all (the flag landed four weeks later) and both padded to
  512. And "no completed ESMFold2 fold has ever been observed" was false — a 50/50
  pool plus two single folds are on record on a 24 GB card; ESMC-6B loads bf16 at
  ~11.8 GiB resident, so the 12 GB dev box was the constraint, not the engine.

- **TmProt never ran from a generated run script.** `write_run_evaluate` reads
  `cfg.get("use_tmprot")` and `cfg.get("tmprot_threshold")`, but the wizard
  wrote those keys only into `tools_enabled`, never into `cfg`. The lookups
  fell through to their defaults, so **every** generated `run_evaluate.sh`
  carried `--skip-tmprot` regardless of how the wizard was answered, and the
  Tm column was silently absent from every report. Found by a new AST test
  that checks the cfg keys the wizard writes against the ones the writer
  reads — no behavioural test could see it, because both existing ones
  hand-build their own `cfg`.

- **`evaluate.sh` aborted before step 0 on any host with the
  `binder-eval-tmprot` env.** The TmProt block sat ~90 lines above the
  initialisation block that owns `STEP`, `N_STEPS` and `TMPROT_CSV`, so under
  `set -u` (line 74) the run died with `STEP: unbound variable` before the
  SoluProt screen and before any refold engine. The env is auto-detected, so
  no flag was needed to trigger it. Past that, `TMPROT_OK` was reset to 0
  *below* the block that sets it, so the report could never have received
  `--tmprot-results` either. The block is now below the initialisation.

  These two masked each other: the configurator always passed `--skip-tmprot`,
  so the crash could not fire through the documented path. Fixing either alone
  would have been wrong — the first turns a silent no-op into a hard abort.

### Removed

- **`--soluprot-filter` — SoluProt is a label, not a filter.** The flag dropped
  sub-threshold designs from the FASTA before any refold engine ran. Measured
  against experimental results on two targets, at its own default 0.5 threshold
  it discarded several of the tightest measured binders and lost designs from
  the full run's own top-10; no threshold above 0.0 met Part Z's recall gate,
  because solubility and affinity are close to orthogonal on these pools. A drop
  at that point is unrecoverable — the design never reaches the report.

  `evaluate.sh` now **exits 1** with an explanation rather than ignoring the
  flag, so anything that scripted it finds out instead of quietly receiving a
  different pool. The score is unaffected and still reaches the report as
  `native_soluprot_score` / `soluprot_passes`. The configurator no longer asks,
  no longer writes a `soluprot_filter` key, and **warns** when replaying an older
  `config.json` that sets it true, then **drops the key** so it does not round-trip
  into the regenerated config. (Warning alone was not enough: the key was written
  straight back out, so it was never retired and the warning fired forever on every
  later replay.) That replay produces a *larger* pool than the original run, and a
  config file exists to prevent exactly that kind of silent difference. The now-unreachable implementation is deleted from `evaluate.sh`
  (59 lines), along with the `soluprot_filter` checkbox in
  `docs/config-builder.html` that had been emitting a key nothing honoured.

  Note the names that remain and do **not** mean filtering: the CLI verb
  `binder-compare filter-soluprot` and `refolding.run_soluprot_filter` only
  *score*. They are kept because they are public API.

### Measured

- **The cross-engine premise, tested: true about errors, false about ranking — and an
  engine-set change found on Cao was retracted on replication the same day.** Full
  write-up: `docs/INVESTIGATION_coverage_premise_2026-10-03.md`.

  **Confirmed.** One engine buries a true binder in its within-target bottom quartile
  **5.2×** more often than all three do together (7.6 % on clean labels), and the ratio
  *grows* as the cut sharpens (10.5× at bottom-decile). It holds in the false-alarm
  direction (3.8×). Perfect independence would give 19.9×, identical engines 1.0× — the
  three sit about halfway on a log scale. Error correlation measured *within target and
  within class* is **ρ ≈ 0.382**, i.e. effective n = 1.70 of 3. The mean rescues **73.2 %**
  of binders buried by exactly one engine (27.5 % of those buried by two, 0 % by three).

  **Not confirmed for ranking.** The 3-mean beats the *average* single engine (+0.0088) and
  **loses to the best** (AF3 alone 0.5603 vs 0.5552; AF3 is the out-of-fold pick on 12/12
  folds, so not a selection artifact).

  **Retracted.** An apparent win for `mean(af3,esm)` over `mean(all 3)` on "clean" Cao
  (+0.0210, p=0.0078) **reverses with significance** on the curated Adaptyv benchmark
  (−0.0210, CI [−0.0309,−0.0095], p<0.0001, 0/4 targets, both metric panels) and does not
  survive Cao's **own** label flag `kd_ok` (−0.0097, p=0.673). My hand-rolled "finite
  `kd_ub`" slice admitted 48 designs with `kd_lb == 0` — degenerate [0,X] intervals — and
  Tie2 existed as a 12th target only because of them while carrying the largest per-target
  delta. I also bundled two slices: the quoted "+0.153 enrichment" was the *all-labels*
  number, and on the AUC slice the enrichment delta is +0.0000. The mechanism inverts as
  well: Boltz-2 is the **strongest** engine on Adaptyv (0.720 vs AF3 0.613) while equally
  decorrelated, so the change would have dropped the strongest engine on the benchmark the
  shipped metric was validated against. **Keep all three engines and the shipped ranking.**

  **Shrinkage, proposed and withdrawn the same day** (conclusion §5.0): +0.0003…+0.0006
  macro AUC with CIs straddling zero, *worse* on precision@top-10 % in 8/8 regimes, `k`
  unidentifiable — and its premise was wrong, because coverage is 100 % constant on every
  labelled set we own, making the gate, the raw mean and shrinkage the same ranking.

  **Two of Part U's supporting claims withdrawn.** Its binary-assay corroboration is
  near-circular (`binder_4000_nm` is predicted by `kd_ub < 4000` at MCC 0.819, 0.075 %
  error over 654,716 rows), and one-sided binders are not "experimentally indistinguishable"
  from non-binders — 8.7× the pass rate (p=4e-62), 32× at 400 nM. Part U's headline stands:
  73.41 % reproduces exactly, and the 0.5552 → 0.7228 clean-label lift to four decimals.

- **Part AI: NULL, and the deliverable is a power calculation.** Five arms
  (baseline / helix / Rg / both / random placebo at three magnitudes), each
  refolded on both held-out engines. **Nothing survives multiple comparisons:**
  across 4 arms × 2 engines the Bonferroni threshold is 0.0063 and the best
  p is 0.0168. Three placebo arms that measure the same thing scatter by 0.072 on
  ESMFold2, and helix's +0.079 sits *inside* that scatter.

  The magnitude hypothesis (committed earlier the same day) made a falsifiable
  prediction and failed it: a placebo at measured magnitude 0.835 should have
  given +0.115 and gave **+0.042** / **+0.011**. At magnitude 0.335 the two
  engines disagree in sign.

  **The usable finding:** at baseline sd 0.117 / 0.155, detecting +0.04 at 80 %
  power needs **~137 / ~240 designs per arm**. We ran 16–24 — 3× to 12×
  underpowered. Part AI cannot be answered with 8-design arms; a real answer is
  ≈26 GPU-hours. Also: achieved term magnitude does not track the weight
  (scale 5→0.30, 12.5→0.335, 25→0.835), because a stronger term drives the
  composition to reduce itself.

- ~~**Part AI, OVERTURNED BY ITS OWN CONTROL: it is magnitude, not geometry.**~~
  **SUPERSEDED — see above.** A
  placebo arm — a frozen random linear functional of the binder composition, same
  elu hinge and same 0.1 weight as `HelixLoss`, zero structural content — cannot be
  distinguished from the helix arm: **AF3 p=0.199, ESMFold2 p=0.48**. And the effect
  per unit of measured term magnitude is identical on both engines
  (helix 0.138 / 0.135, placebo 0.135 / 0.135), which is the signature of
  regularisation rather than of a useful prior. The pattern across all four original
  arms is explained by magnitude alone — `compact`'s +0.031 implies a term magnitude
  near 0.23, consistent with an Rg hinge near its target.

  So the reframing is the result: Mosaic's nine-term loss looks **under-regularised**,
  and Part AI's question is *how much* regularisation rather than *which* structural
  prior. The sharp falsifiable prediction, not yet run: a placebo scaled to
  HelixLoss's 0.63 magnitude should reproduce helix's +0.087 exactly.

  The superseded first pass is kept below, because the sequence is the lesson — a
  single-replicate baseline, then two held-out engines agreeing, then a control that
  removed the attribution.

- ~~**Part AI's first data point: `HelixLoss` at 0.1 helps, the Rg hinge at 0.1 does
  not.**~~ **SUPERSEDED — see above.** Four arms of the newly wired `ss_bias` knob (none / helix / compact /
  helix+compact), 8 designs each with 2 replicates per arm, refolded on **both**
  held-out engines — AF3 and ESMFold2, never Boltz-2, which Mosaic optimises by
  construction. Permutation test, n=16 vs 16:

  | arm | AF3 Δ | AF3 p | ESMFold2 Δ | ESM p |
  |---|---|---|---|---|
  | **helix** | **+0.111** | **0.0062** | +0.093 | 0.088 |
  | compact | +0.031 | 0.489 | +0.021 | 0.699 |
  | helix+compact | +0.073 | 0.070 | +0.060 | 0.317 |

  AF3's helix result survives Bonferroni over all six tests. ESMFold2 agrees in
  direction and magnitude without reaching significance, being the noisier engine
  (baseline sd 0.155 vs 0.117). Stacking the two terms is *worse* than helix alone,
  and a geometry readout found the compact arm produced binders **looser** than
  baseline (Rg/expected 1.204 vs 1.104) — it failed at its own stated job.

  **Read with the limitation first: the target is a helix.** A helix-promoting term
  helping on the 32-aa CALCA helix is the least surprising possible outcome, and may
  be target-matched rather than generally useful. One target, one binder length, and
  the arms do not share an objective — so "the extra term regularises against
  Boltz-2 overfitting" is an unexcluded alternative, because the control that would
  separate it (an unrelated term of similar magnitude) was not run.

  The methodological point worth keeping: the first pass had **one** baseline
  replicate and showed +0.143/+0.134. A second baseline moved the control by
  0.065–0.080 — comparable to the effects — and cut every delta by about a third,
  leaving one of three arms standing. The control, not the arms, was the experiment's
  weakest joint.

### Added

- **`adaptyv` labels rebuilt from the raw exports' `evaluations`, not the flat columns.**
  Prompted by a finding on the `docs/adaptyv-proteinbase-one-dataset` branch: the exports are
  long-format per (design, target) with replicates, and `master_designs.csv`'s flattened
  `binding`/`kd` columns silently pick a target and a replicate, so a design counter-screened
  against two targets can yield a chimeric row. Checked rather than assumed, and the outcome
  was better than feared: **2,018/2,018 of our rows match the exports**, with two egfr/il7r
  rows corrected (binders 323 → 325) and expression corrected from the flat file's 1,795/223
  to the export's 1,810/208. Labels now carry `n_binding_replicates` (median **6**) and
  `replicates_disagree` (**7** of 2,018 pairs).

  **The nipah discrepancy is resolved, and it was the flat file's error, not ours.** Nipah's
  labels come from a *separate* export, `proteinbase_collection_nipah-binder-competition-results.csv`,
  which screened against **two** targets — `nipah-glycoprotein-g` and `human-serum-albumin`.
  All 1,030 of our nipah rows match it exactly (103 binders both ways). `master_designs.csv`'s
  "927 designs / 1 binder" is the flattening artifact. The manifest now says plainly: do not
  take labels from that file.

- **First pool registered in the label registry: `adaptyv`** (Part Y shipped as a working
  library whose `list_benchmarks()` returned `[]`). 2,018 labelled designs over 4 targets;
  the manifest is committed, the label rows are not — they live in the private store named
  by `$BINDERSCOUT_BENCHMARK_STORE` and are verified against the manifest's SHA-256. Only
  Adaptyv is registered: our own SPOC panels are deliberately left out for now.

  The manifest carries four caveats, two of which bound what may be computed from the pool:
  Adaptyv and ProteinBase are **one** dataset (75.6 % design overlap, so agreeing figures
  from the two refold batches are not independent replication); only **563 of the 2,018**
  designs were scored by all three engines, which is the subset every published macro-AUC
  including 0.7113 comes from, and coverage was never random, so a figure recomputed on all
  2,018 is not comparable; non-expressed designs are labelled non-binders (immaterial here
  at 20 of 305 negatives, **−0.002**, but the identical conflation moves our 125-design
  CALCA panel by ~0.22, so the "immaterial" finding must not be carried to a smaller pool);
  and the nipah labels **disagree with the source table** — 1,030 labelled / 103 binders
  here against `master_designs.csv`'s `nipah-glycoprotein-g` at 927 / 1, which is
  unresolved and makes any nipah-inclusive number provisional.

- **`tests/test_registered_pools_are_wellformed.py`** — validates the manifests actually in
  the tree, which nothing did: the existing suite exercises the library against synthetic
  manifests under `tmp_path`, so a malformed real manifest would only surface when someone
  loaded that pool, by which time its number carries a right-looking name. Checks the audit
  fields, that `name` matches its directory (a mismatch loads one pool's provenance against
  another's rows), that the checksum is a real digest rather than the schema's placeholder,
  that caveats are not a stub, and that the declared label file is neither present nor
  tracked **and would be gitignored** — `git add` refuses an ignored path without `-f`, so
  that last one is the guard that actually prevents the irreversible mistake. Runs with no
  private data, which is every CI run. Mutation-tested against five reversions.

- **`agreement_denom` — `agreement_count` now ships with a per-design denominator.**
  `(vals > thr).fillna(False)` is False both when an engine scored a design and rejected it
  and when the engine never scored it at all, so `agreement_count = 1` could not
  distinguish "two engines doubt this" from "two engines never ran" — opposite meanings,
  only one of which is a statement about the design. Measured on the canonical benchmark:
  **99 labelled designs carry exactly 2 of 3 engines**, so their count is capped at 2 and
  can never reach 3 while sitting in the same table as designs whose ceiling is 3.
  `consensus_iptm_mean` has carried `consensus_iptm_n` for this reason; `agreement_count`
  shipped without the equivalent. The wet-lab note now reads `agreement 1 of 3 engines` and
  stays **silent** where the bar is unreachable. The pool-level guard this replaces could
  not catch the case that actually occurs — all three engine columns present, empty only for
  *this* design because its refold failed.

- **`docs/PLAN_2.0_PART_AK_verify_the_rank.md`** — planned, nothing launched. Scoped to
  *verify* the existing ranking, not re-scope it: no new metric, no engine change, no
  normalisation, no metric search. Step AK0 is free and blocking.

- **`Evaluator/docs/evaluation/DRAFT_evaluation_reference.md`** — the consolidated
  ranking/metrics reference, under review. Committed as a DRAFT so it is not lost; intended
  to split into `ranking.md` + `metrics.md` in that directory once settled.

- **`tools/loss_screen.py` — a CPU screen for candidate design-loss terms.** A Mosaic
  loss arm costs a hallucination campaign (>24 GB VRAM) plus refolds on two
  independent engines. Most bad candidates are not *mediocre*, they are wrongly
  shaped, and the wrong shape is visible from the gradient in under a second.

  Four checks. **direction** — at a composition where the term is active, does the
  gradient push the named residue class the way the author intends (a loss is
  minimised, so a positive gradient *suppresses*). **length** — hold the
  distribution fixed, vary L; catches the extensive-vs-intensive bug that silently
  penalises long binders. **silence** — a one-sided hinge must be exactly inert once
  the property holds, because a term that always pulls always distorts, invisibly.
  **order** — shuffling preserves composition and destroys adjacency, so a term
  claiming to read order must move more than shuffle noise.

  Backend-agnostic: `jax.grad` inside the Mosaic venv where real terms live, central
  finite differences on numpy otherwise, so the harness and its tests run in CI with
  no GPU and no jax.

  Validated by rebuilding the case that motivated it. Upstream Mosaic's
  `UnigramExcess` (`sum(relu(empirical − natural)²)`) is **flagged**: being one-sided
  *above* the natural marginal makes it inert on exactly the residues hallucination
  over-produces and active only on those below it, most of which are hydrophobic —
  measured here at **2.66×** more suppressive gradient on hydrophobics than on
  everything else combined, wrong-signed for promoting a hydrophobic core. The
  one-sided hydrophobic-*deficit* hinge derived as its replacement **passes** all
  three. Both are test fixtures, so the harness is pinned against the real defect
  rather than a synthetic one (10 mutations, all caught).

  Two design errors of my own were caught by writing those fixtures, and both are
  encoded in the tool. Direction must be probed where the term is **active** — a
  correct one-sided hinge is inert at a uniform PSSM, so probing only there would
  flag the good term and pass the bad one. And the length check defaults to the
  **design-time** regime (exact-frequency PSSM, the smooth input a loss actually
  sees), not iid sampling: in the discrete regime *both* a wrongly-shaped and a
  correctly-shaped one-sided term look length-confounded, because both fire only on
  finite-sample excursions, so reading that as a design-time verdict rejects the
  correct term too.

  A pass is advisory — it means a term is not obviously mis-shaped, not that it
  helps. That still costs a campaign, judged on AF3 or ESMFold2 and never on
  Boltz-2, which Mosaic optimises by construction.

### Added — 2.0 evaluation and provenance

- **Per-design `generation_index`, with its provenance.** `ExtractedBinder`
  records where a design fell in its campaign's generation order, for the
  discovery-rank metric. Five of eight tools can report one — from a counter the
  tool wrote (Mosaic, Protein-Hunter), a join on design hash (BindCraft 2's
  `trajectory`), or a parsed identifier (BoltzGen, RFD3). **Row position is used
  for none of them**: where a file happens to be in generation order the
  extractor re-sorts before iterating, and where it is not, the order is a
  quality sort. PXDesign, Proteina-Complexa and BindCraft 1 report
  `unavailable`, which is a first-class answer — for Proteina-Complexa it is the
  *correct* one, since under MCTS the pool is a flattened tree and a scalar index
  has no consistent meaning.
- **Self-consistency RMSD** (`self_consistency.py`) — the second axis every
  published RFdiffusion-family gate couples with interface confidence, and which
  this pipeline lacked. Target-aligned: superposing on the binder would measure
  its fold, superposing on the target measures its placement, and a binder that
  folds perfectly while docking on the wrong face scores ~0 Å the first way.
- **BindCraft's confidence filters, ported** (`confidence_gate.py`): i_pAE
  ≤ 10.85 Å, binder pLDDT ≥ 0.8, interface i_pTM ≥ 0.5. The conversion is exact
  — ColabDesign divides PAE by 31.0, so BindCraft's normalised 0.35 is 10.85 Å,
  not 31.75 (the last PAE bin *centre*, not the divisor).
- **Private label registry** (`benchmarks.py`, Part Y). The repo carries
  `MANIFEST.json` per pool — enough to audit a result; the label rows live in a
  private store resolved by checksum. Every failure mode raises rather than
  degrading, because each yields a wrong number under a right-looking name.
- **A static config-builder page** (`docs/config-builder.html`), generated from
  `REQUIRED_CFG_KEYS` so it cannot drift, with a test that fails when it does.
- **RFD3's geometry gate runs before ProteinMPNN**, and its designs now get a
  native rank from a Boltz-2 fold-back instead of sequence recovery.
- Original tool CSVs and design structures are kept by every run
  (`--tool-root`, `--collect-structures`), which previously they were not.

### Fixed — 2.0

- **ESMFold2, the default refold engine, could not fold under the 2.0 pin.** The engine runs on the
  **biohub fork** of transformers (`github.com/Biohub/transformers` @ `3a8956fb`, which reports
  version 4.57.6), the only build whose `ESMFold2Model` has `load_esmc`. PyPI transformers 5.16.1,
  5.17.0 and 5.18.0 expose a same-named class without it, so `from_pretrained(..., load_esmc=False)`
  raised `TypeError` on every released 5.x. `transformers>=5.16` and the default checkpoint
  `69869f737bef` (authored against a 5.16.0.dev0 pre-release) had replaced a working loader with one
  that cannot fold, while the env still verified clean. Reverted to `8fc3ff471022`, the revision every
  validated result used. The loader now refuses a class without `load_esmc` and names the fork and the
  mirroring procedure; neither installer pins 5.x or installs over a present fork; the pin test, which
  asserted the opposite contract, is rewritten. The fork's git URL 404s, so an env without it must
  copy `site-packages/transformers` from a machine that has it (pure Python).
- **A Boltz-2 refold could publish another run's rows.** `engine_boltz2` was the only engine that did
  not pass `--output-dir`, whose default is relative to the current directory, so `--resume` read a
  shared `refold_designs.csv`. A fresh 20-design run skipped 86 "completed" binders, folded nothing and
  reported 260 new rows, which the row guard accepted because it counts non-empty iPTM. Scoped to
  `$OUTPUT/refold_boltz2`, as AF3 and ESMFold2 already were.
- **AF3 wrote every confidence score to two decimals.** iPTM 0.87 instead of 0.868557: 81 distinct values
  over 563 designs against 563 for each other engine, which understated AF3 in every rank-based metric.
  `install/patches/af3_full_precision.py` fixes the installed package; both installers run it after
  every build (a reinstall silently undoes it), and `--verify` detects a lost patch through its
  `--check` mode. It is a script file, not a heredoc (`conda run` does not forward stdin), re-reads
  what it wrote, and fails loudly on source it does not recognise.

- **Every heredoc-fed installer patch executed nothing and reported success.**
  `run_logged` launches its command with `&`, and bash redirects an async
  command's stdin from `/dev/null`; `conda run` compounds it by not forwarding
  stdin even in the foreground, though `mamba run` does. So all four PXDesign
  site-packages patches on x86, and three on aarch64 including the load-bearing
  protenix `sm_120` + `-std=c++20` one, were skipped while the log printed a
  green check. Measured on an x86_64 workstation: a May install whose log claimed all four applied
  had none of them. Each body now goes to a temp file passed as an argv path,
  and an assertion greps the target for the marker the patch writes, so a silent
  no-op fails loudly.
- **The 2.0 env rename stranded the envs it renamed.** Nothing named the
  pre-rename spellings, so install created a duplicate beside each one, status
  and verify reported installed tools as missing, and uninstall reported success
  while leaving 28.6 GB behind. Install, status, verify and the configurator now
  resolve a legacy env in place; uninstall removes both names through
  `env_exists` + `run_logged`, never `rm -rf`, and surviving legacy envs are
  listed with their size in the "Left in place" report.
- **An uninstall could not reach five of thirteen tools.** The dispatch is now
  driven by `TOOL_REGISTRY`, so a tool cannot be installable with no uninstall
  path; TmProt gained its arm, step counter and preflight footprint, and aarch64
  gained its missing RFD3 and Proteina-Complexa dispatch.
- **`--resume` skipped exactly the designs it existed to retry.** The merger
  kept a blank refold row and dropped the retried score for the same design.
  `PartialRefoldFailure` now also exits 3 rather than 1, as the contract says.
- **`fleet.sh` probed a directory that exists on no machine**, so every probe
  reported no envs and no version. It resolves the checkout instead of
  hardcoding one spelling. `gpu_mem_guard.sh` also refuses to fork a second MPS
  daemon beside a legacy one rather than silently doubling it.
- **RFD3's ProteinMPNN checkpoint was never fetched on x86** while aarch64
  fetched it unconditionally, and verify counted only `.ckpt` so both reported
  RFD3 usable. The download moved outside the weights-dir guard and verify now
  requires the `.pt`.
- **The pre-cached AF2 weights path was renamed although the directory on disk
  was not**, so a reinstall re-downloaded weights already on the box. The
  pre-rename spelling is back in the search order as a fallback.
- **`rank` could be corrupted by a duplicate sequence.** Four unguarded left
  joins in `report.py` multiplied rows when two designs shared a sequence —
  confirmed live in a shipped 2VDY campaign, where 3 duplicates turned 439
  designs into 445 rows.
- **The Rosetta interface panel had never emitted a value.** Three stacked
  silent failures: PyRosetta replaced the string interface spec with a
  `DockingPartners` object; DAlphaBall could not load `libgfortran.so.5`; and the
  id namespaces never overlapped so both joins attached nothing.
- **Part N's affinity ranking was ranking clash energy.** `interface_energy.py`
  never relaxed while the docs said it did: on one AF3 structure, dG is +213.8
  REU unrelaxed and −89.5 after FastRelax — a sign flip against a gate of dG ≤ 0.
- **The PXDesign collector's preferred path was dead code**, globbing a file
  PXDesign deletes during its own run, so every run silently took an unranked
  fallback and shipped `pxdesign_rank` empty.
- **`extract --collect-structures` crashed in `binder-eval`**, where gemmi is
  deliberately absent — after successfully extracting every sequence.
- **Two CLAUDE.md claims were false**: usernames were not "scrubbed from tree and
  history", and Proteina-Complexa's aarch64 deprecation blamed "a different
  problem" when its AF2 reward is the same ColabDesign BindCraft runs on the GPU,
  pinned to a jax that predates sm_121.
- **Two docstrings named a conda env that has never existed**
  (`binder-eval-boltz2`); Boltz-2 refolding runs in the Mosaic venv.

### Changed

- **`agreement_count` no longer withholds `wetlab_recommended`; it is a note** (operator
  decision). It had been appending `agreement {n} < 2` to the blocking `reasons` list, so
  a low count silently vetoed the badge. It now prints in `wetlab_reason` alongside the
  blockers without suppressing the recommendation, exactly as SoluProt was moved on
  2026-09-28 — and the `report.html` glossary string advertising both as criteria, wrong
  about SoluProt for five days, was corrected with it.

  The rationale: `agreement_count` reads a **different quantity** from the rank. The rank
  averages ipTM (`*_pae_iptm`); `agreement_count` counts engines over an **absolute ipSAE**
  cut, and that cut measured *inverted* against our own Kd data. Two tests changed sign,
  and because a pair of sign-flipped tests is satisfiable by a function that never blocks
  anything, `test_wetlab_blocks_on_plddt_even_when_agreement_is_fine` holds the other side.

  Re-measured on the canonical benchmark while doing this: the figure in CLAUDE.md and in
  the benchmark's own README — "a flat null, macro-AUC 0.532, 87.2 % tied at zero" — is the
  **Cao** result, carried over without re-measurement. On the all-3-engine labelled subset
  it is **0.6295** with 70.5 % tied, and the binder rate runs 0.378 → 0.567 → **0.778** →
  0.758. So it carries real signal, is worse than the mean as a ranker, and **2-vs-3 is
  indistinguishable** — warning-shaped, not rank-shaped, and a gate at 3 would be
  unjustified.

- **Refold structures are saved under the design's `binder_id`.** All three
  engines named every artifact after the loop index — `refold7_a1b2c3d4.pdb`,
  `af3_0007.pdb`, `esmfold2_0007.pdb` — three different names for one design,
  none of them the design's own id, and the index meaningful only relative to
  the FASTA that produced it. Finding a design's structures meant joining the
  refold CSV on sequence first. They are now `<binder_id>_<engine>.pdb`, with
  `_pae.npy` and `_plddt.csv` / `_model.cif` beside them. The engine is in the
  name and not only in the directory, because the three directories get pooled —
  that is the normal way to hand over "all the PDBs", and without the suffix a
  design's three structures are three files of the same name.
  The id comes from the FASTA header `extract` already writes, so `evaluate.sh`,
  `binder-compare run` and the configurator needed no change; a design with no
  usable id keeps the old index-based name. The mapping lives in
  `binder_comparison/io/design_ids.py` and is shared with the Foldseek join, so
  a structure on disk and a row in the report agree on the name. Two designs
  claiming one id get `__2`, `__3` rather than one silently overwriting the
  other, and a mismatch between the id and sequence counts is refused before any
  GPU work — that off-by-one would name every structure after a different
  design while leaving every path resolvable.
  AF3's own prediction directory stays index-based: that layout belongs to AF3
  and `_load_top_sample` globs it. What we export carries the id.
  **Re-running an engine into the same output directory now overwrites a
  design's structure instead of accumulating a new uuid-stamped copy.**

- **BindMaster is now BinderScout, everywhere.** The repository had been
  `BinderScout` on GitHub while the CLI, the Python package, the conda
  environments and ~3,000 references stayed `bindmaster`. 2.0 closes that:
  `bindmaster` → `binderscout`, `BindMaster` → `BinderScout`,
  `BINDMASTER_*` → `BINDERSCOUT_*`. The command is `binderscout`,
  `bindmaster.py` is `binderscout.py`, `bindmaster_examples/` is
  `binderscout_examples/`, the five `.claude/skills/bindmaster-*` are
  `binderscout-*`, and the conda environments are `binderscout_pxdesign`,
  `binderscout_protein_hunter` and `binderscout_rfd3`.

  **Three names were deliberately NOT renamed**, because they do not refer to
  this project:
  - The machine hostnames in `docs/superpowers/plans/2026-07-27-fleet-orchestration.md`
    that happen to contain the old project name are **not the project**.
  - `BindMaster 2` (`docs/bindmaster2_grafts.md`, and the
    `damborik22/BindMaster2` URL) is a **separate, abandoned repository** whose
    orchestration capabilities were grafted onto the Evaluator. Renaming it to
    "BinderScout 2" would have been factually wrong and would have collided
    with BinderScout 2.0 — this version.
  - `docs/data/**` and the two dated HTML snapshots record filesystem paths as
    they were at measurement time. They are experimental records, not brand
    surface.

  **Two back-compat shims** keep pre-2.0 machines working:
  `BINDMASTER_DIR` is still honoured by the configurator, and
  `_resolve_cache_dir()` falls back to `~/.cache/bindmaster/target_msa` when
  the new path does not exist — starting that cache cold would re-query
  ColabFold for every target and trip the rate limit the cache exists to
  prevent.

  The MPS pipe directory, the floor directory and the systemd unit moved with
  everything else (`/tmp/binderscout-mps`, `/tmp/binderscout-floors`,
  `binderscout-mps.service`). **Operators on GB10 must re-install the systemd
  unit** — the old `bindmaster-mps.service` will keep running under its old
  name until it is disabled and the new unit installed, and
  `gpu_mem_guard.sh` now looks for `UNIT=binderscout-mps`.

  **Upgrading a machine that was installed before 2.0** takes four steps, none
  of which the git checkout does for you. They were derived by migrating three
  x86_64 machines and one aarch64 machine:

  1. `python3 binderscout.py configure --status` once, which writes
     `bin/binderscout` and `~/.local/bin/binderscout` and unlinks a stale
     `bindmaster` shim. It must be a real subcommand: `--version` and `--help`
     are deliberately side-effect-free and write nothing.
  2. `conda rename -n bindmaster_<tool> binderscout_<tool>` for `pxdesign`,
     `protein_hunter` and `rfd3`, on an idle box only. It is a clone-then-remove,
     so it must never run while a job is live out of the source env. The
     installer and the configurator both reuse a legacy env in place instead, so
     this is tidying rather than a prerequisite.
  3. `sed -i 's/bindmaster_/binderscout_/g' bin/{pxdesign,protein-hunter,rfd3}`
     in the same window as step 2 — those wrappers hardcode the env name, so
     they work before the rename and break after it.
  4. On GB10 only, migrate the MPS unit: `systemctl --user disable --now
     bindmaster-mps`, copy `tools/systemd/binderscout-mps.service` into
     `~/.config/systemd/user/`, then `systemctl --user enable --now
     binderscout-mps`. Until this is done the driver-enforced memory ceiling is
     off, because the guard looks for a unit that does not exist.

  The `binder-eval-esmfold2` env also needs `pip install 'transformers>=5.16'`
  if it predates 2.0: the pinned checkpoint revision cannot be parsed by the
  4.x loader, and ESMFold2 is the default refold engine.

## [1.1.1] — 2026-09-23

### Fixed

- **The GB10 guards in `bin/` were hand-applied to gitignored files.** Every
  wrapper that caps a GPU job on the DGX Spark — `bindcraft`, `bindcraft2`,
  `boltzgen`, `mosaic`, `protein-hunter`, `pxdesign` — carried its guard as a
  hand edit to a file `bin/` gitignores, so each lived on exactly one disk and
  any reinstall of that tool reverted it. `--force` did exactly that to
  `bindcraft2` on 2026-09-22, leaving it uncapped until 09-23. Uncapped is not
  an OOM risk there: the GPU pool IS system RAM, so JAX's default reserves
  91.3 GiB at import and takes the box down. All six are now generated by
  `install_aarch.sh`.
- **`install_bindcraft`'s "env already exists" path skipped the shortcut
  writer**, so re-running the installer — the obvious repair — was the one path
  that could not repair a wrapper.
- **Two preflight tests passed only where the tools were absent.** Backported to
  1.0.5; see that entry.

### Changed

- **CI shellcheck derives its file list** from `git ls-files` instead of a
  hand-maintained one that had drifted to 12 of 20 eligible scripts —
  `tools/preflight.sh` and `tools/gpu_mem_guard.sh` had never been linted,
  despite `evaluate.sh:33` refusing to run without the latter.
- **One x86_64 machine is the fleet orchestrator**, and GPU work on a GB10 is sized by querying
  `gpurun --max` rather than quoting a number. The admissible cap moves with
  load — 92 GiB with a desktop up against 90 on a quiet box — so any number
  copied into a run script is stale. `lab-deploy.md` said "All commands run from
  the aarch64 box"; `fleet.sh` has read `$FLEET_MACHINES` since `7b71d50`.

### Removed

- **RFAA**, four months after the code was deleted (2026-05-28). Its rows
  survived in `tools/gb10-env.sh`'s budget and framework tables, and a stale
  install — clone, `LigandMPNN/`, conda env and `bin/rfaa` — sat on three x86_64
  machines and one aarch64 machine. Roughly 12 GiB reclaimed. Protein-Hunter's *vendored* `LigandMPNN` is a
  different path and was left intact.

## [1.1.0] — 2026-09-23

### Added — BindCraft 2, the eighth design tool

BindCraft 2 is a rewrite of BindCraft rather than a new version of it — JAX only,
no PyRosetta, no conda, Python >=3.12, one layered campaign file instead of three
settings JSONs, mmCIF instead of PDB — so the two coexist as separate tools with
separate environments. Every archived BindCraft 1 campaign stays reproducible,
and the two can be run head-to-head against one target inside a single report.
The full design and its evidence are in
[docs/PLAN_bindcraft2_integration.md](docs/PLAN_bindcraft2_integration.md).

Installed with `binderscout install --tool bindcraft2`, which clones
[https://github.com/PacesaLab/BindCraft2](https://github.com/PacesaLab/BindCraft2) at `v1.0.1`.
BindCraft 2 went public on 2026-09-16; it is source-available under its own
non-MIT licence, so `BindCraft2/` stays gitignored and no file of it is
committed here — the same posture as the AF3 weights. `--bc2-source` overrides
the default with a `.zip`, a directory, or another git URL.

**It ranks on `i_pDAE`, not i_pTM, and not a composite.** The `rank` column is a
plain descending sort on that one metric, higher-is-better despite the name
reading like an error term, verified across all 100 rows of the two design sets
delivered to us and against a campaign run here. Ties are pervasive — the values
are rounded, giving a 17-way tie in one pool — so rank inside a tie block is
acceptance order, not quality order, and it is read from the tool's own file
rather than recomputed. Its i_pTM is design-time-biased exactly as BindCraft 1's
is, so it stays a native metric and never enters `consensus_iptm_mean`.

`BindCraft2Extractor` reads **two schemas**, because we hold pools in both: the
`3_Ranked/!_Ranked.csv` that v1.0.0 writes, and the flat `<target>_ranked.csv`
of the pre-1.0 build our archived CBG and CALCA pools came from. An extractor
written to the current documentation alone could not re-report our own archive.
It refuses rather than guesses on the tables that would parse cleanly and be
wrong — the pre-ProteinMPNN trajectory table, the candidate table that mixes
rejects in, and `accepted.csv`, which has no rank column at all.

Runs on **aarch64**, where it is opt-in for throughput rather than capability —
and the throughput cost is ours. Per trajectory a GB10 matches a 24 GB RTX 3090
(343 s against 328 s, same binder and target), but the guard that avoids the
`[N/A]` crash also disables worker fan-out, so a GB10 runs one design worker
where the 3090 packs two. It joins BindCraft 1 on that platform rather than
replacing it; both AF2-hallucination designers run there.

Two settings avoid a crash there that neither one alone does.
`design_gpu_memory_gb()` calls `float()` on nvidia-smi's memory reading behind
an `except (OSError, CalledProcessError)`; GB10 answers `[N/A]`, which raises
`ValueError` and escapes that handler. `auto_multi_gpu=false` silences only the
first of two call sites — the campaign reaches the same call again through
`campaign_subbatch_size` while `subbatch_size` is at its default. Both are
documented settings, so nothing in BindCraft 2's source is patched, and they are
applied by the machine that is running rather than written into the campaign
file, because configs here are generated on one machine and run on another.

The wizard prompts for an attempt budget on every campaign, as a yes/no before
the number. `number_of_final_designs` is a quota of *accepted* designs and
`max_trajectories` is the only cap in the package — there is no wall-clock
setting anywhere — so an unset budget runs until the quota is met. Unbounded
remains available; it cannot be reached by pressing Enter past a prompt.

### Fixed

- **`settings.json` was invalid JSON on any GB10.** `gpu_memory_mib` is the one
  unquoted value in the provenance block every run script writes, and it came
  from an `nvidia-smi` call guarded only against failure. On GB10 that query
  *succeeds* and returns the string `[N/A]`, so the guard never fired and the
  bare string landed in the file — on the machine that orchestrates the fleet.
  It went unnoticed because every `settings.json` in `runs/` was produced on the
  x86 boxes, where the query returns a number. Fixed for all eight writers at
  once.

  The test meant to catch this could not run on a machine with a GPU: it built a
  PATH to simulate "no nvidia-smi" but included `/usr/bin`, where nvidia-smi
  lives, so its own guard assertion failed before the test body ever ran. It
  passed in CI and failed for anyone with a card.

- **`boltzgen` was missing from two per-tool render registries.** `_ENGINE_BAR_LABEL`
  and `_TOOLCOL` carried only the `boltzgen_protein` and `boltzgen_nano`
  sub-variants, never the canonical key the extractor actually tags designs
  with. Found by the new registry-completeness test, which asserts every key in
  `CANONICAL_TOOL_ORDER` appears in all thirteen per-tool lookups and has a
  `.tool-<key>` CSS rule — the check that would have caught the eighth tool
  shipping with no CSS rule and a link pointing at BindCraft 1's repository.

### Added

- **A product version.** The repository had none: `binderscout.py` carried no
  constant and the bundled evaluator repeated `0.1.0` as three independent
  literals. `binderscout.__version__` is now the single source of truth for the
  product, printed by `binderscout --version` (a side-effect-free inspection
  command, like `--help`, so it answers on a read-only checkout) and destined
  for every run's `settings.json` provenance block.

  `binder-comparison` keeps its own, independent SemVer — it is a separately
  packaged library installed editable into four conda environments, and tying
  it to the product version would make every product release a reinstall. Its
  number is now declared once, in `Evaluator/pyproject.toml`, with
  `binder_comparison.__version__` and `binder-compare --version` reading it
  back through package metadata instead of restating it. The two versions are
  expected to differ.

## [1.0.0] — 2026-09-17

The seven-tool pipeline as validated and running: Mosaic, BoltzGen, BindCraft,
PXDesign, Proteina-Complexa, Protein-Hunter and RFD3, evaluated by the
three-engine cross-refold (Boltz-2 + AF3 + ESMFold2) and ranked by
`consensus_iptm_mean` behind the engine gate.

Everything below shipped in 1.0.0. The version was assigned retrospectively, at
the point the eighth tool began, so that release has a name to be compared
against — `master` is frozen here and this heading records what it contains.

> **Note.** 1.0.0 also contains a dormant `bindcraft2` key in the report's
> per-tool lookups, from "Register bindcraft2 as a first-class tool in the
> report". No extractor, installer or run path exists for it in this release,
> and a pool without `bindcraft2` rows renders identically. It is corrected and
> completed on the 1.1.0 line; do not treat the 1.0.0 registration as
> authoritative.

## [1.0.3] — 2026-09-22

Two refold-engine fixes, both found by benchmarking the engines across every GPU we
own (`docs/data/gpu_benchmark_2026-09-18/`). Both affect every machine.

### Fixed

- **AF3 no longer reserves half of a large GPU.** The discrete-host branch of
  `_default_mem_fraction` floored the fraction at 0.5 (`max(frac, 0.5)`), so AF3
  reserved **22.5 GiB on an L40S and 70.2 GiB on an H200** — for a working set
  measured at **2.3–5.2 GiB** across 150–900 tokens. Because `PREALLOCATE` stays
  true (correctly — `false` removes the only ceiling), that is taken in full at
  import, so **two concurrent AF3 jobs would not fit a 140 GB H200** and the
  concurrency sweep had to override the fraction by hand. The floor is now a
  ceiling (`min(frac, 0.5)`): every host reserves the 12 GiB target, already ~2.3×
  the largest measured need, and ~11 concurrent jobs fit an H200 where 2 did.
  The 0.5 clamp still bites on small cards, where `12/23.6 = 0.508` would
  otherwise hand AF3 more than half a 24 GB card. A complex far outside our regime
  needs `AF3_XLA_MEM_FRACTION` raised for that run.

- **ESMFold2 now exits non-zero when every binder fails.** It caught each
  per-binder failure, wrote an **empty row** and continued, so a CUDA OOM printed
  `Wrote 1 row(s)` and returned 0 — measured on a 24 GB card at 900 tokens, where
  the engine needs ~28.7 GB. The run looked complete while contributing a column
  of blanks, and every design silently dropped to a 2-engine mean and failed the
  ≥3-engine gate for no visible reason: **a design demoted for a hardware reason,
  reading as a quality judgement.** All four empty-row paths now count, and an
  all-failed run raises with the first underlying error. `refold_af3.py` and
  `refold_boltz2.py` already had this guard; ESMFold2 was the only engine missing it.


## [1.0.2] — 2026-09-18

### Fixed

- **ESMFold2 — the default refold engine — was broken on every machine tracking
  `master`.** `ESMFold2Model.from_pretrained()` was called with no `revision`, so each
  host silently got whatever upstream had tagged `main` on the day it installed. A
  machine that installed on 2026-09-16 gets `69869f737bef`, whose config nests
  `architectures` / `model_type` inside `structure_head`; the pinned transformers
  4.57.6 `DiffusionStructureHeadConfig` rejects those and the run dies with
  `TypeError: ... unexpected keyword argument 'architectures'`. Confirmed on an x86_64 workstation while
  benchmarking. The revision is now pinned to `8fc3ff471022`, the one every validated
  result in this project was produced with, overridable per-run via `$ESMFOLD2_REVISION`.
  The engine also announces which revision it loaded, so an unpinned host is visible in
  the log instead of silent.

  Two machines in the same campaign could previously fold with **different weights** and
  nothing anywhere said so — and because a failing engine still left the run looking
  complete, it could contribute an entire engine of nothing to a 3-engine gate.


## [1.0.1] — 2026-09-18

Three aarch64 platform fixes. Each tool reported itself healthy and was not:
BindCraft 1 was silently on the CPU, and PXDesign could not launch a CUDA kernel
at all. No behaviour change on x86_64.

### Fixed

- **BindCraft 1 now runs on the GPU on DGX Spark (GB10 / sm_121).** It was never
  using the GPU there: the configurator emitted `export JAX_PLATFORMS=cpu` for
  aarch64, so trajectories ran on the CPU at 1-2.5 h each. Removing that exposes
  the real fault -- `jaxlib 0.4.34`'s bundled LLVM knows `sm_20..sm_90a` only, so
  for GB10 (cc 12.1) it falls back to a subtarget without bf16, while ColabDesign
  runs AF2 in bf16 by default. Every AF2 graph then died at compile with
  `Unsupported conversion from bf16 to f16` / `LLVM ERROR: Unsupported rounding
  mode for conversion`. The installer now pins `jax[cuda12]==0.6.2`: the first
  jaxlib that knows `sm_121` *and* still ships a cp310 wheel, so the py3.10 env
  and its aarch64 conda PyRosetta are untouched, and ColabDesign needs no patch
  (`jax.lib.xla_bridge.get_backend` is still there, deprecated). Measured on a
  120aa target + 40aa binder: **2.39 s/iter against 5.40 s/iter** for the only
  configuration that made 0.4.34 run at all (bf16 disabled, which also doubles
  memory). The generated run script now also caps GPU memory -- on this box the
  GPU pool *is* system RAM, so XLA's default 0.75 would reserve ~91 GiB of 122
  and take the machine down.

- **PXDesign can launch CUDA kernels again.** `torch.cuda.is_available()`
  returned `True` while every kernel launch failed with `no kernel image is
  available for execution on the device`: a `torch 2.5.1` built against cu124 had
  displaced the cu130 build, and CUDA 12.4 predates Blackwell. Reinstalling from
  the cu130 index then exposed a second fault -- protenix hardcodes
  `-std=c++17` and torch >= 2.9 headers hard-error on it, so its fused LayerNorm
  extension would not build. The installer's protenix patch now applies the arch
  fix and the C++20 fix **independently** (the previous single "already patched"
  guard skipped the second one forever on any env an older installer had already
  arch-patched) and clears stale build artefacts left from the previous torch ABI.

- **PXDesign's AF2 evaluation no longer aborts on aarch64.** Hidden behind the
  above: with diffusion working, the pipeline reached the AF2 eval and died on a
  `JSONDecodeError` reading an empty file. The real event was one line earlier --
  `Run subprocess success: -6`, a SIGABRT from
  `LLVM ERROR: Cannot select: nxv4bf16 = AArch64ISD::UINT_TO_FP_MERGE_PASSTHRU`.
  jaxlib's **AArch64** backend cannot lower a bf16 convert under SVE, the AF2
  eval is pinned to the CPU here, and ColabDesign defaults to bf16. The installer
  now patches `use_bfloat16=False` into both pxdbench AF2 entry points (bf16 buys
  nothing on a CPU path; x86 is unaffected). Verified: both AF2 subprocesses
  return 0, and the eval writes real metrics -- pLDDT 0.65, pTM 0.52, i_pTM 0.37
  -- against a two-chain 675-atom complex.

- **Documentation corrected against the shipped behaviour.** The README asserted AF3
  needs **>=100 GB of GPU memory** in seven places while already carrying the
  correction elsewhere in the same file; AF3 peaks at ~4.4 GiB for a 258-391 token
  complex and runs on a 24 GB card, and the real constraint is the **gated weights**.
  The README's aarch64 notes also said BindCraft "may fail because jaxlib CUDA conda
  packages are not available for aarch64" (those exist; the problem was the LLVM
  target) and that BoltzGen takes plain PyPI torch "without +cuXXX suffix" -- the
  opposite of the truth, and acting on it replaces a working CUDA build with a
  CPU-only one. Verified against the live env: `torch 2.10.0+cu130`, arch list
  `sm_120`/`compute_120`.

- **`binderscout evaluate <run-dir>` removed from the docs: it never worked.**
  `binderscout evaluate` is a passthrough to `binder-compare`, whose first argument
  must be a subcommand -- a directory is rejected by argparse. It was nevertheless
  shown as the primary usage in `CLAUDE.md`'s Quick start, twice in
  `Evaluator/README.md` (with `--refold` / `--target` flags that also do not exist),
  and in the orchestrator skill, which would send an agent straight into the error.
  All four now show `bash runs/<name>/run_evaluate.sh`.

- **The agent skills no longer instruct a ranking we removed.** `binderscout-orchestrator`
  still described the pre-Part-U pipeline: *"Ranking is `agreement_count` desc, then
  `ipsae_min` desc."* `agreement_count` is a flat null as a screen — macro-AUC **0.532**
  with **87.2 %** of designs tied at zero — and the shipped ranking is a cross-engine gate
  then `consensus_iptm_mean`. Skills are executable instructions, so an agent reading that
  line would have ranked a whole campaign by a discredited metric. The same skill also
  documented the non-existent `binderscout evaluate <run-dir>` interface, and the evaluator
  and target-analyst skills labelled AF3 "big-VRAM" rather than gated-weights. Verified
  already-correct and left alone: `binderscout-evaluator` (both files state the removals),
  `orchestrator/references/evaluation.md`, and `tools/protenix.md`.

### Note on this file

Everything previously filed under `[Unreleased]` shipped in **v1.0.0** -- the tag
sits on the commit this release branches from, with no commits in between -- so
that section is now labelled `[1.0.0]` rather than left open.

## [1.0.0] — 2026-09-16

### Fixed (2026-08-14 — the rest of the terminal-path audit: the gate you cannot reach, the wizard session you lose, the menu that errors)

Follow-on to the two fixes below, closing every remaining finding from the same pass.

- **The cross-engine gate was unreachable from the script that runs the pipeline.**
  `evaluate.sh` never passed `--min-engines`, so the default of 3 always applied — and
  AF3 needs >100 GB of GPU memory, so on a typical host only Boltz-2 and ESMFold2 run
  and *every* design failed the gate. The operator had to know to re-run the report
  step by hand. `evaluate.sh` gained `--min-engines N` (validated: integer, floor 2)
  and now counts the engines it will actually run, warning **before** any GPU time is
  spent and naming the flag that fixes it. The gate is deliberately **not** derived
  from the local install — that would make two operators with the same designs produce
  different rankings, the same contradiction Part J's revert removed for Protenix.
- **`evaluate.sh --help` required a Mosaic install, and `--skip-boltz2` did not skip it.**
  The Mosaic venv was resolved at the top of the script, before argument parsing and
  unconditionally, so the help could not be read without a full install and an
  AF3 + ESMFold2 evaluation was refused on a host that legitimately has no Mosaic. Now
  resolved after parsing, and only when Boltz-2 will run.
- **The configurator turned a missing tool into a traceback and ate the session.**
  Step 5 shows install status but never stopped you enabling a tool that is not there,
  and the generators read that tool's files unguarded — BindCraft's filter/advanced
  presets, Mosaic's `hallucinate_binderscout.py`, BoltzGen's nanobody scaffolds. The
  failure landed as a bare `FileNotFoundError` partway through, over a half-written run
  directory. A new `preflight()` runs before anything is written and reports **every**
  problem at once — each missing asset with the install command that supplies it —
  then exits 1.
- **`--config` replay is validated.** `load_run_config` checked three keys while the
  generators read some fifty more directly, so a hand-edited config died with a bare
  `KeyError: 'boltzgen_intermediate'` mid-generation. `REQUIRED_CFG_KEYS` names what
  each tool needs; missing keys are listed by name, with a pointer to a wizard-written
  config. The map is re-derived from the writer sources by a test, so a new `cfg["…"]`
  in a generator cannot reach a user as a KeyError.
- **`config.json` is written first, not last.** It was the final line of `generate()`,
  so any failure before it cost the operator the entire wizard session — ~80 answers,
  nothing to replay. Written immediately after the run directory is created, and again
  at the end to capture the paths `generate()` derives.
- **The TUI's "Evaluate results" entry showed an error, not the subcommands.** It ran
  `binderscout evaluate` with no arguments, which reaches argparse with a required
  subcommand missing: one usage line, exit 2 — while the code comment promised it
  "shows available subcommands". It now asks for `--help`.
- **`run_all.sh` housekeeping.** The header comment named all seven tools regardless of
  what was enabled, so a two-tool run advertised five it would never start; it is now
  built from the enabled set. The output check ran `ls -A` on paths that are CSVs for
  four of the tools, and `ls -A` on a file prints its name — so a 0-byte
  `sequences.csv` counted as real output. Directories and files are now checked as what
  they are. The `# shellcheck disable=SC1090` directive was present in three of the six
  generated scripts; all six carry it, so every generated script is shellcheck-clean.

### Added (2026-08-14 — README documents all 22 `binder-compare` subcommands)

Fifteen had no human-facing documentation: `analyze-target`, `mature`, `monomer`,
`affinity` and `wetlab` existed only inside `.claude/skills/` — agent instructions, not
a manual — and `prefilter`, `qc-annotate`, `epitope`, `epitope-map`, `beta-check`,
`diversity`, `hits` and `validate` were documented nowhere, so a terminal user could
not discover them without reading `main.py`. They are now one grouped table, and
`tests/test_readme_documents_the_cli.py` fails if the table and the parser disagree in
either direction — an undocumented new subcommand, or a documented one that argparse
would reject.

### Fixed (2026-08-14 — two silent failures in the terminal path: a void ranking, and a pipeline that stopped at the first casualty)

Both found by driving the non-agent path end to end (`configure --config` → generated
run scripts → `extract` → `report`) on synthetic data. Neither is reachable from the
unit tests as they stood, and neither announced itself at runtime.

- **A report built without its PAE files produced a `rank` column that ranked nothing, silently.**
  Every `{engine}_pae_iptm` — the sole input to `consensus_iptm` / `consensus_iptm_mean`,
  i.e. the whole ranking — is recomputed from the `.npy` PAE matrices named in the refold
  CSVs, *not* from the CSV's own `iptm`. When those paths did not resolve, all three
  loaders appended NaN and moved on without a word, and `rank_designs`' "nothing cleared
  the gate" warning was guarded by `cons.notna().any()`, which is false precisely when
  *no* engine scored *anything*. Result: exit 0, a full `metrics.csv` and `report.html`,
  `passes_engine_gate` False on every row, `consensus_iptm_mean` empty — and `rank`
  populated 1..N from the tiebreakers alone. This is the shape of a results directory
  separated from its CSVs (a `fleet.sh fetch`, an archived run, a CSV copied on its own).
  `add_boltz_ipsae_from_files`, `add_ipsae_from_pae_files` and `add_iptm_from_pae_files`
  now emit one aggregate `[pae] N/M PAE files … were not found` per call (not per row — a
  real pool is thousands of designs), naming the column and the `base_dir` that was tried;
  a blank path is still not counted, since that means the engine never folded that design.
  `rank_designs` gained the zero-coverage branch the existing test could not reach.
- **One tool's failure ended the whole campaign.** `run_all.sh` ran under `set -euo
  pipefail` with a bare `"$RUN_DIR/run_<tool>.sh"` per step and a `check_outputs … exit 1`
  after each, so a BoltzGen OOM at hour 2 aborted the script: RFD3 and Protein-Hunter
  never started, and the Evaluator never ran on the designs that *had* finished. The
  Mosaic block already carried this fix and the comment explaining why; it now applies to
  every step. Each tool runs through a `run_tool` helper that records the failure and
  returns, the Evaluator reports on whatever completed, and the script exits non-zero at
  the end naming every failed step. Because a failed tool leaves an empty output dir and
  `extract` treats that as fatal (deliberately — a mistyped path must not silently shrink
  the pool), `run_all.sh` exports `BINDERSCOUT_ALLOW_EMPTY=1` when it knows a tool died;
  `run_evaluate.sh` passes `--allow-empty` only then, so a hand-run evaluation stays
  strict. An entirely empty pool still errors inside `extract`.

### Fixed (2026-08-14 — docs: the Known-issues list had outlived every issue in it)

`README.md` listed thirteen findings (F1, F2, F3, F5, F8, F9, F15, F20, F33, F34, F38,
F40, F41) as live defects with workarounds. All thirteen were verified fixed in the
current tree — `run` accepts all seven tools, `run_evaluate.sh` points `--rfd3` at the
directory `run_rfd3.sh` writes, `extract` errors on a per-tool yield of zero, NGL is
inlined from the vendored copy, the ranking gates on `consensus_iptm_n`, and so on — so
a reader was being told to apply workarounds for problems that no longer exist. The
tables are replaced by what is actually true today (the configurator's traceback-on-
missing-tool, the unvalidated `--config` replay, `evaluate.sh` having no `--min-engines`
passthrough, the TUI's dead-end Evaluate entry) plus the PAE caveat above.

Also corrected: `CLAUDE.md`'s Evaluate section documented `binderscout evaluate
runs/<name>`, `--metric`, `--top`, `--refold` and `--target`, none of which have existed
since `evaluate` became a `binder-compare` passthrough — argparse rejects all of them;
`CLAUDE.md`'s status line stopped at Part M (master is through Part U) and pointed at
the pre-rename repository URL; `install.sh --help` omitted `soluprot` from the `--tool
all` list it *is* in, called it "opt-in only" and "x86 only (USEARCH dep is x86 binary)"
with TMHMM/drive5.com download instructions, when both platforms build open-source
USEARCH v12 from source and the shipped `--no_tmhmm` model needs neither; and
`binderscout --help` still advertised `--tool bindcraft|boltzgen|mosaic|all` out of
eleven valid values.

### Fixed (2026-07-29 — candidates.csv: every cell now describes the sequence in its own row)

Follow-on to the shortlist fixes below, all found by reading the shipped CALCA top-50 file. The common defect: a cell was resolved through `design_group`, so it printed a number belonging to a **sibling** — a different MPNN sequence of the same backbone.

- **"Ranking native" on the refold block came from the backbone.** Our rank-22 row holds `l127_s975277_mpnn4` and printed native rank **4**, which is `_mpnn3`'s; `_mpnn4`'s own native rank is 10. This is visible precisely because the tool and the refold disagree about which sibling is better — BindCraft scores `_mpnn3` 0.890 vs `_mpnn4` 0.880, while our engines score `_mpnn4` 0.921 vs `_mpnn3` 0.917. Native rank is now computed **per sequence** over every in-pool design the tool ranked (`collapse_native_df` gains `collapse=False`).
- **The per-tool native block was being collapsed.** Backbone collapse exists so *our* shortlist does not spend slots on several MPNN sequences of one design; it was also rewriting each tool's own top-N, which is not ours to renumber. BindCraft's native top-20 came out as `1,2,3,4,7,8,11,14,15,16,18,19,21,23,24,26,27,29,30,33` — holes wherever a sibling of an already-listed backbone was dropped. Native blocks now reproduce the tool's list untouched: **every tool on both live pools reads 1..20 with no holes.** The refold block still collapses and therefore still skips a number where a sibling was dropped — that skip is the point of the collapse, and it is the only place collapse belongs.
- **A sequence listed twice in a native CSV took the *last* copy's rank**, because the lookup was a dict comprehension. First occurrence (the better rank) now wins. No native CSV in either live pool has an in-pool duplicate, so nothing shipped was affected.

Both rankings count sequences, and every cell is looked up by sequence, never by `design_group`. Verified on both pools: **0** native rows and **0** refold rows quote a rank belonging to a different sequence.

Not a code change, but worth recording: these tools' headline metrics are coarse enough that native rank was largely arbitrary. BindCraft reports `Average_i_pTM` to 2 decimals — 314 of 350 values tied, and the value at native #4 was shared by five designs occupying ranks 2–6. The campaign-side snapshot builders now sort on a chain (`Average_i_pTM` → `Average_i_pAE` → `Average_pLDDT` → `MPNN_score`, directions checked against the data: ρ = −0.73 / +0.59 / −0.16), taking distinct values from 36 to 346 of 350 and unseparated sibling groups from 38 to 2 of 153.

### Deprecated (2026-07-29 — Proteina-Complexa on aarch64 / DGX Spark: not viable)

**Run upstream Proteina-Complexa on x86_64. It is deprecated on Spark — a throughput verdict, not an install failure.**

The install works and was under-described before: upstream `complexa` (`916eaae`) runs on Spark (uv venv, torch 2.13.0+cu130, GB10/sm_121) and has **produced real designs there**, reproducible byte-identically 16 days later. It is also **not a different algorithm** — both platforms run one reward model, `af2folding` with `i_pae = -1.0` and every other weight zero. Three previously-recorded blockers were stale: tmol's CUDA kernels **do** build at sm_121, `rf3` **is** installed and working, and the `torch_scatter` shim is **never entered** (`fold_emb` is absent from the shipped checkpoint). The old "PyG / torchtext lack aarch64 wheels" rationale in `CLAUDE.md` and the installer was simply wrong — PC imports neither.

The real blocker is that **no CUDA `jaxlib` exists for aarch64**, so the AF2 reward — the only member of the composite — runs on CPU:

| | H200 | GB10 (Spark) |
|---|---|---|
| per AF2 call | ≤ 2.46 s | **~320 s** |
| 100-design MCTS replicate (generate) | 2.25 h | **12.2 days** |
| ApoE4 campaign, 5 replicates | 16 h 12 m | ~61 days |
| PC-v3, 50 replicates | ~2 weeks | **~1.7 years** |

The production recipe is `search.algorithm=mcts, n_simulations=8`, whose budget is fixed by construction at `nsamples × (1 + 8×4)` = 3300 AF2 calls per 100-design replicate. Threading cannot rescue it — AF2-on-CPU asymptotes at ~4 of 20 cores — and `evaluate` adds a second CPU wall because `binder_folding_method: colabdesign` is also JAX.

Two traps recorded so they are not rediscovered:

- **Do not switch to `best-of-n` to make it affordable.** It costs ~1 AF2 call per sample only because `best_of_n_search.py` / `single_pass_generation.py` never call `compute_reward_from_samples` — the reward is post-hoc ranking. MCTS was adopted on 2VDY because it beat best-of-n **10× at iPTM ≥ 0.85 in a third of the wall clock**. Under MCTS the reward is backpropagated into node statistics, so CPU-vs-GPU floats change the search *trajectory*, not just the ordering.
- **Do not expect identical designs from any two machines.** `generate.py:596` deliberately enables TF32, there is no `use_deterministic_algorithms` / `cudnn.deterministic` / `CUBLAS_WORKSPACE_CONFIG` anywhere, and a 400-step SDE amplifies the drift. Bit-identity holds only for same box + same stack + same config — and even there `dataloader.batch_size` alone changes the designs at a fixed seed, so `seed=X` is not a sufficient provenance record.

Reopens only if a CUDA jaxlib for aarch64/sm_121 appears, or if a GPU-native reward replaces AF2 (`rf3` is installed on Spark and PC's rf3 folding reward is commented out at `binder_generate.yaml:194-213` — a different objective, so a new experiment, not parity). `install/install_aarch.sh` now refuses with the real reason and the numbers; the full verdict was recorded in `docs/plans.md`.
### Fixed (2026-07-29 — the candidates shortlist described designs that do not exist)

Both defects were found by a reader comparing `candidates.csv` against `metrics.csv` on the shipped CALCA top-50 pool, and both are *internally* consistent per file — which is why review missed them. Every figure below is measured on that pool (350 designs, 7 tools) and on the 2VDY combined pool (350 designs, 7 tools).

- **A native row mixed one sibling's metrics with another's rank.** A backbone can carry several sibling sequences (BindCraft MPNN re-designs, Protein-Hunter cycles). The per-tool native block printed the **best-native** sibling's sequence and metrics next to the **refold representative** sibling's rank, so a reader who looked up the stated rank found different numbers — the row described no actual design. **10 of 140 native rows** on CALCA, all BindCraft (the only tool there with siblings on one backbone). Canonical case, `bindcraft` "Ranking native" 4: sequence and `Mean_ipTM` came from `…_mpnn3` (0.917, whose true rank is 26) while "Ranking refolded" read 22, which is `…_mpnn4` (0.921). Native rows are now rendered entirely from the backbone's representative, so sequence, metrics and rank describe one molecule. "Ranking native" still resolves by `design_group`, so a representative that is a different sibling than the native-best one keeps its backbone's native rank.

- **`rank` named two different things.** `cli/report.py` reassigns a **dense** rank to the display frame after collapsing near-duplicate variants, but `metrics.csv` kept a rank over every refolded *sequence*. Both columns are called `rank`, so the same number identified different designs depending on the file: **5 of the 30** `top30_candidates.csv` rows and **25 of the 50** `candidates.csv` rows disagreed with `metrics.csv` on CALCA, drifting one place per collapsed sibling above them. (The pre-Part-U build hid this differently — its shortlist quoted the full-pool rank, so `top30_candidates.csv` held 30 rows whose ranks ran 1..31 with **26 missing**.) `rank` now counts **distinct designs** everywhere; a collapsed sibling carries no rank, because it is an alternative sequence for a backbone that is already ranked and `design_group` / `is_representative` already record that. CALCA: 16 of 350 rows unranked, ranking runs 1..334. 2VDY: nothing collapses, 1..350, unchanged. Disagreements across all three files: **0** on both pools.

- **A native CSV covering only *part* of the refold pool was silent.** `collapse_native_df` already refuses quietly-empty snapshots, but the partial case just left blank cells with no explanation. On the 2VDY combined pool three snapshots predate a backfill that topped each tool to 50 — mosaic 48/50, boltzgen_protein 48/50, proteina_complexa 47/50 — so 7 designs had no native rank and 2 surfaced as blanks in the refold top-50. `build_candidates_table` now warns with the per-tool count and the likely cause.

- **`candidates.csv` refold block goes to top-50** (was top-30) by request; per-tool native blocks stay at 20. The CLI line no longer hard-codes either number.

### Fixed (2026-07-29 — the docs and the agent instructions catch up with Part U)

Part U removed `--rank-by` and `--screen-metric` from the code but not from the things that *tell people and agents to use them*.

- **`binder-compare validate --target-pdb` returned an error string as the target sequence.** `cli/validate.py` imported `extract_sequence_from_pdb` from `io.read`, which defines no such function — the real helper is `parse_pdb_sequence`. The import sat inside a bare `except Exception: return f"ERROR: {e}"`, so the command reported the ImportError *as the sequence*, compared every design length against it, and exited 0.
- **Every report shipped a pre-Part-U benchmark blurb.** `_benchmark_provenance_html()` is rendered unconditionally and still presented the retired Stage-1 max screen as live, tabulated "Mean-screen AUC / Max-screen AUC", and instructed the reader to "Pass `--screen-metric max` to revert to max-first" — a flag that now exits 2. Rewritten around the Cao 2022 result: the three-benchmark AUC ladder, why Cao's 0.556 is label censoring rather than metric failure, that metric selection is closed, and the honest headline — **~1.9× enrichment from the top decile, beating a random ordering on only 6 of 12 targets**. It is a triage filter, not a decision procedure.
- **The `binderscout-evaluator` skill prescribed a removed flag.** `SKILL.md` and `references/pipeline.md` both handed out `binder-compare report … --rank-by two_stage`; `references/ranking.md` was entirely pre-Part-U (Stage-1 `passes_max_screen`, `two_stage_rank` "is the column", "`adaptyv_rank` and `consensus_rank` coexist for comparison"). These are agent instructions — they get executed. Rewritten to the shipped ranking, with `agreement_count` demoted to diagnostic-only and the inflated `chain_iptm_interface` ≈ 0.745 figure corrected to ≈ 0.69.
- **New guard: `tests/test_skill_commands_are_real.py`** parses every `binder-compare <cmd> --flag` in `.claude/skills/**` against the real argparse subparsers, so a skill can no longer outlive the flag it documents. It reproduces both known defects before the fix.
- **Bookkeeping:** `docs/plans.md` still listed F2 (headless configurator) as deferred three days after it shipped, and budgeted a `binder-eval-af2` env that Part I deleted. `PLAN_ranking_and_engines_roadmap.md`'s Part U *section* still described the unbuilt ProtDBench harness its own summary row marked done — rewritten to record what was actually run (Cao 2022) and what stays open.

### Fixed (2026-07-28 — F44: extractor ingestion integrity — three silent-corruption classes)

Every one of these produced a **plausible, non-zero pool** with no error, so nothing downstream — including `--allow-empty` — could catch it. Measured on shipped run data, not hypothesised.

**(a) Proteina-Complexa emitted the whole complex as the binder.** The NVIDIA-native `aatype` column encodes `target + binder + poly-alanine pad`. Verified on three production runs: 2VDY (1000 designs at 500–509 aa against a 389-aa target), ApoE4 (100 at 298–305 vs 185 aa) and ApoE4-iso PC-v3 (4804/4804 rows carrying the 141-aa target as an exact prefix). Refolded unstripped, each design was scored against a target it already contained.

- `ProteinaComplexaExtractor(target_sequence=...)`, fed by a new `binder-compare extract --target-seq`. `binder-compare run` and the configurator's generated `run_evaluate.sh` both already held the target and now forward it — one line each.
- The binder END comes from `_n_<N>_` in the job-directory name (= `len(target) + len(binder)`, exact on 1100/1100 designs checked against PC's own evaluation CSVs). Where the job name has no length field, a trailing alanine run of ≥ 10 is treated as padding — above the longest genuine C-terminal alanine run on disk (7) and below the pads measured on PC-v3 (up to 42).
- With no `--target-seq`, the prefix shared by every row of a run is inferred and **the inference is announced**. A declared target that is *not* a prefix is refused rather than cut at the wrong residue (PC's `target_input` can select a sub-range).
- PC's own binder-only columns (`binder_sequence`, `self_sequence`) are now recognised and preferred — no decode, no arithmetic.
- **Result on the live PC-v3 pool: 4804 designs at 60–100 aa (was 96 at 219–241), max residual alanine tail 5.**

**(a2) RFD3's FASTA-fallback guard rejected 0 % of real concatenations.** `_MAX_PLAUSIBLE_BINDER_LEN = 500` is calibrated on binder length, not target+binder length, so it only fires when the target alone exceeds ~360 aa: on the shipped CALCA run it passed all 8000 mpnn sequences, every one carrying the same 32-aa target prefix. Replaced by a shared-prefix check — a prefix ≥ 20 aa common to every FASTA sequence refuses the pool and names `sequences.csv` as the remedy. mpnn's trailing comma (`>name, sequence_recovery=…`) no longer rides into `binder_id`.

**(b) All seven extractors resolved a multi-match glob with `matches[0]`** — raw filesystem order, no warning. Pointed at a parent of N replicates that kept ONE: 96 of 4804 rows on PC-v3, 100 of 500 on a cluster run. On an ordinary multi-variant run dir it picked `bindcraft_variant_a` out of four, and BoltzGen's `sorted()[-1]` discarded a whole 700-design pool. New `resolve_single_match()` in `extractors/base.py` **stops the run and lists every candidate**. Where several files genuinely are one pool, `extract --aggregate-replicates` opts in and reports the count. The top-level `sequences.csv` short-circuit is preserved, so a stray nested CSV cannot turn a correct run dir into an error.

**(c) A duplicate `binder_id` was a silent DROP.** `add_design_groups` keys `design_group` on it and the report keeps only the first row per group, so the colliding design vanished from the report, Top-N, candidates and diversity while surviving in `metrics.csv` — announced by a "Collapsing N near-duplicate variant(s)" line indistinguishable from the intended Protein-Hunter/BindCraft collapse. **PC on 2VDY collapsed 1000 designs into 253 ids (75 %); a merged Protein-Hunter summary gave 1654 rows → 1487 ids with all 164 collisions covering *different* sequences.**

- `_disambiguate_ids` moved from PXDesign (its only user) to `extractors/base.py` and applied in all seven.
- Proteina-Complexa ids are re-keyed on the replicate directory (`complexa_s<seed>_<tag>`) — `metadata_tag` carries no seed, so it collides across replicates by construction.
- The six advisory `binder_id` joins in `cli/report.py` gained the `validate="m:1"` that `merger.py` already used on its sequence join, so a sidecar built from a colliding pool can no longer multiply metrics rows.

24 new tests; the clean layouts are unchanged (CALCA `sequences.csv` still 778 designs at 21–140 aa with identical ids; the RFD3 CSV path still 704).

### Removed (2026-07-28 — Part U: one ranking, no way to choose another)

**Breaking change to `metrics.csv` / `top30_candidates.csv`.** Three ranking methods collapse into one. `rank_by_two_stage`, `rank_by_consensus_iptm` and `rank_by_adaptyv_method` are replaced by a single `rank_designs(df, min_engines=3)`: cross-engine gate, then `consensus_iptm_mean`, ties on `consensus_iptm_n` → `consensus_iptm` → binder pLDDT.

- **Columns removed:** `two_stage_rank`, `adaptyv_rank`, `consensus_rank`, `active_rank`, `passes_max_screen`. **Added:** `rank` (the one ranking) and `passes_engine_gate` (cleared the cross-engine gate; gate failures rank **last, not dropped**).
- **CLI flags removed:** `--rank-by` and `--screen-metric`. `--min-engines` is the only ranking knob left.
- **Why each one went** — all from the Cao 2022 benchmark (4,442 designs / 12 targets / all three engines on every design):
  - `adaptyv_rank` ranked on `quality_tier → agreement_count → ipsae_min`, but **`agreement_count` is a flat null as a screen**: macro-AUC 0.532 with **87.2% of designs tied at zero**.
  - `consensus_rank` ranked on max-iPTM, which **loses to mean-ranking** (precision@top-10% 0.79 vs 0.92).
  - Offering a *choice* of ranking metric is itself the error: **honest nested selection over 72 metrics scores macro-AUC 0.5170, worse than the 0.5552 of the metric we already ship** (+0.0382, CI [+0.0142,+0.0633], p=0.0014, 8/12 targets). Six different metrics win across the 12 folds. Best of 2,489 nested-CV combinations was 0.5591, inside the label-permutation null.
- **No compatibility shim, by decision.** Older `metrics.csv` files were written by an older version and are left untouched; nothing reads or migrates the legacy column names. Re-report from the per-engine refold CSVs if an archived run needs the new schema.
- **Report simplifications that follow:** the Top-30 legend, the display-column selector, the screening-summary intro and the methodology paragraph each had three `rank_method` branches and now have none. `_two_stage_methodology_html` → `_ranking_methodology_html` (still rendered from the live `min_engines` argument — the anti-drift property that F32 exists to protect). The retired Stage-1 threshold line is gone from the iPTM scatter.
- Tests: `test_scoring.py`'s screen-mechanics block is replaced by gate-and-rank tests, including one asserting every legacy column is **absent** so the break cannot silently regress. The `ceil`-half screen-size parametrisation went with the screen. 348 pass in `tests/binder_comparison/`, 437 repo-wide; ruff clean. Verified end-to-end on the real Cao EGFRc pool: `rank` equals the pure `consensus_iptm_mean` ordering for all 400 rows, and all five legacy columns are absent.

### Changed (2026-07-28 — Part U: the Stage-1 screen is retired)
- **`passes_max_screen` is no longer a sort key.** Ranking is now `Stage 0 (>= --min-engines cross-engine gate)` → `consensus_iptm_mean`, with `consensus_iptm_n` then `consensus_iptm` as tiebreakers. The flag is still computed and reported — it marks where the top-50% cut falls and the report's threshold line is drawn from it — but it does not steer the order. **Measured on the Cao et al. 2022 benchmark** (4,442 yeast-display minibinders, 12 targets, all three of Boltz-2/AF3/ESMFold2 on every design): the screen removed **0 designs from the top-5, top-10, top-20, top-50 and top-10% on 12/12 targets**; the earliest rank it moved at all was **21.0% down the pool** (EGFRc, rank 84/400), and full-list Spearman between screened and unscreened orderings was **0.983–0.999**. It cost a code path, a CLI flag and a paragraph of docs while changing nothing at any shortlist depth a human reads.
- **This is an empirical property of correlated engines, not a theorem.** Elementwise `mean <= max` does *not* imply the max-screen preserves the head of the mean ordering — A=(0.5,0.5,0.5) has mean 0.5/max 0.5 and B=(0.9,0.1,0.1) has mean 0.367/max 0.9, so a cut at 0.6 drops A and keeps B despite A's higher mean. It holds here because max and mean co-rank at Spearman **0.89–0.98** within target. Documented in the `rank_by_two_stage` docstring so the reasoning is not lost.
- **`--screen-metric` is deprecated** and warns when set to a non-default value. It still selects which column the diagnostic flag is computed from, but can no longer change the ranking. Part U also found the documented rationale for the `max` default to be **backwards**: at the same 50% cut the `mean` screen retained *more* true binders (1,114 vs 1,093; +0.0123 macro recall, CI [+0.0027, +0.0226], p=0.0094, 8/12 targets). Moot now, but recorded so the `max` screen is not reinstated on the old reasoning (it has already been flipped twice — `f1bc405` mean, `5769064` back to max).
- **Explicitly unchanged, with evidence.** `min_engines` stays at 3 (the case for lowering it rested on a random-dropout simulation whose result flipped sign under reseeding; under informative dropout the gate buys +0.006–0.038). All three engines stay — do **not** drop Boltz-2 despite it being weakest on Cao (0.528): `af3+esm` loses to the 3-engine mean on Adaptyv by −0.0190, CI [−0.0307, −0.0074], p<0.001, 0/4 targets, and single-engine commitment carries the largest worst-case regret of any option (0.106–0.116 vs 0.042). `consensus_iptm_mean` stays the ranking metric — it beats honest nested metric-selection over 72 candidates by +0.0382 (p=0.0014, 8/12 targets); selecting a metric from labelled data scores 0.5170, *worse* than what ships.
- **The report now states a calibrated expectation** instead of implying the top-N is a verdict. On a hard near-miss pool the top decile is worth **~1.5–2× enrichment** and beats a random ranking on only **6 of 12 targets** (on TrkA and Tie2 it is worse than not ranking). The methodology blurb and CLAUDE.md say so directly.
- **`CLAUDE.md`: "engine disagreement is signal" is qualified.** The cross-engine *mean* resisting single-engine gaming holds; *stratifying* by disagreement does not — median-split changed AUC by −0.006/+0.005 against a random-split null of ±0.018 (p=0.71/0.81), and `agreement_count` scores macro-AUC 0.532 with 87.2% of designs tied at zero. It stays a diagnostic column; do not gate on it.
- Tests: `test_two_stage_ranks_purely_by_mean_not_by_screen` and `test_two_stage_rank_is_invariant_to_screen_metric` replace the old pin that asserted the screen was the primary sort key; the `TestTwoStageMethodologyText` drift-guards now assert the blurb no longer claims a "binder-likely pool" or that Stage 2 ranks only "survivors", and that the calibrated enrichment is present. 357 → 359 pass.

### Fixed (2026-07-27 — audit leftovers, part 2: MSA cache, QC coverage, provenance, ingestion)
- **No engine folds without an MSA any more (F21).** On a cold cache one engine could fold single-sequence while another got a full MSA, with nothing recording which. The MSA drives *target* fold confidence and iPTM is a two-chain interface metric, so an MSA-less engine is *systematically* penalised — it drags `consensus_iptm_mean` down and can demote a good design with nothing visible in the report. `prepare_target_msa()` is now the single entry point all three engines call up front: the first fetches, the rest hit disk. If the MSA cannot be obtained the engine **aborts before model load** with a message naming the cause, the pre-warm command and the opt-out. Proceeding single-sequence requires `--allow-no-msa` (or `BINDERSCOUT_ALLOW_NO_MSA=1`) and is recorded to `target_msa_mode.json`. Enforced per-engine rather than in `evaluate.sh`, so the rule holds however an engine is invoked. **Behaviour change:** an air-gapped host with a cold cache that previously produced silently non-comparable results will now abort until it pre-warms or passes the flag.
- **The MSA cache write is atomic and reads are validated (F22).** It was a bare `write_text()` "validated" by `st_size > 0`; two engines starting together could race, one reading a partially-written a3m that passes a size check. Writes now go to a temp file in the same directory, `flush` + `fsync`, then `os.replace()`. Reads reject empty files, a missing leading `>`, headers with no sequence, a missing trailing newline (the classic truncation) and a trailing bare header; an invalid entry is discarded and re-fetched. `target_msa_cache_path` — the offline Boltz-2/Mosaic path — uses the same validation. Deliberately, the "first record matches the target" check is a **warning, not a reject**: rejecting would cause an unbounded re-fetch loop across processes against the ColabFold rate limit, the exact failure this cache exists to prevent.
- **`qc-annotate` no longer deletes designs it never measured (F36).** The metrics↔panel merge is a LEFT join, so a design the Rosetta panel never processed got NaN in all five `interface_*` columns → `qc_pass=False`, indistinguishable from a measured failure, and `--drop-failures` deleted it. `qc_pass` is now three-state, with NA **never** dropped; a measured violation still beats missing metrics, so partial coverage plus a real failure cannot smuggle a bad design through. New `qc_covered` / `qc_missing_metrics` columns carry what the old `=NA` tokens said, and both are now wired through `_QC_PANEL_COLS` into the report — without that the fix would have been invisible to the reader it exists for. Also fixed: the summary counted flagged rows *after* the drop, so a hard-filter run reported "0 flagged" while deleting the whole shortlist.
- **All seven run-script writers emit `settings.json` (F28).** `write_run_bindcraft`, `write_run_boltzgen` and `write_run_mosaic` had no provenance at all, breaking CLAUDE.md's reproducibility convention for three of the seven tools. All three now use the shared `_settings_json_block()` helper, so the guarded GPU probes come with it. Verified on a host without `nvidia-smi`: all seven emitted blocks execute under `set -euo pipefail`, exit 0 and produce valid JSON.
- **Three ingestion mismatches (F43).** PXDesign `binder_id`s were positional (`pxdesign_0`, `pxdesign_1`) because `_make_id` ignored the `design_id` the configurator's collector writes — not greppable back to `sequences.csv` and unstable under any re-sort; ids now prefer `design_id`/`name`, with a warning and a deterministic hash suffix when the collector's file-stem fallback produces duplicates that `add_design_groups` would otherwise silently collapse. Proteina-Complexa's native-metric map expected raw evaluation names while the collector writes renamed ones, so **no native metric was picked up at all** for the layout the extractor's own docstring claimed to support. And `discover_tool_csvs.py` matched neither PXDesign nor Protein-Hunter in the canonical layout — `protein_hunter_*` misses `protein_hunter/` by one character, a miss repeated in `_TOOL_PDB_DIR_PATTERNS`. Join safety was checked before changing the producer: refold merges and the native-metrics sidecar all join on `sequence`; only the optional advisory panels join on `binder_id`, so a **stale** advisory artifact must be regenerated once.
- `--allow-no-msa` is exposed on `binder-compare refold-af3` / `refold-esmfold2` and forwarded through the runners, and `MissingTargetMSA` now exits 2 with its message instead of a traceback — an expected operator condition should not look like a crash.
- **`evaluate.sh` pre-warms the shared MSA before any engine starts**, and gained `--allow-no-msa`. Correctness does not depend on this step — each engine enforces the rule itself — but without it a cold-cache failure only surfaces *after* the first engine has loaded its weights, which on AF3 is minutes of GPU time. The step is skipped entirely when every engine is skipped, so a report-only re-run makes no network call. When `--allow-no-msa` is given it exports `BINDERSCOUT_ALLOW_NO_MSA=1` so all three engines degrade *together* rather than one silently diverging. Verified across all four paths (fetch OK / fetch fails without the flag → exit 2 / fetch fails with the flag → warn and continue / all engines skipped → no call) by stubbing `conda`.
- Tests: `test_target_msa.py` (22, network mocked — including a temp-then-`os.replace` spy and the full abort/opt-in matrix), `test_qc_annotate.py` (11), `test_settings_json_convention.py` (29, derived from `TOOL_SEQUENCE` so a new tool is covered automatically), `test_discover_tool_csvs.py` (7), plus 9 extractor cases. Each was verified to fail against the pre-fix code. 356 → 452 pass.

### Fixed (2026-07-27 — audit leftovers: the findings never scheduled into a batch)
- **The installer's `evaluate` shortcut always died on startup (F10).** `Evaluator/run.sh` passed `--target-pdb` to `evaluate.sh`, which has no such case arm and falls through to `*) echo "Unknown argument: $1"; exit 1`. Both installers write that shortcut as `exec bash Evaluator/run.sh`, so the documented human entry point failed before printing its banner. **Fixed by dropping the flag, not by wiring it through** — of the eight `binder-compare` subcommands `evaluate.sh` calls, only `refold-boltz2` accepts a `--target-pdb`, and its own help calls that opt-in "forced template mode … omit for sequence-only mode". Threading it through would have silently moved every wizard user into template mode **for Boltz-2 only**, constraining one engine's target backbone while AF3 and ESMFold2 still predicted it de novo — making the per-engine iPTMs non-comparable and corrupting `consensus_iptm_mean`, the primary ranking metric. `$TARGET_PDB` is not orphaned; `run.sh` still uses it to derive `$TARGET_SEQ`. The stale troubleshooting row for this symptom is removed from `README.md`.
- **The TUI knew only 4 of the 7 tools (F27).** Three status surfaces each hardcoded `("mosaic", "boltzgen", "bindcraft", "pxdesign")` — the run-picker hint, the curses run-status view and its dumb-terminal fallback — so a run that produced RFD3, Protein-Hunter or Proteina-Complexa designs showed nothing for them. A fourth site, `_detect_tools`, had the same defect with different keys and drives the `Tools: BindCraft: OK | …` header. All four now iterate one `TOOL_SEQUENCE` table, mirroring the fix already proven in the configurator; it is defined locally rather than imported, because the TUI is stdlib-only. Output subdirs were verified against the configurator's `write_run_*` heredocs and both run-script templates, and a drift test asserts the two tables agree entry-for-entry. Protein-Hunter's nested `<name>/` layout is handled. Status views now print display labels (`Proteina-Complexa`) instead of raw subdir names, matching `configurator.cmd_status`.
- **`scripts/install_pxdesign.sh` could destroy a working environment (F25).** It carried another user's absolute paths (`/home/<user>/tools/PXDesign`, `/home/<user>/cutlass`, `/home/<user>/BinderScout/tests/…`) and ran `conda env create --force`, which silently deletes and recreates the live `binderscout_pxdesign` env — taking the `CPATH`/`CUTLASS_PATH` `activate.d` hooks, the `.so` dev symlinks and hours of downloaded wheels with it. **Kept rather than deleted:** its genuine value over the canonical installer is per-architecture selection (aarch64 torch 2.5 / CUDA 12.6 / CUTLASS SM 100 vs x86_64 2.1 / 12.1 / SM 80;86;89) plus `git submodule init`, where `install/install.sh` hardcodes x86 CUDA 12.4. Paths now derive from the repo root via `${BASH_SOURCE[0]}`, `--force` is opt-in matching `install.sh`'s convention, and a header states that `binderscout install --tool pxdesign` is the supported path.
- Tests: `tests/evaluator/test_evaluate_sh_flags.py` parses `evaluate.sh`'s case arms (handling `--output|-o)` alternation) and the flags `run.sh` passes, asserting subset — so future drift in either file is caught rather than just this one flag. `tests/tui/test_tool_sequence.py` AST-walks for re-introduced inline tool lists. `tests/test_script_hygiene.py` is repo-wide over `scripts/` and `install/`: no literal `/home/<name>` paths, no `conda env create` carrying an unconditional `--force`. Each was verified to fail against the pre-fix code.

### Removed (2026-07-27 — the vestigial AF2 refold engine entry)
- **`_ENGINE_IPSAE_COLS` still registered an `"af2"` engine** four months after Part I removed AF2 refolding. Nothing has written `af2_ipsae_min` since (the surviving `af2` schema fields are PXDesign's `pxdesign_af2_iptm` / `af2_ipae` and Proteina-Complexa's `complexa_af2_reward` — those are *design-tool* metrics and are untouched). The dead entry kept three things alive: a `--threshold-af2` CLI flag that could never affect anything, a `DEFAULT_ENGINE_THRESHOLDS["af2"] = 0.30` special case, and a `passes_af2_filter_informational` column with its own branch in `apply_screening_thresholds`. All six sites removed.
- **`compute_agreement` was already correct** — it uses its own boltz/af3/esmfold2 dict, so AF2 never inflated `agreement_count`, matching what its docstring and the CLI help both claimed. Verified rather than assumed. That local dict is now an exact duplicate of `_ENGINE_IPSAE_COLS`; left as-is (deduping would couple agreement counting to the canonical map, which is a separate call) but flagged here as the one remaining copy that could drift.
- **Old metrics CSVs still work.** A pre-Part-I CSV that carries an `af2_ipsae_min` column keeps it — nothing is dropped or rewritten; it simply no longer produces a pass flag. Verified: such a frame yields `passes_boltz/af3/esmfold2_filter` only, `agreement_count` unchanged at 3, and the `af2_ipsae_min` data preserved. `notebooks/_analysis.py`, which reads that column out of historical CSVs directly, is unaffected.
- `--threshold-af2` is now rejected by argparse; `--threshold-boltz`, `--threshold-af3` and `--threshold-esmfold2` are unchanged. This is the only breaking change, and the flag was a no-op.
- `test_metric_labels.py` now derives its live-engine list from `_ENGINE_IPSAE_COLS` instead of hardcoding the exception, so a newly registered engine is label-checked automatically.

### Fixed (2026-07-27 — report tables printed raw column names)
- **26 of the 50 displayable report columns had no display label**, so `_df_to_html`'s silent fallback printed their raw names. In one table a reader saw `Boltz ipSAE_min ↑ [0–1]` sitting next to bare `af3_ipsae_min` and `esmfold2_ipsae_min` — the same metric from the other two engines, unlabelled, undirected and unitless. Also affected: every `interface_*` QC column, every `epitope_*` column, `family_size` / `family_rank`, both alternative consensus iPTM columns (`consensus_iptm`, `_min`, `_spread`), both rank columns and `passes_max_screen`. All are now in `plots.METRIC_META`.
- **Directions were derived, not guessed.** The five interface-QC arrows are taken from the BindCraft filters in `cli/qc_annotate.py` (`dG<=0`, `sc>=0.55`, `hbonds>=3`, `unsat<=4`, `nres>=7`), so the arrow a reader sees agrees with the gate that judges the design — a test pins that correspondence. The two interface columns with no threshold there (`interface_dG_SASA_ratio`, `interface_hydrophobicity`) get a label but **no arrow**, rather than an invented one.
- Tests: new `tests/binder_comparison/test_metric_labels.py` — 8 cases. The main guard derives the displayable set from `_select_display_cols` itself, so a column reaches the test the moment it reaches a table, rather than needing a hand-maintained list. Plus: no label may equal its own column name, every direction must be one of ↑/↓/blank, no two metrics may share a header (`two_stage_rank`/`consensus_rank` excepted — only one rank column shows at a time), and the interface arrows must match the QC thresholds. Verified to fail against the pre-fix table (4 of 8 failed). 338 → 346 pass.
- Noted, not changed: `_ENGINE_IPSAE_COLS` still carries an `"af2"` entry left from before Part I removed AF2 refolding. Nothing writes `af2_ipsae_min` any more — the surviving `af2` schema fields are PXDesign's and Proteina-Complexa's own native metrics — so it can never reach a table, and `--threshold-af2` has nothing to act on. Left in place (removing it would drop a CLI flag) and excluded from the per-engine label test rather than labelled, so no label is invented for a column that cannot appear.

### Changed (2026-07-26 — SoluProt is part of `--tool all`)
- **`--tool all` now installs SoluProt** on both platforms. It screens the design pool *before* any GPU refolding, so a "full" install that omitted it could not run the documented workflow without a second install step — and the one filter that saves GPU time was the one thing you had to know to ask for. AF3 stays opt-in (gated weights) and aarch64 RFD3 stays opt-in (unvalidated hardware).
- **New cost, stated plainly:** `--tool all` now also creates the Python 3.7 `binder-eval-soluprot` env and **source-builds USEARCH v12**, so it requires a C/C++ toolchain (`git make g++`). The preflight disk table already carried SoluProt's ~2 GB, so the abort threshold rises with it automatically. CI is unaffected: `Dockerfile.test` already installs `build-essential`, the vendored SoluProt distribution means no network call to Loschmidt, and a failing tool is collected into `failed_tools` rather than aborting the run.
- Verified by extracting each installer's argument parser and running it standalone: `--tool all` → SoluProt on, AF3 off, and (on aarch64) RFD3 still off; `--tool soluprot` → SoluProt only. The uninstall-side `TOOL_ALL` widening and its comment were updated to match — it now only needs to add AF3.

### Changed (2026-07-26 — USEARCH is built from source, not redistributed)
- **The two committed USEARCH binaries are removed** (`Evaluator/tools/soluprot/usearch.x86_64`, `usearch.aarch64`, 4.2 MB). USEARCH v12 is **GPLv3**, so shipping it inside this MIT-licensed repository put a copyleft redistribution obligation on every clone. `install_aarch.sh` already had a complete `_build_usearch_v12()` and only skipped it because the committed binary pre-empted the check; that function is now ported to `install.sh` as well (x86_64 is usearch12's native platform), so **both** installers build it from [`rcedgar/usearch12`](https://github.com/rcedgar/usearch12) during `--tool soluprot`. The binary is produced on the user's machine and never distributed by us.
  - **Verified equivalent before removing anything:** cloned and built usearch12 on x86_64 (static link, clean), then ran SoluProt's exact `-usearch_global … -db Ecoli_xray_nmr_pdb_no_nesg.fa -id 0.0 -blast6out … -top_hits_only` command with both the previously committed binary and the fresh build. Output is **byte-identical** (`diff` clean at `-threads 1`; at `-threads 2` only row order differs, as thread scheduling dictates). The built binary is 2,250,936 bytes against the committed 2,306,888 — the committed one was this same source build.
  - **Caveat recorded, not papered over:** the binaries remain reachable in git history (they entered in `b8d2b87`), so a full clone still fetches them. Removing them from `HEAD` stops future archives from carrying them; ending that outright needs a history rewrite, which would break every existing clone *and* invalidate the `binderscout_git_sha` recorded in every past run's `settings.json` — the provenance record this project deliberately keeps. That trade-off was declined, and a **GPLv3 written offer** added to `THIRD_PARTY_NOTICES.md` covers the historical distribution instead: it names the exact distribution window (`b8d2b87` 2026-06-30 → `2ae1bdb` 2026-07-26), identifies both binaries by size and SHA-256, points at the upstream source with the commit pinned, and adds a three-year offer to supply corresponding source on request. Every hash and size in the offer was verified against the objects in git. The text is careful about what is *known*: it states that this project applies no source patches and names the one build-time deviation (the aarch64 fallback stripping `-static`), while declining to claim bit-for-bit reproducibility for binaries built before the current records.
- **A missing USEARCH now fails the SoluProt install instead of warning.** `install.sh` only *checked* for the binary and printed a warning — but SoluProt cannot score without it and **fails silently**: `soluprot.py` catches `UsearchInvalidPath`, prints to stderr, and returns, so the process exits **0** having written no output CSV. The `--help` smoke test cannot catch this (argparse exits before the USEARCH path runs). Both installers now build it, and abort `--tool soluprot` with the toolchain requirement and the source URL if they cannot.
- **New: the installer verifies USEARCH can actually start.** `-x` only tests the mode bit, which passes for a wrong-architecture binary or one missing a shared library — and the bioconda `usearch 12.0_beta` build is known to crash at startup on aarch64. `_check_usearch_runs` executes it and fails only on a failure to exec (126/127) or a fatal signal (≥128), so no assumption is made about USEARCH's CLI. Verified against four fixtures: ordinary non-zero exit passes, exit 127 fails, SIGSEGV (139) fails, and `$SOLUPROT_USEARCH` overrides correctly.
- **Both installers resolve USEARCH the way the runner does.** New `_resolve_usearch` mirrors `soluprot_runner._resolve_usearch` — `$SOLUPROT_USEARCH`, then `<dir>/usearch.<arch>`, then `<dir>/usearch`, then PATH — so what the installer validates is what `binder-compare` will execute, rather than a hardcoded per-arch filename that could diverge.
- **Removed a recommendation that made the licensing worse.** `install.sh` told users to download USEARCH from `drive5.com/usearch/` — "32-bit, free for academic". That is the older **proprietary** USEARCH under an academic-use-only licence: stricter than the GPLv3 v12 it would replace, in a repository that advertises RFD3 as "commercial-use OK", and not the version SoluProt is patched for (`usearch_global` vs `search_global`). Both installers now point at the GPLv3 source instead and say explicitly not to substitute the drive5 build.

### Fixed (2026-07-26 — skill references and wizard step numbering)
- **Two skill references prescribed an installer flag that does not exist.** `binderscout-worker/references/troubleshooting.md` §5.6 told the reader to "rerun `install/install.sh --pxdesign`" to restore the PXDesign patches, and `references/tools/pxdesign.md` suggested `install.sh --pxdesign --check` "(if available)". The installer selects tools with `--tool <name>` and has no `--check` mode, so the documented recovery for a known, documented failure mode exits 1 on the spot. Both now say `binderscout install --tool pxdesign`, and note that the re-run resumes into the existing env rather than rebuilding it (per the installer resumability fix earlier in this release), so only the patch steps redo work.
- **The wizard's step numbering skipped 6e.** Per-tool sub-steps ran 6a, 6b, 6c, 6d, **6f**, 6g, 6h — a visible off-by-one for every user who enables Proteina-Complexa or later. Renumbered to 6a–6g. The two `Step 6d` labels are left as they are: they are an `if`/`elif` pair (PXDesign local run vs. import), so only one ever prints.
- **Two skills still described a "5-step wizard".** It has been steps 1–7 with per-tool sub-steps and ~80 prompts for some time; both now say so, and the orchestrator skill gains the `--config` headless replay added earlier in this release.
- `docs/walkthrough_and_dataflow.html`'s step table is updated to the new numbering and line numbers, and its "duplicate label" flag on the second `Step 6d` is corrected — the duplicate is deliberate, the 6e gap was the real defect.

### Fixed (2026-07-26 — repository hygiene)
- **`binderscout --help` no longer writes to the filesystem.** `main()` called `_install_binderscout_shortcut()` before parsing anything, so merely asking for usage created `BinderScout/bin/`, created `~/.local/bin/`, and dropped an executable named `binderscout` into the user's PATH. An inspection command must not do that. The shortcut install now runs after the `--help` short-circuit, so it still happens for the TUI and every dispatched sub-command — the paths that actually benefit from it.
- **A read-only checkout no longer kills the CLI.** The primary `REPO/bin` write was unguarded (only the `~/.local/bin` one was), so an unwritable repository directory raised `OSError` out of `main()` before any sub-command ran. It now warns and continues, matching how the secondary location was already handled. Verified both ways: `--help` on a fresh tree creates neither directory and exits 0, and an un-creatable `REPO/bin` prints a warning and returns normally instead of raising.
- **`INVESTIGATION_RANKING_DISCREPANCY.md` existed twice**, byte-identical at the repository root and in `docs/` — so a reader had no way to know which was current, and an edit to one would silently diverge from the other. The root copy is removed; the four code comments and one doc reference that cited it by bare filename now point at `docs/`. `PLAN_chai_and_designers.md` moved to `docs/` alongside its five `PLAN_*.md` siblings.
- **The Quick Start handed out the pre-rename clone URL.** `README.md`, `CLAUDE.md` and `CONTRIBUTING.md` all said `git clone https://github.com/damborik22/BinderScout.git` while the README's own rename notice states the remote is `damborik22/BinderScout` — so the first command a new user runs relied on a GitHub redirect that the project does not control. All three now clone the real remote. (`binderscout.py`'s usage text was already correct.)

### Added (2026-07-26 — `THIRD_PARTY_NOTICES.md`)
- **The repository redistributes third-party binaries and data under a top-level MIT licence that said nothing about them.** `LICENSE` and the README's "License: MIT" badge were the only licensing statements in the tree, so anyone cloning, forking or packaging BinderScout inherited terms they had no way to see. New `THIRD_PARTY_NOTICES.md` documents each vendored asset with its in-tree path and size, the version verified **from the artifact itself** (binary version strings and copyright banners, not assumption), the upstream project and URL, and its licence — marking explicitly which ones could *not* be verified from a licence file in-tree, since the vendored copies carry none. Covered: `Evaluator/tools/ngl/ngl-2.3.1.min.js` (NGL Viewer, MIT), `Evaluator/tools/soluprot/` (SoluProt 1.0 — Hon et al. 2021, Loschmidt Laboratories — ~51 MB of code, trained classifiers and reference FASTA databases), the bundled `usearch.x86_64` / `usearch.aarch64` binaries, and the ARM64 `tools/aarch64/DAlphaBall.gcc` (Rosetta-derived) and `tools/aarch64/dssp` (`mkdssp 3.1.4`, CMBI) builds.
- **Flagged: the vendored USEARCH binaries are GPLv3**, self-reporting `usearch v12.0` with Robert C. Edgar's copyright, sitting in an MIT repository. The notice states plainly what this does and does not mean — it does *not* relicense BinderScout (SoluProt invokes USEARCH as a separate process, so this is aggregation), but it *does* mean anyone distributing this repository is distributing GPLv3 binaries and inherits the obligation to pass on those terms and offer corresponding source. The practical fix is recorded alongside it: drop the two binaries and fetch or build them at install time, which `install/install_aarch.sh` already does for aarch64 — the x86_64 binary is the only reason the obligation exists on `master` today. Flagged for the repository owner to decide; nothing was removed.
- Also listed, for a complete dependency surface in one place, the components the installer **fetches** rather than redistributes (the seven design tools, AF3 with its gated weights, ESMFold2, PyRosetta) and a note that no model weights live in this repository.
- `README.md`'s License section and a note appended below the MIT grant in `LICENSE` both point at the new file. The MIT grant text itself is unchanged.

### Fixed (2026-07-26 — the report now prints the thresholds it applied)
- **`--threshold-boltz` / `--threshold-af3` / `--threshold-esmfold2` relabelled nothing.** They change what `apply_screening_thresholds` and `compute_agreement` *compute*, but the "Per-engine cutoffs" legend was a hardcoded `Boltz-2 ≥ 0.61 · AF3 ≥ 0.61 · ESMFold2 ≥ 0.61` and every `agreement_count` description read "score ipSAE_min &gt; 0.61". So a report run with `--threshold-af3 0.75` screened at 0.75 and told the reader 0.61 — in the one place a reader can check what the cutoffs were. The legend and both column-legend tables now render from the resolved threshold dict that scoring used, and spell the cutoffs out per engine when they differ. Verified end to end: `--threshold-af3 0.75 --threshold-esmfold2 0.55` now appears as such in `report.html`, with Boltz-2 still at its default.
- **The tier bands are no longer retyped.** `0.80` / `0.61` / `0.40` appeared as literal strings in 18 places across `visualization/report.py`, so editing `IPSAE_HIGH_THRESHOLD`, `IPSAE_PASS_THRESHOLD` or `IPSAE_MIN_THRESHOLD` would have changed which designs land in which tier while every legend, glossary entry and methodology paragraph kept quoting the old numbers. All of them now format from the constants. `top30_slim._tier` was worse than a label — a **second, independent implementation** of the tier cutoffs, which could colour a row differently from the `quality_tier` the full report assigned it; it now reads the same constants, and a test asserts the two agree band-for-band across the boundaries.
- **The report no longer claims three engines ran when fewer did.** "How many of the 3 engines (Boltz-2 / AF3 / ESMFold2) … so 0–3" was fixed text, but `agreement_count` has a smaller ceiling when an engine is skipped — an auto-detected, supported configuration. A 2-of-2 design read as having failed one of three. The engine list and count are now derived from the ipSAE columns actually present, in the report legends, the disagreement-flag reason string ("only 1/3 engines pass") and the slim table's legend.
- Fixed while in the same strings: the `agreement_count` glossary entry still said "Currently Boltz-2 only (0 or 1); AlphaFold 3 and ESMFold2 will be added as the refactor progresses" — both have been live since Part K.
- Tests: new `tests/binder_comparison/test_report_thresholds.py` — 23 cases covering per-engine override rendering (including independent overrides and mixed-vs-uniform phrasing), engine-count derivation, tier bands matching the constants in all five renderers, a source-level guard against re-typing a band literal, and the slim/full tier agreement. The two behavioural defects were verified against the pre-fix code: the old `_engine_threshold_legend_html` could not even *accept* an override, and the old two-engine legend still printed "0–3" and named ESMFold2. 315 → 338 pass.

### Added (2026-07-26 — tests for the scoring kernels and the seven extractors)
- **`compute_ipsae_from_pae` and `compute_iptm_from_pae` had no tests**, despite producing every number the pipeline ranks on — `consensus_iptm`, `consensus_iptm_mean` and `ipsae_min` all originate in those two functions, and both take a PAE matrix whose row/column orientation differs per engine (Boltz-2 is native `[binder|target]`; AF3 and ESMFold2 are token-order and transposed on ingest). A silent transpose or a wrong `d0` would not fail anything; it would just quietly reorder the shortlist. New `tests/binder_comparison/test_scoring_kernels.py` — 24 cases checking both kernels against **reference implementations written from the published formulas** rather than snapshots of current output, so a change of answer is caught rather than re-baselined. The fixture PAE is deliberately **asymmetric**, so a transpose bug cannot hide: `test_mislabelling_the_ordering_changes_the_answer` asserts the two orderings give different numbers, and `test_target_first_ordering_is_transposed_not_ignored` pins that `target_first=True` transposes rather than ignores. Also covered: the 10 Å ipSAE cutoff actually excluding distant pairs, ipTM having **no** cutoff, min/max being the pessimistic/optimistic directions, monotonicity in interface quality, boundedness, NaN (not a crash) on degenerate lengths, and rejection of non-square input. A `TestTheTwoKernelsUseDifferentD0` class pins the one difference that is easiest to "fix" into a bug: ipSAE floors N at 27, ipTM does not.
- **Fixed a latent crash found by those tests.** `compute_iptm_from_pae` computed `d0 = max(1.0, 1.24 * (L_b + L_t - 15) ** (1.0/3.0) - 1.8)`. For a complex totalling fewer than 15 residues the base is negative, and Python's `**` on a negative float returns a **complex number** — so `max(1.0, complex)` raised `TypeError: '>' not supported between instances of 'complex' and 'float'` rather than producing a score. Now `np.cbrt`, which takes the real cube root the formula intends and lets `max()` floor it to 1.0. Unreachable through the configurator (binders are ≥ 10 aa and targets larger) but reachable from sequence-only mode; verified failing against the pre-fix code.
- **The seven extractors had no tests either** — only the retired `evaluator_legacy` parser did, so the repo's extractor coverage pointed at code the CLI no longer dispatches while the live ingestion path had none. New `tests/binder_comparison/test_extractors.py` — 22 cases built from each tool's **exact** filenames and column names, concentrating on the failure modes CLAUDE.md's "Critical domain facts" already documents as having bitten real runs: BoltzGen's `designed_chain_sequence` vs `designed_sequence` trap (the latter is the CDR subset only, so refolding it feeds a truncated binder), Mosaic's `is_top` filter and mixed-width worker rows, PXDesign's `af2_ipae`/`af2_ipAE` casing drift, Proteina-Complexa's comma-separated `aatype` decoding, BindCraft's MPNN-variant and Protein-Hunter's cycle collapse, and RFD3 preferring the aggregated CSV over the FASTA fallback. Plus cross-extractor hygiene: every extractor tags its own `source_tool` and emits clean sequences.
- 293 → 315 pass. `tests/evaluator/test_evaluator_parsers.py` is kept as-is: `evaluator_legacy/evaluator.py` is still on disk and still runnable by hand, and the reason to drop those 5 cases was that they were the *only* extractor tests — which is no longer true.

### Added (2026-07-26 — headless configurator: `--config` replay)
- **`configurator --config <file>` generates a run directory with no prompts**, closing CLAUDE.md's deferred item **F2** ("`--headless` mode for configurator") and the one hard blocker to running this pipeline from a script or cron. The wizard's ~80 answers were previously discarded the instant the run scripts were written: reproducing a campaign meant re-typing every one, and nothing on disk recorded what a run had been configured with. The `cfg` dict already *was* the complete description — it was simply never saved.
  - **Dump** — `generate()` now writes `runs/<name>/config.json` alongside the run scripts (`write_run_config`), so every interactive run leaves a replayable, machine-readable artefact. Useful on its own, with no behaviour change.
  - **Load** — `load_run_config()` restores it (re-resolving `run_dir` / `target_pdb` / `target_pdb_src` as `Path`s, so a config can be copied to another machine or retargeted at a new run directory) and `cmd_from_config()` calls `generate()` directly, skipping the 80 `ask()` calls wholesale rather than defaulting them one at a time. `--run` also starts the pipeline.
  - Validation refuses to guess: a missing file, a JSON blob that is not a run config, a missing required key, or a `target_pdb_src` that does not exist each fail with a specific message instead of producing a half-configured run.
  - **Verified byte-identical:** generated a run, rewrote `run_dir` in the saved config, replayed it into a fresh directory, and diffed — `run_rfd3.sh`, `run_evaluate.sh` and `run_all.sh` all match modulo the run-directory path.
  - This is also the seam a front-end should use. A GUI, a cron job or another script reads and writes `config.json`; none of them need to re-implement the interview.
- Tests: 8 new configurator cases — config written by `generate()`, `Path` keys surviving the round trip, replay producing identical scripts, every enabled tool recorded, and the four validation failure modes. 261 → 269 pass.

### Fixed (2026-07-26 — ingestion: every tool reachable, empty pools caught)
- **`binder-compare run` can ingest all seven tools.** It offered only `--bindcraft`, `--boltzgen`, `--mosaic`, `--pxdesign` and `--proteina-complexa`, so the advertised single-command path silently omitted every design from **RFD3 and Protein-Hunter** (the Part L and Part M additions) and `--rfd3` was rejected by argparse with no hint that `extract` accepted it. Both subcommands now build their flags from one shared table, `cli/_tool_args.py` (`TOOL_FLAGS` / `add_tool_args` / `requested_tools`), and `run` forwards to `extract` by iterating that table instead of a hand-written if-chain — so a newly wired tool cannot reach one subcommand and not the other.
- **A requested tool that yields nothing is now an error.** The guard only fired when *every* tool came up empty, so a typo in one of four `--<tool>` paths (or a tool whose run died before writing its CSV) printed `→ 0 sequences`, exited **0**, and `run_evaluate.sh` under `set -e` then spent hours of Boltz-2 + AF3 + ESMFold2 GPU time on a silently partial pool that looked complete in the report. `extract` now names the offending tools and exits 1; `--allow-empty` overrides.
- **The RFD3 FASTA fallback no longer emits target+binder concatenations as binders.** That path runs when a manual foundry workflow left no aggregated `sequences.csv`, and `mpnn` writes the **full chain** — the preserved target prefix followed by the designed binder. CLAUDE.md's own RFD3 gotchas say you must "strip the target prefix (first `len(target_seq)` chars)", but the fallback has no target to strip with, so it would hand the refold engines a chimera labelled as a binder and every iPTM computed for it would be meaningless. Sequences longer than a plausible binder (500 aa, the configurator's own ceiling; real designs run 60–150 aa) are now skipped with a warning that points at the aggregated CSV `run_rfd3.sh` produces.
- **ESMFold2 appears in the z-score and summary tables.** `ZSCORE_METRICS` had no `esmfold2_*` entries, so `metrics_zscore.csv` had no `esmfold2_*_z` columns and `summary.json` no ESMFold2 stats — the engine that drives `consensus_iptm` and feeds the autosize gate was missing from the very tables a reader uses to judge cross-engine agreement. Eight columns added alongside the AF3 set, including `esmfold2_chain_iptm_interface`.
- **`Evaluator/README.md` and `Evaluator/docs/pipeline_reference.md` no longer document a deleted engine.** Both still described `refold-af2`, the `binder-eval-af2` env, `AF2_DATA_DIR` and ColabDesign troubleshooting — all removed in Part I — as the Evaluator's only per-subcommand reference. Rewritten for Boltz-2 + AF3 + ESMFold2, with the PAE-orientation and pLDDT-scale notes corrected per engine, the seven `extract`/`run` inputs listed, and the troubleshooting entries replaced with ones that can actually happen (a silently skipped engine, `invalid choice` for the removed subcommands, and an empty Stage-1 screen).
- Tests: new `tests/binder_comparison/test_cli_tool_args.py` — 12 cases covering the shared table, hyphen→underscore dests, `--rfd3` acceptance, that `extract` and `run` expose the *same* seven tools, that `run` forwards from the table rather than an if-chain, the zero-yield exit code and message (as a real subprocess), and both RFD3 length-guard paths. 249 → 261 pass.

### Fixed (2026-07-26 — installer safety: non-destructive `--yes`, resumable, preflight)
- **`--yes` no longer deletes your weights.** `confirm()` returned true unconditionally under `--yes`, so `--tool all --yes --skip-examples` — simultaneously the documented CI command (`Dockerfile.test`, `test_env.sh`) and the skills' recommended *repair* step — answered **yes** to "Remove and reclone?" on a second run, deleting `BindCraft/` including `params/*.npz` (~4 GB of AF2 weights that Proteina-Complexa symlinks against). It also inverted the prompt's own displayed `[y/N]` default. Split into `confirm()` (safe prompts: proceed?, run the example? — still auto-accepted, so CI is unaffected) and **`confirm_destructive()`** (re-clone, re-create env, remove local Miniforge3 — `--yes` answers *no* and says so; new **`--force`** opts in). 7 destructive call sites in `install.sh` and 6 in `install_aarch.sh` switched; both share one `_confirm_interactive()` read loop.
- **The PXDesign install is resumable.** Its `conda create` had no `env_exists` guard, so a re-run after a mid-install network failure aborted there instead of continuing — and every remaining step of that ~25-step function is network-bound (Protenix, PXDesignBench, ColabDesign, deepspeed, the CUTLASS clone, weight downloads), which is exactly where it drops out. Now reuses the existing env (the later steps are idempotent) unless `--force` is passed, matching the pattern `binder-eval-esmfold2` already used.
- **`--uninstall --tool all` now removes everything it installed, and admits what it does not.** The `all` case is shared with install, which deliberately omits AF3 (gated weights) and SoluProt (opt-in), so their envs plus `alphafold3/` and `Evaluator/tools/soluprot` survived an "uninstall everything" while the script printed "Uninstall complete." A new `TOOL_ALL` flag widens the set in uninstall mode only. `uninstall_tool pxdesign` now also removes the `~/cutlass` clone (~150 MB) it created. And the summary lists what is deliberately left behind — `runs/`, `install.log`, `~/.boltz/`, `~/.cache/binderscout/`, `~/.cache/huggingface/`, and the `~/.bashrc` PATH line — rather than implying the disk is clean. Those are the user's data and shell config, so they are reported, not deleted.
- **New preflight before ~60 GB of downloads.** Neither installer checked anything, so an under-provisioned host failed an hour in with an opaque tar/pip error deep in `install.log`, leaving half-built envs that (before the fix above) could not be resumed. `preflight()` runs after tool selection — so the estimate matches what was chosen — and checks free disk against a per-tool footprint table (**aborts** if short, with the shortfall and the three ways out), plus GPU presence and pypi.org reachability (advisory: an install can legitimately precede the driver, or sit behind a proxy). `--skip-preflight` bypasses it; uninstall skips it. Verified on this host: 30 GB free → passes for `--tool evaluator` (~2 GB), aborts for everything (~76 GB) with exit 1.
- Verified by extracting `confirm`/`confirm_destructive` and `preflight` and executing them standalone across all modes: `--yes` alone (destructive=no, safe=yes), `--yes --force` (both yes), interactive-Enter (both no), interactive-y (both yes); preflight pass / abort / skip. `bash -n` clean on both installers.

### Fixed (2026-07-26 — aarch64 parity: both platforms actually installable)
- **`binderscout install` now picks the installer for the host.** Both it (`binderscout.py`) and the TUI's "Install tools" (two call sites in `tui/app.py`) hardcoded `install/install.sh`, so on a DGX Spark the documented command ran the **x86_64** installer: CUDA defaulting to 12.4 instead of 13.0, conda asked for `pytorch-cuda=12.4` and `gcc_linux-64` (no linux-aarch64 builds), and none of the aarch64 patches applied. `install.sh` warned but proceeded. Dispatch is now `platform.machine() == "aarch64"` in one place, and the TUI routes through a shared `_installer_for_host()`.
- **aarch64 ESMFold2 installed a package that does not exist.** `install_aarch.sh` ran `pip install esmfold gemmi`, while `install.sh` carries the comment "*there is NO `esmfold` PyPI package*" and installs the real runtime: `torch` (from an arch-aware wheel index), `transformers>=4.50`, `safetensors`, `gemmi`, and `esm @ git+https://github.com/Biohub/esm.git@c94ed8d`. The aarch64 env therefore had no torch and no biohub SDK, so `refold-esmfold2` died at import — while the `--help`-only smoke test still passed, letting the installer report success. Now installs the same dependency set with the cu130 wheel index.
- **`--tool all` on aarch64 now includes ESMFold2**, the documented default refold engine. It previously installed five things and omitted it, so `evaluate.sh` silently skipped the engine and `consensus_iptm` was built from fewer engines than the two-stage ranking assumes.
- **`--tool rfd3` exists on aarch64.** The value was rejected outright while CLAUDE.md claimed "RFD3: fully supported on aarch64", so the documented install path for a landed feature could not be run. `install_rfd3()` is ported from `install.sh` (cu130 torch wheels, `rc-foundry[rfd3]` + `[mpnn]` pinned to `FOUNDRY_VERSION`, RFD3 weights **and** the separate ProteinMPNN checkpoint into `weights/foundry/`), with a matching `uninstall_tool rfd3` case, step-counter and summary entries. **Opt-in, deliberately not in `--tool all`:** it is unvalidated on aarch64 hardware, and the docs now say so instead of overclaiming.
- **Protein-Hunter and Proteina-Complexa now explain themselves** rather than returning a generic "Invalid `--tool` value" — PyRosetta publishes no aarch64 wheels; PyG/torchtext may not either.
- Verified by extracting the installer's argument parser and running it standalone for every `--tool` value: `all` → esmfold2 on / rfd3 off, `rfd3` → on, `protein-hunter` and `proteina-complexa` → exit 1 with their reasons, unknown → the corrected valid-value list. `bash -n` clean on all four shell scripts.

### Fixed (2026-07-26 — the documented click path now works end to end)
- **`run_all.sh` no longer aborts before any tool runs.** The Mosaic block is emitted *first* and ended in `exit 1` unless `mosaic/designs.csv` already existed, so `bash runs/<name>/run_all.sh` — the documented one-command way to execute a campaign — died immediately on a fresh run directory with Mosaic enabled, before BoltzGen, BindCraft, PXDesign, Proteina-Complexa, RFD3 or Protein-Hunter started. Missing Mosaic output is now a warning that names the script to run and continues.
- **"Run the pipeline now?" no longer silently skips RFD3 and Protein-Hunter.** The preview tree, the "To run later" list and `run_pipeline()` were three independently maintained tool if-chains: the tree knew 4 of the 7 tools, the other two knew 5. A user could enable RFD3, watch the wizard generate `run_rfd3.sh`, never be told it existed, and have the "Run the pipeline now?" default of *yes* run nothing for it — then have the Evaluator report on an empty pool. All three now iterate a single `TOOL_SEQUENCE` table (`enabled_tools()`), so adding a tool cannot leave a UI surface behind. `write_run_all` already covered all seven and is unchanged.
- **RFD3 designs now reach the Evaluator.** `run_evaluate.sh` pointed `--rfd3` at `runs/<name>/rfd3/outputs/` — a directory `generate()` dutifully created and nothing ever wrote to — while `run_rfd3.sh` writes `rfd3/sequences.csv` one level up, which `write_run_all`'s own `check_outputs` already verified. A completed RFD3 run (23 h GPU on the documented 2VDY campaign) contributed zero designs to the report with no error, because the extractor was handed an empty directory. The flag now points at `rfd3/`, and the empty decoy directory is no longer created.
- **Run scripts no longer die on hosts without `nvidia-smi`.** The `settings.json` provenance block probes the GPU, and under the `set -euo pipefail` that every generated script sets, an unguarded command substitution in an assignment exits **127** — before the design step. The neighbouring `GIT_SHA`, `GIT_BRANCH` and `PY_VER` lines were already guarded with `|| echo`; `GPU_NAME` and `GPU_MEM` were not, so a CPU login node, a container without the NVIDIA runtime, or a wrong `--gpu-id` killed the run inside the block that exists to *improve* reproducibility. Verified by executing the isolated block both ways with `nvidia-smi` off `PATH`: 127 before, 0 after, and the emitted JSON stays valid (`"gpu_name": "unknown"`, `"gpu_memory_mib": 0` — unquoted, so still a number).
- Tests: 8 new configurator cases (TOOL_SEQUENCE coverage and ordering, every script present in the preview tree and `run_all.sh`, no `exit 1` in the Mosaic block, the RFD3 extractor path, guarded GPU probes) — all 8 verified to fail against the pre-fix code. 241 → 249 pass.

### Fixed (2026-07-26 — the report now tells the truth about itself)
- **Every generated `report.html` described a ranking method the code had stopped using.** The `two_stage` methodology paragraph was a hardcoded string reading "Ranking is **two-stage mean iPTM** … **Stage 1 — screen:** `consensus_iptm_mean` … Mean was selected as default over max … The *legacy* max-screen … so Stage 1 + Stage 2 collapse to a single mean-iPTM gate-then-rank." Commit `5769064` reverted the default to **max** and touched `CHANGELOG.md`, `CLAUDE.md`, `cli/report.py`, `comparison/scoring.py` and `test_scoring.py` — but **not** `visualization/report.py`. So every report ran a max screen while telling the reader it had run a mean screen, with benchmark AUC numbers attached to lend it authority. The paragraph is now rendered by `_two_stage_methodology_html(screen_metric, min_engines, …)` from the settings that actually ran, and `generate_report()` takes both; the neighbouring `_top_table_legend_html` already worked this way for `rank_method`, so this completes existing intent rather than adding a mechanism.
- **The report's 3D viewer no longer needs the internet.** `report.html` loaded NGL via `<script src="https://unpkg.com/ngl@2.3.1/…">`, so the "3D Structure Viewer — Top 20" section rendered a blank black box on any air-gapped compute node — the exact environment the shared MSA cache is designed around — even though `Evaluator/tools/ngl/ngl-2.3.1.min.js` (1.3 MB) has been vendored all along and `cli/epitope_map.py` already inlined it. `report.py` now inlines the same file, falling back to the CDN tag with a printed note if it is missing.
- **`wetlab_recommended` is no longer uniformly `False` on a single-engine install.** The gate required `agreement_count >= 2`, which `compute_agreement` cannot reach when only one engine ran — a supported, auto-detected configuration. Every design failed for a reason no design change could fix, making the column pure noise. Consistent with this function's existing NaN policy ("unknowns do not block"), the criterion is now skipped when fewer engines ran than it needs, with a one-time warning so the operator knows it was not applied. A genuinely low `agreement_count` with enough engines present still blocks.
- Tests: 5 cases pinning the methodology text to the active `screen_metric` and `min_engines` (including that it no longer claims mean is the default), 1 asserting the NGL tag is inline and carries the real library, and 2 for the wet-lab agreement policy. 233 → 241 pass.

### Fixed (2026-07-26 — ranking integrity: cross-engine gate, screen size, merge fan-out)
- **Designs refolded by a single engine can no longer top the ranking.** `DataFrame.mean(axis=1)` skips NaN, so `consensus_iptm_mean` for a design only Boltz-2 refolded *was* that one Boltz value, competing against 3-engine means on an incomparable scale — and since Mosaic *is* Boltz-2 gradient hallucination, the one engine backing it was the one biased in its favour. That is exactly what the two-stage design exists to prevent, and `consensus_iptm_n` was already computed but never used. **New Stage 0 gate:** `rank_by_two_stage(min_engines=)` / `report --min-engines N`, **default 3** (all of Boltz-2 / AF3 / ESMFold2), floor 2 — below that a "cross-engine consensus" is one engine's opinion, so values under 2 raise `ValueError`. `consensus_iptm_n` also joins the Stage-2 sort keys, so an equal mean backed by more engines wins. When no design in the pool clears the gate the run emits a warning naming the best coverage found and the exact flag to relax it, instead of silently reporting an all-`False` screen that reads as "nothing was good enough".
- **The Stage-1 screen kept the wrong number of designs.** `round(n * 0.5)` is banker's rounding: n=1 kept **0** (so a single-design evaluation reported that its only candidate failed the screen), n=5 kept 2 (40%), n=3 kept 2 (67%). Now `math.ceil`, so n=1→1, 3→2, 5→3, 7→4.
- **Duplicate sequences no longer fan out into multiple report rows.** `_attach_fasta_metadata` left-joined a non-deduplicated frame, so a FASTA carrying one sequence under two `binder_id`s (i.e. `extract --keep-duplicates`) multiplied the metrics rows: one design occupied several Top-30 slots and inflated the eligible count the screen takes its top 50% from. Now deduplicated first-occurrence-wins with a warning, and the join is `validate="m:1"` so a future regression raises instead of silently inflating. `cli/autosize.py` already guarded its equivalent merge this way.
- **AF3's and ESMFold2's per-engine ipSAE now reach the wet-lab shortlist.** `top30_candidates.csv` and the per-engine threshold legend read hardcoded `af3_pae_ipsae_min` / `protenix_pae_ipsae_min` — names **nothing in the repo ever wrote**. Boltz uses `boltz_pae_*` (from `add_boltz_ipsae_from_files`) while every other engine uses `<engine>_ipsae_min` (from `add_ipsae_from_pae_files`); `scoring._ENGINE_IPSAE_COLS` already documented and mapped this correctly. All five call sites now read from that map, so the two conventions cannot drift apart again. The legend's AF2 row is dropped (AF2 refolding went in Part I and can never populate) and ESMFold2 gains one.
- Tests: new `tests/binder_comparison/test_merger.py` (6 cases — engine prefixing, outer join, duplicate fan-out, clean-FASTA no-warning, empty inputs) and 14 new `test_scoring.py` cases covering the gate, the tie-break, the floor, the warning and a parametrised `ceil` table. The pre-existing two-engine screen tests now pass `min_engines=2` explicitly so they keep testing screen mechanics rather than the gate. 213 → 233 pass.

### Removed (2026-07-26 — Protenix refolding removed; AF3 is the 2nd engine)
- **Protenix v0.5.0 is no longer a refold engine (Part J reverted).** AF3 already fills the independent-cross-check role, so the pipeline is now exactly three engines: **Boltz-2 + AF3 + ESMFold2**. Deleted `Evaluator/scripts/refold_protenix.py`, `refolding/protenix_runner.py` and `cli/refold_protenix.py`; pruned the `refold-protenix` subcommand, every `protenix_*` field from `StandardisedMetrics` / `PerResidueData` / `ZSCORE_METRICS`, the `protenix_csv` merge input, the entries in `_ENGINE_IPSAE_COLS` / `_ENGINE_IPSAE_THRESHOLDS` and the consensus/agreement column lists, the `--protenix-results` / `--threshold-protenix` report flags, the radar + per-engine table rows, the `evaluate.sh` step and its `--skip-protenix` / `--protenix-env` flags, and the wizard's Protenix engine prompt.
  - **This also fixes a live reproducibility bug.** `evaluate.sh` ran Protenix **opt-OUT** — whenever the `binderscout_pxdesign` env existed — while `CLAUDE.md` stated three times that it ran "only when explicitly enabled". Because `protenix_pae_iptm` fed `consensus_iptm` / `consensus_iptm_mean`, two operators with identical designs could get **different rankings** depending only on whether they had installed PXDesign. Mirrors the Part I removal of AF2 refolding.
  - **PXDesign is unaffected.** It uses Protenix internally as a *design* tool: the `protenix` pip install, the sm_120 / LayerNorm / `ProtenixFilter` patches and the JIT smoke test all stay, and `pxdesign_protenix_iptm` remains a native metric (never used for ranking, since a tool's self-assessment favours its own designs).
  - Removed as now-purposeless: the `pip install binder-compare` step into `binderscout_pxdesign`, which existed solely so `refold-protenix` could run there.
  - `--primary-engine` choices are now `boltz | af3 | esmfold2` in both `evaluate.sh` and `report`.
- Fixed while in the same code: the wizard's Step 7 preview listed Boltz-2/AF3/Protenix but never **ESMFold2**, so a selected ESMFold2 was invisible in the run summary.

### Fixed (2026-07-26 — configurator targeted the wrong chain)
- **mmCIF targets ignored the chain you selected.** `extract_sequence_from_cif` tried `_cif_entity_poly_seq()` first, which takes no chain argument and returns the **longest** polymer entity; the chain-aware `_atom_site` branch only ran when `_entity_poly` was absent. Since essentially every PDB-derived mmCIF carries `_entity_poly`, the Step 3 chain answer was almost always discarded — asking for a 100 aa antigen in an antibody-antigen structure yielded the 220 aa heavy chain, and every tool then designed against the wrong protein while the Evaluator refolded and scored that same wrong target. Reordered so the chain-aware branch runs first; `_entity_poly` is now a last resort that prints an explicit warning naming the chain and the fallback length. `.pdb` input was never affected (`extract_sequence_from_pdb` already filtered on chain).
- **Mosaic hotspots always resolved against chain A.** `hotspots_to_epitope_idx` read `cfg["target_chain"]` / `cfg["chain"]`, neither of which the wizard ever assigns — it writes `cfg["chains"]` — so the `"A"` fallback was used on every run and hotspot residue numbers came from chain A's numbering regardless of the user's selection.
- Tests: 12 new cases in `tests/configurator/test_configurator_writers.py` with two-chain mmCIF/PDB fixtures where the requested chain is the *shorter* entity, so a longest-entity answer is distinguishable; 8 of them fail against the pre-fix code. 213 pass.

### Changed (2026-07-23 — two-stage screen reverted to `max`)
- **`max` is the default two-stage screen metric again (correcting the 2026-06-16 flip to `mean`).** The two-stage design is a *lenient recall screen* → *strict consensus rank*: Stage 1 screens by `consensus_iptm` (**max** over engines) so a genuine binder isn't dropped because one engine's per-target blind spot lowers its mean; Stage 2 then ranks survivors by `consensus_iptm_mean`. Screening by mean made Stage 1 too strict (it can drop a design a single engine strongly likes). `--screen-metric mean` still available (Adaptyv macro AUC 0.710 vs 0.689; max is ProteinBase ~0.755). `rank_by_two_stage(screen_metric=)` and `report --screen-metric` default to `max`; tests updated.

### Added (2026-06-26 — `prefilter`: fold-back ranking for tools with no native interface metric)
- **`binder-compare prefilter`** ranks designs by a cheap Boltz-2 **fold-back interface score** (`boltz_pae_ipsae_min` default, or `boltz_pae_iptm`) recomputed from the Boltz-2 PAE files — the literature-standard RFdiffusion recipe (diffusion gives geometry, the fold-back gives the rank; Bennett et al. 2023; the 2025 3,766-binder meta-analysis found ipSAE the best single in-silico predictor). Intended for **RFD3**, the one tool with no native interface metric, which was otherwise selected by `mpnn_sequence_recovery` (a sequence proxy with no binding signal) — the reason its refold pool was full of non-interfacing designs (ipSAE_min = 0). New module `cli/prefilter.py` (`build_selection`, `_fasta_metadata`); registered in `main.py`.
  - Recipe: `refold-boltz2` (Mosaic venv) over all designs → `prefilter --metric ipsae_min --top N` (binder-eval) → feed the ranked CSV as `report --tool-csv rfd3=<sel>` and select the top-N for the full cross-engine refold. Output is sorted best-first with a `sequence` column, so it drops straight into the report's native section / `candidates.csv` (RFD3 then ranks by fold-back, not recovery).
  - Reuses `add_boltz_ipsae_from_files` + `add_iptm_from_pae_files` so the prefilter numbers match the evaluator's consensus inputs; falls back to the raw Boltz-2 `ipsae_min`/`iptm` columns when PAE files are absent.
- Tests: `tests/binder_comparison/test_prefilter.py` (best-first ranking, sequence de-dupe, top-N, FASTA id attach, metric switch); 117 pass.

### Added (2026-06-25 — combined `candidates.csv` per-tool + refold shortlist)
- **`binder-compare report` now writes `candidates.csv`** — a single reviewer-facing shortlist: one "Native top-20" block per tool (in canonical order: BindCraft, BoltzGen, Mosaic, Proteina-Complexa, PXDesign, Protein-Hunter, RFD3) followed by the "Refold top-30" cross-engine two-stage ranking last. Columns: `Set, Method, Ranking native, Ranking refolded, Mean_ipTM, Mean_ipSAE_min, Solubility SoluProt, Length, Primary sequence`. New module `comparison/candidates.py` (`build_candidates_table`, `collapse_native_df`, `order_tools`). Built straight from the tools' **raw** native CSVs — no pre-processing scripts.
  - **In-pool filter** — native designs that were never refolded carry no cross-engine metrics, so they are dropped (the general, target-agnostic form of the old campaign-specific "drop PXDesign 150/160aa" hand-step; verified to reproduce the prior per-tool native top-20 exactly).
  - **Backbone collapse** — MPNN/cycle siblings collapse to one row per `design_group` (best native rank kept); the native top-20 is distinct backbones.
  - **Single dense refold rank** — both blocks' "Ranking refolded" use the collapsed two-stage order keyed by `design_group`, so a native design and the refold-block appearance of its backbone agree; "Ranking native" for a refold rep also resolves by `design_group` (a refold rep that is a different MPNN sibling than the native-best one still gets its backbone's native rank).
- **Report HTML "Top Designs per Tool" section** now applies the same collapse + in-pool filter from raw native CSVs (previously it relied on externally pre-collapsed/-filtered CSVs), orders tools canonically, and its `eval_rank` matches the dense refold rank used by the Top-30 table and `candidates.csv`.
- Native sequence-column preference is now full-chain-first (`designed_chain_sequence` before `sequence`) — fixes nanobody/CDR-redesign BoltzGen, whose native `sequence` column is the truncated CDR while the refold pool is keyed on the full VHH.
- Tests: `tests/binder_comparison/test_candidates.py` (order, in-pool filter, backbone collapse, design_group rank resolution, dense-rank consistency, full-chain seq preference); 112 pass.

### Changed (2026-06-16 — two-stage `mean` screen default · Part N gate-then-density · advisory report panels)
- **`mean` is now the default two-stage screen metric.** `binder-compare report` / `rank_by_two_stage` default `--screen-metric mean` (`consensus_iptm_mean`) — the stronger binder-vs-non-binder screen on the Adaptyv 4-target benchmark with experimental Kd (macro AUC 0.710 vs 0.689 for max; +20 true binders recalled and higher purity at the 50% cut), and more robust to one engine's per-target blind spots. The legacy max screen stays available via `--screen-metric max` (ProteinBase-validated, ~0.755). Column name `passes_max_screen` kept for plot/viz compatibility.
- **Part N affinity redesigned to gate-then-pure-density.** On Adaptyv (experimental Kd) `ipsae_min` carries ~0 / sign-unstable correlation with affinity among binders, so it is no longer a multiplier: `affinity_energy_density = |dG/dSASA|` ranks affinity and `passes_affinity_gate = ipsae_min ≥ 0.61` gates. `affinity_composite`/`add_affinity_composite` renamed `interface_energy_density`/`add_affinity_ranking`; `binder-compare affinity --gate-threshold` added. (ΔG itself still unvalidated as an affinity ranker — open follow-up.)
- **`binder-compare report --qc-results`** ingests qc-annotate's BindCraft interface panel (`qc_pass` / `qc_fail_reasons` / `interface_*`) joined by `binder_id`.
- **Advisory SoluProt + qc-annotate columns surfaced in the report HTML** (top-N table + full table + legend) — shown only when present; advisory, never used to reorder or drop designs (hard-gating either removes true binders).
- Tests: screen-metric + gate-then-density (incl. ipsae-independence) + report-advisory suites; 108 pass.

### Added (2026-06-16 — SoluProt aarch64 enablement)
- **SoluProt now runs on aarch64 / DGX Spark.** Install with `bash install/install_aarch.sh --tool soluprot` (the aarch64 installer; the x86 `install.sh` now redirects aarch64 users here instead of refusing). It builds the env imperatively and works around all four aarch64 blockers, validated on Spark both for cross-platform fidelity (r≈0.96 vs the x86 reference output) and for **accuracy on SoluProt's own labeled benchmark** (the paper's balanced independent test set, 3100 seqs in `soluprot_data.zip`): **ROC-AUC 0.621 / MCC 0.157, matching Hon et al. 2021's reported 0.62 / 0.17** (the small MCC gap is the documented −0.5% from `--no_tmhmm`):
  - **scikit-learn 0.20.4 built from source** — the pinned 0.20.1 has no aarch64 build, and the model pickle won't `predict()` under aarch64's 0.21/0.22 (raises `get_init_raw_predictions`); 0.20.4 is the same minor series and still `<0.23` so `sklearn.externals.joblib` imports.
  - **open-source USEARCH v12 built from source** (`rcedgar/usearch12`, GPLv3) for the identity feature — `vsearch` cannot substitute (nucleotide-only) and the `bioconda::usearch 12.0_beta` aarch64 build crashes at startup.
  - **`--no_tmhmm` model** (shipped `grad_clf_v1_tc_notmhmm.pkl`, ~-0.5% accuracy) drops the x86-only TMHMM binary.
  - **biopython ≥1.78 source patch** for `soluprot.py` + 3 `feature_scripts/*.py` (removed `Bio.Alphabet`/`IUPAC`); `numpy<1.24` / `pandas<1.4` pins.

### Fixed (2026-06-16)
- **`soluprot_runner.py` invoked the wrong CLI** — it called `soluprot.py --input/--output`, but SoluProt 1.0.1.0's real CLI is `--i_fa/--o_csv/--tmp_dir` (and needs `--no_tmhmm`/`--usearch`); the integration would have failed on *any* platform. The runner now builds the correct command, auto-resolves the USEARCH binary (`$SOLUPROT_USEARCH` → `<dir>/usearch` → PATH) and the `--no_tmhmm` decision (auto when no TMHMM binary is found), and uses Python-3.7-safe cleanup (the env is py3.7; the previous `Path.unlink(missing_ok=)` is 3.8+). New optional `--usearch` / `--no-tmhmm` overrides on `binder-compare filter-soluprot` and `scripts/filter_soluprot.py`.
- **SoluProt download URL was a 404** — both installers used `.../soluprot/api/download/soluprot.zip`; corrected to `.../soluprot/?page=download&f=soluprot.zip`.
- **SoluProt's `usearch_global` command** — both installers now patch the downloaded `soluprot.py`'s `-search_global` (rejected by USEARCH v12, undocumented in any version) to the canonical `-usearch_global`.
- **`binder-compare` can't live in the Python 3.7 SoluProt env** — `binder-comparison` is `requires-python>=3.10` (`numpy>=1.24` / `pandas>=2.0`), so installing it into `binder-eval-soluprot` (py3.7, scikit-learn 0.20.x) is impossible; yet `evaluate.sh`, the installer smoke test, and the `soluprot` shortcut all ran it *there*. Decoupled: `binder-compare filter-soluprot` now runs in `binder-eval` (py3.10) and the runner shells out to the py3.7 env's interpreter via `$SOLUPROT_PYTHON` (auto-resolved to the sibling `binder-eval-soluprot` env otherwise). Installers no longer pip-install binder-compare into the py3.7 env; the smoke test is `soluprot.py --help` in that env. Also fixes `core/schema.py` importing `typing.Literal` (3.8+) — now guarded for the py3.7 env via `TYPE_CHECKING`.

### Added (2026-05-28 / 29 — repo rename + master/aarch64 alignment + SoluProt)
- **Project renamed from BinderScout (working name) to BinderScout** (GitHub repo `damborik22/BinderScout`). CLI command, conda env names, file/dir names, and env vars still use `binderscout` and will be migrated incrementally. README + CI badge URL updated; old `damborik22/BinderScout` URL redirects.
- **AF3 v3.0.2 ported from aarch64-only to master** — `binder-compare refold-af3` subcommand, `Evaluator/scripts/refold_af3.py`, runner, env spec, and full installer integration on both `install/install.sh` (x86) and `install/install_aarch.sh` (aarch64). Opt-in via `--tool af3`; not in `--tool all` because of the ≥100 GB GPU memory gate and gated weights. Auto-detected by `evaluate.sh` and the configurator.
- **ESMFold2 ported from aarch64 to master** — `binder-compare refold-esmfold2` subcommand + producer files + installer (`--tool esmfold2`, both installers, opt-in). Lightweight 4th refold engine, no gated weights. Merger + report consume the CSV; `--primary-engine` choices extended to include `esmfold2`. Configurator's Step 5 picker surfaces ESMFold2 when `binder-eval-esmfold2` env is present.
- **SoluProt 1.0 solubility screen** (Hon et al. 2021) integrated as opt-in via `--tool soluprot` on both installers (aarch64 enabled as of 2026-06-16 — see entry above). New `binder-compare filter-soluprot` subcommand, `binder-eval-soluprot` conda env (Python 3.7 + scikit-learn 0.20.1 pinned), standalone `Evaluator/scripts/filter_soluprot.py`, runner wrapper. `evaluate.sh` runs SoluProt as Step 0.5 with `--skip-soluprot` / `--soluprot-env` / `--soluprot-threshold` / `--soluprot-filter` flags; the last drops sub-threshold designs from the FASTA *before* any refold engine sees them. Report consumes `--soluprot-results` CSV; `NativeMetrics` gains `soluprot_score` + `soluprot_passes` fields. Configurator Step 5 sub-prompt walks the user through enable / threshold / filter-mode. Not part of `agreement_count` — it's a screen, not a re-ranker. Plan at `docs/PLAN_soluprot_integration.md`.
- **Native (design-time) metrics preserved for every tool.** All seven design tools' extractors (BindCraft, BoltzGen, Mosaic, PXDesign, Proteina-Complexa, Protein-Hunter, RFD3) now populate `NativeMetrics` with tool-specific fields. `binder-compare extract` writes a sidecar `<fasta_stem>_native_metrics.csv` alongside the FASTA; `binder-compare report` auto-detects it and joins on sequence. Result: the final `metrics.csv` now carries `native_<tool>_<metric>` columns showing what each design tool said about its own output, next to the cross-validation refold scores. Schema grew 9 → 36 fields; ~25 new tool-prefixed fields. Plan rationale: "compare what the tool said about its own design vs. what the refold engines say."
- **`--top-per-tool N` flag on `binder-compare report`** replaces five hardcoded `head(10)` calls in the per-tool native-ranked sections (radar plots, per-tool tables, per-tool 3D viewers). Default still 10; users wanting more per-tool drill-down can bump it. Lands the user requirement: "if user wants more than our 10 in report."
- **Configurator wizard upgrade.** Step 5 picker now covers all 8 tools (RFD3 + Protein-Hunter were previously orphaned despite having `write_run_*` functions). Refolding-engine sub-prompt (Boltz-2 / Protenix / AF3 / ESMFold2) only shows engines whose env is installed; single-select primary-engine prompt fires when more than one engine is chosen. New Step 6g (RFD3) and Step 6h (Protein-Hunter) per-tool settings sections covering tool-specific knobs (batch_size / num_cycles / MSA mode etc.) plus the standard length / n_designs overrides.
- **`binder-compare extract --rfd3 / --protein-hunter`** flags carried through to `evaluate.sh`'s extract step.
- **Two repository visualizations** in README: upgraded pipeline Mermaid (now shows all 4 refold engines + SoluProt screen + the optional drop path) plus a new "Components at a glance" Mermaid (CLI → install/configure/evaluate dispatch → design-tool envs / evaluator envs / per-run artifact layout, colour-coded).

### Changed (2026-05-28 / 29)
- **Best-practice defaults for the configurator.** Mosaic `TOP_K` default `n_designs` → `min(5, n_designs)` (matches the `hallucinate_binderscout.py` template). RFD3 `diffusion_batch_size` default 8 → 10 (template guidance). Protein-Hunter `num_cycles` 5 → 7 (CALCA-validated). Protein-Hunter `msa_mode` `mmseqs` → `single` (paper-fastest, no ColabFold roundtrip).
- **`Evaluator/evaluate.sh` is a 4-engine orchestrator** + SoluProt screen. Engine selection via `--skip-{boltz2,protenix,af3,esmfold2,soluprot}`, env override via `--{protenix,af3,esmfold2,soluprot}-env ENV`, primary picked via `--primary-engine boltz|protenix|af3|esmfold2`. Step counter `N_STEPS` auto-sizes to active engines + report.
- **`binder-compare report`** accepts `--esmfold2-results`, `--soluprot-results`. `--primary-engine` choices extended to `boltz|protenix|af3|esmfold2`. `_ENGINE_IPSAE_COLS` gains the esmfold2 entry.
- **`write_run_evaluate` (configurator)** now produces correct calls into `evaluate.sh`: dropped the broken `--target-pdb` and `--mosaic-path` flags (`evaluate.sh` never accepted them); appends correct `--skip-*` flags per the user's engine selection, plus `--primary-engine` and `--soluprot-threshold` / `--soluprot-filter` when relevant.

### Fixed (2026-05-28 / 29)
- **`binderscout evaluate` dispatcher path** (`binderscout.py:110`) — was pointing at `evaluator/evaluator.py` (which doesn't exist) instead of `evaluator_legacy/evaluator.py`. Same fix applied to `tui/app.py` Evaluate menu paths.
- **Installer drift on master**: `install.sh:142` `--help` Usage line was missing `protein-hunter` and `rfd3` (the validator accepted them but `--help` didn't list them). Now lists all current-generation tools + the opt-in eval tools.
- **`Evaluator/evaluate.sh` arg parsing**: `Evaluator/run.sh` and configurator-generated `run_evaluate.sh` were both passing `--target-pdb` to `evaluate.sh` which rejected it with `Unknown argument`. The flag is removed from the configurator (target sequence is already passed separately) and `evaluate.sh`'s arg parser is unchanged.

### Removed
- **Unused `binderscout/` Python package removed.** The experimental scaffolding — `BinderScore`/`ToolOrigin` unified scoring (`scoring/unified.py`), the `ToolAdapter`/`ToolResult` contract + `PXDesignRunner` (`tools/`), the `FeatureFlags` system (`feature_flags.py`), and the empty `scheduler/` stub — was never wired into the CLI, TUI, configurator, or evaluator; its only importers were `examples/pxdesign_pdl1_test.py` and its own unit tests. The `Evaluator` package (`StandardisedMetrics` + benchmark-validated `consensus_iptm` ranking) is the single scoring layer, so the parallel records were dead duplication. Removed the package, the example, and `tests/scoring/` + `tests/tools/`. Git history retains it if the pre-refold-screen idea is ever revived.
- **RFAA fully removed.** RFDiffusionAA + LigandMPNN install path, the `binderscout_rfaa` conda env, the `--tool rfaa` flag in both installers, the RFAA extractor in the Evaluator package, the `--rfaa` flag on `binder-compare extract`, the `_parse_rfaa()` legacy parser, the `binderscout.tools.rfaa` Python package, the `binderscout_examples/`-equivalent test scripts, the `bin/rfaa` shortcut, the `rf_diffusion_all_atom/` and `LigandMPNN/` cloned repos, and `docs/rfaa_manual_reinstall.md`. Use RFD3 (`--tool rfd3`) for all-atom diffusion-based binder design instead. Git history retains the recipe if anyone ever needs to reproduce an old RFAA result.

### Added (previous Unreleased entries)
- **PXDesign** (Protenix): full pipeline support — diffusion, MPNN sequence design, AF2 complex/monomer evaluation
- Post-install patches in both installers for PXDesign upstream issues (NumpyEncoder, num_workers, CUDA arch, ColabDesign, deepspeed, JAX pin)
- aarch64 run scripts auto-detect platform and set `TORCH_CUDA_ARCH_LIST` and `JAX_PLATFORMS` for Blackwell GPUs

### Changed (previous Unreleased entries)
- **BindCraft pin** `828fd9f` → `7cd4ace` (3 upstream bugfixes): graylab→west.rosettacommons.org PyRosetta wheels (x86_64), `range(11,15)→(11,16)` model-selection fix, stage-3 `onehot_plddt` init + `align_pdbs` crash guard

### Added (Parts L + M — Protein-Hunter & RFD3, on `refactor/af3-rfd3-ph`)
- **Part L — Protein-Hunter** (Cho et al. 2025) installable via `binderscout install --tool protein-hunter` (x86 only; aarch64 blocked by pyrosetta). Conda env `binderscout_protein_hunter` (Py 3.10), vendored Boltz-2 + LigandMPNN + Chai-1 (sokrypton fork), shortcut `bin/protein-hunter`. New Evaluator extractor reads `summary_high_iptm.csv` by default (`--all-protein-hunter-designs` for all runs). Supports all 6 modalities via upstream `design.py` flags (protein / cyclic / ligand-CCD / ligand-SMILES / DNA / RNA). `SourceTool` Literal + tool colors/displays extended.
- **Part M — RFD3 (RosettaCommons/foundry v0.1.9)** installable via `binderscout install --tool rfd3`. Conda env `binderscout_rfd3` (Py 3.12), `rc-foundry[rfd3,mpnn]` from PyPI, weights at `BinderScout/weights/foundry/`. BSD-3-Clause, commercial-use OK, works on aarch64 (no DGL). Shortcut `bin/rfd3` runs `rfd3 design ...` or opens an env shell. New `RFD3Extractor` with defensive CSV/FASTA parsing. Tool colors/displays added.

### Added (Part K — AF3 v3.0.2 refolder, canonical 2nd engine)
- **AlphaFold 3 v3.0.2 as the canonical 2nd refolding engine on big-VRAM hardware** (DGX Spark, H200, any host with >100 GB unified or device memory — full AF3 inference does not fit on consumer 24 GB GPUs).
- New CLI: `binder-compare refold-af3` — runs inside the dedicated `binder-eval-af3` conda env (separate from the BindCraft / Mosaic / PXDesign envs so PyTorch + JAX versions don't fight).
- Schema: `af3_*` columns in `StandardisedMetrics` (iptm, ptm, ranking_score, plddt_binder_mean/min, plddt_target_mean, pae_bt/tb/bb, bt_ipsae, tb_ipsae, ipsae_min). pLDDT rescaled 0-100 → 0-1 on ingest. PAE transposed from AF3 token-order to `[binder|target]` to match Boltz-2.
- `binder-compare report` gains `--af3-results` flag.
- `Evaluator/evaluate.sh` runs Boltz-2 + AF3 by default on hosts that have the `binder-eval-af3` env.

### Added (Part J — Protenix refolder, optional fallback, on `refactor/af3-rfd3-ph`)
- **Protenix v0.5.0 as optional 3rd refolding engine for smaller GPUs** — ByteDance's open-source AlphaFold 3 reimplementation (~3-4 GB weights auto-downloaded from ByteDance TOS, runs comfortably on 24 GB GPUs). Not part of the canonical Boltz-2 + AF3 pipeline; opt in when AF3 isn't an option.
- New CLI: `binder-compare refold-protenix` — runs inside the existing `binderscout_pxdesign` conda env (no new env needed).
- New files: `Evaluator/scripts/refold_protenix.py`, `Evaluator/binder_comparison/refolding/protenix_runner.py`, `Evaluator/binder_comparison/cli/refold_protenix.py`.
- Schema: `protenix_*` columns in `StandardisedMetrics` (iptm, ptm, ranking_score, plddt_binder_mean/min, plddt_target_mean, pae_bt/tb/bb, bt_ipsae, tb_ipsae, ipsae_min). `af3_*` counterparts also reserved for Part K. pLDDT rescaled 0-100 → 0-1 on ingest.
- Scoring: new generic `add_ipsae_from_pae_files(df, prefix=...)` for any engine's saved PAE matrix.
- Merger: multi-engine support — `merge_refold_results(boltz2_csv, ..., protenix_csv=..., af3_csv=...)`. Accepts any combination; outer-joins on `sequence`.
- `compute_agreement` now sums {boltz_pae_ipsae_min, protenix_ipsae_min, af3_ipsae_min} passing the 0.61 threshold (0–3 on Spark, 0–2 on x86).
- Orchestration:
  - `Evaluator/evaluate.sh` auto-detects `binderscout_pxdesign`; Protenix step runs between Boltz-2 and report unless `--skip-protenix` or env missing.
  - `binder-compare run --protenix-env binderscout_pxdesign` enables Protenix; omit to skip.
  - `binder-compare report` gains `--protenix-results` and `--af3-results`.
- Installer: PXDesign step now pip-installs `binder-compare` into `binderscout_pxdesign` env so Protenix refolding is available after `binderscout install --tool pxdesign`.
- **Live smoke test passed** — 2 × 43aa random binders against 76aa ubiquitin target: inference ~12 s/design on RTX 3090, CSV + `*_pae.npy` populated, token-pair PAE extracted via `need_atom_confidence=True`, DunbrackLab ipSAE computed downstream in the report.

### Removed (Part I — AF2 refolding removal, on `refactor/af3-rfd3-ph`)
- Evaluator AF2 refolding is gone. This is step 1 of the AF3/Protenix refactor; AF3 (Part K) becomes the canonical 2nd engine on big-VRAM hardware (Spark / H200), with Protenix (Part J) as the optional fallback for 24 GB GPUs.
- Deleted files: `Evaluator/scripts/refold_af2.py`, `Evaluator/scripts/refold_Version6.py`, `Evaluator/binder_comparison/refolding/af2_runner.py`, `Evaluator/binder_comparison/cli/refold_af2.py`, `Evaluator/envs/binder-eval-af2.yml`
- Installer no longer creates `binder-eval-af2` conda env (uninstall path still cleans legacy installs)
- Schema: removed 8 `af2_*` fields from `StandardisedMetrics`, 2 from `PerResidueData`; pruned `af2_*` entries from `LOWER_IS_BETTER`, `ZSCORE_METRICS`; `model_weights` default now `{"boltz2": 1.0}`
- Scoring: deleted `add_af2_ipsae_from_files`; `compute_agreement` engine list now `[boltz_pae_ipsae_min, protenix_ipsae_min, af3_ipsae_min]` (Protenix/AF3 columns land in Parts J & K)
- Merger: `merge_refold_results(boltz2_csv, sequences_fasta)` (dropped `af2_csv` param)
- Report & plots: removed `_compute_af2_boltz2_r`, `_correlation_callout_html`, `plot_af2_vs_boltz2_scatter`; pruned all `af2_*` columns from display lists and tooltip map
- Evaluator orchestration: `evaluate.sh` is now 2-step (Boltz-2 + report); `binder-compare run` is 3-step (extract + refold-boltz2 + report)
- BindCraft's internal AF2 design path, PXDesign's internal AF2 eval, and Proteina-Complexa's AF2 cross-val **all stay** — only Evaluator AF2 refolding was removed

### Fixed
- Configurator `ask_choice()` return value destructuring for PXDesign mode and preset selection
- RFAA template: Python 3.12 f-string syntax replaced with 3.10-compatible `ligand_line` variable
- RFAA template: added missing PYTHONPATH export and `inference.ckpt_path`
- PXDesign requirements.txt overwrites PyTorch with CPU-only version — installer now force-reinstalls with CUDA

## [0.7.0] — Part H: Standalone installer (server-friendly)

### Added
- **Standalone mode**: installer auto-downloads Miniforge3 into `BinderScout/conda/` when system conda is unavailable or read-only (H1–H3)
- `--standalone` flag to force local Miniforge install (H1)
- `--system-conda` flag to opt out and use existing system conda (H1)
- Local conda detection in all Evaluator shell scripts — `evaluate.sh`, `run.sh`, `install.sh` (H13–H15)
- Local conda as first search entry in all generated run scripts from configurator (H12)
- `PLAN_standalone_installer.md` — detailed implementation plan for Part H
- `TODO_standalone_pack.md` — future plan for pre-packed distribution (Part I)

### Changed
- Shortcuts now write to `BinderScout/bin/` instead of `~/.local/bin/` (H4, H9)
- `detect_conda()` rewritten with priority: local conda → writable system conda → auto-bootstrap (H3)
- `_find_conda_base()` in configurator checks `BinderScout/conda/` first (H11)
- `binderscout.py` shortcut writes to `REPO/bin/` as primary, `~/.local/bin/` as non-fatal fallback (H9)
- Uninstall offers to remove local Miniforge when all tools are uninstalled (H7)
- Install summary now prints PATH instructions for `BinderScout/bin/` (H4)
- All changes mirrored in `install_aarch.sh` for aarch64 / DGX Spark (H8)

## [0.6.1] — Part G: Documentation & CI

### Added
- GitHub Actions CI workflow — shellcheck, ruff, Docker build (G1)
- README badges: CI status, license, Python version, platform (G2)
- CONTRIBUTING.md with development setup and PR conventions (G3)
- CHANGELOG.md (G4)
- Mermaid architecture diagram in README (G5)
- Evaluator troubleshooting section with 7 common issues (G6)
- `ruff.toml` configuration for Python linting and formatting (G1)

### Changed
- Shell scripts now pass `shellcheck --severity=warning` with targeted directives (G1)
- Python code auto-formatted with `ruff format` (G1)

## [0.6.0] — Part F: Configurator UX

### Added
- Evaluator as a tool option in configurator wizard — Step 5 (F1)
- Run folder archiving: `configurator.py --archive <run>` creates tar.gz (F3)
- `configurator.py --status` shows all runs and their completion state (F4)
- Target sequence auto-extraction from mmCIF files (F5)

## [0.5.0] — Part E: Evaluator Enhancements

### Added
- DunbrackLab ipSAE formula: mean aggregation, model-specific PAE cutoffs (E1)
- `--resume` flag for evaluate.sh — skip completed binders via CSV check (E2)
- PXDesign as tool option in configurator wizard (E3)
- `binder-compare validate` subcommand for input sequence sanity checks (E4)
- Per-binder PAE heatmap visualisation in HTML report (E5)

### Changed
- ipSAE columns renamed: Mosaic aux columns get `_aux` suffix, PAE-based columns get `boltz_pae_`/`af2_` prefix (E1)
- Primary ranking column `ipsae_min` now promoted from best available PAE-based source (E1)

## [0.4.0] — Part D: Installer Robustness

### Added
- `Dockerfile.test` with GPU-capable CUDA base image and multi-stage test target (D1)
- `--dry-run` flag for `test_env.sh` — non-interactive install validation (D2)
- `--cuda` flag for `install_aarch.sh` with compatibility warning (D3)
- Retry logic in `run_logged()` with optional `--retries N` (D4)
- Numbered progress summary: "[1/4] BindCraft", "[2/4] BoltzGen", etc. (D5)
- `--uninstall` flag for per-tool removal of conda envs, venvs, and shortcuts (D6)

### Changed
- Tool repos pinned to specific commits for reproducible installs (D7)

## [0.3.0] — Part B: Batch 1 Fixes

### Added
- MIT LICENSE at repo root (B1)
- `--yes/-y` flag for non-interactive installs in `install.sh` (B3)
- Evaluator support in `install_aarch.sh` (B4)
- Exception-based checkpoint in `refold_boltz2.py` (B9)

### Fixed
- `run_logged()` tty guard and tmpfile for failure output (B2)
- Configurator Ctrl+C message (B5)
- `docker-entrypoint.sh` mamba.sh, HOME fallback, .bashrc (B6)
- CSV file handle leaks in refold scripts (B8)
- Hardcoded `AF2_DATA_DIR` in `refold_af2.py` (B10)
- Scatter plot crash on empty mask in `plots.py` (B11)
- Radar chart in `plots.py` — use z-scores (B12)

### Changed
- Added `.dockerignore` (B7)

## [0.2.0] — Part A: Monorepo Merge

### Added
- Evaluator files merged under `Evaluator/` directory (A1)

### Changed
- Root `.gitignore` updated for evaluator patterns (A2)
- `install.sh` `install_evaluator()` uses local dir instead of git clone (A3)
- README updated to reflect bundled evaluator (A4)

## [0.1.0] — Initial Release

### Added
- Unified `binderscout` CLI entry point (`install`, `configure`, `evaluate`)
- Installers for BindCraft, BoltzGen, and Mosaic
- Interactive configurator wizard
- Evaluator with Boltz-2 and AF2 refolding pipeline
- aarch64 installer for DGX Spark / Grace-Hopper
- Docker test environment
