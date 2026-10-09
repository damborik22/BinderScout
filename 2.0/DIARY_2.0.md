# Repo diary — the 2.0 chapter

> **Originally an extract of lines 2099+ of `docs/REPO_DIARY.md`; now the 2.0 diary in its own
> right (operator, 2026-10-04).** `docs/REPO_DIARY.md` is the *historical* diary and is not where
> 2.0 work goes — a 2026-10-04 attempt to consolidate this chapter into it was reverted and that
> file left untouched. Write 2.0 entries HERE. The MUNI copy under
> `HITS with RESULTS/Claude outputs/` stays as the local record and keeps its own longer-form
> write-ups; it is not retired.
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

### The follow-up: `<binder_id>_<engine>`, and why the directory was not enough

The first cut named a structure after the binder id alone, on the reasoning that each
engine owns its own output directory so nothing can collide. That reasoning is correct
and beside the point. The whole request was "we need **all** the PDBs" — and the way
anyone acts on that is to copy the three directories into one folder. At that moment a
design's three structures become three files called `rfd3_b7.pdb`, two of which are
overwritten on the way in, and the survivor does not say which engine produced it.

So the engine belongs in the *name*, not only in the path: `rfd3_b7_boltz2.pdb`,
`rfd3_b7_af3.pdb`, `rfd3_b7_esmfold2.pdb`. The legacy fallback names are left alone —
they already say `af3_0007` — and a test pins that they are not suffixed into
`af3_0007_af3`. A second test pools all three engines over the same id list and asserts
six distinct filenames, which is the property that actually matters and which the
per-engine directory never gave us.

### The one behaviour change to know about

A re-run into the same output directory now **overwrites** a design's structure. The old
names carried a per-run uuid and accumulated instead. For `--resume` this is strictly
better — the completed files are already under their final names — but it is a real
change and it is in CHANGELOG and CLAUDE.md rather than left to be discovered.

Not done, deliberately: no `binder_id` column was added to the engine CSVs. The merger
already attaches one from the FASTA, and a second `binder_id` arriving through the
prefixing and the outer join is how you get `binder_id_x` / `binder_id_y`. The filename
was the ask; the column would have been scope.

---

## A CI pin, a half-removed flag, and two bugs that were hiding each other

**2026-09-29 (cont.)** Started as two lines of housekeeping — bump the GitHub Actions,
add a canary — and turned into the largest correctness haul of the session. Almost none
of it was in the request. What follows is mostly how each thing surfaced, because in
every case the *route* was the transferable part.

### The pin was an answer that never gets checked

CI was warning that `actions/checkout@v4` and `setup-python@v5` were being forced onto
Node 24, and `ubuntu-latest` was about to migrate. Bumping to v7 was trivial. Pinning
`runs-on: ubuntu-24.04` was trivial too — and wrong on its own, in a way worth naming:
**a pin converts a scheduled surprise into an indefinite unknown.** Nothing would ever
tell us the migration breaks us, because nothing would ever try it.

So the pin got a companion: a job that runs the OS-sensitive checks on `ubuntu-26.04`
today. Deciding *which* checks was the whole design. My first draft ran ruff and pytest,
which was the instinct to "run CI, but on the new thing" rather than to ask what can
actually differ. Both run the same static binary and the same manylinux wheels on the
same hostedtoolcache 3.10.21 on either image, so neither can produce an Ubuntu-26 result
— and `pip install ruff` is unpinned, so that canary would periodically go red for
reasons that have nothing to do with the OS. A canary that cries wolf is worse than none.

What survived: shellcheck (apt 0.9 → 0.11, unpinned by CI), the system `python3`
(3.12 → 3.14, which is what the stdlib-only `binderscout.py` and configurator actually
run under), and docker (engine 28 → 29). The first run answered the question the pin
never could: **shellcheck 0.11.0 is clean on all 20 scripts, the configurator and TUI
import under 3.14.4, docker 29.4.2 builds.** Zero annotations. We are already Ubuntu-26
clean, and now we will hear about it the week that stops being true.

### Three things I had asserted the day before, all wrong

Worth recording as a set, because they came from the same habit.

**"ubuntu-26.04 is in preview."** It is GA, since 2026-09-17. I had fetched the
runner-images README through a summariser, which attached Xcode 27's preview badge to
the Ubuntu row. Reading the table markup directly took one command and settled it.

**"migrates from 2026-10-19."** It is a gradual rollout *between* October 19 and
November 19. A window, not a date — which changes what "prepare for it" means.

**"`continue-on-error` gives a warning."** It does not. The docs say exactly what it
does — *"Prevents a workflow run from failing when a job fails"* — and that is the run
*conclusion* only. The job keeps a red X and a PR still reads "Some checks were not
successful". The yellow rendering I was picturing is an unimplemented feature request.
The fix was to stop depending on the keyword: every step is non-fatal, the job exits 0,
and a `::warning::` annotation *is* the signal.

The pattern in all three: I reported a summariser's paraphrase, or my own recollection,
in the register I use for things I checked. The corrective is not "be more careful" but
**go to the markup**.

### Two bugs I wrote into the canary, caught by running it

**The python probe was a no-op.** `python3 binderscout.py --help` looked like a system-
python smoke test. It is not: `main()` prints `USAGE` and exits at `binderscout.py:167`
*before any import*, so the only modules on that path are `os`/`sys`/`pathlib` and
nothing there can fail on any interpreter. It would have stayed green through any 3.14
breakage. It now imports the 3.7k-line configurator and the curses TUI — the actual
stdlib-only surface — verified locally on 3.14.4, the same version the image ships.

**`shell: bash` made the canary stricter than the job it watches.** The explicit form is
`bash -eo pipefail`; the real jobs get the Linux default `bash -e`. A canary running
under stricter flags reports *its own strictness* as a migration failure. Removing it
also removed a real SIGPIPE race (`yes | head -2` exits 141 under pipefail).

And the comment I wrote justifying that removal contained a false claim —
`mapfile -t x < <(a | b)` discards the process substitution's status, so pipefail could
never have failed that step. I had reasoned it instead of running it. One command
(`rc=0`, empty array) showed it. **A comment asserting a mechanism is a claim, and it
should be measured to the same standard as code.**

### The flag had been half-removed for a day, and `--help` was still selling it

`--soluprot-filter` was removed on 2026-09-28: `evaluate.sh` exits 1 on it. The
implementation behind it was unreachable, so deleting it should have been a tidy-up.
An audit found **21 places still advertising the flag**, and the live ones were the
problem:

- `evaluate.sh --help` prints its own usage block by `sed`-ing the file's comments — so
  `--help` documented, in full, a flag the parser refuses.
- `binder-compare screen-tmprot --help` is `description=__doc__`, and that docstring
  said SoluProt "has a `--soluprot-filter` mode that drops sub-threshold designs".
- `docs/config-builder.html` — which README tells people to open — had a **checkbox**
  emitting a config key the configurator silently ignores.
- The orchestrator skill named the flag as a knob. An agent following it gets exit 1
  mid-campaign.
- `CLAUDE.md:98` and `:173`. I had edited CLAUDE.md that same morning and missed both.
- `soluprot_runner.py`'s docstring still *prescribed* "drop the bottom of the
  distribution" — the exact use Part Z measured and rejected.

The lesson is about what "removed" means. Making the flag fail loudly was the safety
fix and it was right. But a refusal plus a dozen documents describing the feature is a
repo that argues with itself, and the loudest voices are the ones that execute: help
text, generated forms, agent instructions. **Retiring a feature means retiring every
surface that offers it, and the executable surfaces first.**

One more, found by checking what the warning actually did rather than that it fired:
`load_run_config` warned about a stale `soluprot_filter` key and then left it in `cfg`,
so the regenerated `config.json` wrote it straight back out. The key was never retired
— it propagated, and the warning would have fired forever on every later replay. It is
dropped now.

### My replacement tests were hollow too, which is the fourth time this session

I had rewritten one grep-based test into a behavioural one and felt done. Adversarial
review mutated all of them:

- the stale-config test asserted `"soluprot_filter" in output` — and the config being
  loaded *contains that key by construction*, so deleting the warning entirely still
  passed;
- it also could not distinguish a conditional warning from `if True:`, i.e. a warning
  that fires on every load;
- the emission test pinned one cfg key name, so re-adding the emission behind a renamed
  key survived it.

Each is the same error in a new costume: **asserting that a string is present, when the
property is about behaviour under a condition.** The fix that generalises is to test the
negative case too — a clean config must stay *silent* — because that is what separates
"the code ran" from "the code discriminated".

### The test that paid for itself immediately

Both behavioural tests hand-build their own `cfg`, so neither touches what the wizard
actually writes. That gap is invisible to any amount of behavioural testing, so I added
an AST test comparing the cfg keys the wizard **writes** against the keys
`write_run_evaluate` **reads**.

It failed on the first run, on untouched code:

> `write_run_evaluate reads cfg keys the wizard never writes: ['tmprot_threshold', 'use_tmprot']`

**TmProt had never run from a generated run script.** The wizard wrote those keys only
into `tools_enabled`; `cfg.get("use_tmprot", False)` fell through every time, so every
`run_evaluate.sh` ever generated carried `--skip-tmprot` no matter how the wizard was
answered, and the Tm column was silently missing from every report.

Then the shell audit found the other half: the TmProt block sat ~90 lines *above* the
initialisation block that owns `STEP`, `N_STEPS` and `TMPROT_CSV`. Under `set -u` that
is `STEP: unbound variable` — a hard abort of the entire evaluation before step 0 and
before any engine, on any host where the `binder-eval-tmprot` env exists. The env is
auto-detected, so no flag was needed to trigger it. And past that, `TMPROT_OK` was reset
to 0 *below* the block that sets it, so the report could never have received
`--tmprot-results` anyway.

**The two bugs were hiding each other.** The configurator always passed `--skip-tmprot`,
so the crash could not fire through the documented path; and because it never ran,
nobody noticed the column was missing. Fixing either alone would have been actively
harmful — repairing the configurator would have turned a silent no-op into a hard abort
for every user with the env installed. They went in together.

This is the sharpest instance yet of the standing rule about checking all four modules.
Installer, configurator, evaluator, report were each *individually* fine here. The
defect lived in the contract *between* two of them, where neither side's tests look.

### A hazard in the tooling: the review agents mutate the working tree

The adversarial verification ran mutation tests to check my tests had teeth. One of them
**did not restore its mutation** — `configurator.py` was left with `if True:` in place
of the stale-config guard.

I caught it only because the behaviour did not match what I had just written. And my own
edit had concealed it: I used a single `assert s != o` for a two-part replacement, so the
half that silently failed to match was masked by the half that succeeded. That is the
same "assert the mutation was applied" discipline I enforce on mutation scripts, not
applied to my own edits. Every replacement now asserts its own result.

Two takeaways. Review agents that mutation-test share your working tree, so **diff the
tree against what you believe you wrote** before committing after one runs. And a
compound edit needs a compound assertion.

### What shipped

Three commits: the actions bump and runner pin with the corrected facts; the Ubuntu 26
canary; and the SoluProt completion carrying the two TmProt fixes. 962 tests, 8
mutations applied and caught, ruff and shellcheck clean, and the canary green on
Ubuntu 26 with no annotations.

Noted and deliberately not touched: `binder-compare filter-soluprot` and
`refolding.run_soluprot_filter` only *score* despite their names — public API, so
documented rather than renamed — and a pre-existing `if True:` at
`visualization/report.py:1530`.

---

## The knob that was never connected, and what it took to run four arms

**2026-09-30.** Two pieces: wiring `ss_bias`, and actually running the arms. The wiring
was twenty minutes. The running was the interesting part, and most of it was about not
breaking somebody else's machine.

### A dead knob is not a missing feature, which is why it survives

`design()` in the Mosaic template took an `ss_bias` argument. It gated two real loss
terms — `sp.HelixLoss()` and `sp.DistogramRadiusOfGyration()`. It had a `print` that
announced the bias when set. Everything about it read as a working feature.

**Its sole call site never passed it.** So it was permanently `"none"`, both terms were
unreachable in every script the configurator has ever generated, and the template went on
advertising helix/compact shaping that no run could reach. The configurator injects eight
values and this was not among them, so there was no route to it through the documented
path either.

That shape is worth naming because it is this repo's most repeated defect and it is
*invisible to testing the parts*: the parameter works, the terms work, the print works.
Only the join is missing. The same shape produced the AggreProt reduction that nothing
calls, and — found the same week — the TmProt keys the wizard wrote into `tools_enabled`
while the writer read them off `cfg`.

Two more defects fell out while wiring it, both of the same family:

* the branch was `if/elif`, so `"helix+compact"` silently meant `"helix"`. They are
  different properties; upstream composes its contact and globularity terms rather than
  choosing between them. Now they stack.
* an unrecognised value was silently ignored, which costs a *whole campaign* running with
  no bias at all. It now raises and names the valid set.

Worth having because it moves the RFD3 lesson in-loop. There we learned to gate on
geometry — `Rg/expected <= 1.45`, long-range contacts `>= 0.80/res` — **after** backbone
generation, and that a Pro/Gly-rich sequence is a *symptom* of a coil rather than an MPNN
problem. As a differentiable term the backbone never gets to be a coil in the first place.
Upstream independently converged on shipping globularity as a standing term in its
minibinder recipe.

### Running the arms meant not touching a working machine

BM2 has the GPU. BM2's Mosaic is **seven commits behind our pin**, so the template would
not even import — `batched_simplex_APGM` arrived in the commit we pin.

The two obvious routes were both bad. Checking our pin out *in place* moves the source
under their venv's editable install, and their Boltz-2 refolder rides that venv — so the
experiment would have changed the behaviour of a production engine on someone else's box.
`uv` is not installed there, so an isolated venv means installing uv and pulling gigabytes
of jax-cuda wheels.

The third route cost seconds: a **git worktree** at our pin plus `PYTHONPATH`, reusing
their existing venv. `PYTHONPATH` precedes the `.pth` an editable install appends, so the
pinned source shadows theirs for our process and for nothing else. Our offline-MSA patch
is a working-tree modification rather than a commit, so it had to be carried across
explicitly — which is a nice illustration of why that patch being installer-managed rather
than committed is a standing liability.

Verified before spending GPU: both loss terms importable, `TargetChain.msa_path` present,
**zero writes to their installation**.

### Two mistakes of mine in the experimental setup

**The queue died silently.** I backgrounded a `nohup`'d chain on BM2 to run the remaining
arms after the first. It was running when I checked, and gone afterwards with an empty log
— the process group took the SIGHUP when the ssh session ended, `nohup` notwithstanding.
Nothing had run. Relaunching the chain from this side, where the ssh connection is itself
the background job, is both simpler and observable.

**All four arms share a working directory.** They write the same `designs.csv` and the
same `structures_28aa_8_top2/`. I noticed while arm 2 was already running. It is
recoverable — every row carries a `worker_id`, each run generates a fresh one, and each
arm's id is in its own log — so the arms are separable post hoc and no re-run is needed.
But the correct setup was one CWD per arm, and I did not think about it until the second
arm was writing into the first one's file.

### The readout to trust, and the one not to

The load-bearing check is the cheapest one: **how many terms the optimiser prints**. The
baseline arm logs exactly ten (`.0` target_contact through `.9` plddt — an earlier note here
said nine, from a lowercase-only grep that skipped `pTMEnergy`). A bias must add one each;
the DELTA is the evidence, and it is unaffected by that miscount. That is the only direct evidence the term reached the loss — everything else is
downstream of it, and a knob that silently does nothing would otherwise look like a term
that simply did not help.

What this run **cannot** answer is whether geometry bias is good. Eight designs, one
length, one target, and the weight is unvalidated: ours is 0.1, upstream ships 0.2 against
a different three-term loss, and our nine-term loss already carries `WithinBinderPAE` and
`WithinBinderContact`, both correlated with compactness. A null result here would not mean
the term is useless, only that this weight in this loss moved nothing. Judging it properly
means refolding on AF3 or ESMFold2 — never Boltz-2, which Mosaic optimises by
construction — across more than one target.

### The result, and what nearly went in the changelog instead

The four arms answered. On both held-out engines, permutation test over n=16 vs 16:

| arm | AF3 Δ | AF3 p | ESMFold2 Δ | ESM p |
|---|---|---|---|---|
| **helix** | **+0.111** | **0.0062** | +0.093 | 0.088 |
| compact | +0.031 | 0.489 | +0.021 | 0.699 |
| helix+compact | +0.073 | 0.070 | +0.060 | 0.317 |

`HelixLoss` at 0.1 helps. The Rg hinge at 0.1 does not, and stacking it onto helix makes
things *worse* than helix alone. A geometry readout corroborates the second half from a
completely different direction: the compact arm produced binders **looser** than baseline
(Rg/expected 1.204 vs 1.104), so the term failed at its own stated job before it failed to
help. Wiring the knob was right; the compactness half of what it exposes is not earning
its place.

**The limitation belongs first, not last: the target is a helix.** A helix-promoting term
helping on the 32-aa CALCA helix is the least surprising result available. It may be
target-matched rather than useful, and nothing here touches a globular target.

### What the control did to the story

The first pass had **one** baseline replicate. It read:

    helix +0.143 (AF3) / +0.134 (ESMFold2)   -- two engines, magnitudes within 0.01

and I had written most of a message calling that a clean two-engine agreement. It was
agreement, and it was also partly agreement about a baseline measured once. A second
baseline replicate moved the control by **0.065** on AF3 and **0.080** on ESMFold2 —
comparable to the effects themselves — and cut every delta by roughly a third. Two of the
three arms did not survive it.

So the honest sequence is: I flagged the single-replicate baseline as the weakest joint,
reported the result anyway, and then had to walk most of it back one message later. The
flag was not worth much without the second run behind it. **A control measured once is not
a control; it is one more arm.** Cheap here — 12 minutes of GPU — and it changed the
conclusion from three effects to one.

The permutation test mattered for the same reason. Eyeballing "effect vs replicate spread"
had me calling helix+compact marginal and compact dead; the test agrees on compact
(p=0.49, 0.70) but puts helix+compact at p=0.070/0.317, i.e. also dead, and lifts AF3's
helix to p=0.0062 — which survives Bonferroni across all six tests. Three arms of eyeball
became one arm of measurement.

### The confound I could not remove

The arms **do not share an objective**. Adding a geometry term changes the loss, so an
equally good reading is that *any* well-behaved extra term regularises Mosaic away from
Boltz-2-specific overfitting, and the held-out engines reward that rather than rewarding
geometry. Distinguishing the two needs an arm with an *unrelated* term of similar
magnitude, and that arm was never run. Until it is, "HelixLoss helps" should be read as
"adding this term helped, on this target, for a reason not yet isolated".

### Infrastructure that came out solid regardless

Three things were validated by production runs rather than probes, which is the standard
this repo keeps failing and then fixing:

* **`ss_bias` is genuinely wired** — term counts 10 / 11 / 11 / 12 across the arms, with
  the 12 proving the `if/elif` → `if/if` fix at runtime.
* **AF3 refolded 56/56 on a 60-token pool on sm_86, zero empty rows**, at
  `--buckets=256`. That is this morning's floor holding on a real pool, in the exact
  configuration that aborted with a shared-memory error.
* **ESMFold2 completed a full 56-design pool in 64 s.** "No completed ESMFold2 fold has
  ever been observed" is now falsified twice over.

And nothing on BM2's installation was modified at any point: a git worktree plus
`PYTHONPATH` for Mosaic, `--scripts-path` for AF3, BM2's own script for ESMFold2 — the
last because our pinned ESMFold2 revision has no weights there and upgrading `transformers`
to satisfy it would break the configuration that demonstrably works. Two engines, two
opposite decisions about whose code to trust, both recorded rather than guessed.

One own-goal for the record: staging our AF3 script for `--scripts-path` broke its
relative resolution of the AF3 repo, so the first refold failed instantly. It failed
*loudly*, naming `AF3_REPO_DIR` as the fix, which cost a minute instead of producing 56
empty rows — the 1.0.3 work on silent refold failures paying for itself.

### The control overturned it, and the proportionality is the finding

**2026-10-03.** I committed `HelixLoss at 0.1 helps` three days ago with p=0.0062 on AF3,
agreement from a second held-out engine, and a corroborating geometry readout. The control
arm removed it.

A placebo — a frozen random linear functional of the binder's composition, same elu hinge
and same 0.1 weight as `HelixLoss`, no structural content whatsoever — is **statistically
indistinguishable from the helix arm**: AF3 +0.046 p=0.199, ESMFold2 +0.039 p=0.48. The
third helix replicate landed at 0.610 against the placebo's 0.612.

The number that settles it is the ratio of effect to the term's measured magnitude in the
loss:

| | term magnitude | AF3 Δ/mag | ESMFold2 Δ/mag |
|---|---|---|---|
| helix | 0.63 | 0.138 | 0.125 |
| placebo | 0.30 | 0.135 | 0.135 |

**Identical, on two independent engines.** A random functional buys exactly as much
held-out score per unit of loss magnitude as an α-helix prior does. Content contributes
nothing; magnitude contributes everything. And it explains the arm I had called a clean
negative: `compact` at +0.031 implies a magnitude near 0.23, which is what an Rg hinge
sitting close to its target would add. **One parameter explains all four arms.**

So Part AI is asking the wrong question. It asks *which structural prior*; the answer is
that Mosaic's nine-term loss is **under-regularised**, and the question is *how much*. That
is a more useful finding than the one I thought I had, and I would not have reached it by
adding more structural terms.

### Four stages, each of which looked like a result

Worth laying out, because the shape is the transferable part:

1. **One baseline replicate.** helix +0.143 AF3 / +0.134 ESMFold2, two engines agreeing to
   within 0.01. I nearly reported this as settled.
2. **A second baseline replicate.** Moved the control by 0.065–0.080 — comparable to the
   effects — and cut every delta by about a third. Two of three arms died.
3. **A permutation test.** Replaced eyeballing "effect vs spread". `compact` p=0.49,
   `helix+compact` p=0.070 — both dead; helix survived Bonferroni at p=0.0062.
4. **The placebo.** Removed the attribution entirely.

Each step was cheap — 12 to 35 minutes of GPU — and each one deleted a conclusion the
previous step supported. The flagging was not the problem; I flagged the weak baseline and
the missing control both times. **Flagging a weakness and then reporting anyway is not
caution, it is a hedge.** The run was 25 minutes.

One asymmetry worth keeping: the control could only ever weaken the result, never
strengthen it. I said so before running it. That is the right reason to run something.

### The next test, stated so it can falsify this too

The placebo is half HelixLoss's magnitude (0.30 vs 0.63). The constant ratio predicts a
placebo scaled to 0.63 lands at **+0.085**, matching helix. If it does, H2 is confirmed
outright. If it lands at +0.041 again — i.e. magnitude does *not* scale — then the
proportionality was a coincidence of two points and I am wrong again. ~25 min.

### The dose-response refuted my refutation, and the answer is "underpowered"

**2026-10-03 (later).** I wrote the falsification condition down before running it:

> "The constant ratio predicts a placebo scaled to 0.63 lands at +0.085. If it returns
> +0.041 instead, the proportionality was a coincidence of two points and I am wrong
> again."

The arm at measured magnitude **0.835** returned **+0.042** (AF3) and **+0.011**
(ESMFold2), against a prediction of +0.115. The ratio collapses from 0.135 to 0.051/0.013,
and at magnitude 0.335 the two engines disagree in **sign** (+0.055 vs −0.032). The
proportionality was a coincidence of two points.

That is three overturns of the same experiment in four days:

1. `HelixLoss helps`, p=0.0062 — killed by a second baseline replicate and a placebo.
2. `It is magnitude, not content`, two engines agreeing on the ratio to 0.003 — killed by
   a third magnitude.
3. Now: **nothing is detectable.**

### Why I kept getting results that were not there

Three placebo arms should measure the same thing. On ESMFold2 they span **0.072**
(−0.032 to +0.040), and helix's +0.079 sits *inside* that. Across 4 arms × 2 engines the
Bonferroni threshold is 0.0063 and the best p is 0.0168. No arm survives.

The arithmetic I should have done on day one:

| to detect | AF3 (sd 0.117) | ESMFold2 (sd 0.155) |
|---|---|---|
| Δ = +0.04 | ~137/arm | ~240/arm |
| Δ = +0.087 | ~29/arm | ~51/arm |

We ran **8 per campaign, 16–24 per arm** — between 3× and 12× underpowered for the effects
being chased. Every apparent result was noise large enough to look like signal at n=16,
and each new control happened to delete the previous interpretation rather than the
underlying nothing.

**The deliverable is therefore a budget, not a verdict.** A real answer needs ~140 designs
per arm × 4 arms × 2 replicates ≈ **26 GPU-hours** plus refolds. That was never budgeted,
and not budgeting it is why four days produced three retractions. A power calculation costs
one minute and would have prevented all of them.

One incidental finding worth keeping for whoever designs that sweep: **the achieved term
magnitude does not track the weight.** Scale 5.0 → 0.30, 12.5 → 0.335, 25.0 → 0.835. A
stronger term drives the composition to reduce itself, so the loss is self-limiting and a
weight sweep is not a magnitude sweep.

### What I would do differently, concretely

Not "be more careful". Three specific things:

* **Compute the detectable effect size before the first arm.** If the smallest interesting
  effect needs 10× the n you can afford, the experiment is not worth running in that form
  — and you learn that in a minute rather than in four days.
* **Run the control first, not last.** The placebo was the cheapest arm and the most
  informative; it ran fourth. Had it run first, "HelixLoss helps" would never have been
  written down.
* **Treat agreement between two engines as one observation, not two.** AF3 and ESMFold2
  agreeing to within 0.01 felt like replication and was the single most persuasive thing
  in the whole sequence. They were scoring *the same designs*; correlated readouts of one
  underpowered sample do not become powered by being read twice.

---

## The ranking was never wrong — only every label describing it

**2026-10-03.** Asked to write down how the evaluator ranks, because it "seems lost
throughout time". It was. Reading the code and every file that describes it turned up 50
contradictions, four of them load-bearing enough to change what someone does.

The shape of this one is worth recording because it is the opposite of the usual failure.
`rank_designs()` has been correct the whole time: gate on `--min-engines`, sort on
`consensus_iptm_mean`, tie-break on `consensus_iptm_n` → `consensus_iptm` → binder pLDDT.
No run produced a wrong order. No test went red. Nothing in any output looked wrong. What
had drifted was every *description* of it:

* `report.html`'s own glossary told the operator `ipsae_min` was "the primary ranking
  metric" — on the same page that ranks by `consensus_iptm_mean`.
* `Evaluator/docs/pipeline_reference.md`, the file CLAUDE.md names as **the** metrics
  reference, said the same in its metrics table.
* The orchestrator skill's `references/evaluation.md` instructed an agent to sort on
  `agreement_count` **descending** as the primary key.
* `SKILL.md` §6.3 said `ipsae_min` agreement "is what unifies them at the campaign's final
  ranking".

An agent following the third would have produced a differently-ordered shortlist from the
report's own and had no mechanism to notice the disagreement. That is the real cost: not a
wrong number, but two authorities giving different orders with no arbiter.

### Why the glossary one mattered more than it looked

I nearly logged the `report.html` string as cosmetic. Rendering an actual report is what
changed my mind, and it only worked on the second attempt — my first render passed
`summary={}` and the new text did **not** appear. `_METRIC_DESCRIPTION` renders only for
metrics present in the `summary` dict, and per the `compute_statistics`-ordering defect
that dict is built *before* the consensus columns exist. So the shipped per-tool table
shows `ipsae_min` and **never shows `consensus_iptm_mean` at all**. The glossary was the
operator's only in-page statement of what ranks, and it named the wrong column.

I would have "verified" that fix with a grep and been wrong about its importance in both
directions — thinking it cosmetic, and not knowing whether the string renders. Grepping the
source tells you a string exists. It does not tell you a human ever sees it.

### agreement_count moved to notes, and the code disagreed with the intent

Separately: `agreement_count` was *blocking* `wetlab_recommended`
(`scoring.py` appended `agreement {n} < 2` to `reasons`, and the badge is
`len(reasons) == 0`), while the operator's position is that it is a warning and must not
discriminate. It now lands in `notes`, exactly where SoluProt went on 2026-09-28.

Two things fell out of that worth keeping:

* **The same string had been wrong about SoluProt for five days.** The glossary still read
  `wetlab_recommended = SoluProt pass + agreement_count ≥ 2 of 3 + …` after SoluProt became
  note-only. Moving a criterion out of a gate is a two-line change; finding every sentence
  that still advertises it is not, and nothing connects the two.
* **Two tests had to change sign, which is the moment to be careful.** A test asserting
  "low agreement blocks" becomes "low agreement does not block", and a pair of tests like
  that is satisfiable by a function that never blocks anything. So the third test exists:
  `test_wetlab_blocks_on_plddt_even_when_agreement_is_fine`. Without it the suite would
  pass if `reasons` were deleted outright.

### What I did differently, and it caught something

Every fix here is pinned by `tests/test_ranking_metric_is_not_misnamed.py`, and I
mutation-tested it against all four reversions **plus** the escape I expected to be the
real weakness: deleting every mention of ranking rather than correcting it. A pure negative
test ("must not say ipsae_min ranks") passes on a file that says nothing at all, which
would leave an operator with no statement of what the order means. So each surface must
also *name* `consensus_iptm_mean`. That fifth mutation failed the test, which is the only
reason I know the pin is worth anything.

---

## Four things that only showed up when I ran them: Chai-1's MSA, a registry's labels, a gate pointing backwards, and a tool that was never re-installable

**2026-10-03, later the same day.** All four of these were "already known" in some sense — written
down in a plan, a docstring, or a commit message. Each was wrong in a way only execution exposed.

### 1. Chai-1 folds on sm_86, and the headline was an MSA artifact

Part AF had a source analysis and no execution: *"No Chai-1 fold was executed — the GPU was in
use, and this box is a 12 GB RTX 3060."* BM2's 3090 came free, so I ran it. 326-token complex,
`chai_lab 0.6.1`:

| | wall | peak alloc | iPTM |
|---|---|---|---|
| `use_esm_embeddings=True` | 345.9 s | 9,484 MiB | 0.285 |
| `use_esm_embeddings=False` | 86.4 s | 9,484 MiB | 0.104 |

The source analysis was right about everything structural: no `triton`/`pallas`, no
shared-memory abort, and peak allocated **identical** with and without the ~6 GB ESM2-3B —
which is only possible because `_component_moved_to` moves each component to the GPU and back
rather than retaining it. Peak is the largest single component, not the sum.

Then I checked what the design actually was, and it was a **confirmed non-binder** that Boltz-2
scored 0.905 and ESMFold2 0.827. Chai-1 at 0.285 was the only engine to reject it — exactly the
independent-fourth-opinion case AF was re-scoped around. I recorded it as suggestive and
explicitly not as evidence, on two grounds: n=1, and Chai-1 had run **MSA-free** while our three
engines read a cached target MSA, so a uniformly less-confident engine would reject binders and
non-binders alike.

**The second ground turned out to be the whole story.** `msa_directory` takes `.aligned.pqt`
files keyed by `expected_basename(sequence)`, and `a3m_to_aligned_dataframe` converts our cached
a3m, so parity was achievable — target aligned, binder single-sequence, matching `use_msa=False`.
At parity the same design scores **0.818**. Chai-1 makes the same mistake as the others.

So the striking result was the missing MSA, not the model. **Had I run the 563-design study
MSA-free it would have produced a false positive for adoption** — and the shape of that error,
impressive on one pool and driven by a confound, is the shape of the five retractions in the
week of 2026-09-29. The study now runs at parity, with criteria fixed in advance.

Worth keeping: I proved the MSA was consumed rather than assuming it. 0.818 vs 0.286 on one
input is the proof. Passing `msa_directory` and never checking would have been indistinguishable
from passing nothing.

### 2. The registry's first pool, and `master_designs.csv` is not a label source

Part Y shipped as a working library whose `list_benchmarks()` returned `[]`, which blocked
promoting three shadow-mode columns. Registering `adaptyv` fixed that: manifest committed, rows
in a private store, verified by SHA-256.

Then the `docs/adaptyv-proteinbase-one-dataset` branch landed a warning — the raw exports are
long-format per (design, target) with replicates, and `master_designs.csv`'s flattened
`binding`/`kd` columns silently pick a target and a replicate, so a counter-screened design
yields a chimeric row. I had built labels partly from that file.

Checking beat assuming in both directions. **2,018/2,018 of our rows match the exports** — two
egfr/il7r rows were wrong and are corrected (binders 323 → 325), and expression was wrong too
(1,795/223 → 1,810/208). And the **nipah discrepancy I had logged as "unresolved" yesterday was
the flat file's error, not ours**: nipah's labels come from a *separate* export whose competition
screened against **two** targets, `nipah-glycoprotein-g` and `human-serum-albumin`. All 1,030 of
our nipah rows match it exactly, 103 binders both ways. `master_designs.csv`'s "927 designs,
1 binder" is the flattening artifact.

Also found while rebuilding: `expressed` is a property of the **design**, not of a
(design, target) pair — it records whether the protein was produced at all. Keying it per-target
produced an all-null column, which the join hid completely.

### 3. The composition gate points backwards, and that is what the registry was for

With a registered pool, `would_exclude_composition` could finally be judged against outcomes
instead of intuition. Over all 2,018 labelled designs:

| | |
|---|---|
| flagged for exclusion | 1,512 (74.9 %) |
| true binders it would remove | **271 of 325 (83.4 %)** |
| binder rate among **kept** | 0.107 |
| binder rate among **excluded** | **0.179** |

Lift **0.663× — inverted.** The designs it discards bind at a *higher* rate than the ones it
keeps. It survives the obvious confounds: inverted in **4 of 5** length bands and on both large
targets (egfr 0.062 vs 0.171, nipah 0.065 vs 0.119). And no individual feature carries signal —
every one scores between **0.462 and 0.547** AUC, with `comp_pro_gly_frac` at 0.462, i.e.
pointing the wrong way.

The honest reading is not "composition is uninformative" but "these thresholds do not transfer".
They were calibrated on the RFD3 Pro/Gly-coil failure mode, where a bad backbone really does
produce a Pro/Gly-rich sequence. A de novo competition pool has no such artifact, and flagging
75 % of it is the symptom. **`would_exclude_composition` must not be promoted.** The two targets
that point the right way (il7r, pd-l1) are n=96 and n=66 at 0.64/0.48 prevalence.

### 4. A tool documented as installable was never *re-*installable

PC's aarch64 install was fixed on 2026-09-26 to use `jax[cuda12]==0.6.2` instead of the CPU-only
`jax[cpu]==0.4.29`. I went to measure the MCTS throughput that has blocked the tool since
2026-07-29, and found BM5's PC venv reporting:

```
An NVIDIA GPU may be present on this machine, but a CUDA-enabled jaxlib is not installed.
jax 0.4.29 jaxlib 0.4.29 backend cpu
```

The fix had never arrived. Running the installer showed why in one line: **`uv venv` refuses when
a venv already exists** ("Use `--clear` to replace it"), exits non-zero, the installer's
`|| { print_fail; return 1; }` fires, and the tool is reported as failed while the *old* env is
left untouched. BM5 had a pre-0.6.2 venv, so every re-install since has been a no-op that
reported failure.

So "installable on aarch64 since 2026-09-26" was only ever true of a box that had **never
installed it**. The deprecation's whole cost argument — ~130× too slow, 1.7 years for PC-v3's
50 replicates — rests on a CPU-bound AF2 reward, and the box's own BindCraft env has been running
`jax 0.6.2` on `gpu` the entire time. The hardware was never the problem and the fix existed; it
just could not land.

Three call sites had it, not one: aarch64 PC plus BindCraft 2 on both platforms.

**What writing the test taught me, which is the part I would otherwise have got wrong.** A plain
`\buv\s+venv\b` matcher reported **six phantom offenders** — both installers carry "uv venv" in
menu descriptions, comments, `run_logged` labels and a `print_fail` string. I nearly "fixed" nine
call sites when three existed. The matcher now requires a flag or path to follow, and a second
test bounds the match count so it cannot go loose again and start passing vacuously.

### The pattern across all four

Each was recorded as settled. The source analysis said Chai-1 would fold — right, but silent on
the MSA. The branch said our labels were suspect — right about the file, wrong about our rows.
The gate shipped with thresholds that read as principled. The installer's own log said the tool
failed, and nobody asked why a *re*-install would. **In every case the written claim was true of
a situation that was not ours**, and the only thing that separated them was running it on the
machine that mattered.

---

## Proteina-Complexa was never too slow for Spark. It was six bugs deep in our own installer

**2026-10-04.** The tool has been deprecated since 2026-07-29 on a throughput argument: 3,300
AF2 calls per 100-design replicate at ~320 s each = 12.2 days, ~1.7 years for PC-v3's 50
replicates, "run Proteina-Complexa on x86". Asked to run a short MCTS and time it.

**Measured, same box, same config, `mcts n_simulations=2` through `gpurun --cap 40`:**

| | |
|---|---|
| single-pass, no reward | **39.9 s**, 1 sample |
| MCTS, 9 AF2 reward evaluations | **112.3 s → ~12.5 s per AF2 call** |

Against ~320 s that is **~25×**, which re-costs the production recipe at **~11.5 h per
100-design replicate** and PC-v3 at **~24 days**. GB10 is about **5× an H200, not 130×**.

### Getting there took six fixes, and not one of them was aarch64

The deprecation's premise — that the AF2 reward has no GPU here — had already been undermined
in CLAUDE.md on 2026-09-25: PC's reward *is* the ColabDesign that BindCraft had been running on
this GPU for weeks. What nobody had done was try it. Six things were in the way, each of which
alone looks like "the tool doesn't work on this platform":

1. **`uv venv` without `--clear`.** It refuses when a venv exists, exits non-zero, the
   installer reports the tool as failed and leaves the OLD env in place. BM5 had a pre-0.6.2
   venv, so **every re-install since 2026-09-26 was a no-op that reported failure** — which is
   exactly why the jax 0.6.2 fix never reached the one machine it was written for. "Installable
   on aarch64" was only ever true of a box that had never installed it.
2. **The editable install's index strategy.** PC's pyproject carries
   `[tool.uv] extra-index-url` pointing at the PyTorch wheel index, and uv's default
   `first-index` stops at the first index holding a package. That index has *some* `tqdm` but not
   the `tqdm==4.66.4` proteinfoundation pins, so resolution failed outright instead of falling
   through to PyPI. uv's own hint names the fix.
3. **The bf16 smoke test blaming XLA for an OOM kill.** This is the one I would most like to
   have written differently. The guard exists *specifically* to stop us overclaiming aarch64
   support — and it printed `jax 0.6.2 | backend gpu`, `bf16 graph compiled and ran: 128.000`,
   `colabdesign imports`, then exited **137** at interpreter shutdown, and the installer
   concluded "the XLA/LLVM blocker is NOT resolved here". That is the one conclusion its own
   output ruled out: the graph had already compiled and run. Cause was BM5's memory model, which
   `tools/gpurun`'s own docstring describes: jax reserves 0.75 of a pool that *is* system RAM,
   ~91 GiB of 121, and the kernel takes the process. With `PREALLOCATE=false` the identical
   script exits 0.
4. **`openbabel` missing.** `atomworks.ml.transforms.openbabel_utils` imports it at module level,
   and `gen_dataset.py` imports that, so a protein-only binder run needs a chemistry toolkit.
   Hydra reported it as `Error locating target 'gen_dataset.collate_fn'` — a symbol that exists.
5. **The installer shadowing PC's vendored ColabDesign.** PC maps its own fork
   (`"community_models/colabdesign" = "colabdesign"`), and that fork accepts a `device` kwarg
   (`af/model.py:35`: `self._device = kwargs.pop("device", None)`) which PC's reward passes.
   The jax step installed `git+ColabDesign` alongside jax, *after* the editable install, so
   upstream 1.1.3 landed in site-packages and won. Every run then died in 25–33 s with
   `AssertionError("the following inputs were not set: {'device': CudaDevice(id=0)}")`, again
   surfaced by hydra as a failure to locate the dataloader.
6. **(mine) `env.sh` not sourced, and sourcing it under `set -u`.** `complexa` refuses with
   "Environment not initialized"; `env.sh` then references variables it does not define.

### The pattern, which is the same one as yesterday

Three of those six report a cause that is not the cause. Hydra names the dataloader when the
real problem is a missing C++ toolkit or a shadowed fork. The installer names XLA when the real
problem is memory. **The error message pointed somewhere other than the fault in half the
cases**, and the only thing that worked was running the next layer down by hand: import
`gen_dataset` directly, run the smoke script directly, print where `colabdesign.__file__`
resolves.

And the deprecation itself is the larger version of the same shape. Its arithmetic was right.
Its measurement was right. Its *premise* — that this hardware puts the reward on the CPU — was an
artifact of tooling, and it survived two months and three separate corrections to the stated
blocker because nobody ran the thing.

### What I have NOT shown

n=1, 9 calls, one target, and the 112.3 s includes a cold compile. The archived CPU baselines
(354 s, 394 s per call) were taken on `apoe4_ntd` while this ran on `33_TrkA`, so a CPU control
on the identical config is running to remove the target confound — the 25× gap is far too large
for target size to explain, but that is an argument rather than a measurement. And **nothing
here says anything about design quality on this platform**, only throughput.

### RETRACTION, same hour: the AF2 reward never ran, so the 25× was not real

**The entry above is wrong where it matters and I am leaving it visible rather than editing it
away.** The ~12.5 s per AF2 call is not an AF2 cost. In the GPU run **and** in the CPU control,
every reward was `0.0` and AF2 never loaded:

```
DEBUG    Sample 0: reward = 0.0          reward_utils.py:164
         Mean reward: 0.0000
```

The two runs also produced **byte-identical sequences**, which cannot happen if a reward
influenced the search. What I timed was MCTS lookahead with a null reward.

**The CPU control is the only reason I know.** GPU 112.31 s against CPU 111.52 s for the same
nine "evaluations" — a 0.7 % difference where the hypothesis predicted ~25×. And I had not run
that control to test the reward at all; I ran it to remove a *target* confound between
`apoe4_ntd` and `33_TrkA`. If it had returned ~3,000 s I would have taken it as confirmation and
shipped a speedup that does not exist. I did ship the claim, for about forty minutes, before the
control landed.

**The specific mistake, stated plainly.** I used wall-clock as a proxy for "AF2 executed" and
never checked the thing itself: whether a reward was computed. `total_reward` was sitting in the
rewards CSV the whole time, one column away from the row count I *did* read to get my "9 AF2
calls". I read the denominator and not the numerator. My own standing note for this repo is
*verify the real interface, not a proxy*, and the failure mode I walked into — a run that reports
plausible numbers while the expensive part silently no-ops — is the one CLAUDE.md records twice
about this very platform ("each previously reported itself healthy while being unusable there").

**What survives.** The six install fixes are real and independently verified: PC now runs end to
end on aarch64 for the first time, `complexa generate` exits 0, single-pass generation takes
39.9 s, `jax 0.6.2` reports `gpu`, and the bf16 lowering compiles. That was the hard part and it
holds.

**What does not.** Every throughput number. The 2026-07-29 deprecation arithmetic is untouched
until an AF2 call is genuinely timed. Leading suspect for the silent 0.0: `af_params_dir` was
pointed at a directory containing only the five `*_multimer_v3.npz` files, and ColabDesign may
want a different layout or the non-multimer params too — with the load failure swallowed into a
zero reward instead of raised. **That swallowing is itself worth a fix**: a reward model that
cannot load its weights should refuse, not score everything 0.0 and let a search run to
completion looking healthy.

### Root cause: jax 0.6.2 vs ColabDesign 1.1.1.1, and the premise was backwards

Chasing the 0.0 reward gave the real answer, and it is more useful than the throughput number I
got wrong.

The weights were never the problem — the suspicion in my own retraction was also wrong.
`AF2RewardModel` constructs in **3.0 s**, prints `Found 5 model parameters` and all five multimer
names, `device=cuda:0`. The flat `~/af2_params/*.npz` layout is fine: the fork tries four
fallbacks and the second matches it.

Calling `score()` directly is what surfaces it:

```
AttributeError: jax.tree_map was removed in JAX v0.6.0
AttributeError: module 'jax' has no attribute 'clear_backends'
```

The AF2 call raises, then PC's own `_cleanup_jax_state()` raises a **second** time on
`jax.clear_backends` while handling the first — so the original error is masked — and the
pipeline swallows both into `reward = 0.0`. A 112-second MCTS then completes, writes nine rows,
and looks healthy.

**And this refutes the premise the whole reopen argument rested on.** CLAUDE.md has said since
2026-09-25 that PC "inherits" BindCraft's jax fix because "PC's AF2 reward *is* ColabDesign — the
same library, verified in its venv". Measured:

| | version | `jax.tree_map` sites |
|---|---|---|
| BindCraft's, running on jax 0.6.2 here | 1.1.3 | **0** |
| PC's vendored fork | **1.1.1.1** | **93, in 23 files** |

Not the same library. And the sharpest part: **CLAUDE.md recorded both version numbers in the
same paragraph** — "BindCraft here runs `colabdesign 1.1.3` on `jax 0.6.0`, PC runs
`colabdesign 1.1.1.1`" — and treated the difference as a mere *pin* to be bumped, when the
version gap is itself the blocker. The evidence to refute the conclusion was sitting inside the
sentence that stated it.

So PC on sm_121 is pinched from both sides: jax 0.4.x cannot compile AF2 for this GPU, jax 0.6.2
removed what 1.1.1.1 calls, and 0.5.3 is no middle ground (it tops out at sm_120).

**The fix is small, which is the good news.** PC vendors 1.1.1.1 only to carry a `device` kwarg,
and that patch is **4 call sites in 2 files** (`af/model.py:35,143`, `shared/model.py:163,167`).
Porting 4 lines onto 1.1.3 — already proven on 0.6.2 on this box — beats migrating 93 call sites.
PC's own 2 `jax.tree_map` uses and its `clear_backends` call need fixing either way.

**The lesson I want to keep is not "check the reward".** It is that two of my three errors today
came from accepting a written claim about *identity* — "the same ColabDesign", "installable since
2026-09-26" — where the artefact in front of me recorded a version or a date that contradicted
it. The installer said PC was installable; the log said it had never re-installed. CLAUDE.md said
same library; the same sentence said 1.1.1.1 versus 1.1.3.

---

## The label convention was wrong, and the rows I called non-binders were never ordered

**2026-10-04.** A review landed (`INVESTIGATION_label_convention_2026-10-04.md`, nine items) whose
first item says the 2026-10-03 label convention is void. **It is right, and the error was mine.**

Both SPOC sheets carry a **divider row**: below it, designs were not ordered, because of
duplication. On CALCA the `No` column simply restarts — …112, 113, 114, then 87, 89, 92 — and
every row past the restart has an empty `KD` and the *highest* `Mean_ipTM` in the pool (0.938,
0.936, 0.929). Those designs have no experimental outcome. They cannot be non-binders.

Verified before editing anything:

| panel | n tested | split | excluded | AUC [95 % CI] |
|---|---|---|---|---|
| CALCA | 114 | 99 / 15 | **11** never ordered | **0.7061** [0.581, 0.831] |
| CBG / 2VDY | 114 | 10 / 104 | **23** (20 + 3 flagged dups) | **0.4957** [0.308, 0.683] |
| ~~my versions~~ | ~~125 / 137~~ | — | — | ~~0.4835 / 0.4579~~ |

My numbers reproduce exactly, which is how I know the mechanism is the one described. **CALCA's
interval overlaps the Adaptyv benchmark's 0.7113**, so our own wet-lab data *corroborates* the
benchmark; the surviving caveat is sample size — 15 non-binders — not sign.

### Two mechanisms, and the second is the one I will remember

**CALCA.** I read an empty `KD` as "tested, did not bind". The divider was already in the sheet.
No inference about expression was ever required — I asked the operator what blanks meant, got
"not detected binding / not expressed", implemented "not bound", and never checked whether the
sheet itself distinguished *tested* from *ordered*. The answer to a question I asked was not a
substitute for reading the file.

**CBG.** The sheet **did** distinguish them: `N/A` for tested-and-not-bound, empty for
never-ordered. And **`pd.read_csv` converts `"N/A"` to `NaN` by default**, so 104 real negatives
and 20 unordered rows arrived in one indistinguishable bucket. `keep_default_na=False` recovers it
and reproduces 0.4957 to four decimals. A library default that destroys exactly the distinction
under test is the quietest data loss I have hit — nothing warns, the column simply loses a
category.

### The check that should have caught it in seconds

Eleven rows cannot move a 114-design AUC from 0.706 to 0.4835 **unless they sit at the top of the
ranking** — and they do, outranking **81 %** of the 99 confirmed binders (median ipTM 0.923 vs
0.903). A supposed negative that beats four fifths of the positives is far more likely to be
*unmeasured* than *negative*. That signature needs no divider, no flag and no provenance: it is
computable from the labels and the scores alone, and it is now written into Part AK §0 as a
routine check on any label import.

### What this is the third instance of

§4.7 of the conclusion says a measurement needs its numerator checked, not just its denominator.
This is the same failure one level up: **I checked the scores and not the labels.** The run of
errors over two days now reads
— reward `0.0` swallowed → timed a null reward as if it were AF2;
— `agreement_count` 0.532 quoted from Cao as if it were this pool;
— blanks counted as negatives when the sheet said otherwise.
Each one was a *category* error in the input, not an arithmetic error, and in each case the
contradicting evidence was already in the artefact I was reading.

**What I will do differently, concretely:** before any AUC, print the label provenance —
how many positives, how many negatives, how many excluded and *why* — and refuse to compute if
the three do not sum to the rows read. D8 of the review proposes exactly this as a registry
schema change (`outcome: bound | not_bound | not_tested | excluded:<reason>`, no default, loader
refuses a row without one). That makes the failure structurally impossible rather than
remembered, and Part Y is still imported by nothing, so it is the cheapest it will ever be.

---

## 2026-10-04 (later) — D6/D7/D9: the review's remaining items, and what the "NOT TO Order" row actually was

The eight remaining review items split cleanly: one was a real code fix (D6), two were
"record the design, do not build it" (D7, D9), and the rest were decisions to write down.
The code fix turned out to be bigger than the item described.

### D6 — the silent-demotion hole was four holes, and the guard that was meant to catch it counted the wrong thing

The item said: *make the runners refuse below a VRAM threshold rather than truncate
silently, make an empty engine row a non-zero exit, and enforce in code that BM3 never
produces authoritative refolds.* Each engine already refused when **every** design failed
— added after a total OOM reported "Wrote 1 row(s)" with rc=0. Nothing refused when
**some** did, which is the more likely case and the harder one to see, because the engines'
demand rises with token count: on a marginal card the long binders fail and the short ones
pass, so the CSV comes back plausible.

Tracing it end to end found four independent ways the failure stayed quiet, each of which
defeats the others:

1. **No preflight.** ESMFold2 discovered a 12 GB card was too small *after* fetching the
   MSA and downloading ~12 GB of weights, one design at a time.
2. **A partial failure exited 0** in all three engines.
3. **`--resume` keyed on `idx`** — and a failed design's blank row has an `idx`. So the
   retry skipped precisely the designs it existed to repair, reproduced the gap exactly,
   and reported success. This is in all three *runners*, which is the path production
   uses, not just the scripts' dev entrypoints.
4. **`evaluate.sh` counted rows.** A blank row is a row, so `tail -n +2 | wc -l` over 50
   blanks printed `ok -- 50 new row(s)`. The guard that existed specifically to catch "an
   engine that exits 0 and writes nothing" was reading a proxy for the thing it cared
   about.

(4) is the one worth keeping in mind. That guard was written deliberately, with a comment
explaining the incident it came from — and it still measured the wrong quantity, because
"did the file grow" is not "did the engine produce scores". It now counts rows with a
non-empty `iptm`, found by column name rather than index, since the three engines order
their columns differently and a hard-coded `$6` would read a different column per engine.

**Only ESMFold2 gets a static device floor, and the asymmetry is the content of the fix.**
Its cost is dominated by resident ESMC-6B weights, so its smallest-size peak *is* its
floor — 14,248 MiB on a 3090 and 13,781 on GB10, two architectures agreeing, which is what
makes "a card below this cannot run it at any size" a prediction rather than a guess.
Boltz-2 deliberately gets none: 8,518 MiB at 150 tokens on a 3090, 16,712 at 300, outright
failure at 600, and GB10 needs ~1.5× a discrete card for identical work. Any static floor
would either refuse a card that can genuinely fold a 60-token complex (CALCA is 60) or
pass one that cannot do 300. The benchmark README exists to stop exactly that inference.
So Boltz-2 is covered by (2) instead, which **measures** rather than predicts.

### How it was found out, and the two hollow tests

The trail started from the evidence file rather than the code: `rtx3090_sweep.jsonl` has
ESMFold2 succeeding at all four sizes and Boltz-2 at `peak_mib: 0, ok: false, rc: 2` at
all four — including 150 tokens. `rc=2` is `MissingTargetMSA`, so that arm never folded
anything and measures nothing about memory. The real Boltz-2 numbers are in a separate
file. Part AK §6's claim "Boltz-2 fails outright at 600 and 900 on 24 GB" happens to be
**true**, but reading it off the sweep would have been right by accident at 600 and 900
and wrong at 150 and 300, so both files are now named explicitly at the claim.

Mutation testing caught two tests that verified text instead of behaviour:

- **Commenting the preflight out** (`pass  # require_device_memory("esmfold2")`) left the
  ordering test green, because it asserted on `src.index(...)` and the substring was still
  there — inside the comment. Replaced with an AST check that the call exists inside
  `refold_batch` and precedes both the MSA fetch and the weight load by line number. Both
  variants (comment out; move it after the load) now fail.
- **Making a runner swallow the exception** (`raise partial` → `pass`) passed everything.
  Nothing tested the runner boundary — which is the only boundary production crosses,
  since `binder-compare refold-<engine>` calls the runner, not the script's `main()`. Now
  tested by injecting a stub module under the name the runner imports, so the real
  boundary runs with no torch, no JAX and no GPU. A second test asserts the rows that
  *did* fold are still published, because re-raising immediately strands them: the
  publish/absolutise step sits **after** the call in all three runners.

### The wiring check caught a fifth hole, in the installer

The standing rule on this branch is that a new thing must be live in all four modules, so
I went looking for the installer's view of it — and found the same defect one stage
earlier. `install_esmfold2` verified that `binder-compare refold-esmfold2 --help` parses
and then printed **"ESMFold2 refolder installation complete"** on a 12 GB box. The env is
genuinely correct; the engine simply cannot fold there. That is exactly what CLAUDE.md
records for BindCraft 1 and PXDesign, both of which "reported themselves healthy while
being unusable" on Spark.

Both installers now warn, naming the measured size and the floor. A warning and not a
refusal, because installing on a small box is legitimate — this box is the CI box. The
property worth keeping is that it **imports `ENGINE_MIN_DEVICE_MIB`** instead of repeating
`14248`: a second copy of a threshold is a second thing to forget. Verified live on this
machine: the probe returns rc=7 and `12288 14248`.

One thing I would not have trusted by reading: the warning branch reads `$?` inside an
`else`, which is fragile enough that I executed all three cases (rc=7 with output, rc=0,
rc=1 with no output) rather than reasoning about it. rc=1 matters — a probe that itself
breaks must not warn about memory, and the mutation that warned on any non-zero rc is
caught.

19 mutations, all caught. 1084 tests pass.

### D9 — the DO-NOT-ORDER row was de-duplication, not a verdict

The question was whether the veto's reason is recorded per row, and if so to tabulate the
vetoed designs against the composition and ProtParam filters. The answer makes the second
half not worth doing.

Checking all 34 below-divider rows by sequence against the ordered block: **30 are
exact-sequence duplicates of a design that *was* ordered**, 3 are near-duplicates at
97.2–98.6 % identity carrying an explicit `Duplicated, exclude` note, and **1** has no
near-match and no recorded reason. So 33 of 34 are bookkeeping — the same design listed
twice, once under its per-method code and once under its refold-ranked `BinderScout-NN`
code. A filter that "agreed" with that block would be agreeing with a spreadsheet's
duplicate removal, and the agreement rate would measure nothing. Recorded, not run.

**Two things fall out of it.** First, the ordered block is **exactly 114 rows on both
targets**, every row carries an outcome, there are **no blank `KD` cells** and **no
repeated sequence** inside either block — so the published n = 114 panels (CALCA 99/15,
CBG 10/104) are 114 distinct designs with 114 known outcomes, and the AUCs do not depend
on any judgement about the excluded rows. That is a stronger footing than the correction
claimed for itself.

Second, it explains the original error more precisely than "blanks were read as negatives".
Those rows are blank **because they are duplicates**, and each one's twin inside the 114
has a recorded outcome — on CALCA, twins among the tightest binders in the pool. That is
why the 11 outranked 81 % of the positives: they were not unmeasured designs that happened
to score well, they were *copies of the best measured designs*. Calling them "never
ordered" was itself imprecise, and Part AK now says "below the divider" and names what
they are.

### D4 — the default stays at 3, with the case against it written down

Three lines point at lowering `MIN_ENGINES_DEFAULT` to 2, and the strongest is not a
statistic: `--tool all` ships two engines (AF3's weights are gated), so a fresh install
fails the gate on every design. The other two are that `mean(boltz, esm)` out-scores the
3-engine mean on the benchmark, and that the 3-mean does not beat the best single engine
out of fold.

It stays at 3. Both statistical arguments are single-pool effects, and the drop-AF3 one
does not keep its sign across leave-one-target-out folds of its own pool — the same shape
as the four effects retracted the week of 2026-09-29. More to the point, **the case for
three engines is adversarial, not statistical**, so a benchmark AUC is the wrong
instrument: Mosaic games `boltz_iptm` by construction, so a 2-engine default of Boltz-2 +
ESMFold2 scores a Mosaic design with the engine that designed it plus one other. Half the
mean is a gamed number, and an out-of-fold AUC on a public pool cannot see that, because
that pool was not produced by our tools. The install friction is already handled loudly
rather than silently, and `--min-engines 2` is one flag away. What would settle it is a
labelled pool of *our own* designs — AK1's output, not its premise.

---

## 2026-10-04 (release) — v2.0.0 tagged on `v2.0.x`, fleet only

Tagged `v2.0.0` at `d6ed96b`, 158 commits past `v1.1.1`. Deliberately **not** merged to
`master` (still frozen at 1.0.3, now 194 commits behind) and **not** published. `v2.0.x`
remains the working branch.

### What I checked before saying "ready", and the two things that were not

The code was ready — 1084 tests, ruff and shellcheck clean, `binderscout --version` already
reporting 2.0.0 since 2026-09-28. The release was not, in two places that would both have
mattered only later:

**CHANGELOG had no `[2.0.0]` section.** Every 2.0 entry sat under `[Unreleased]`. A tag
pointing at an `[Unreleased]` changelog is specifically the artefact that makes a future
session unable to tell what shipped from what was merely in flight — and this repo has
already spent days on exactly that class of ambiguity. Cut it as
`## [2.0.0] — 2026-10-04`, with a heading that says what the release *is* rather than
listing 570 lines of entries unoriented: an **evaluation** release, not a feature release.

**CLAUDE.md described a pre-2.0 world.** It opened with *"`master` is frozen at 1.0.3…
Active work is **1.1.0** on the `v1.1.x` branch"* and did not mention `v2.0.x` anywhere. It
is the one document every session reads first, so for the whole of 2.0 the map handed to
each new session was two releases out of date. That is a worse defect than any single stale
fact inside it, because every other correction in this diary was made *from* that map.

Also stale, and found while fixing the above: `PLAN_2.0_CONCLUSION.md` §8's "how to confirm
this state" block told the reader to expect commit `5fb9d99` and `887 passed`, against a
HEAD 158 commits later and 1084 tests. A confirmation procedure that cannot pass is worse
than none, since it reads as a broken repo rather than a stale doc.

### The decision that was overridden, and why it is coherent

The status table said the tag **waits on §3's GPU-memory pass** (Stage 6). The operator
overrode that today. Recorded as an override rather than quietly deleted, because the
reasoning actually inverts in favour of shipping: Stage 6 goes last *because a reading taken
against an unfinished pipeline is stale by the time it ships* — which means the pipeline has
to ship before the reading is worth taking. Stage 6 is post-2.0.0 work.

### `behind=0` was a lie, and I nearly reported it

Asked whether the fleet was on the release, both reachable boxes answered
`behind_origin_v2.0.x=0` while sitting at visibly older commits — BM2 at `9176112`, BM5 at
`7557805`. The comparison was against each box's **local** `origin/v2.0.x` ref, which had not
been fetched since they were last updated, so each was measuring its distance from its own
past. Forcing `git fetch` first: BM2 is **9** commits behind, BM5 **5**.

This is the same shape as the defects D6 fixed an hour earlier — a check that reads a proxy
(a cached ref) for the quantity it claims to measure (distance from the remote), and answers
confidently. The tell was identical too: a number that was *too clean* for the circumstances.
Worth keeping as a rule: **a `behind` count without a preceding fetch is not a measurement.**

Two operational facts went into CLAUDE.md because both cost time today: the fleet checkout is
`~/dev/BindMaster`, the pre-rename directory name — four guessed paths failed before I looked
— and BM4 owns the rollout.

### One hazard attached to the rollout

**Do not pull on BM2 until the Chai-1 study finishes** (272/563 at the time of tagging, ~11 h
to go). It runs against the *editable* `binder_comparison` install in `~/dev/BindMaster`, so a
pull swaps the package under a live process. The study is Part AF — adopt or do not adopt a
fourth engine — so its answer lands after the tag and belongs to 2.1 either way.


## 2026-10-07 to 10-09 — AK1 ran, and most of what it taught was about the apparatus

Part AK1 was the plan's own verification step: refold every labelled design on the four targets
with a known sequence through all three engines, so the shipped ranking is measured on more data
than 563 designs. It ran: 2,033 designs x 3 engines = 6,099 folds, 50 chunks, four sites (Clara
x5 workers, BM5, BM2, BM4), no chunk failed. The ranking result is in plan §4.16. This entry is
about everything that had to be fixed before the run could be believed, because that is where
nearly all of the two days went.

### The default engine had been dead since the pin, and "upgrading" it made it worse

I started AK1 on BM5 through the Evaluator, deliberately, to exercise it. Boltz-2 and AF3
reproduced the stored benchmark (Spearman 0.994 and 0.981 on 20 designs). ESMFold2 died with
`TypeError: EsmFold2Model.__init__() got an unexpected keyword argument 'load_esmc'` and the
evaluator refused to report a partial pool, which is the 2.0 behaviour working as designed.

**Wrong turn.** Earlier I had upgraded `transformers` to 5.18 on BM4 and BM5 to satisfy the
installer's `>=5.16` floor and told the owner it fixed ESMFold2. It had not: it moved the failure
from "config cannot be parsed" to "model API does not match". I tested 5.16.1, 5.17.0 and 5.18.0
and none has `load_esmc`, so the cause could not be a 5.18 regression, and I had been proposing a
choice between "fix the loader" and "run two-engine" as though the engine had only ever been half
built.

The owner's correction reframed it: *ESMFold2 produced all our CALCA and CBG data, and the
benchmark.* It had worked. So what differed on a machine that still worked? BM2, untouched since
that data was made, had `transformers 4.57.6` whose `direct_url.json` named
`github.com/Biohub/transformers` at commit `3a8956fb`. The engine runs on a fork. PyPI's 5.x
ships a same-named class without the method. The 2026-09-27 reasoning that `8fc3ff471022`
"cannot be loaded by any installable transformers" was true and irrelevant. Mirroring the fork
(pure Python, copied between architectures) and pairing it with `8fc3ff471022` gave iPTM 0.8875
against a stored 0.8925 on the control design. pip had been saying it all along:
`esm 3.3.0 requires transformers @ git+...Biohub/transformers.git@3a8956fb`.

### Three failures that looked like one

BM5 failed Boltz-2 on nipah's longest design three times on the same 53.75 GiB allocation, under
a "48G" cap, a "70G" run and an "85G" attempt. I read the first as "48G is too small" and raised it.
The log line that settled it was `XLA mem fraction 0.197 ... target 24 GiB`, printed *after* I had
passed 85G: `--gpu-cap-boltz2` sets the MPS driver limit and never the JAX pool, which
`refold_boltz2.py` hardcodes at 24 GiB. The first and second failures were the same pool. The
85 GiB attempt then died differently, with SIGKILL (rc 137), and that was `gb10-guard`: `MemFree`
fell to 15.9 GiB against its 24 GiB floor, and it kills **unregistered** jobs first ("launch it via
gpurun so it can be reasoned about"). `gpurun --max` had advertised 91 GiB. A job launched through
`gpurun --cap 70` registered a budget and left 33 GiB. The 70 GiB run then failed on the real limit:
Boltz-2 on GB10 needs about 1.5x a discrete card, and the same designs fit a 70 GiB pool on an H200.
So BM5 took the short end of nipah and Clara the long. Three runs, three causes, one symptom.

### The phantom resume

The first clean-looking evaluator run on BM5 printed `Resuming - skipping 86 already-completed
binders` into a brand-new output directory, folded nothing, and ended with
`[Boltz-2] ok -- 260 new row(s)`. `engine_boltz2` was the only engine without `--output-dir`; its
default is relative to the working directory, so `--resume` read another run's CSV and the row
guard (non-empty iPTM) counted someone else's 260 rows as this run's. The 2.0 guard catches an
engine that writes nothing and cannot catch one that publishes something else. Found only because
I used the Evaluator for the job instead of calling the engines directly.

### Where the time went: distinct lengths, not designs

Boltz-2 took 25 minutes on egfr c01 and 101 on c02, both 40 designs of similar size. c01 has one
distinct length and c02 thirteen. JAX recompiles per input shape, about 6 minutes each on an H200
against 0.6 to fold. I had projected from the first chunk and was wrong by a factor of two for
the next; the corrected estimate came from three measured chunks.

### Clara: a path alias

All three first Clara workers died in 3 seconds on `No module named 'binder_comparison'`. The pre-warm
step discards its own output, so the error was invisible; running its command by hand showed
`conda run -n binder-eval python` resolving to the **base** interpreter. Conda reports its base as
its filesystem's canonical mount path and strips only that spelling from PATH; the shorter
home-directory alias I had put on PATH stayed, and won. Canonical spelling fixed it for all four envs. No GPU time was lost.

### The AF3 patch I applied by hand, and what it cost to leave it there

AF3 rounds confidence scores to two decimals (81 distinct iPTM values over 563 designs). I patched
`site-packages` on four machines. Then I rebuilt BM5's AF3 to the pinned commit and the patch
vanished, exactly as a reinstall would. It is now `install/patches/af3_full_precision.py`, run by
both installers and checked by `--verify`; I confirmed the new tests go red when the call is
turned into a heredoc and when the verify branch is removed. The same pass found that BM5's AF3
was the April v3.0.2 build while the pin is July's `fd39d2c5`, and that its ESMFold2 env had
xformers.

### Auditing my own result, which found that I had overstated it

I had written that the three-engine mean "has the best macro AUC and is a robust choice" and that
AF3 "carries no signal on egfr". Five independent auditors, told to find what was wrong and given
no credit for confirming, rebuilt everything from raw files. The data held (all 16 AUCs and the
egfr bootstrap interval reproduced); my claims did not. The mean's +0.021 over the best single
engine is within noise and reverses under n-weighting; AF3's egfr result is confounded by binder
collapse (352 of 826 designs). I also generalised "refolding noise is about +-0.1 AUC" from pd-l1
(Boltz-2 0.717 to 0.820) and il7r then showed under 0.01. Both are corrected in plan §4.16 and
§4.18. The audit also confirmed one stale label and 215 unexpressed designs scored as negatives.

### Small mistakes, listed because each cost time

* `pkill -f` with a pattern that also matched my own ssh command line killed my session, not the
  job. The repo's own guard script warns about exactly this in a comment I had not re-read.
* I let GPU runs write to muni-disk, which is transfer and backup, not a working disk; moved them
  to local NVMe and kept the first output as evidence.
* A dedupe in my monitor lost its state inside a pipe subshell and replayed old failures as new
  ones every cycle; it also ended one watch window as "silence", when my filter had no heartbeat.
* I read an archive stream's start time as 30 minutes ago when it was 3.
* A `$HOME` in a single-quoted deploy argument created a literal directory named `$HOME` inside the
  repo. Moved and removed; the tree stayed clean.

### Two external sets, and why neither is the next benchmark

**OpenBind** (small molecules against one viral protease) was prepared and then dropped on the
owner's clarification that the goal is designing proteins that bind a small molecule, the inverse
direction. What carried over: the affinity task reproduced the June numbers (molecular weight 0.486,
Boltz-2 0.401); co-folding pose success at top-1 is only 5.7% (Boltz-2) to 26% (Protenix), so a
designed protein-ligand complex cannot be trusted on ipTM alone; and AF3 accepts a SMILES ligand in
the JSON it already builds (two hand-built complexes folded). Public data for the real task is tiny
(17 designs / 2 binders; 26 / 4).

**GuideFlip** (de novo binders to flexible targets): the repository has no experimental data, only
the preprint's supplementary tables, which I parsed (88 designs, 71 measured, 30 binders). Its own
labelling is careful and I kept it: designs with no assay record are excluded, not negatives. The
nanobody arm folded in 25 minutes and was uninformative: Boltz-2 gave every design 0.90 to 0.94,
ESMFold2 0.85 to 0.90, AF3 almost every design 0.11 to 0.20, identically for binders and
non-binders (5 non-binders). The tested designs were pre-filtered on structure-prediction
confidence, so there is no spread left, and the target is an agonist-bound conformation that a
protein-only fold cannot express. The owner set it aside as BinderScout nano work.

### Where it stands

All sites were on the tag on 2026-10-09; `v2.0.x` is one commit ahead (the installer patch) and
the changelog now describes what the tag contains. The tag was re-cut five times after release and
should be moved once more, then frozen: further fixes belong in a patch version, because "v2.0.0"
no longer names one thing in anyone's notes. In flight when this was written: the Clara rerun of
nipah c24-c26 (the clean test of the BM5 site effect), the GuideFlip alpha-synuclein and RBX1
arms, and the muni-disk archive, which has not been read back.

### 2026-10-09 (late) — the Clara rerun, and the tag

The 85 nipah designs refolded on Clara agree with BM5 closely for ESMFold2 (mean |delta iPTM| 0.022), less for AF3 (0.068) and least for Boltz-2 (0.108), which ran identical software at both sites. So the spread is mostly run-to-run noise, and the AF3 build difference is not distinguishable from it. No same-site repeat was run, so that is an inference. Recorded in plan 4.13. The `v2.0.0` tag was re-cut once more to include the AF3 installer patch and these records; later fixes go into `v2.0.1`.
