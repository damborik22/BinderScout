# Repo diary — the 2.0 chapter

> **Extract, not a source.** Lines 2099+ of `docs/REPO_DIARY.md` as of `23379f2`.
> The diary is the living copy; this exists so the 2.0 chapter can travel without
> its 2,098 lines of predecessors. If they disagree, the diary is right.
>
> It records **how each finding was reached**, including the wrong turns. That is
> the point of it — the conclusions are in `docs/PLAN_2.0_CONCLUSION.md`.

---

# Part 2.0 — the 2.0 release line

Everything below is `v2.0.x` work. One entry per stage as it lands, newest at the
bottom, in the same register as the chapters above: what changed, what it cost,
and what turned out to be wrong.

---

## 2026-09-23 → 09-25 — Stage 0: the pipeline kept no original output, and three shipped commands had never produced a number

Five threads, and the connecting theme is that every defect below was **silent** —
each had a legitimate-looking state it could hide inside, and several masked each
other.

**`rank` was corruptible by a duplicate sequence.** Four unguarded left joins in
`report.py` multiplied rows when two designs shared a sequence. Confirmed live in a
shipped 2VDY campaign — 3 duplicate sequences turned 439 designs into 445 rows —
which escaped only because none reached the reported top 350. All four now route
through one guarded merge that drops duplicates and warns.

**Stage 1 (item AD) rested on a premise that was wrong.** The plan called
`generation_index` "one line per extractor", assuming each globs per-design files so
`stat()` gives a generation time. Seven of eight instead read ONE aggregate CSV.
The investigation (`INVESTIGATION_generation_index_2026-09-24.md`) established per
tool what can honestly be recovered, and the answer is that **row position is usable
for no tool at all** — where a file is in generation order the extractor re-sorts
before iterating, and where it is not, the order is quality. Five tools can report an
index, by four different routes: an explicit counter (Mosaic, Protein-Hunter), a join
on design hash to another table (BindCraft 2's `trajectory`), or a parsed identifier
(BoltzGen, RFD3). Three cannot, and for Proteina-Complexa that is **structural rather
than missing**: under MCTS the pool is a flattened tree mixing lookahead roll-outs with
terminal states, so a scalar index has no consistent meaning, and its `sequences.csv`
path is `random.shuffle`d outright. `unavailable` is therefore a first-class value,
pinned by tests that no production code makes pass.

**A regression introduced and caught inside the same session.** Adding
`generation_index` to the Mosaic template put it *between* `rank` and `is_top`.
`designs.csv` is append-mode across runs and the extractor reads it positionally, so
a file holding both vintages read the newer rows one position out and `sequence`
picked up `is_top` — the reproduction reads a sequence as `'1'`. Appended last
instead, a mixed file degrades to an unnamed trailing column. The lesson is narrow
and worth keeping: in a positionally-read append-mode file, new columns go at the
end, never in the middle.

**The PXDesign collector's preferred path was dead code.** It globbed
`filtered_summary.csv`, which PXDesign's own `cleanup_outputs()` unlinks during the
run — so it never matched once, every run silently took the unranked fallback, and
`pxdesign_rank` shipped empty. `summary.csv` holds the same rows and survives. Two
traps made it more than a filename swap, both silent: `trim_summary_df` **renames**
the AF2 metrics, so swapping only the glob would recover `rank` and blank three
metrics; and `summary.csv` has no per-design `name`, so every id would have collapsed
to `pxdesign_summary`.

**The pipeline preserved neither original CSVs nor structures.** `--tool-csv`,
`--collect-structures` and a per-tool discovery script all existed; the generated
`run_evaluate.sh` passed none of them. So a run kept only refold-derived numbers and
discarded what each tool said about its own designs. Now wired, with `--tool-root` on
`evaluate.sh`.

**The Rosetta interface panel had never emitted a value.** Three stacked failures:
PyRosetta replaced the string interface spec with a `DockingPartners` object (and each
call site's per-structure `except` turned the `TypeError` into an empty row per
design); DAlphaBall could not load `libgfortran.so.5`, present in the env but not on
the subprocess search path; and the id namespaces never overlapped, so both left joins
attached nothing. Each masked the next — nobody reached bug 3 because bug 1 killed it
first. Verified fixed on a real golden-pool structure: `sc 0.77, dG −84.23, nres 32,
hbonds 4, unsat 2.0`, carried through `qc-annotate` to `1 covered, 1 qc_pass=True`.

**And a fourth, found by measuring rather than reading.** `interface_energy.py` never
relaxed, while `completed_plans.md` claimed it did "relax-before-score as BindCraft
does". On one AF3 structure: **dG +213.8 REU unrelaxed, −89.5 after FastRelax** — a
303 REU swing that flips the sign, against a gate of dG ≤ 0. Part N's `|dG/dSASA|`
ranking had been ranking clash energy.

**A literature pass corrected our reading of the field.** RFD3 emits no quality score
*by design* — the preprint names no selection metric, foundry's FAQ disclaims the one
score in its output, and the packages ship no filter module. The field's answer is
uniform: don't rank backbones, fold them back and rank the fold. Crucially the
canonical threshold does **not** transfer: `pae_interaction < 10` is an AF2
*initial-guess* number, measuring whether a predictor **holds** a pose it was handed
rather than **finds** it, and none of our three engines is AF2-IG. What does transfer
is BindCraft's confidence half, now ported in shadow mode with the conversion nailed
exactly — ColabDesign divides PAE by **31.0**, so 0.35 → **10.85 Å** (not 31.75, the
last bin *centre*). One trap caught by measurement: ESMFold2's scalar `iptm` is
chain-averaged and runs **+0.137 to +0.239** above the interface value on all six
golden-pool designs.

**Process notes.** Adversarial verification earned its keep twice and was itself
wrong once — a refutation of the PXDesign fix claimed a 100× pool collapse from
argparse defaults, missing that `cli.py` overrides them; and a literature synthesis
contained **six fabricated or misattributed citations**, including a PMID/PMCID pair
that does not exist. Verify the verifier. Separately, `ruff check . | tail -1` takes
its exit code from `tail`, so a failing lint passed an `&&` chain and shipped — the
second exit-code-masking mistake of the session.

**Open at the end of Stage 0:** the pool-filtering question for AD's metric (most
extractor inputs are already downstream of a quality filter, so a discovery rank over
them is conditioned on survival); `tools/rfd3_gate.py` and `binder-compare prefilter`
both written and neither wired; and the self-consistency RMSD axis, which every
published gate couples with interface confidence and we do not compute at all.

---

## 2026-09-25 — Stage 1: the RFD3 gate and the fold-back rank were both written and neither was connected

Two capabilities already in the repo, neither reachable from a generated run.
That is now three instances of the same defect class in this release line — the
tool CSVs, the design structures, and these — which is enough to call it a
pattern rather than an accident: **this repo's characteristic failure is
building the thing and not wiring it.**

**The geometry gate now runs between diffusion and ProteinMPNN**, which is where
CLAUDE.md has said it belongs since the round-3 post-mortem. The history is the
argument: 304 backbones shipped as extended coils because
`infer_ori_strategy: hotspots` was missing, and nothing caught it — the
structures still report `n_chainbreaks=0`, so every downstream guard passed. It
cost an MPNN pass, a refold, and a wrong conclusion about the epitope, and the
ApoE4 run shipped a gene order with the same defect. The detector is arithmetic
on data rfd3 already writes: `|fixed_com|` is ~23 Å with the key and ~0 without.

It **stops** rather than annotates, which is a deliberate departure from the 2.0
shadow-mode rule, and the distinction is worth stating: shadow mode governs
*design-quality* filters whose false-negative rate is unvalidated. This is a
*config-correctness* check — it says the run is broken, not that the designs are
weak. `RFD3_IGNORE_GATE=1` overrides. Wired into both the template and the
configurator, which mirrors the template rather than generating from it; a
hand-written script copied from that template is precisely how the original
omission propagated.

**The fold-back ranking gives RFD3 a native rank it otherwise lacks.** A
diffusion model scores nothing, so the fallback was `mpnn_sequence_recovery` — a
sequence proxy with no binding signal. Running `prefilter` on the Boltz-2
results the pipeline *already produced* costs no extra GPU, and matches the
field-standard recipe the literature pass established: diffusion gives geometry,
the fold-back gives the rank.

**Wiring it exposed a real gap, and this is the part worth remembering.**
`prefilter`'s documented recipe assumes an RFD3-only FASTA. The pipeline's FASTA
is every tool, and `report --tool-csv <tool>=<file>` takes the whole file as that
tool's ranked list *without consulting the `tool` column it contains*. So an
unfiltered selection would have filed every tool's designs under RFD3's name,
ranked by Boltz-2 — a plausible-looking native block that was mostly other
tools' work. Hence `--only-tool`, applied before `--top` so a top-N means N of
that tool. A tool absent from the pool now yields 0 rows rather than everything,
which is the failure mode that would have been hardest to notice.

Verified on the golden pool: six real designs ranked 0.712 → 0.479. The order
differs slightly from the report's own ranking, which is the point — `prefilter`
ranks on single-engine Boltz-2 `ipsae_min` while the report ranks on cross-engine
`consensus_iptm_mean`.

**Small guard added:** `bash -n` on the generated RFD3 script. The gate block is
real shell, and a quoting slip would kill the run at launch — after the diffusion
time the gate exists to protect.

**Open:** the pool-filtering question for AD's discovery metric is unchanged and
still needs a decision rather than an implementation; and the self-consistency
RMSD axis, which every published gate couples with interface confidence, is still
uncomputed.

---

## 2026-09-25 — Stage 2: the self-consistency axis, and a crash shipped by the previous stage's fix

**We had one of the field's two gate axes.** Every published RFdiffusion-family
pipeline couples an interface-confidence term with a design-vs-refold RMSD —
RFD3's own gate is target-aligned binder Cα-RMSD < 2.5 Å, Bennett 2023 uses
`af2_complex_rmsd < 5`. We computed nothing like it.

**The alignment is the whole metric, and choosing wrong is silent.** Superposing
the binder onto itself measures its FOLD; superposing on the target — the one
molecule common to both structures — measures its PLACE. A binder that folds
perfectly but docks on the wrong face scores ~0 Å the first way. Two paired
tests pin the difference: the same wrongly-docked binder must fail the gate
target-aligned *and* come back ~0.0 from `kabsch_rmsd`, so a refactor cannot
quietly substitute one for the other.

Not ported: BindCraft's 3.5 Å binder-RMSD. It is computed without superposition
on trajectory-frame sub-poses, so it sits on no scale we can reproduce. RFD3's
2.5 Å is target-aligned and transfers — though the preprint says it is itself
borrowed ("cutoffs from [ref]"), which the constant records so nobody cites it
as RFD3-validated.

**A crash shipped by the previous stage.** Wiring `--collect-structures`
yesterday broke `extract`: `structures.py` imported gemmi unguarded, extract runs
in `binder-eval`, and gemmi is deliberately absent there. `pyproject.toml` states
that contract outright — *"imported inside functions, behind guards that keep
their modules importable without them"* — and that one file did not hold it.
Every generated run would have extracted its sequences successfully and then died
with `ModuleNotFoundError`. Found by executing the path, not by reading it. The
narrow lesson: wiring a capability into a **different environment** than the one
it was written for is its own risk, and this repo maintains four conda envs
precisely because that matters.

Following the thread further: gemmi is needed only to *convert* mmCIF, yet its
absence was skipping collection entirely — including for plain `.pdb` files that
never needed it. Now only the mmCIF tools lose out, and they say so.

**Three gaps between the maths and a usable column**, each a quiet source of
wrong numbers. Chain resolution is done **by sequence**, not by letter, because
Boltz-2 puts the binder in A while AF3 and ESMFold2 use B and a design tool uses
whatever it wrote — a mismatch CLAUDE.md already lists as a bug source. Every
non-binder chain is target, so a multi-chain target is not truncated to one.
And collected structures are named by position in the input list, so a manifest
now maps them back by sequence, as everything else in this pipeline joins.

**The verification that mattered.** Run through the full report on the golden
pool, using its own AF3 structures as stand-in design models: the AF3 column
reads **0.000 for all six** — the control proving alignment and chain resolution
are correct — while Boltz-2 reads 1.0–3.0 Å and ESMFold2 0.56–5.10 Å. Those
cross-engine numbers are only obtainable if the resolver handled AF3's
binder-in-B against Boltz-2's binder-in-A. ESMFold2 shows the widest spread
again, matching what the confidence gate found.

**Open:** unchanged — the pool-filtering decision for AD's discovery metric, and
whether the confidence and self-consistency shadow columns should ever become a
real gate, which needs outcome labels rather than more code.

---

## 2026-09-25 (night) — Stages Y and 5, and two documented facts that were not facts

Four pieces, and the through-line is that **two of the four were corrections to
this repo's own written record.** That is worth naming: the diary and CLAUDE.md
are load-bearing, and a confident false sentence in them costs more than a gap.

**Part Y — the private label registry.** Three shadow-mode columns now ship
(`would_exclude_composition`, `would_exclude_confidence`,
`would_exclude_self_consistency`) and not one can leave shadow mode without
knowing which designs expressed and bound. Y is how a labelled pool is named,
audited and loaded without its labels entering a public repo: the tree carries
`MANIFEST.json` per pool — enough to *audit* a result — while the rows live in a
private store located by `$BINDERSCOUT_BENCHMARK_STORE` and verified against the
checksum the manifest records.

The failure behaviour is the substance, because every way this goes wrong yields
a **wrong number under a right-looking name**. So each is an exception, never a
warning or an empty frame: no store configured names the env var and the pool; a
checksum mismatch is an error, because the rows are then not the ones the
manifest describes; and zero rows is an error, because a validation run over an
empty pool reports cleanly and means nothing.

One detail worth keeping: the worked example lives *inside* `SCHEMA.json`,
because `.gitignore`'s `benchmarks/**/*.json` rule negates only `MANIFEST.json`
— a separate `EXAMPLE_MANIFEST.json` would have been silently ignored. The leak
guard was re-verified with real files present rather than the hypothetical paths
the existing test asserts.

**Stage 5 — the config-builder page, generated so it cannot drift.** A form that
emits `config.json` is a second door into a pipeline whose wizard is ~4,600 lines
and eighty prompts. The hazard is the one this repo keeps paying for: a second
surface listing tools and flags drifting from the first. So the page is
*generated* from `REQUIRED_CFG_KEYS`, and a test fails when the committed HTML
stops matching the generator — mutation-tested by adding a tool to
`configurator.py` and watching both guards fail. Drift is a red CI run rather
than a config that silently enables nothing.

**"Scrubbed from tree and history 2026-09-22" was false.** Six tracked files
still carried an absolute `/home/<username>` path three days later — a CHANGELOG
entry, two investigation write-ups, a plan, a notebook and a test fixture. None
of them shell scripts, which is exactly why `test_script_hygiene.py` never saw
them: it checks scripts, not the tree. The tree is clean now, and the real fix is
the tree-wide guard that did not exist, which is why the claim could sit there
false. Two things a tree scrub does not fix, now stated rather than implied: the
history still carries them and is already published, and `tools/aarch64/dssp` has
a build path baked in by its compiler. The guard earned itself immediately by
failing on the CLAUDE.md edit that documented the problem and quoted the path
verbatim.

**Proteina-Complexa's aarch64 deprecation rests on a premise its sibling
disproved.** CLAUDE.md records that jax 0.6.x put BindCraft's AF2 on the GPU on
sm_121, then asserts the same reasoning "does NOT rescue Proteina-Complexa — its
blocker is the CPU-bound AF2 reward, a different problem". That is circular, and
checking it shows why: **PC's AF2 reward *is* ColabDesign**, the same library, so
the CPU-bound reward is not a different problem but this one. The difference is
only the pin — BindCraft runs colabdesign 1.1.3 on jax 0.6.0, PC runs colabdesign
1.1.1.1 on **jax 0.4.29**, which predates sm_121 exactly as 0.4.34 did.

This does **not** mean PC is rescued, and the note says so: the upgrade is
untested against PC's own uv-managed venv with a different ColabDesign version,
and trying it needs Spark. What is established is narrower and still
consequential — a "1.7 years" throughput figure and a "reopens only if a CUDA
jaxlib appears" condition both rest on something already disproved on the same
machine by the tool beside it.

**Open:** unchanged, plus the two decisions in
[MORNING_DECISIONS.md](MORNING_DECISIONS.md).

---

## 2026-09-25 (night, cont.) — an adversarial review of the night's own work found eleven defects

Worth its own entry, because the pattern in what it found is more useful than
the list. An independent agent reviewed the fourteen commits above, verifying
every finding by *running* something rather than reading.

**Five were guards that could not catch the case they were written for.** That
is the uncomfortable one. Each had been added the same night, each looked
reasonable, and each was confirmed hollow by mutation:

- the config-builder's "every tool appears" check was satisfied by the embedded
  `REQUIRED` JSON blob, so all twelve tests passed with RFD3 **deleted from the
  form** — the page would have emitted a config with no `rfd3` key at all;
- its self-contained check tested `"http://"` and `"https://cdn"`, so a
  fonts.googleapis stylesheet and an unpkg script both sailed through;
- the optional-import guard skipped module-level imports — in `structures.py`,
  the exact file whose breakage its docstring cites;
- the conda-env guard excused any all-lowercase name, so an instruction to
  `conda activate` the *Mosaic* environment passed. That is the highest-value
  case in the repo: Mosaic is a **uv venv**, not a conda env, so such an
  instruction can only ever fail — and quoting it verbatim here trips the fixed
  guard, which is itself the demonstration;
- the install-command guard matched one command shape and one installer, missing
  `--uninstall --tool` and every `install_aarch.sh` invocation.

The lesson is narrow and it is not "write more tests". It is that **a guard
written alongside the fix inherits the author's blind spot**, and the only thing
that establishes it works is watching it fail on the case it targets. I had
mutation-tested three guards that night and they held; the five I did not are
the five that were hollow.

**Three were silent wrong numbers**, this codebase's signature failure.
`confidence_gate` skipped the iPTM check whenever `esmfold2_iptm_pair` was NaN
while still counting the engine as measured — an interface iPTM of **0.12**
passed a 0.5 gate with no reason recorded, indistinguishable from a real pass.
`split_target_binder` resolved an ambiguous chain by file order, so a target
chain carrying the binder's sequence returned the **target's** coordinates as
the binder; lengths necessarily agree there, so nothing downstream could have
flagged the plausible RMSD. And `interface_energy`'s new "refusing to write an
empty panel" guard counted a row as scored if dG was non-empty — but a wrong
`--interface` returns dG 0.0 / dSASA 0.0 *without raising*, so a full panel of
zeros passed it. Measured on a real pose: `B_A` gives dSASA 4469, a bogus `Z_Q`
gives 0.0 in silence.

**One was a confidently wrong diagnosis.** `rfd3_gate` returned False for "no
`fixed_com` in the sidecars" and "no chain-B CA atoms" — conditions meaning the
check *could not run*. The run script reports that as "these backbones look like
coils… check `infer_ori_strategy`". So an rc-foundry release that renames a
metric or relabels the binder chain would abort every campaign, **after the full
diffusion cost**, with a diagnosis that is not merely unhelpful but wrong. Now
exit 2 means could-not-verify, distinct from 1 for a measured failure.

**And one found while fixing another.** The config-builder patch silently did
not apply: the script asserted both edits then wrote once, an earlier assert
raised, and nothing was written. I only noticed because the mutation test for
that fix still passed. Two lessons for the price of one — patch scripts should
write per-edit, and a fix you have not watched work has not been made.

**Also of note**, three times this session a lint failure reached a commit
because `ruff check . | tail -1` and `ruff format --check . ; echo $?` both take
their status from the wrong command. Same slip each time.

---

## 2026-09-26 → 09-27 — Proteina-Complexa was already possible on Spark, and the installers had silently diverged

Two entries' worth of work, joined by one theme: **this repo's own records were
the obstacle, twice.**

**Proteina-Complexa on aarch64 was never actually blocked — the stated reason was
wrong twice over.** Deprecated 2026-07-29 for "no CUDA `jaxlib` exists for
aarch64". That was disproved on 09-18 (`96a1f02`): the CUDA plugin does exist and
gives `backend: gpu` on jax 0.4.29. The same commit found the real blocker — jax
0.4.x cannot compile an AF2-class graph for sm_121, aborting with `LLVM ERROR:
Unsupported rounding mode for conversion`, reproduced in two environments.

And that blocker was *already fixed on this hardware, twice*: BindCraft 1 runs
AF2 on the GPU there on `jax[cuda12]==0.6.2` (`9c29729`), BindCraft 2 on
`jax-cuda13 0.11.1`. PC's AF2 reward **is** ColabDesign — the same library — so it
inherits the fix. Nobody had connected those three facts, and the installer still
answered `--tool proteina-complexa` with `exit 1`.

I reached the same conclusion from the wrong direction: I "discovered" the jaxlib
claim was false without checking whether that had already been established, and
had to be told the capability existed. The lesson is cheap and I keep relearning
it — **read the history before reasoning from the docs**, because a stale doc and
an open question look identical from inside.

`install_aarch.sh` now installs PC with the documented five-blocker Blackwell
recipe (cu130 torch, a `torch_scatter` shim for the one `scatter_mean` it uses,
biotite 1.6.0 + graphein + atomworks) and 0.6.2 in place of the manual port's
`jax[cpu]==0.4.29`. No CPU-fallback patch: the original `jax.devices("gpu")` is
now correct code.

**The smoke test is the part worth copying.** It compiles a jitted **bf16** graph
— the exact lowering that aborted — and refuses rather than reporting success if
that fails. It claims nothing more, because this repo has already once declared
aarch64 support on the strength of `jax` reporting `gpu` plus a clean import, and
had to retract it. What is still unproven is the deprecation's actual content:
**throughput**. 3,300 AF2 calls per 100-design replicate meant 12.2 days with a
CPU reward; with the reward on the GPU nobody has measured the replacement.

**Then a standing rule arrived — check every new thing across installer,
configurator, evaluator and report generator — and found two gaps immediately.**
TmProt was wired in three of five places: 59 references in `install.sh` and
**zero** in `install_aarch.sh`, so it could not be installed on Spark at all, and
zero in the configurator, so there was no wizard question, no `cfg` key and no
generated flags. I had built its runner earlier in the same week and checked
neither installer.

**The root cause is that one entry point is not one implementation.**
`binderscout install` *does* dispatch by platform, and `install.sh` now refuses on
aarch64 rather than warning. But `install_aarch.sh` is a separate ~3,000-line
script with its own `install_*` functions, so every tool is written twice and the
second copy is the one that gets forgotten — PC had no function there either.

So the comparison is a test now, on three surfaces: the `--tool` vocabulary, the
`install_*` functions, the `DO_*` flags. Deliberately not the bodies, which
genuinely differ (cu121 vs cu130, conda vs pip PyRosetta, source builds) — a tool
present on one platform and absent on the other is the defect; implementing it
differently is the point. Parity after the port: 25 tool names, 14 functions, 13
flags. Mutation-tested on the actual historical bug, and my first threshold was
off by one and passed everything, which the mutation caught.

**Also decided:** P5 is not built. Four shadow-mode columns already ship and none
can be promoted without labels, and Part U measured that hunting for extra
metrics scored *worse* than `consensus_iptm_mean` alone (0.5170 vs 0.5552). A
fifth unvalidated screen would have repeated that. SoluProt and TmProt stand.

**Open:** the discovery metric's pre-filtered-pool question, and which labelled
pools to register — deferred. Four exist (Cao 4,442 / Adaptyv ~2,517 / de novo
BindCraft 110 / our own CBG+CALCA SPOC), all already refolded through our
engines, so registering them is bookkeeping rather than compute. The reason to be
careful is that **73.4% of Cao's binder labels are one-sided Kd**, and excluding
them moves macro-AUC from 0.53 to 0.73 — so which subset gets registered changes
every number computed from it.

## 2026-09-27 — The whole pipeline, end to end: five verifiers passed envs that could not run, and a pre-GPU gate would have deleted a validated pool

Ran the pipeline the way an operator would, in order — `install --verify`,
`configure`, a simulated run for all eight tools, `extract`, refold, `evaluate`,
`report` — and checked the data flow at each junction rather than the unit tests.
The plumbing turned out to be in good shape. The **audit** of the plumbing was
not: five separate checks reported green on things that cannot work.

### What the pipeline does correctly

Worth writing down, because most of it had never been demonstrated end to end:

* **Extract, 8/8 tools, provenance correct on all five routes.** BindCraft 2
  `joined` through the trajectory hash (23), BoltzGen `parsed` (42, zero-padding
  stripped), Mosaic `explicit` (7), RFD3 `parsed`, Protein-Hunter `explicit` (4),
  and the three tools that genuinely cannot report an index say `unavailable`
  rather than inventing one. `generation_index` reaches `metrics.csv` and
  `top30_slim.html` when `--native-metrics` is passed.
* **The MSA cache claim holds.** Cold target → one ColabFold fetch → 150
  sequences cached under the key the code predicts; second call `mode=cached`,
  no network. All three engines read that one file.
* **The cross-engine gate is real, and parameterised.** Built a pool where
  PXDesign has by far the BEST `consensus_iptm_mean` (0.9646) but only two
  engines: it was ranked **8 of 8, last, and not dropped** — exactly as
  documented — while `--min-engines 2` promoted it straight to rank 1.
* **Self-consistency measures what it claims.** Design == refold → 0.000;
  the whole complex rotated 0.4 rad and translated → **0.000**, which is the
  load-bearing proof that the superposition is *target*-aligned (a naive RMSD
  would have said ~8 Å); the binder alone displaced 10 Å → **10.000**, recovering
  the displacement exactly.
* **Failures are loud.** AF3 OOM'd on this 12 GB card (~4 GB free, the rest held
  by the host compositor) and the runner raised `RuntimeError: ... This is an
  environment fault, not bad input` instead of writing empty rows — the guard
  written for the 2026-08-20 `JAX_PLATFORMS=cpu` incident, firing correctly for a
  different cause.

### Five verifiers that passed unusable environments

The pattern is identical each time: **the check tested a proxy, and the proxy was
satisfied by something that cannot run.**

| checked | what it missed |
|---|---|
| `import alphafold3` | the env had **no `binder-compare` at all**, and `evaluate.sh:527` invokes exactly that |
| `import alphafold3` | `build_data`'s CCD pickle absent → AF3 aborts later, on `alphafold3.constants.chemical_component_sets` |
| `import esm` | `esm.models.esmfold2` and `esm.utils.msa.msa` — the two modules the refold actually imports — both `ModuleNotFoundError` |
| `--verify` on aarch64 | there was **no verifier in that file at all** (0 references vs 21), and a comment already pointed readers at a `verify_tool()` that did not exist there |
| "kept in sync with install.sh" | `install_aarch.sh` lacked `--no-deps` on the esm install — the precise failure that took out the default engine on x86 on 2026-09-23 |

The ESMFold2 one is the worst of them: `esm` is installed `--no-deps` on purpose
(its pyproject pins a git URL that 404s), and **nothing then installed its
runtime dependencies**. So the *default* refold engine was non-functional in an
environment `--verify` called usable. Walking the `ModuleNotFoundError` chain to
exhaustion gave the complete set — biopython, attrs, scipy, zstd, cloudpathlib,
biotite, brotli, einops, msgpack-numpy — and the verifier now imports the real
modules, so a future gap goes red instead of silent.

The lesson is narrow enough to be useful: **verify the interface the pipeline
uses, not a proxy for it.** `evaluate.sh` drives every step through
`binder-compare`, so the verifier now runs `binder-compare <subcommand> --help`,
which exercises the whole import chain. That is also what exposed the corollary —
`cli/__init__` imports every subcommand, so `report.py`'s module-level matplotlib
import is mandatory even for a refold, which means CLAUDE.md's documented repair
recipe (`pip install -e Evaluator --no-deps`) **could never have worked** on an
env missing deps. Corrected to the `[report]` extra.

The env list for that test is parsed out of `evaluate.sh` rather than hardcoded,
so a new `binder-compare` step in a new env fails until its verifier follows.

### The composition gate would have deleted a validated pool

The most consequential finding, and it came from running the report on real data
rather than from reading anything. The shadow-mode composition gate flags **6 of
6 real BindCraft 2 designs** in the golden pool — including the rank-1 design at
`consensus_iptm_mean` 0.918.

| threshold | value | observed on that pool | verdict |
|---|---|---|---|
| `min_hydrophobic_frac` | ≥ 0.40 | 0.320 – 0.410 | floor is **above** the pool mean (0.363) |
| `max_glu_arg_frac` | ≤ 0.36 | 0.222 – 0.411 | ceiling sits **at** the pool mean (0.347) |
| `max_ala_frac` | ≤ 0.20 | 0.038 – 0.111 | transfers fine |
| `max_pro_gly_frac` | ≤ 0.12 | 0.028 – 0.087 | transfers fine |

The two that fail are the two carried over from `tools/rfd3_gate.py`, and the
reason is a tool mismatch, not a bad constant: RFD3's failure mode is a Pro/Gly
coil, so the thresholds that catch it are a hydrophobic floor and a charge
ceiling — and BindCraft 2 hallucinates against AF2, producing charged, helical,
comparatively hydrophobic-poor sequences *by construction*. What this needs is
per-tool calibration, not a nudged global pair.

This is shadow mode earning its keep. The design rule — a pre-GPU filter may only
start excluding once it removes zero confirmed binders on a calibration pool —
had been justified by the *absence* of a pool. It is now justified by a
measurement, pinned in a test that fails if anyone quietly relaxes a threshold to
make the pool pass. If a future recalibration genuinely fixes it, that test is
*supposed* to fail; the instruction is to re-measure, not to delete it.

### A demotion nobody could explain

`rank_designs` puts gate failures last regardless of score, which makes the gate
the only criterion in the report that actually reorders the table — and it was
the one thing missing from the operator-facing `Notes` column. The PXDesign
design with the pool's best mean sat at rank 8 with an **empty** Notes cell while
all seven designs that *passed* the gate carried reasons. Anyone reading that
table would conclude the best design was inexplicably last. It now reads
`cross-engine gate FAILED (only 2 engine(s)) — ranked last`.

### Two things that were my fixture's fault, not the code's

Recorded because I nearly reported both as defects: constant `*_ipae_ang` across
designs (I copied one golden row as a template and never varied its `ipae`), and
the doubled prefix in `rfd3_rfd3_helix_binder_3_model_1` (my synthetic
`design_id` already began with `rfd3_`; a real run's does not). The extractor
prefixes unconditionally, which I left alone — I could not show a real RFD3 run
produces a prefixed id, and changing code on a guess is how the last round of
hollow guards got written.

### Also

`--tool all` installs **two** refold engines, not three: AF3's weights are gated
behind a Google DeepMind request, so it cannot be in `all`. Against the report's
default `--min-engines 3` that means every design fails the gate on a fresh
install. The report says so loudly and names the shortfall, which is the right
behaviour, but nothing documented it — now in CLAUDE.md. The AF3
all-binders-failed message also named neither cause seen here (insufficient VRAM,
missing `build_data`) and now leads with both.

**867 tests (+23).** Every new guard mutation-tested. One of those mutations was
itself broken — I inserted the "promote out of shadow mode" line *between* the two
column assignments, so the function raised instead of dropping rows, and the test
written to catch dropping stayed green for the wrong reason. I only noticed
because the *other* test failed and that one didn't. Asserting that the mutation
applied is not optional; this is the second time in three days.

## 2026-09-27 (cont.) — The refold half: four engines, four different reasons it could not run, and only one of them was hardware

The morning's pipeline test stopped at the GPU because this box had ~4 GB free. The
user freed memory and asked me to try again. What followed was not one blocker but a
chain of four, each hiding the next, and only the third was a real hardware limit.
The pattern that made them expensive is the same one from the morning, one layer in:
**a check that covers most of an interface still passes on a broken one.**

### 1. AF3's memory fraction was 2%, and the guard against that had a blind path

AF3 died on a **54 MiB** allocation with 8.9 GB free. The fraction it chose was
**0.020** — about 246 MiB.

`_default_mem_fraction` decides whether memory is UNIFIED (so that over-reserving
would starve the OS) by asking *is the GPU pool the same size as system RAM?* Two
things made that question answer itself:

* the ctypes probe loads `libcudart` **by bare name**, which fails whenever CUDA came
  from pip wheels — the libs live in `nvidia/*/lib`, off the loader path. All three
  names failed in `binder-eval-af3`, so this was every run, not an edge case;
* `pool_gib` then fell back to **system RAM**, making `pool == ram` exactly. The
  difference is 0, so every host was declared unified, `(pool − 40)/pool` went
  negative on anything under 40 GiB, and the fraction hit the 0.02 floor.

The function's own comment says applying the OS floor to a small card "would drive the
fraction to 0.02 (0.5 GB), below the ~4.4 GB working set, OOM-ing every design." It was
right. It just could not see this route to it. Fixed by querying `nvidia-smi` when the
ctypes probe fails, and by making the unified verdict conditional on the pool size
having actually come from the GPU. **0.020 → 0.500**, and if both probes fail the
fallback is now benign in both directions instead of fatal in one.

Worth noting: `refold_boltz2.py` has its own copy of this logic and got it right —
it printed `discrete 12.0 GiB device (host RAM is separate; runaway is recoverable)`.
AF3's was the broken sibling.

### 2. AF3 cannot run on consumer Ampere/Ada at all, and this is not about VRAM

With the fraction fixed, every design failed differently:

```
RESOURCE_EXHAUSTED: Shared memory size limit exceeded: requested 110592, available: 101376
```

That is **shared memory per block** — a per-SM architectural limit. AF3 v3.0.2 runs
attention and gated-linear-unit layers as **tokamax Pallas/Triton** kernels
(`PallasTritonFlashAttention`, `PallasTritonGatedLinearUnit`, visible autotuning on the
card), and one needs 108 KB. sm_86/sm_89 expose 99 KB; A100 164 KB; H100/GB10 228 KB.

Four things left it completely unchanged: `--flash_attention_implementation=xla` (AF3
documents it as "portable across GPU devices"), `--xla_gpu_enable_triton_gemm=false`,
a cold compile cache, and the memory fraction. So it is a wall, not a knob.

**This puts a documented claim in doubt.** CLAUDE.md says AF3 "runs fleet-wide
(BM1/BM2/BM4)" on the strength of a 2026-08-14 measurement on BM2 — **an RTX 3090,
which is also sm_86 with the same 101,376-byte limit.** That result cannot be
reproducible on a commit using these kernels. The likely explanation is that
`AF3_COMMIT` has moved since (tokamax is new in AF3 3.0.x), which would leave the
4.4 GB VRAM finding true and the *card list* stale. Both measurements are kept and the
claim is marked IN DOUBT; it needs one re-run on BM2 recording which commit was used.
Deleting either number would lose information.

The operator-facing failure said only "environment fault" plus 4,000 characters of
traceback, which sends the reader after a memory cap that cannot help. It now names the
limit, says what does *not* fix it, and gives the alternative.

### 3. `~/.boltz` was a broken download, and the downloader cannot see that

Boltz-2 failed inside pytorch_lightning with `PytorchStreamReader failed reading zip
archive: failed finding central directory`. The cache had been interrupted three days
earlier and held **three** separate broken artifacts:

| artifact | found | expected |
|---|---|---|
| `boltz2_conf.ckpt` | **0.21 GB**, not a valid zip | ~2.3 GB |
| `boltz2_aff.ckpt` | absent | ~2.1 GB |
| `mols/` | 2,949 entries, **ALA/GLY/SER/LYS missing, GLU present** | 45,227 |
| `mols.tar` | 114 MB, truncated, no canonical residues | — |

`boltz.main.download_boltz2` decides what to fetch **by whether a path exists** — not
size, not integrity. So re-running the documented bootstrap printed its normal
"Downloading …" banner, skipped every incomplete artifact and reported `DONE` while
fixing nothing. It took three rounds because each fault only surfaced once the previous
one was cleared: the tar, then the directory (existence again), then the checkpoint.

`refold_boltz2` now refuses a cache like that before loading the model, reports every
fault in one message, and gives the deletion step — since re-running the downloader
alone genuinely cannot repair it. It probes **all six** canonical residues, because the
partial extraction kept GLU and dropped ALA, so any single spot-check would have passed
this cache. An absent cache stays silent; that is the normal first-run path.

### Boltz-2 then folded, and the report was exercised on real data at last

Eight CALCA designs, 28 aa binders against the 32 aa target (a 60-token complex):

| ipTM | 0.8243 | 0.8498 | 0.9007 | 0.5593 | 0.8870 | 0.4855 | 0.8870 | 0.8559 |
|---|---|---|---|---|---|---|---|---|
| `ipsae_min` | 0.5310 | 0.6388 | 0.6492 | 0.4538 | 0.6696 | 0.5366 | 0.5680 | 0.6575 |

36 columns, schema byte-identical to the golden pool, and the report on it behaved as
documented: all eight tools attributed, `generation_index` provenance intact, eight real
PDBs in `top20_structures/`, and the cross-engine gate **named the shortfall** —
`no design was refolded by 3+ engines (best coverage in this pool: 1) … lower the gate
with --min-engines 2` — rather than quietly reporting that nothing was good enough. A
second warning correctly recorded that `agreement_count` could not be assessed with one
engine and so was not applied to `wetlab_recommended`.

**A postscript on that run.** It ended with a fatal XLA CHECK at teardown —
`bfc_allocator.cc:1065 Check failed: central_gap_ == kInvalidChunkHandle … spatial
partitioning expects one central gap` — *after* all eight folds were written. Because
`boltz2_runner` copies `refold_designs.csv` to the requested `-o` path only once
`refold_batch` returns, the completed work was stranded under the inner filename. I first
wrote here that `--resume` recovers this. **Then I tested it, and it does not.** The
resume invocation read `refold_designs.csv`, correctly reported `skipping 8
already-completed binders` — and died at the *same* CHECK, 2 runs out of 2, before
`refold_batch` returned. The abort is in allocator teardown, so it happens whether or not
anything is folded, and a Python `finally` cannot catch a SIGABRT raised by a C++ CHECK.
On this box the `-o` CSV can therefore **never** be produced, while eight correct folds
sit on disk permanently out of reach.

`evaluate.sh` handles the consequence correctly — `check_engine_rows` refuses to report a
partial pool and aborts loudly on a non-zero rc — so nothing silently ships short. But the
work is unrecoverable, and that is a real defect rather than a hardware one: the publish
step is gated behind a return that never happens. Fixed by publishing
`refold_designs.csv` to the requested path **before** folding as well as after, so a
re-run recovers prior work even if it later aborts. Writing that claim before testing it
is precisely the habit this diary exists to catch; the only reason it did not ship is
that I checked it.

### 4. ESMFold2 — the DEFAULT engine — could not load a model, for two reasons

First, transformers **renamed the class**: `ESMFold2Model` in 4.x, `EsmFold2Model` from
5.x. `refold_esmfold2` imported the old name, and its `except ImportError` branch told
the operator to "install a version that ships ESMFold2 support" — which was already
installed — while Python's own `Did you mean: 'EsmFold2Model'?` sat buried under the
re-raised RuntimeError. It now tries both names.

Second, and this is the part that stings: **the verifier I added this morning checked
two of that script's three imports.** It covered both `esm` SDK modules and not the
transformers model class, so ESMFold2 verified *usable* with a model class that does
not exist. The morning's lesson was "verify the real interface, not a proxy"; the
refinement is that the real interface means **all** of it. Mutation-verified by renaming
the class in site-packages.

Then a deeper one. The installer pins `transformers>=4.50` **with no upper bound**, and
that pin is wrong in both directions:

* **4.57.6 has no `transformers.models.esmfold2` module at all** — ESMFold2 support is
  5.x-only, so the `>=4.50` floor never described anything real;
* **5.17.0 changed the distogram head from 64 to 128 bins**, so the model revision
  pinned in 1.0.2 (`8fc3ff47`) now fails to load:
  `distogram_head.weight: ckpt torch.Size([64, 256]) vs model torch.Size([128, 256])`.

A pinned checkpoint with an unpinned loader was always going to drift apart; 1.0.2
pinned one side of a two-sided contract.

**Resolved from the two checkpoint configs, which say exactly what happened:**

| revision | `transformers_version` | `structure_head` |
|---|---|---|
| pinned `8fc3ff471022` | 4.57.6 | `distogram_bins: 64` **only** |
| current `69869f737bef` | 5.16.0.dev0 | `num_distogram_bins: 64` **and** `distogram_bins: 64` |

The config **key was renamed**. transformers 5.x reads `num_distogram_bins`; the pinned
config has only the old spelling, so the head is built from the class default of 128 over
64-bin weights. The newer snapshot carries both names precisely to survive this. So the
fix is to move *both* halves: revision to `69869f737bef`, and the loader floor to
`transformers>=5.16` — in both installers, since they are separate implementations.

Six static tests pin the invariant, including that the unloadable revision can never come
back as the default and that the two installers agree with each other. Static because the
alternative needs ~10 GB of weights and a card this box does not have: the newer
snapshot's shards passed 11 GB while still downloading, which on a 12 GB card leaves
nothing for activations and independently corroborates the ~14 GB floor already recorded
in `docs/NEXT_STAGES.md`.

**Then the download finished, and the run settled both halves separately.** With the newer
revision on transformers 5.17.0 the weight load produced **zero MISMATCH lines** — the
load-time contract is fixed, not merely argued from the configs. It then died one step
later, in `t.cuda(device)`, with `CUDA error: out of memory`: the model cannot be moved
onto a 12 GB card at all. So the two failures were genuinely independent, and the ~14 GB
floor is now corroborated on this hardware rather than quoted from a note.

It failed **loudly** — `EXIT=1`, no CSV written, no empty rows — so the 1.0.3 fix for
ESMFold2's silent-empty-row behaviour holds, and `evaluate.sh`'s `check_engine_rows` would
refuse to report a partial pool on that rc. Still outstanding: a completed ESMFold2 *fold*,
which needs a card this box does not have.

Note what settled this: not a guess about which side to pin, but reading the two
`config.json` files sitting in the HF cache. Every blocker today yielded to looking at
the artifact rather than reasoning about it.

### What this session says about the documentation

Three claims did not survive contact with the hardware: AF3 "runs fleet-wide", the
`--no-deps` repair recipe (which could never have worked), and a comment asserting two
installer functions were "kept in sync" while one lacked a load-bearing flag. None were
lies; each was true when written and nothing re-checked it. The countermeasure that
actually works is the one the drift test demonstrated today — it caught me editing
`verify_tool` in one installer within minutes, which is faster than any amount of care.

---

## Structures under the binder id — and the four tests that were lying about it

**2026-09-29.** The ask was small: *"We need all PDBs. When we are refolding, save them
as raw results under the binder ID."* The first thing worth recording is that the
premise turned out to be half right in a way that changed the work.

**All three engines already saved every structure.** Boltz-2 wrote a PDB, a PAE `.npy`
and a pLDDT CSV; AF3 wrote a PDB and converted the CIF; ESMFold2 wrote a CIF, a PDB and
a PAE. Nothing was being discarded. So "we need all PDBs" was not a gap in *what* was
saved — it was a gap in *finding* them, and the cause was the name:

    refold7_a1b2c3d4.pdb     af3_0007.pdb     esmfold2_0007.pdb

Three names for one design, none of them the design's own id, and `7` meaningful only
relative to the FASTA that produced it. Retrieving a design's structures meant joining
the refold CSV on its *sequence* first. That is why this is worth having: the id is
already the join key everywhere else in the report.

**The id was there the whole time, and three separate places threw it away.** The
`extract` FASTA header's first token *is* the `binder_id` — `merger._attach_fasta_metadata`
reads it back that way. But `cli/refold_af3.py` did `sequences = [seq for _, seq in entries]`,
discarding the header it had just parsed; and the standalone scripts skipped any line
starting with `>`. So the plumbing was three one-line losses, not a missing capability.

**The hazard that shaped the design.** `refold_boltz2.py`'s `main()` *filters* invalid
sequences out of the batch. Carry ids alongside without filtering them in lockstep and
every structure after the first rejection is written under a different design's id —
every file exists, every path resolves, every downstream join succeeds, and the report is
silently wrong about which structure belongs to which design. That failure mode is the
reason `structure_stems` refuses a length mismatch before any GPU work rather than
zipping to the shorter list. Same reasoning for duplicate ids: `__2` is ugly, losing a
structure to a silent clobber is worse.

One sanitiser, not two. The Foldseek family join built its filename stems with an inline
comprehension — a second copy of the same logic, and if the two ever disagreed by one
character a structure simply could not be found by its id. It now imports `safe_stem`,
and a test fails if that comprehension comes back.

### What actually went wrong today

**Four of my twelve mutations survived, and all four were the same mistake.** The CLI
tests asserted `"binder_ids" in src`. Mutating the CLI to compute the ids and then *not
pass them* left that substring in the file, so the test passed on broken code. The
script test had a nastier version of it: the guarded-import fallback **defines**
`parse_fasta_pairs`, so the name is in the file even when the entry point has stopped
calling it.

The fixes were different in kind, and the difference is the lesson:

* the CLIs are importable in `binder-eval`, so the test now *calls* `run()` with the
  runner monkeypatched and asserts `binder_ids == ["rfd3_b7", "bc_l28_s3"]`;
* the refold scripts are **not** importable there (they need `gemmi`, `equinox` — they
  belong to other envs), so that test parses the AST and checks the *entry point*
  reaches the parser, following one level of local helpers. Scoping is what makes it
  sharp; a whole-file search is what made it hollow.

Fifteen mutations now, all caught. This is the fourth time this session that a test
matched text that survived the mutation it was supposed to detect. The pattern is
consistent enough to state plainly: **a test that greps the file it is testing is
presumed hollow until a mutation proves otherwise**, and "assert the mutation was
actually applied" is what turns that presumption into evidence.

### Wired in all four modules

Installer: nothing — the module ships with the package and adds no dependency.
Configurator and `evaluate.sh`: nothing, and that is the point — both drive
`binder-compare refold-*`, which parses the FASTA, so the ids flow without either
knowing. Evaluator: the three CLIs, three runners, three engines. Report: the Foldseek
join now shares the sanitiser.

### The one behaviour change to know about

A re-run into the same output directory now **overwrites** a design's structure. The old
names carried a per-run uuid and accumulated instead. For `--resume` this is strictly
better — the completed files are already under their final names — but it is a real
change and it is in CHANGELOG and CLAUDE.md rather than left to be discovered.

Not done, deliberately: no `binder_id` column was added to the engine CSVs. The merger
already attaches one from the FASTA, and a second `binder_id` arriving through the
prefixing and the outer join is how you get `binder_id_x` / `binder_id_y`. The filename
was the ask; the column would have been scope.
