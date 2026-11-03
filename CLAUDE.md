# CLAUDE.md — BinderScout / BoltzGen Pipeline

## Overview

BinderScout is a unified toolkit for GPU-accelerated **protein binder design**. It wraps nine independent design tools (BindCraft, BindCraft 2, BoltzGen, Mosaic, PXDesign, Proteina-Complexa, Protein-Hunter, RFD3, RFD4-Proteina) behind a single CLI (`binderscout`) that handles installation, interactive configuration, execution, and cross-tool evaluation of designed binders. BindCraft 2 is a rewrite, not a new version of BindCraft: it does not replace it, and the two coexist as separate tools in separate environments.

**Current status: `v2.0.2`, tagged 2026-10-27 on the `v2.0.x` branch** (2.0.0 was tagged
2026-10-04; 2.0.1 on 10-15). 2.0.2 adds RFD4-Proteina as the ninth tool and purges the
internal lab material from the tree *and* the published history — **every commit SHA and
tag below `v2.0.2` changed on 2026-10-27, so an older clone must be re-cloned, not pulled.**
The tags `v2.0.0`–`v2.0.2` and the `v2.0.x` branch are on the public remote; `v2.0.3` is in
preparation. The line is deliberately **not merged to `master`**. `v2.0.x` is the working
branch: all work on these machines lands there, never on `master`.

**`master` is NOT frozen at 1.0.3 — that claim is stale (corrected 2026-10-29).** Master is a
**separate line**: `v2.0.x` is not an ancestor of it (`git merge-base --is-ancestor v2.0.x
master` is false). The two share exactly one commit, `602345a` (`v1.0.3`), and have diverged
since, with paths that differ too (master still has `bindmaster.py`, this line `binderscout.py`).
As of 2026-10-29 master is at **`v1.2.1`** (1.0.6 → 1.0.7 → 1.0.8 → 1.2.0 → 1.2.1 all landed
that day; `v1.2.0` added `binder-compare filter-tmprot`, `v1.0.8` added the refold-CSV
target-mismatch guard).
**Consequence for porting: a fix cannot be cherry-picked between the lines** — diff the trees and
re-apply. `v1.1.x` was retired to the tag `archive/v1.1.x` and no longer exists as a branch.
Of the three master fixes once missing here, two have been ported: `_refuse_mismatched_targets`
(commit `a3e775c`) and `refolding/resume.py`, the sequence-keyed resume (commit `6791f0c`, which
also keeps this line's score gate). `filter-tmprot` is still absent from `v2.0.x`.

**Local-only branch worth knowing about:** `feat/d1-ligand-target`, 30 commits off `v2.0.2`,
never merged and not on any remote. It carries the ligand-target support (`core/ligand.py`) and —
more importantly for any specificity campaign — a counter-screen and specificity-margin framework
(`comparison/counterscreen.py`, `refolding/counterscreen_runner.py`,
`comparison/design_objective.py`) plus the hapten campaign's measured limits on what a margin can
deliver. Read it before building a counter-screen from scratch.

**What 2.0 is.** An *evaluation* release, not a feature release. The `v2.0.0` tag shipped no new
design tool (the eighth, BindCraft 2, arrived in 1.1.0) and the same three-engine refold pipeline
— Boltz-2 + AF3 + ESMFold2. **RFD4-Proteina, the ninth tool, was added to the branch on
2026-10-27, after the tag** — it is opt-in, designed and run on x86_64 (installable on aarch64 since 2026-10-29, not yet run there); see its gotchas section. What changed is what the pipeline is allowed to claim:

- **One ranking, and no way to choose another** (Part U): cross-engine gate then
  `consensus_iptm_mean`, one `rank` column. `two_stage_rank`, `adaptyv_rank`, `consensus_rank`,
  `active_rank`, `passes_max_screen`, `--rank-by` and `--screen-metric` are gone with **no
  compatibility shim** — that is the breaking change and the reason for the major version.
- **Silent success is now a failure.** A run that produced nothing, or produced blanks, used to
  exit 0. Each of those paths now refuses and names what is wrong — see the ESMFold2 device
  floor, `PartialRefoldFailure` (exit 3), the AF3 bucket floor, and `evaluate.sh` counting
  *scored* rows rather than rows.
- **Claims are separated from evidence.** Negative results are recorded as loudly as positive
  ones; four single-pool effects were retracted rather than shipped; Cao 2022 was withdrawn as a
  benchmark on label censoring.

**Where 2.0's own records live** — read these before re-deriving anything:
`DIARY_2.0.md` (the 2.0 chapter; `REPO_DIARY.md` is the *historical* diary and is not where 2.0 work goes) — **both diaries live only on the lab's private share, never in this repo (they hold sensitive data)**, `docs/PLAN_2.0_CONCLUSION.md` (§3 remaining work, **§4 findings that must
not be relearned**, §5 decisions), `docs/PLAN_2.0_PART_RESULTS.md` (per-part verdicts, including
the parts that were deliberately *not* built), and `docs/PLAN_2.0_PART_AK_verify_the_rank.md`.

**Known not-done, by decision:** the **GPU-memory pass goes last**, because a reading taken
against an unfinished pipeline is stale by the time it ships. Stages 1–4 of the plan are feature
work, not shipping blockers.

**Engine line-up** (unchanged from 1.1 and carried forward): Evaluator AF2 refolding removed
(Part I), AF3 v3.0.2 as the canonical 2nd refolding engine (Part K — **runs on 24 GB consumer
GPUs for our size regime**; the old ">=100 GB" figure was a preallocation artifact, see the AF3
memory note below), Protenix refolding removed (Part J reverted — AF3 covers the 2nd-engine
role), Protein-Hunter (Part L) and RFD3 (Part M) installed and configurable. Affinity-from-
structure-confidence closed as a negative result (Part N). SoluProt is part of `--tool all` and
both platforms build USEARCH v12 from source. Proteina-Complexa installs and **runs** on aarch64
as of 2026-10-04 (opt-in; throughput still unmeasured — see the aarch64 entry, which has been
wrong three times). **Both BindCraft 1 and PXDesign run on the GPU on DGX Spark** — each
previously reported itself healthy while being unusable there.

**Fleet note.** On the multi-machine fleet the checkout directory is machine-local: some boxes
still use `~/dev/BindMaster` (the pre-rename name), others `~/dev/BinderScout`. Resolve it
rather than naming one. One x86_64 machine with a discrete GPU orchestrates and owns the rollout.

**Repository:** `github.com/damborik22/BinderScout` (the working-tree directory may be checked out as `BinderScout`; the CLI command and Python package are both `binderscout`. The old `damborik22/BinderScout` URL redirects.)

---

## Behavioral Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. These apply on top of the project-specific instructions below.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### Think before coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity first

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

### Goal-driven execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Architecture

### Pipeline flow

```
Target structure (.pdb / .mmcif)
  → Configurator wizard (interactive, generates configs + run scripts)
    → Design tools run in sequence (configurable per run):
       Mosaic               (JAX + Boltz-2 hallucination)
       BoltzGen             (Boltz-1 diffusion)
       BindCraft            (AF2 + MPNN + PyRosetta)
       BindCraft 2          (AF2 hallucination + MPNN, JAX only — no PyRosetta; ranks on i_pDAE)
       PXDesign             (Protenix + MPNN + AF2 eval)
       Proteina-Complexa    (NVIDIA flow matching + ITO)
       Protein-Hunter       (Boltz-2 / Chai-1; 6 modalities: protein / cyclic / ligand CCD / ligand SMILES / DNA / RNA)
       RFD3                 (RosettaCommons foundry diffusion + ProteinMPNN)
       RFD4-Proteina        (IPD x NVIDIA latent-reasoning diffusion; backbone AND sequence
                             in one pass, no MPNN step; opt-in; run on x86_64,
                             installable but not yet run on aarch64)
    → Evaluator (canonical pipeline = Boltz-2 + AF3 + ESMFold2; SoluProt optional screen):
       1. Extract sequences from all tool outputs (one extractor per tool)
       1.5. (optional) Screen with SoluProt 1.0 (binder-eval-soluprot env)     [live, x86 + aarch64; LABEL ONLY — scores every design, never drops one]
       2. Refold with Boltz-2 (Mosaic venv)                                    [live, all platforms]
       3. Refold with AlphaFold 3 v3.0.2 (binder-eval-af3 env)                 [live, canonical 2nd engine — runs on 24 GB GPUs; ~4.4 GB peak for a 260–390-token complex]
       4. Refold with ESMFold2 (binder-eval-esmfold2 env)                      [live, DEFAULT engine — installed by --tool all; auto-detected by evaluate.sh; feeds consensus_iptm + autosize gate]
       5. Rank by cross-engine iPTM (≥3-engine gate → `consensus_iptm_mean`; `--min-engines 2` to relax); generate HTML + CSV report
```

### Directory layout

```
BinderScout/
├── binderscout.py              ← unified CLI dispatcher (system Python, stdlib only)
├── tui/
│   └── app.py                 ← interactive curses menu + numbered fallback (`binderscout` no-args)
├── install/
│   ├── install.sh             ← x86_64 installer (master branch)
│   └── install_aarch.sh       ← aarch64 / DGX Spark installer
├── conda/                     ← LOCAL Miniforge3 (standalone mode, gitignored)
├── bin/                       ← LOCAL shortcuts (standalone mode, gitignored)
├── configurator/
│   └── configurator.py        ← setup wizard (steps 1–7, ~80 prompts, 3.7k lines)
│                                 + `--config JSON` headless replay
├── evaluator_legacy/
│   └── evaluator.py           ← LEGACY single-file evaluator (~955 lines). Retired:
│                                 `binderscout evaluate` now passes through to binder-compare.
├── Evaluator/                 ← bundled full evaluation pipeline package
│   ├── binder_comparison/     ← core Python package (extractors, refolding, scoring, viz)
│   ├── scripts/               ← standalone refold scripts (refold_boltz2.py, refold_af3.py, refold_esmfold2.py)
│   ├── evaluate.sh            ← shell orchestrator (extract → refold-boltz2 → refold-af3 → refold-esmfold2 → report)
│   ├── envs/                  ← conda env specs (binder-eval.yml, binder-eval-af3.yml [Spark / H200 / big-VRAM])
│   ├── docs/                  ← pipeline_reference.md (metrics, known issues)
│   └── pyproject.toml         ← package: "binder-comparison" v0.1.0
├── binderscout_examples/       ← canonical run-script templates
│   ├── hallucinate_binderscout.py     ← Mosaic template (copied into Mosaic/ on install)
│   ├── run_rfd3.sh.template          ← RFD3 two-stage (backbone diffusion + MPNN)
│   ├── run_protein_hunter.sh.template ← Protein-Hunter Boltz-2 hallucination
│   └── run_bindcraft2.sh.template    ← BindCraft 2 layered campaign JSON + design run
├── tools/
│   └── aarch64/               ← pre-built ARM64 binaries (DAlphaBall, dssp)
├── .github/workflows/ci.yml  ← shellcheck + ruff + pytest + Docker build
├── test_env.sh                ← Docker test environment launcher
├── Dockerfile.test            ← CUDA 12.4, Ubuntu 22.04, Miniforge
├── docker-entrypoint.sh       ← container init (conda, HOME setup)
├── ruff.toml                  ← Python linting/formatting config
├── STAGES.md                  ← implementation milestones (Parts A–H; later parts live in CHANGELOG)
├── CONTRIBUTING.md            ← dev setup, PR conventions
├── CHANGELOG.md               ← Keep a Changelog format
└── LICENSE                    ← MIT
```

**Gitignored (created at runtime):**
- `BindCraft/`, `BoltzGen/`, `Mosaic/`, `PXDesign/`, `Proteina-Complexa/`, `Protein-Hunter/` — cloned by installer
- `RFD4-Proteina/` — cloned by the installer at a pinned commit, with its uv venv inside it; the
  checkout is the installation, so it is gitignored like `BindCraft2/`. Weights land under
  `weights/rfd4/` (used as `HF_HOME`), already covered by the `weights/` rule
- `BindCraft2/` — *staged*, not vendored: BindCraft 2 is public (https://github.com/PacesaLab/BindCraft2, released September 2026) but source-available under its own licence (BindCraft2 Source-Available, hosting-restricted), not this repo's MIT, so no file of it is committed here — the same posture as the AF3 weights. The installer unpacks it from `--bc2-source` and installs it **editable**, so the checkout is the installation — moving or deleting it breaks the `bindcraft` command
- `weights/foundry/` — RFD3 / ProteinMPNN checkpoints fetched by `foundry install` (no clone dir; `rc-foundry` is pip-installed into `binderscout_rfd3`)
- `runs/` — generated experiment directories
- `install.log`, `install_aarch.log` — installer output (both STREAM now: `tail -f` works
  while a step is running, and a non-TTY run prints a heartbeat every two minutes)
- `.install_state/` — one file per tool, written by the installer only after that tool's
  install returned 0. A conda env DIRECTORY is not an install (conda creates it when it
  starts solving and leaves it behind when the solve fails), so `detect_installs()` and
  the TUI require a marker **and** their own probe. Enforcement switches on only once at
  least one marker exists, so every env that predates this keeps working untouched
- `refold_boltz2/` — intermediate refolding outputs

### Environment isolation (critical)

Each tool runs in its own isolated environment. **Never mix packages across environments.**

| Environment | Tool | Python | Manager | Purpose |
|---|---|---|---|---|
| `BindCraft` | BindCraft | 3.10 | conda | AF2 + MPNN + PyRosetta binder design |
| `BindCraft2/.venv` | BindCraft 2 | >=3.12 | **uv** | AF2 hallucination + MPNN, JAX only — **no conda env and no PyRosetta**. Installed editable into a venv beside its own checkout, so `BindCraft2/.venv/bin/python` is the one detection marker |
| `BoltzGen` | BoltzGen | 3.12 | conda | Boltz-1 diffusion-based generation |
| `Mosaic/.venv` | Mosaic | 3.12 | uv | JAX + Boltz-2 hallucination |
| `binderscout_pxdesign` | PXDesign | 3.11 | conda | Protenix-based binder design + eval (PXDesign's own internal Protenix; not a refold engine) |
| `Proteina-Complexa/.venv` | Proteina-Complexa | 3.12 | uv | Flow matching + test-time compute binder design |
| `binderscout_protein_hunter` | Protein-Hunter | 3.10 | conda | Boltz-2 / Chai-1 hallucination, 6 modalities |
| `binderscout_rfd3` | RFD3 (`rc-foundry`) | 3.12 | conda | RosettaCommons foundry diffusion + ProteinMPNN |
| `RFD4-Proteina/.venv` | RFD4-Proteina | 3.12 | **uv** | IPD × NVIDIA latent-reasoning diffusion. Run on **x86_64**; installable on aarch64 since 2026-10-29 (resolve + install on one GB10, no design campaign yet). Upstream's own `scripts/setup_venv.sh` exits 1 on any other arch, but our installers never call it: they build the venv with `uv` directly. No conda env; the checkout IS the installation, so moving or deleting it breaks `rfd4-generate`. Opt-in (`--tool rfd4`), **not** in `--tool all` |
| `binder-eval` | Evaluator | 3.10 | conda | Sequence extraction + reporting |
| `binder-eval-af3` | AF3 refolder | 3.10 | conda | AlphaFold 3 v3.0.2 refolding — **canonical 2nd engine** (Part K; live on Spark / H200 **and on 24 GB consumer GPUs**, checked on three x86_64 machines) |
| `binder-eval-esmfold2` | ESMFold2 refolder | 3.10 | conda | **Default refold engine** (biohub). **Measured working: a 50-design pool refolded 50/50 on a 24 GB RTX 3090 (iptm 0.671–0.921, median 0.863), plus a 299-token monomer in 8.3 s and a 598-token dimer in 59.6 s.** ESMC-6B loads bf16 by default (~11.8 GiB resident from a 23.66 GiB fp32 checkpoint), which is why 24 GB suffices and a 12 GB card cannot run it at any size — the dev box was the constraint, never the engine. **That 11.8 GiB is the resident weights, NOT the run: a refold of a ~300-token complex held 18.86 GiB on a 3090 (measured 2026-10-31).** Read it as "ESMFold2 wants the whole card", not "11.8 of 24, so something else fits" — co-scheduling Boltz-2 (4.63 GiB) beside it filled the card and every binder from #12 on raised CUDA OOM. Worse, the run then wrote a full-length CSV with 8 of 100 scored and **exited 0**; `--resume` repairs it (it keys on a non-empty `iptm`), but nothing refuses. **Also: the biohub transformers fork is NOT on every box.** Two of the three x86_64 machines checked have `ESMFold2Model` with `load_esmc` under `transformers.models.esmfold2.modeling_esmfold2`; the third has PyPI transformers at the same version string (4.57.6) and no `esmfold2` module at all, so this engine cannot run there. `hasattr(transformers, "ESMFold2Model")` is the wrong probe — the class is in that submodule. Installed by `--tool all`, auto-detected by `evaluate.sh`; lightweight, no gated weights; feeds `consensus_iptm` + autosize gate |
| `binder-eval-soluprot` | SoluProt screen | 3.7 | conda | Sequence-only *E. coli* solubility filter (Hon et al. 2021); x86 + aarch64 (aarch64 builds scikit-learn 0.20.4 + USEARCH v12 from source, uses the `--no_tmhmm` model). NOT a refold engine and NOT a filter; runs before refolding and labels every design with `soluprot_score` / `soluprot_passes`. `--soluprot-filter` was removed 2026-09-28 and now exits 1 |

The `binderscout.py` CLI dispatcher uses `os.execv()` to launch sub-commands in their correct environment — `install` runs in bash, `configure` runs in system Python, and `evaluate` is a **passthrough to the `binder-compare` CLI** run in the `binder-eval` conda env (`binderscout evaluate <binder-compare args>`). The legacy single-file evaluator (`evaluator_legacy/evaluator.py`, formerly run in the Mosaic `.venv`) is retired and no longer dispatched.

In **standalone mode** (`--standalone` or auto-detected), all conda environments live under `BinderScout/conda/envs/` instead of the system conda's envs directory. This requires zero system permissions.

### Machines and platforms

There is **no `aarch64` branch**: one tree, two installers. Branches are release lines, not platforms.

| Platform | Installer | CUDA default |
|---|---|---|
| x86_64 Linux + NVIDIA GPU | `install/install.sh` | 12.4 |
| NVIDIA DGX Spark / Grace-Hopper (GB10 Blackwell), aarch64 | `install/install_aarch.sh` | 13.0 |

**aarch64 specifics:**
- BindCraft ARM64 binaries (`DAlphaBall.gcc`, `dssp`) bundled in `tools/aarch64/`
- **BindCraft 1 RUNS on aarch64 — but only on jax 0.6.2, and this entry has been wrong in both directions.** It *did* work here before: `runs/2VDY-Spark-BindCraft/` holds a completed May 2026 campaign — 27 trajectories, 211 MPNN designs, 4 accepted, zero LLVM errors in 7,397 log lines. But it was running at **1–2.5 h per trajectory**, because the configurator emitted `export JAX_PLATFORMS=cpu` for aarch64 — it was on the CPU by construction. Take that out on the stock 0.4.34 pin and AF2 aborts at compile:
  `Unsupported conversion from bf16 to f16` / `LLVM ERROR: Unsupported rounding mode for conversion.`
  Root cause: **jaxlib 0.4.34's bundled LLVM knows sm_20..sm_90a only** (checked in the shipped `.so`); GB10 reports **cc 12.1**, so LLVM falls back to a subtarget with no bf16, and ColabDesign runs AF2 in bf16 by default (`colabdesign/af/model.py:35`). The model contains no f16 anywhere — XLA's lowering introduces it. Measured on a 120aa target + 40aa binder, AF2 fwd+bwd:

  | | steady state | notes |
  |---|---|---|
  | 0.4.34 + `use_bfloat16=False` | 5.40 s/iter | works, but fp32 **doubles** memory — a 389-res target then needs a 21.4 GB allocation |
  | **0.6.2 + bf16 left on** | **2.39 s/iter** | 2.3x faster, half the memory, no ColabDesign patch — **what the installer now does** |

  **"ColabDesign pins us to jax 0.4.x" was wrong.** `jax.lib.xla_bridge.get_backend` is still present (deprecated) in 0.6.2, and ColabDesign calls it in exactly one place — `shared/utils.py:9`, inside `clear_mem()`, already behind a `hasattr` guard. 0.6.2 is the first jaxlib that knows sm_121 *and* still ships a cp310 wheel, so the py3.10 env and its conda PyRosetta are untouched; 0.5.3 tops out at sm_120 and is not enough. **This paragraph used to end "The same reasoning does NOT rescue Proteina-Complexa — its blocker is the CPU-bound AF2 reward, a different problem." That is circular, and checking it (2026-09-25) shows why.** PC's AF2 reward *is* ColabDesign — the same library, verified in its venv — so "the CPU-bound AF2 reward" is not a different problem, it is this one. The difference is only the pin: BindCraft here runs `colabdesign 1.1.3` on `jax 0.6.0`, PC runs `colabdesign 1.1.1.1` on **`jax 0.4.29`**, which predates sm_121 exactly as 0.4.34 did. So PC's reward is on the CPU for the same reason BindCraft's was, and the same upgrade is the obvious candidate. **This does NOT mean PC is rescued** — nobody has run it: the upgrade is untested against PC's own venv (a different ColabDesign version, uv-managed, with its own resolver constraints), and it needs aarch64 hardware to try. What is established is only that the *stated* reason for the deprecation does not hold, so the "1.7 years" figure and the "reopens only if a CUDA jaxlib appears" condition both rest on a premise its sibling tool has already disproved.

  Caveat on the history: the env was byte-identical to May (untouched since 2026-03-07) and both runs used multimer, so why it compiled then is **unexplained**. The only changed variable is the driver (580.95.05 → 580.142 on 2026-06-30, now 580.159.03). Don't repeat that as fact.

- **BindCraft 2: VALIDATED on GB10/sm_121, but opt-in and not in `--tool all`** — and the reason is throughput, not capability. `jax-cuda13` takes the GPU, `biotraj` (the only source build in its tree) compiles, and a campaign runs to completion with the two guard settings `run_bindcraft2.sh` injects (see the runtime gotchas below). It is kept out of `all` because a trajectory costs ~7.4 min here against ~90 s on a GH200. That still makes it the **only AF2-hallucination designer that runs on Spark at all** — BindCraft 1 cannot install here (no aarch64 jaxlib CUDA conda packages), so on this platform the two tools are not interchangeable. Install with `bash install/install_aarch.sh --tool bindcraft2 --bc2-source <zip|dir>`
- BoltzGen: PyTorch from the **cu130 wheel index**, pinned (`torch==2.10.0+cu130`). Plain PyPI torch is **CPU-only** on aarch64 for the versions we pin — an earlier note here said the opposite, and acting on it silently replaced a working CUDA build with a CPU one. Verified on a GB10: the live `BoltzGen` env is `torch 2.10.0+cu130` with `sm_120`/`compute_120` in its arch list.
- Mosaic: `esmj` excluded (no aarch64 wheel); `torchtext` also may fail
- RFD3: installable on aarch64 via `install/install_aarch.sh --tool rfd3` (no DGL dependency; pip-installs cleanly). **Opt-in, not in `--tool all`, because it is unvalidated on aarch64 hardware** — validate on Spark and promote it once confirmed.
- **Protein-Hunter: now installable on aarch64** (`bash install/install_aarch.sh --tool protein-hunter`) — opt-in, not in `--tool all`, because it is new here. Verified on a GB10: PyRosetta imports, `boltz_ph` imports, and a 2-cycle design run completes on the GPU (`Using device: cuda:0`, torch 2.14.0+cu130 on GB10) with ipTM climbing 0.51 → 0.82 across cycles. Three platform deltas: PyRosetta comes from the graylab **conda** channel and must be in the env-creation solve (added afterwards it drags python 3.10.21 back to 3.10.14 over a zlib pin and orphans every pip-built C extension); torch uses the cu130 index; and **Chai-1 is skipped**, which costs nothing, since the Boltz-2 entrypoint `boltz_ph/design.py` never imports `chai_lab`. `gemmi 0.6.5` has no aarch64 wheel and builds from sdist, so a C/C++ toolchain is required. The old refusal said "PyRosetta publishes no aarch64 wheels" — **that was wrong**. PyRosetta does run here: a GB10's `BindCraft` env imports it, runs `pyrosetta.init()` and scores a pose, from the native aarch64 *conda* build (`PyRosetta4.conda.aarch64...`, graylab JHU channel) that `install/install_aarch.sh` already installs. "No aarch64 wheels" was only ever true of PyPI. What is actually unresolved: Protein-Hunter's own installer takes the **wheel** path (`pyrosetta-installer` via pip) and nobody has tried repointing it at the conda build here, and its vendored Boltz-2 + Chai-1 stack has never been built on aarch64. So this is **untested, not blocked** — and do not upgrade "PyRosetta works" into "Protein-Hunter installs". Note also that a `binderscout_protein_hunter` env existed on one GB10 but was an empty ~198 MB shell: the env name is not evidence of an install
- **Proteina-Complexa on aarch64: INSTALLABLE since 2026-09-26, opt-in, and unvalidated end to end.** `bash install/install_aarch.sh --tool proteina-complexa`. It is NOT in `--tool all`.
  The history matters, because the reason was wrong twice. It was deprecated 2026-07-29 for "no CUDA `jaxlib` exists for aarch64" — **disproved 09-18**: the CUDA plugin exists and gives `backend: gpu` on jax 0.4.29. The real blocker, identified then, was that **jax 0.4.x cannot compile an AF2-class graph for sm_121** (`LLVM ERROR: Unsupported rounding mode for conversion`), reproduced in two environments. That blocker is now gone twice over on this hardware — BindCraft 1 runs AF2 on the GPU on `jax[cuda12]==0.6.2`, BindCraft 2 on `jax-cuda13 0.11.1` — and PC's AF2 reward **is the same ColabDesign**, so it inherits the fix. The installer therefore uses 0.6.2 rather than the manual Blackwell port's `jax[cpu]==0.4.29`, and applies no CPU-fallback patch.
  **RETRACTED 2026-10-04 — the install is fixed, throughput is STILL UNMEASURED.** A first
  attempt reported ~12.5 s per AF2 call and lifted the deprecation. That was wrong: **every reward
  in both the GPU run and the CPU control was 0.0 and AF2 never loaded** (`Mean reward: 0.0000`,
  and the two runs produced byte-identical sequences). The CPU control caught it only because it
  came back identical — 112.31 s vs 111.52 s — so the number was MCTS-with-a-null-reward, not an
  AF2 cost. Wall-clock was a proxy for "AF2 ran" and the real interface went unchecked.
  **Established:** six installer defects fixed and PC runs end to end on aarch64 for the first
  time (single-pass generation 39.9 s, exit 0, `jax 0.6.2` on `gpu`, bf16 compiles).
  **Not established:** any throughput claim; the 2026-07-29 arithmetic stands until an AF2 call is
  actually timed. **Root cause found the same day, and it refutes this entry's own premise:** the weights are
  fine (`AF2RewardModel` constructs in 3.0 s, `Found 5 model parameters`, `device=cuda:0`).
  Calling `score()` directly raises `jax.tree_map was removed in JAX v0.6.0`, then PC's
  `_cleanup_jax_state()` raises again on `jax.clear_backends`, masking it — and the pipeline
  swallows both into `reward = 0.0`. **PC's AF2 reward is NOT "the same ColabDesign" BindCraft
  runs:** BindCraft's is **1.1.3** with **0** `jax.tree_map` sites, PC vendors **1.1.1.1** with
  **93 across 23 files**. This file recorded both version numbers and concluded PC "inherits the
  fix"; the version gap *is* the blocker. PC is pinched from both sides — 0.4.x cannot compile
  AF2 for sm_121, 0.6.2 removed what 1.1.1.1 calls, and 0.5.3 tops out at sm_120.
  **Tractable fix:** PC vendors 1.1.1.1 only for a `device` kwarg, which is **4 call sites in 2
  files** (`af/model.py:35,143`, `shared/model.py:163,167`) — port those onto 1.1.3 rather than
  migrate 93 call sites. Plus PC's own 2 `jax.tree_map` uses and its `clear_backends` call.

  **The withdrawn claim, kept legible:** ~~throughput is fine and the deprecation is LIFTED.~~ Same box, same
  config (`search_binder_local_pipeline`, `33_TrkA`), `mcts n_simulations=2`, via
  `tools/gpurun --cap 40`: single-pass with no reward **39.9 s**; MCTS with **9 AF2 reward
  evaluations 112.3 s → ~12.5 s per AF2 call**, against the deprecation's ~320 s. Re-costed, the
  3,300-call production recipe is **~11.5 h per 100-design replicate** (not 12.2 days) and
  PC-v3's 50 replicates ~24 days (not 1.7 years) — so GB10 is ~5x an H200, not 130x. **Spark is a
  usable PC node; "run PC on x86" is no longer the recommendation.** It took five installer fixes
  to get there, none of them hardware: `uv venv --clear`, the editable install's
  `--index-strategy`, the bf16 smoke test running uncapped (jax reserved ~91 GiB of the unified
  pool and the OOM killer took it, reported as an XLA/LLVM failure), missing `openbabel` (which
  `atomworks` imports unconditionally), and the installer shadowing PC's **vendored** ColabDesign
  fork — the only one accepting the `device=` kwarg PC's reward passes — with upstream. Caveats:
  n=1, the 112.3 s includes a cold compile, and the archived CPU baselines were on a different
  target. Full evidence and the preserved original verdict are archived off-repo on the lab share.

  **The superseded paragraph, for context:** throughput. The deprecation's real content was that the production MCTS recipe costs 3300 AF2 calls per 100-design replicate, which on a CPU reward meant 12.2 days against 2.25 h on an H200. With the reward on the GPU that arithmetic no longer applies, but nobody has measured the replacement. Run a short MCTS on Spark and time it before planning a campaign. The installer's smoke test compiles a jitted **bf16** graph — the exact lowering that used to abort — and refuses rather than reporting success if it fails; it deliberately does not claim more than that, because this repo has already once declared aarch64 support on the strength of `jax` reporting `gpu` plus a clean import. The production recipe is `search.algorithm=mcts, n_simulations=8`, whose budget is fixed at `nsamples × (1 + 8×4)` = **3300 AF2 calls per 100-design replicate** → **12.2 days on Spark vs 2.25 h on one H200** (PC-v3's 50 replicates ≈ 1.7 years). Threading cannot fix it — AF2-on-CPU asymptotes at ~4 of 20 cores. **Run Proteina-Complexa on x86_64.** Do NOT "solve" it by switching to `best-of-n`: that is cheap only because it never consults the reward during generation, and MCTS was adopted because it beat best-of-n 10× at iPTM ≥ 0.85 in ⅓ the wall clock. **Reopen condition may already be met — see the jax 0.6.2 note in the BindCraft entry above.** PC's AF2 reward is the same ColabDesign that BindCraft runs on the GPU here; PC is simply pinned to `jax 0.4.29`, which predates sm_121. Whether upgrading PC's venv works is UNTESTED and needs Spark. Otherwise reopens if a GPU-native reward replaces AF2 (`rf3` is installed on Spark; the rf3 folding reward is commented out at `binder_generate.yaml:194-213` — a different objective, so not parity). Full verdict + evidence are archived off-repo on the lab share. **Not to be confused with `jproteina-complexa`**, the escalante-bio JAX reimplementation inside the Mosaic venv, which does work on aarch64 — different implementation, different weights.
- SoluProt: supported on aarch64 via `bash install/install_aarch.sh --tool soluprot` (the x86 `binderscout install` path redirects here). The installer builds scikit-learn 0.20.4 (the model pickle won't `predict()` under aarch64's 0.21/0.22) and open-source USEARCH v12 (`rcedgar/usearch12`, GPLv3) from source — **both platforms now source-build USEARCH**; the committed `usearch.x86_64` / `usearch.aarch64` binaries were removed so the MIT repo does not redistribute GPLv3 binaries, patches `soluprot.py` for biopython≥1.78, and uses the shipped `--no_tmhmm` model (TMHMM/USEARCH x86 binaries are not used). Needs a C/C++ toolchain. `binder-compare` itself runs in the `binder-eval` env and shells out to this py3.7 env via `$SOLUPROT_PYTHON`.
- Pre-cached AF2 weights path: `Documents/OLD/BinderScout/bindcraft-tools`, then `Documents/OLD/BindMaster/bindcraft-tools`. Both installers, the configurator and `run_bindcraft2.sh.template` probe both spellings, new first: that archive lives OUTSIDE the repo and was never renamed on disk, so the new spelling alone misses the cache and re-downloads ~4 GB of AF2 weights (plus 5.3 GB for BindCraft 2).

### Design decisions and WHY

- **Monorepo:** The Evaluator was merged from a separate repo (`BinderScout-evaluator`, now archived) into `Evaluator/` so the full pipeline ships in one `git clone`.
- **stdlib-only CLI:** `binderscout.py` uses only stdlib so it works on any Python 3.10+ without pip installs.
- **uv for Mosaic:** Mosaic uses `uv` instead of conda because it needs JAX with CUDA, and uv resolves this faster and more reliably.
- **Pinned commits:** Tool repos are cloned at pinned commits (`BINDCRAFT_COMMIT`, `BOLTZGEN_COMMIT`, `MOSAIC_COMMIT`) for reproducible installs.
- **Separate evaluator envs:** Boltz-2 refolding runs in the Mosaic venv (JAX). **Two things
  there will send you the wrong way, both measured 2026-10-31.** First, `torch` in every
  Mosaic venv on the fleet is `2.7.1+cpu`, so Boltz's data loader prints "no accelerator is
  found" — that is the data loader, not the fold, which runs on JAX and does use the GPU.
  Second, a `binder-eval-boltz2` conda env **does exist** on the x86_64 fleet machines (this file
  previously said no such env exists) with `torch 2.14.0+cu130` and CUDA
  available — but no JAX stack, so `refold_boltz2.py` dies on `import equinox`. It is not a
  substitute for the Mosaic venv. On a shared card, `BOLTZ2_XLA_MEM_FRACTION` is the setting
  that matters: the runner's pool-aware default takes 0.75–0.80 of the device, which on a
  24 GB card is ~19 GiB and OOMs instantly against anything already resident.
  AF3 v3.0.2 (Part K, live) is the canonical 2nd engine and runs in a dedicated `binder-eval-af3` conda env — on DGX Spark, H200, **and on 24 GB consumer GPUs** (see the AF3 memory note below; the old ">100 GB" requirement was a preallocation artifact). ESMFold2 (biohub) runs in its own `binder-eval-esmfold2` conda env, auto-detected by `evaluate.sh` when present. `evaluate.sh` orchestrates Boltz-2 + AF3 + ESMFold2 — exactly three engines, all auto-detected, each skippable with `--skip-<engine>`.

---

## Conventions

### Python style

- **Minimum version:** Python 3.10 (type hints with `|` union syntax are used)
- **Linter/formatter:** ruff (configured in `ruff.toml`)
  - Line length: 120
  - Quote style: double
  - Rules: E, W, F, I, UP, B, SIM, RUF (with specific ignores)
  - Per-file: `binderscout_examples/*.py` exempted from all rules; `Evaluator/scripts/refold_*.py` allows E402
- **Check and format:**
  ```bash
  pip install ruff
  ruff check .
  ruff format --check .
  ruff format .            # auto-format
  ```

### Shell style

- **Linter:** shellcheck (`--severity=warning`)
- When suppressing warnings, use inline `# shellcheck disable=SCXXXX` directives
- Color output uses ANSI variables: `RED`, `GREEN`, `YELLOW`, `CYAN`, `BOLD`, `RESET`
- Helper functions: `print_step()`, `print_ok()`, `print_warn()`, `print_fail()`
- Logging: `run_logged <label> <command>` runs with spinner, logs to file, shows last 30 lines on failure

### Naming

- Directories: lowercase with underscores (`configurator/`, `binder_comparison/`)
- Python files: lowercase with underscores
- Python classes: PascalCase
- Python variables/functions: snake_case
- Bash constants: UPPER_CASE
- Conda envs: BindCraft, BoltzGen, binder-eval, binder-eval-af3 (canonical 2nd refold engine, Spark / H200), binderscout_pxdesign, binderscout_protein_hunter, binderscout_rfd3

### Per-run `settings.json` (reproducibility convention)

Every tool run script MUST write a `settings.json` into its tool output subdir
(`runs/<name>/<tool>/settings.json`) **before** the design step starts. This
is how future sessions answer "what params produced these designs" without
grepping through `run.log` or trusting the parent run script (which may have
been edited since the run).

Required keys:

```json
{
  "tool":         "<tool-name>",
  "started_at":   "<ISO-8601 UTC>",
  "version":      { "binderscout_git_sha": "...", "binderscout_git_branch": "...", "tool_repo_git_sha or tool_pkg_version": "..." },
  "target":       { "name": "...", "sequence": "...", "length": N },
  "design_params":{ ... tool-specific CLI flags ... },
  "env":          { "conda_env": "...", "python": "...", "gpu_id": N, "gpu_name": "...", "gpu_memory_mib": N }
}
```

Implementation: write the JSON via a `cat > $RUN_DIR/settings.json <<JSON …
JSON` heredoc immediately after conda activation but **before** launching
the heavy workload. Capture `git rev-parse HEAD` of both the BinderScout repo
and the tool's repo (or its installed package version), plus
`nvidia-smi --query-gpu=name,memory.total`. The shipped templates
`binderscout_examples/run_rfd3.sh.template` and
`binderscout_examples/run_protein_hunter.sh.template` are the canonical
examples — copy that block when adding a new tool's run script.

When relaunching the same tool with different parameters (e.g. PH at 700×5
then 700×7), back up the previous output dir to a versioned name like
`protein_hunter_v2_700x5/` so the side-by-side `settings.json` files document
the parameter sweep.

### Git and branching

- **Working branch:** `v2.0.x` — all work on these machines lands there. `master` is the separate 1.x
  line (see Overview) and is not merged into it. There is no platform branch.
- **Commit style:** `Part X: description` matching STAGES.md parts, or imperative mood for smaller changes
- **PR conventions:** imperative title < 70 chars, body references STAGES.md items, CI must pass, one logical change per PR
- **This repo is PUBLIC — no infrastructure identifiers in tracked files.** No machine IPs,
  DNS hostnames, Unix usernames, absolute `/home/<user>` paths, cluster account names or SSH
  host-key fingerprints. **Name machines only by architecture (`x86_64`, `aarch64`) or
  generically ("a multi-user cluster", "a shared login node")** — never by cluster name, ssh alias
  or hostname, and never point at institution storage. GPU model names (GB10, H200, L40S,
  RTX 3090) stay: they are measurements. Use `$HOME` and repo-relative paths. Real values, and
  the alias list, live in machine-local gitignored files (`CLAUDE.local.md`, `docs/local/`)
  or environment variables. `tests/test_public_docs_are_anonymous.py` enforces this for
  documentation and tests.

  **Scrub status — the previous "scrubbed from tree and history 2026-09-22" was not true.**
  Six tracked files still carried an absolute `/home/<username>` path on 2026-09-25
  (`CHANGELOG.md`, two `docs/` files, a plan under `Evaluator/docs/plans/`, a notebook and
  a test fixture). They are gone from the tree now, replaced by `/home/<user>` in prose and
  by a generic name in the one test that needs a *detectable* path. Two things remain true
  and neither is fixed by that:
  - **History still has them**, and they are already on `origin/master` and `origin/v1.1.x`.
    A tree scrub does not unpublish anything.
  - **`tools/aarch64/dssp` has a build-time home path baked into the binary** (a
    `/home/<account>` naming one of our own boxes) by whatever compiled it. Removing it
    needs an aarch64 rebuild, so it is recorded rather than patched — and pinned by
    `tests/test_no_user_home_paths_in_tree.py`, which fails if a *new* binary joins it or
    if that one is ever rebuilt clean and the exemption is left behind.

  `tests/test_script_hygiene.py` detects this class in shell scripts, and
  `tests/test_no_infrastructure_identifiers_in_tree.py` (added 2026-10-30) now enforces
  four of the classes **across every tracked text file**: private IPv4 addresses
  (RFC 1918, by shape), SSH host-key fingerprints (by shape), and **this box's own
  account name and hostname**, both derived at test time rather than listed -- a test
  that spelled them out would have to contain the identifiers it bans, and a derived
  check adapts to whichever machine runs it. RFC 5737 documentation ranges
  (192.0.2.x / 198.51.100.x / 203.0.113.x) and loopback are deliberately allowed,
  because fixtures need addresses and those are the ones to use.

  It was added after a status-monitor fixture pasted a real cluster login-node address
  into a tracked file to exercise an error sanitiser; a manual grep caught it before it
  was pushed, and nothing in the suite would have. All four checks are mutation-proven
  against that exact mistake.

  **Still unenforced:** internal DNS hostnames for boxes *other* than the one running the
  tests, cluster account names other than the local one, and public-range institutional
  addresses. The `loschmidt.chemi.muni.cz` URLs in the tree are a public web service, not
  infrastructure, and must stay.

---

## Domain Knowledge

### Key terminology

| Term | Meaning |
|---|---|
| **Binder** | A designed protein that binds to a specific target protein |
| **Target** | The protein you want to design a binder for (provided as PDB/mmCIF) |
| **Hotspot residues** | Specific residues on the target that the binder should contact |
| **Refolding** | Re-predicting structure from sequence using an independent model (cross-validation) |
| **ipTM** | Interface predicted TM-score (0–1, higher = better). Measures binding interface quality |
| **iPSAE** | Interface Predicted Structural Alignment Error (DunbrackLab 2025 formula). TM-score analogue; **higher is better** |
| **ipsae_min** | min(binder→target iPSAE, target→binder iPSAE). Secondary metric / tiebreaker (primary is the two-stage cross-engine iPTM ranking — see ranking note) |
| **consensus_iptm** | max ipTM across independent refolding engines. A diagnostic column only — **it does not rank** (max-ranking loses to mean; Part U). The ranking metric is `consensus_iptm_mean` |
| **PAE** | Predicted Aligned Error (Angstroms, **lower = better**). Raw error between residue pairs |
| **pLDDT** | Predicted Local Distance Difference Test (0–1, higher = better). Per-residue confidence |
| **MPNN** | ProteinMPNN — sequence design neural network |
| **SPR** | Surface Plasmon Resonance — experimental binding measurement technique |
| **CDR** | Complementarity-Determining Region (of nanobodies/antibodies) |

### Tools and what they do

| Tool | Method | Key papers/repos |
|---|---|---|
| **BindCraft** | AF2 hallucination + MPNN sequence design + PyRosetta filtering | `martinpacesa/BindCraft` |
| **BindCraft 2** | A rewrite of BindCraft, not a new version: AF2 hallucination + MPNN, JAX only, no PyRosetta. Ranks its own designs on `i_pDAE` | [PacesaLab/BindCraft2](https://github.com/PacesaLab/BindCraft2) — source-available (hosting-restricted), cloned at `v1.0.1`, not vendored |
| **BoltzGen** | Boltz-1 structure diffusion + flow matching for binder generation | `HannesStark/boltzgen` |
| **Mosaic** | JAX-based Boltz-2 gradient hallucination (no internal AF2 cross-val) | `escalante-bio/mosaic` |
| **PXDesign** | Protenix-based de novo binder design (diffusion + MPNN + AF2 eval) | `bytedance/PXDesign` |
| **Proteina-Complexa** | Flow matching + inference-time optimization (beam search / MCTS) | `NVIDIA-Digital-Bio/proteina-complexa` |
| **Protein-Hunter** | Boltz-2 / Chai-1 hallucination; 6 modalities (protein, cyclic, ligand CCD, ligand SMILES, DNA, RNA) | Cho et al. 2025 |
| **RFD3** | RosettaCommons foundry diffusion (RFdiffusion3) + ProteinMPNN; BSD-3, commercial-use OK | `RosettaCommons/foundry` (`rc-foundry` on PyPI) |
| **RFD4-Proteina** | Latent-reasoning diffusion, IPD × NVIDIA. Generates backbone **and** sequence in one pass — no separate MPNN step. Code BSD-3; **the weights licence has NOT been verified here** | [`RosettaCommons/RFD4-Proteina`](https://github.com/RosettaCommons/RFD4-Proteina), weights `nvidia/RFD4-Proteina` on HF |

### Evaluation metrics and ranking

**There is ONE ranking, and no way to choose another** (Part U, 2026-07-28): a cross-engine gate, then `consensus_iptm_mean`. It produces a single `rank` column.

**Stage 0 — cross-engine gate.** A design must have been refolded by at least `--min-engines` independent engines (**default 3** = all of Boltz-2 / AF3 / ESMFold2; floor 2). `consensus_iptm_mean` skips missing engines, so without this a single-engine design's mean *is* that one engine's score and it competes against 3-engine means on an incomparable scale — and for Mosaic / Protein-Hunter that engine is the one that designed it. Designs failing the gate are ranked **last, not dropped** (`passes_engine_gate` records it). If nothing clears the gate the run warns and names the shortfall rather than silently reporting that no design was good enough.

**Rank — `consensus_iptm_mean`,** ties broken by `consensus_iptm_n` (more engines backing an equal mean wins), then `consensus_iptm`, then binder pLDDT.

> **The mean is `skipna`, and that is why the gate is load-bearing.** `consensus_iptm_mean` is `numeric.mean(axis=1)` over the three `*_pae_iptm` columns (`scoring.py`), so pandas drops NaNs: a design scored by **one** engine gets that engine's score **as its "mean"**, on a scale not comparable to a 3-engine mean. Stage 0 is the only thing standing between that and the top of the list. Two consequences worth stating plainly: (1) gate failures are **ranked last, not dropped**, so *within* the failed block the order IS that incomparable comparison — do not read a rank below the `passes_engine_gate` boundary as a cross-engine result; (2) the code warns loudly when the gate is **empty**, but the partial case is silently true, so always read `consensus_iptm_n` alongside `rank`. Verified in code 2026-10-29.

**What was removed, and why — do not re-add any of it:**

| removed | evidence |
|---|---|
| Stage-1 top-50% max screen (`passes_max_screen`) | Removed **0 designs from the top-5/10/20/50 and top-10% on 12/12 Cao targets**; earliest rank it moved was 21.0% down the pool; full-list Spearman 0.983–0.999 |
| `--screen-metric` | The `max` default was documented as "the lenient recall step" — **backwards**: at the same cut `mean` retained *more* true binders (1,114 vs 1,093; +0.0123, CI [+0.0027,+0.0226], p=0.0094, 8/12) |
| `adaptyv_rank` (quality_tier → agreement_count → ipsae_min) | `agreement_count` is a flat null as a screen: macro-AUC **0.532** with **87.2%** of designs tied at zero |
| `consensus_rank` (max-iptm) | Max-ranking loses to mean-ranking: precision@top-10% **0.79 vs 0.92** |
| `--rank-by`, `active_rank` | Searching for a better metric on labelled data makes it **worse** — honest nested selection over 72 metrics scores **0.5170** vs **0.5552** for `consensus_iptm_mean` (p=0.0014, 8/12 targets) |

> **Caveat on the Stage-1 inertness.** It is an empirical property of correlated engines (max and mean co-rank at Spearman 0.89–0.98 within target), **not** a theorem. Elementwise `mean ≤ max` does *not* imply rank preservation: A=(0.5,0.5,0.5) has mean 0.5/max 0.5, B=(0.9,0.1,0.1) has mean 0.367/max 0.9, so a cut at 0.6 drops A and keeps B despite A's higher mean.

> **Clean break on the CSV schema.** `two_stage_rank`, `adaptyv_rank`, `consensus_rank`, `active_rank` and `passes_max_screen` are gone from `metrics.csv` — replaced by `rank` and `passes_engine_gate`. There is no compatibility shim: older `metrics.csv` files were written by an older version and are left as-is. Re-report from the per-engine refold CSVs if you need the new schema for an archived run.

`ipsae_min` (min of binder→target and target→binder iPSAE; DunbrackLab 2025 `max_i[mean_j(1/(1+(PAE_ij/d0)²))]`, d0_res variant, uniform 10 Å PAE cutoff) is retained as a diagnostic and for the quality tiers below — not the primary sort. **Caveat:** no structure-confidence metric ranks *affinity* among binders, only binder-vs-non-binder — and **Part N established that nothing else we tested does either** (landed 2026-06-16 with a negative result; archived off-repo on the lab share). Interface ΔG, `|dG/dSASA|`, PRODIGY and the BindCraft 14-metric panel all fail to rank affinity *among* binders (best pooled |ρ| ≈ 0.34, holding on only 2/4 targets), corroborated externally on OpenBind (molecular weight is the best predictor, ρ 0.48) and SKEMPI (PRODIGY 0.20, Rosetta ΔG 0.12). `binder-compare affinity` ships the surviving gate-then-density form — gate on `passes_affinity_gate` (`ipsae_min ≥ 0.61`), then rank survivors by `interface_energy_density` (`|dG/dSASA|`) — as an **advisory** ranker, not a validated one.

**Direction guide:**
- **Higher is better:** `iptm`, `bt_ipsae`, `tb_ipsae`, `ipsae_min`, `plddt_binder_mean`, `binder_ptm`
- **Lower is better:** `ranking_loss`, `pae_bt_mean`, `pae_tb_mean`, `pae_bb_mean`, `pae_max`

**Quality tiers (based on `ipsae_min`):**

| Tier | Threshold | Meaning |
|---|---|---|
| High | > 0.80 | *Nominally* the strongest candidates — but see the warning below: on our two targets this tier fired 0 and 2 times, with zero confirmed binders |
| Medium | 0.61 – 0.80 | Promising, may need optimization |
| Low | 0.40 – 0.61 | Weak binding prediction |
| Reject | ≤ 0.40 | Unlikely to bind |

> **These tiers and the `ipsae_min ≥ 0.61` affinity gate did NOT hold up against our own
> experimental results (checked 2026-09-28, two targets with measured Kd).** On both, the
> designs the gate *rejected* bound tighter than the ones it kept, and on one target the
> "Reject" tier contained most of the confirmed binders while "High" was empty. The
> thresholds are absolute values calibrated elsewhere and do not transfer to a short-helix
> target — consistent with the 2026-05-16 note that ipSAE is mis-calibrated on short
> targets. **Nothing has been changed in code**: `passes_affinity_gate` and the tiers are
> still computed and shipped, so the recommendation is to read them as diagnostics and
> never to present a tier as evidence a design will bind. Options, in order of preference:
> re-base on `Mean_ipTM` (which retained real signal after controlling for length), demote
> `ipsae_min` to a plain diagnostic as `agreement_count` already is, or re-derive the
> thresholds per target class. Caveat: two targets, one of them with few binders.
> Full numbers are NOT in this repo — they are unpublished experimental results and live
> in the local benchmark folder.

### Critical domain facts

- **iptm is gameable by the designing engine** — BindCraft games AF2 ipTM, and BindCraft 2's i_pTM is design-time-biased in exactly the same way (it hallucinates against AF2 too). **Neither tool's own i_pTM ever enters `consensus_iptm_mean` — but read that precisely, because the protection it implies is ASYMMETRIC and only BindCraft / BindCraft 2 actually get it.** What the ranking averages is `boltz_pae_iptm` / `af3_pae_iptm` / `esmfold2_pae_iptm` (`scoring.py:_ENGINE_IPTM_COLS`) — our **own re-derivation from each engine's PAE**, never the tool's reported number. **Consequence when a refold ran on another box: that derivation reads the `pae_file` path stored in the CSV, so copying a refold CSV without its `refold_<engine>/` directory — or copying both to a different account, since the paths are absolute — yields an empty `*_pae_iptm` column and SILENTLY drops every design to 2-engine coverage.** The CSV still looks full (its own `iptm` column is populated), the merge still joins, and the only symptom is the gate warning, which says "run the missing engine" rather than "100 PAE files are unreadable". Measured 2026-10-31. Carry the PAE directory with the CSV and remap the paths, or run the report on the box that folded it. For BindCraft and BindCraft 2 that is a real firewall: AF2 refolding was removed in Part I, so their design engine is absent from the panel entirely. For **Mosaic and Protein-Hunter it is not**: both design against **Boltz-2**, and `boltz_pae_iptm` is one of the three inputs at full 1/3 weight — so a Mosaic design is scored partly by the very model it was optimised against, just via our PAE kernel instead of Mosaic's own metric (BoltzGen is adjacent: Boltz-1 diffusion against a Boltz-2 refold). Verified in code 2026-10-29. The cross-engine mean dilutes that to 1/3, which is the whole point of the >=3-engine gate, but it does not remove it, and a 2-engine run that keeps Boltz-2 dilutes it only to 1/2. Never rank on a single engine's ipTM. The two-stage `consensus_iptm_mean` (mean across independent engines) resists this — a design one engine loves but another rejects is demoted by the mean.
- **More engines really is less wrong — measured, and bounded.** On the canonical Adaptyv benchmark (563 designs, 4 targets, 258 binders, 2026-10-03): one engine buries a true binder in its own within-target bottom quartile **5.69×** more often than all three do together (CI [3.27, 18.39]; 11.4× at a bottom-decile cut), and the mean rescues **92.9%** of binders buried by exactly one engine, 25.0% of those buried by two, and **0%** of those buried by all three. Error correlation measured within target and within class is **ρ ≈ 0.39**, i.e. **effective n = 1.6–1.7 of 3**. This replicates Cao's numbers (5.2×, ρ 0.382, 1.70) on an independent pool — the one cross-engine claim that has survived replication. **Two limits worth stating with it:** the benefit is capped by correlation (a random-ordering null gives **17.2×**, p=0.0008, so the engines are not independent votes), and joint burial is **length-linked** — mean binder length 84.5 aa when no engine buries vs **119.9 aa** when two do, which is the shared failure mode. Full detail and the engine panel: `docs/INVESTIGATION_coverage_premise_2026-10-03.md`.
- **`consensus_iptm_mean` IS the agreement rule — it is not an approximation of one, and a vote count would be worse.** The design intent: one engine can be *played* for or against a design (Mosaic games `boltz_iptm` **by construction** — it is Boltz-2 gradient hallucination; BindCraft games AF2 i_pTM; BindCraft 2's i_pTM is biased the same way), two can disagree, and three is the right number — two in favour do not kill a design, but three must effectively agree for it to reach the top tier. **The mean implements that directly:** a high mean requires all three scores high, one dissenter drags it down proportionally rather than fatally, two drag it below the surface. Measured on the canonical benchmark against real experimental labels — of true binders buried in the bottom quartile by exactly **one** engine the mean rescues **92.9%**, by **two** only **25.0%**, by **three** **0%**. That gradient *is* the rule.
  **`agreement_count` is a WARNING FLAG, and it is NOT redundant with the mean — it reads a different quantity.** The ranking averages **ipTM** (`*_pae_iptm`); `agreement_count` counts engines over a threshold on **ipSAE** (`boltz_pae_ipsae_min` / `af3_ipsae_min` / `esmfold2_ipsae_min`, `scoring.py:454-468`). So the pair carries orthogonal information, and the useful reading is the *disagreement between them*: **a design with a high ipTM mean but only two engines calling its ipSAE high is a caution — the confidence score is high while the interface-error geometry only partly supports it, so something may be wrong.** It is a per-design flag for a human weighing what to order, not an input to `rank`.
  **Part U's null does not contradict that, because it measured a different use.** Part U tested `agreement_count` as a pool-wide *screen / stratifier* and found a flat null (macro-AUC 0.532, 87.2% tied at zero). A screen is judged by discrimination across the whole pool; a warning is judged by whether the designs it flags are genuinely problematic. Those have different success criteria and the second has never been tested. **Keep it diagnostic, keep it reported, do not gate or stratify on it — and do not delete it as redundant either.**
  **One real caveat on the flag:** its thresholds are absolute ipSAE cuts (0.61 for all three engines), and that absolute cut measured **inverted** on our own experimental results (see the quality-tier warning below). The *relative* agreement across engines is less exposed to that than the absolute tier is, but a mis-set threshold still mis-sets the count. Treat the flag's direction as informative and its exact threshold as unvalidated.
  **Note which argument this is.** The case for three engines is **adversarial**, not variance reduction: a gamed engine is confidently wrong in a consistent direction, not noisily wrong, so averaging does not fix it the way it fixes noise — independent opinions do. Optimising a single metric harder is not a substitute, which is also why Part U's metric search made things worse.
- **Do NOT re-litigate the engine set on one pool.** The 3-engine mean beats the *average* single engine (+0.047, p=0.0002) but **not the best one out of fold** (+0.0026, p=0.69), and `mean(boltz,esm)` out-scores it on the benchmark (0.7279 vs 0.7231; +14 binders at top-20). It is still not a reason to change anything: at the shortlist sizes we ship (N=3–8) the whole panel is within ±4 binders, the drop-AF3 effect does not keep its sign across leave-one-target-out folds of that same pool, and it inverts on the secondary pool. Four single-pool effects were retracted in the week of 2026-09-29 — helix, magnitude, shrinkage and `mean(af3,esm)`. **Treat a single-pool effect as a hypothesis, not a result.**
- **Engine disagreement lowers the mean — but is NOT a useful stratifier.** For short binders (~60aa), refolding engines often disagree on interface quality, and `consensus_iptm_mean` captures that continuously (disagreement drags the mean down). That much holds. What does *not* hold is using disagreement to slice the pool: on Cao, splitting at the median engine spread changed AUC by −0.006/+0.005 against a random-split null of ±0.018 (p=0.71/0.81), and `agreement_count` scores macro-AUC 0.532 with 87.2% of designs tied at zero. Keep `agreement_count` as a diagnostic column; do not gate or stratify on it (Part U).
- **DO NOT USE Cao 2022 as a benchmark (operator decision, 2026-10-03).** Its Kd labels are too censored to support a conclusion: **73.4 %** of its binder labels are one-sided (**94.2 %** across the full 654,716-design library), its own `kd_ok` quality flag keeps only ~495 designs, and **8 of 12 targets sit at the random-ordering noise floor** — so any Cao result is decided by ~4 informative targets. Measured 2026-10-03: a hand-rolled "two-sided Kd" slice admits designs with `kd_lb == 0` (a degenerate [0, X] interval), and swapping it for `kd_ok` **flips the sign** of an engine-set effect that had p=0.0078. **The canonical labelled benchmark is the curated Adaptyv/ProteinBase set** (563 designs with the full PAE panel, 4 targets, replicated binding calls), assembled 2026-10-02 and kept on the lab's private share; see its own `README.md` and `PROVENANCE.md`. Note that "Adaptyv" and "ProteinBase" are **one dataset**, not two corroborating ones. **Every Cao-derived figure below and in Parts T/U is therefore provisional and must be re-measured on that benchmark before it is relied on.**
- **The ranking is a triage filter, not a decision procedure.** Calibrate expectations before presenting a top-N as "the best". **(Cao-derived — see the preceding bullet; these specific numbers are provisional.)** On the Cao 2022 near-miss pool (4,442 Rosetta minibinders, 12 targets — the closest analogue to a real campaign pool: hundreds of same-tool, same-length designs against one target) the whole 72-metric field spans macro-AUC **0.471–0.560**, and taking the top decile by the best metric is worth ~**1.5–2× enrichment** (FGFR2 8.98 → 2.13 designs-per-hit) — but it beats a random ranking on only **6/12 targets**, and on TrkA and Tie2 it is *worse than not ranking at all*. Ranking looks much stronger on easier pools (Adaptyv 0.68–0.72, de novo BindCraft 0.72–0.78 macro) and on label-clean positives (Cao rises to 0.73 once one-sided-Kd "binders" are excluded — 73.4% of Cao's binder labels are one-sided; reproduced exactly 2026-10-03, and 94.2% on the full 654,716-design library). **Two of Part U's supporting claims about that were withdrawn on 2026-10-03** — the binary-assay corroboration is near-circular (`binder_4000_nm` is predicted by `kd_ub < 4000` at MCC 0.819, 0.075% error over 654,716 rows), and one-sided binders are NOT "experimentally indistinguishable" from non-binders: they pass at 8.7× the rate (p=4e-62), 32× at 400 nM. Weaker, not indistinguishable. So Cao answers "3 engines vs an *arbitrary* single engine" and must not be used for "vs the *best* single engine" without that caveat. See `docs/INVESTIGATION_coverage_premise_2026-10-03.md`. Part U.
- **~~Binder length is a main driver — longer binders score lower on `ipsae_min` (r ≈ -0.78).~~ RETRACTED 2026-10-29: that correlation does not reproduce anywhere we can test it.** Measured over **12 engine-pools** (4 pools x 3 refold engines, 597 engine-design rows: CALCA/BC2, AK1b pd-l1, GF_asyn100, GF_asynfull), the strongest length correlation on `ipsae_min` is **-0.31** and **five of the twelve are POSITIVE**. `docs/PLAN_2.0_PART_RESULTS.md` had already found the same thing on two targets independently. Where a length effect *does* show up it is substantially a **normalization artifact, not biology**: `compute_iptm_from_pae` takes a global `d0` from `L_b + L_t`, so d0 grows with the complex and the kernel gets more forgiving for longer binders. Pinning d0 flips the sign of the length correlation on CALCA (+0.36 to -0.30) and reorders that pool (Spearman 0.67-0.82), while leaving AK1b and GF essentially unchanged (0.98-0.999) — the distortion scales with how much binder length varies *relative to the target*, so it is large for a wide length sweep against a small target and negligible for a narrow sweep against a big one. **Length is a variable to control for, not a driver to assume.** (Was never testable on Cao either: 75.1% of that set is exactly 65 aa.)
- **What `*_pae_iptm` is, and what the rank resolves (scoring audit, 2026-11).**
  - **It is a point-PAE re-derivation, not the engine's own ipTM.** `boltz_pae_iptm` / `af3_pae_iptm` /
    `esmfold2_pae_iptm` recompute ipTM from each engine's PAE matrix with one shared formula. **Measured
    2026-11-03 on the archived 394-design three-engine TfR1 pool (n=450 PAE matrices per engine, wave-1
    archive): the re-derived values sat ~0.08-0.13 BELOW** that engine's own reported `*_iptm`, and within
    an engine the two were rank-equivalent (Spearman >= 0.994). **The sign and size of that offset are
    properties of that pool, not of the kernel** (for AF3 in particular they differ by pool), so do not
    use 0.08-0.13 as a correction. Across engines the columns share a *formula*, not a *scale*.
  - **It is within-target only.** Compare designs against the same target; a mean on one target is not
    comparable to a mean on another.
  - **The top-N is an unordered tier.** The rank's resolution is ~150x finer than the disagreement between
    engines, so the order inside a shortlist is below what the engines can tell apart. (The ~150x ratio is
    from the same 2026-11 scoring audit; the pool it was taken on was not recorded, so read it as an order
    of magnitude.)
    Treat the top N as a set, not a leaderboard.
  - **Rank reads the optimistic interface direction.** ipTM takes `max(binder->target, target->binder)`;
    `ipsae_min` takes the minimum (the pessimistic direction). A high ipTM with a near-zero `ipsae_min` is a
    one-directional interface, not a contradiction.
  - **`quality_tier` is single-engine** (the primary engine, Boltz-2 by default, the most generous of the
    three), not a cross-engine statement.
  - **2-engine and 3-engine means are not on one scale** (`--min-engines 2` mixes them). Read
    `consensus_iptm_n` beside `rank`.
  - **d0 grows with the complex.** ipTM's d0 uses `L_binder + L_target`, so a longer binder gets a more
    forgiving kernel: up to **+0.036** on the consensus (measured 2026-11-03 on the same TfR1 pool). Pinning d0 (`*_pae_iptm_pinned`,
    `consensus_iptm_mean_pinned`, pool-median binder length or `--d0-binder-length`) was **measured not to
    improve ranking** on the curated 563-design, 4-target labelled benchmark (measured 2026-11-03; macro AUC +0.0025, 95% CI -0.004..+0.010, sign
    split 2/2 across targets: it re-weights by length rather than correcting anything). So **`rank` stays on
    the per-design d0** and the pinned columns are *diagnostic*, there to make the size of the length
    artifact visible per design.
- **Mosaic designs.csv format** — Can mix column formats between workers (old 11-col / new 13-col). The parser must handle this carefully or columns misalign. The `is_top` column marks the ~40 refolded designs out of ~800 total; extractors filter to `is_top=1` by default.
- **Mosaic `target_sequence` placeholder** — The Mosaic template (`hallucinate_binderscout.py`) writes `"REPLACE_ME"` as `target_sequence` when not configured. The legacy evaluator guards against using this as a real target sequence.
- **AF3 memory: the ">=100 GB GPU" requirement was wrong — it fits a 24 GB card, and the small-pool abort was OUR BUG.** Both halves are now measured, and both earlier readings of this bullet were wrong.
  **Memory.** On an x86_64 box with an RTX 3090 (24 GB) a 258-token complex peaks at **4,430 MiB**, and a 391-token complex peaks at the *same* 4,430 MiB. **That identity is not evidence AF3 is size-independent** — an earlier version of this bullet read it that way. Neither run passed `--buckets` at all (the flag did not enter this repo until 2026-09-10, `9a04dac`), so both padded to the **same 512-token shape** under AF3's stock ladder. It is one compiled shape measured twice. Corroboration that memory is genuinely not the constraint here: a 568-token, 50-design pool completed **50/50** on the same card under a hard `XLA_PYTHON_CLIENT_MEM_FRACTION=0.191` (~4.7 GB of 24,576 MiB). The old ">100 GB" figure came from measuring with `XLA_PYTHON_CLIENT_PREALLOCATE=true`, which reserves a fraction of the pool regardless of need — evidence about our env vars, not AF3's working set.
  **The sm_86 abort: ours, not AF3's — settled 2026-09-29.** A 2026-09-27 run on an RTX 3060 aborted with `RESOURCE_EXHAUSTED: Shared memory size limit exceeded: requested 110592, available: 101376` (sm_86/sm_89 expose 101,376 bytes of shared memory per block; A100 164 KB, H100/GB10 228 KB). That was recorded as "AF3 cannot run on consumer Ampere". **It is not.** The variable was token shape: `refold_af3.py` computed `bucket = len(target) + max(len(binder))` with no lower bound, so the failing pool asked for `--buckets=60` (CALCA 32+28) while AF3's own ladder starts at **256**. Measured on an RTX 3090, one `input.json` reused byte-identically across two arms with a cold shared compile cache, only the bucket digits differing:

  | arm | outcome |
  |---|---|
  | `--buckets=60` | **rc=1** in 43 s, the shared-memory abort, no structure |
  | `--buckets=256` | **rc=0** in 69 s, no shared-memory error, 2 structures, iptm 0.52 |

  Below 256, tokamax's Pallas/Triton attention and gated-linear-unit kernels select a tile config whose shared-memory request exceeds sm_86's limit. **Fixed** by `AF3_MIN_BUCKET = 256` in `refold_af3.py`, pinned by `tests/test_af3_bucket_has_a_floor.py`. The floor costs nothing against AF3's documented behaviour — stock AF3 pads a 60-token complex to 256 anyway; we were requesting a shape that cannot run, not saving compute. **AF3 therefore runs on every x86_64 machine we checked, and the >=3-engine gate is not Spark-bound.** Caveat unchanged: this is our ~200–600-token regime, not a universal claim — AF3 documents 5,120 tokens on an 80 GB A100 and pair activations scale super-linearly.
- **pLDDT scale** — Boltz-2 returns [0,1]; AF3 native is [0,100] and is rescaled to [0,1] on ingest by the refold runner so report columns are directly comparable.
- **PAE ordering** — Boltz-2 is native [binder|target]. AF3 is token-order so we always put target first in the input JSON, giving [target|binder] — the evaluator re-blocks it internally into [binder|target] (the four blocks are swapped; the matrix is not transposed). Column prefixes distinguish engines (`boltz_pae_*`, `af3_*`, `esmfold2_*`).
- **Append-mode CSVs** — `refold_boltz2.py` appends to CSV. If rerun after partial failure, check for duplicate `run_id` entries.
- **Refold structures are named `<binder_id>_<engine>`** — `<binder_id>_boltz2.pdb`, `<binder_id>_af3.pdb`, `<binder_id>_esmfold2.pdb`, alongside `_pae.npy` and `_plddt.csv` (Boltz-2) / `_model.cif` (AF3, ESMFold2), each in its own engine's output dir. The engine is in the *name*, not just the directory, because the directories get pooled — copying all three into one folder is the normal way to hand over "all the PDBs", and without the suffix a design's three structures are three files of the same name. The id is the first token of the FASTA header `extract` writes, and the one sanitiser is `binder_comparison/io/design_ids.py:safe_stem` — **shared with the Foldseek structural-family join**, so a second copy of that logic makes structures unfindable by id. Consequences worth knowing: a re-run into the same output dir **overwrites** a design's structure (the old names carried a per-run uuid and accumulated instead); a design whose id is missing or sanitises to nothing keeps the legacy index name (`refold7_<run_id>` / `af3_0007` / `esmfold2_0007`); two designs sharing an id get `__2`, `__3`. **AF3's own prediction directory is still index-based** (`af3_0007/`) — that layout belongs to AF3 and `_load_top_sample` globs it; only what we export carries the id.
- **Target MSA is fetched ONCE PER TARGET, cached on disk, shared by all three refold engines.** `binder_comparison.refolding.target_msa.get_target_msa(seq)` queries ColabFold once, keyed by target-sequence SHA-256, and caches the a3m at `~/.cache/binderscout/target_msa/target_<hash>.a3m` (override with `$BINDERSCOUT_MSA_CACHE`). **AF3, ESMFold2, AND Boltz-2 all read this cache** (Boltz-2's `refold_boltz2.py` monkeypatches Boltz's `run_mmseqs2` to redirect the unpaired/target MSA to `get_target_msa` — the binder is `use_msa=False`). So a fresh refold process is a disk hit and **never** re-queries `api.colabfold.com`; this is what stops the ColabFold rate-limit ("Too many failed attempts for the MSA generation request") from crashing Boltz-2 across sessions. If you ever see that error, the target isn't cached yet — run any one engine once (or pre-warm via `get_target_msa`) and the other two are free. The cache directory on the fleet boxes is `~/.cache/bindmaster/target_msa/` — the
  pre-2.0-rename spelling, not the `binderscout` path above (measured on three x86_64 machines
  on 2026-10-31; `_resolve_cache_dir` is what to ask, rather than either literal).
  **Pre-warm it once before starting engines in parallel**: three cold starts race the
  ColabFold server and the loser gets the rate-limit error above. One
  `get_target_msa(seq)` call, then copy `target_<hash>.a3m` to the other boxes — the cache
  is per box, and nothing shares it across the fleet.
  All the eval environments (`binder-eval`, `binder-eval-af3`, `binder-eval-esmfold2`, and the **Mosaic venv** that runs Boltz-2) are editable-installed against **this** repo (`dev/BinderScout/Evaluator`) — if an env points elsewhere, `pip install -e 'Evaluator[report]'` to re-point it. Use the `[report]` extra, **not** `--no-deps`: `binder_comparison/cli/__init__.py` imports every subcommand, so `report.py`'s module-level matplotlib import runs even for a refold, and a `--no-deps` install leaves `binder-compare` unable to start at all (measured 2026-09-27 — `binder-eval-af3` had no `binder-compare` while `import alphafold3` passed `--verify`; `--verify` now checks the console script itself).

### Lab-specific information

- **AF2 weights path** (`AF2_DATA_DIR`): Must point to AlphaFold2 parameter files (~4 GB). Typically at `bindcraft-tools/af2_params`.
- **DGX Spark specifics:** CUDA 13.0, sm_121 (Blackwell), aarch64 architecture. Pre-cached resources stored at `Documents/OLD/BindMaster/bindcraft-tools` — the directory was never renamed on disk, so the code probes the `BinderScout` spelling first and falls back to this one.
- **Orchestrating the fleet:** one x86_64 machine orchestrates. `binderscout status` reads its machine list from `$BINDERSCOUT_FLEET` (falling back to `$FLEET_MACHINES`, which the archived fleet driver also used), so any box can drive the others. Prefer an x86_64 orchestrator with a *discrete* GPU: its desktop session costs it nothing, whereas on a unified-memory aarch64 box those same processes come out of the GPU pool.
- **Sizing GPU work on a GB10 (aarch64) — query, never quote.** The GPU pool IS system RAM there (121.69 GiB), so every "fraction of device memory" knob is a fraction of the whole machine and an uncapped job reboots the box rather than raising OOM (2026-08-18 AF3 at 0.8 → 97.4 GiB → hard reboot; 2026-08-19 Boltz-2 at JAX's 0.75 default → 91.3 GiB). Before sizing anything: `ssh <aarch64-host> 'bash -lc "cd ~/dev/BindMaster 2>/dev/null || cd ~/dev/BinderScout; tools/gpurun --max"'` — the checkout directory is machine-local and spelled either way after the 2.0 rename, so resolve it rather than naming one. The ceiling moves with load — 92 GiB with a desktop up, 90 on a quiet box — so a number copied into a run script is already stale. Dispatch through `bin/<tool>` or `tools/gpurun --cap`, which join MPS and get a **driver-enforced** ceiling; a cap written into a script is advisory only. The static per-tool table is `tools/gb10-env.sh:gb10_budget` and the analysis is `docs/GB10_FREEZE_FAILSAFE.md`, both tracked — only the live ceiling needs the query. JAX budgets are reservations taken in full at import; PyTorch budgets are ceilings.
- **Boltz-1 weights:** ~6 GB, auto-downloaded on first BoltzGen use. Resumable.
- **Disk requirement:** ~60 GB free for full installation of all tools.

---

## Current State

### Active work and recent decisions

- **Parts A–H complete** (see STAGES.md); **Parts I, J, K, L, M landed on `[Unreleased]`** (see CHANGELOG). All Roadmap items are done.
- **Part I — AF2 refolding removed from Evaluator.** Deleted `refold_af2.py`, `af2_runner.py`, `binder-eval-af2.yml`; pruned all `af2_*` schema fields and report plots. BindCraft / PXDesign / Proteina-Complexa still use AF2 internally — only the Evaluator's AF2 refolding step was removed.
- **Part K — AF3 v3.0.2 is the canonical 2nd refolding engine.** Runs in its own `binder-eval-af3` conda env on DGX Spark, H200, **and on 24 GB consumer GPUs** — the original ">100 GB / OOMs on 24 GB" claim was wrong, see the memory note below. Schema: `af3_*` columns in `StandardisedMetrics`; pLDDT rescaled 0–100 → 0–1 on ingest; PAE transposed from token-order to `[binder|target]` to match Boltz-2.
- **Part J reverted — Protenix refolding removed.** `refold-protenix`, `protenix_runner.py`, `refold_protenix.py` and every `protenix_*` schema/report column are gone; AF3 covers the independent-cross-check role. This also resolved a live contradiction: `evaluate.sh` ran Protenix opt-OUT (whenever `binderscout_pxdesign` existed) while this file claimed it ran only when explicitly enabled, so two operators with the same designs could get different `consensus_iptm`. **PXDesign still uses Protenix internally** — that is a design tool, and `pxdesign_protenix_iptm` remains a native metric.
- **Part L — Protein-Hunter** installable via `binderscout install --tool protein-hunter` (x86 only; aarch64 blocked by PyRosetta). Conda env `binderscout_protein_hunter`, vendored Boltz-2 + Chai-1 (sokrypton fork). New `ProteinHunterExtractor` reads `summary_high_iptm.csv` by default (`--all-protein-hunter-designs` for all runs). Configurator generates `run_protein_hunter.sh`.
- **Part M — RFD3** installable via `binderscout install --tool rfd3` (x86; aarch64 opt-in and unvalidated — see aarch64 specifics). Conda env `binderscout_rfd3`, `rc-foundry[rfd3,mpnn]` from PyPI, weights at `weights/foundry/`. New `RFD3Extractor`. Configurator generates `run_rfd3.sh`.
- **Standalone mode** (Part H, v0.7.0): Installer auto-detects whether system conda is writable. If not, downloads Miniforge3 into `BinderScout/conda/` and creates all environments locally. Shortcuts go to `BinderScout/bin/` instead of `~/.local/bin/`. `--standalone` forces this; `--system-conda` opts out. All generated run scripts and Evaluator shell scripts search local conda first.
- **Mosaic is_top filter**: Both `MosaicExtractor` and legacy `_parse_mosaic()` default to extracting only `is_top=1` designs. `--all-mosaic-designs` flag exposed on `binder-compare extract`, `binder-compare run`, and `binderscout evaluate`. The `REPLACE_ME` target_sequence placeholder is guarded in the legacy evaluator's CSV fallback path.
- **Deferred items:**
  - F6: Multi-chain binder support in BoltzGen YAML generation
- **PXDesign** full pipeline integrated: diffusion → MPNN → AF2 complex/monomer eval → summary CSV. Works on both x86_64 and aarch64 (with automated post-install patches).
- **Proteina-Complexa** integrated: NVIDIA flow matching + inference-time optimization. Uses uv venv (separate from Mosaic). Shares AF2 weights with BindCraft. Supports single-pass, best-of-n, beam-search, and MCTS search algorithms.

### Known issues

- **PXDesign site-packages patches:** The installer applies post-install patches to `protenix` (CUDA arch **and `-std=c++20`** — torch >= 2.9 headers hard-error on c++17), `pxdbench` (NumpyEncoder, **and `use_bfloat16=False` in the AF2 eval on aarch64** — jaxlib's AArch64 backend cannot lower a bf16 convert under SVE, so the eval subprocess SIGABRTs and surfaces only as a `JSONDecodeError` on the empty output file), and `configs_infer.py` (num_workers). These patches are reapplied on each install but would be lost if packages are upgraded manually.
- **PXDesign requirements.txt:** Pins `torch==2.3.1` (CPU-only from PyPI). The installer force-reinstalls PyTorch with CUDA after requirements.txt. Do not run `pip install -r requirements.txt` manually without reinstalling PyTorch afterward.
- **Mosaic `is_top` filtering:** Both extractors (Evaluator package `MosaicExtractor` and legacy `evaluator.py`) now default to `is_top=1` rows only (~40 refolded designs instead of all ~800). Use `--all-mosaic-designs` to override. The `target_sequence` CSV fallback also skips `"REPLACE_ME"` placeholders.
- **Mosaic CSV column mismatch:** `designs.csv` can mix two column formats when multiple workers run. Parser may misalign columns for some workers. Documented in `Evaluator/docs/pipeline_reference.md`.
- **BoltzGen pass rate is low:** In CALCA target testing, only 1/50 BoltzGen designs passed the `ipsae_min > 0.61` threshold. Sequences designed for Boltz-2 often don't cross-validate well.
- **BoltzGen sequence column (`designed_chain_sequence` vs `designed_sequence`):** Extract the binder from `designed_chain_sequence` (the full chain). `designed_sequence` holds only the *designed residues* — for nanobody CDR-redesign that is just the CDR subset (~25-40 aa), so refolding it feeds a truncated binder. Verified on 2VDY: nano `designed_sequence` len 24-42 vs `designed_chain_sequence` len 112-133 (full VHH). `BoltzGenExtractor._SEQUENCE_COL_CANDIDATES` was reordered to prefer `designed_chain_sequence`.
- **aarch64 BindCraft: FIXED by moving to jax 0.6.2.** On the old 0.4.34 pin the env looks healthy (GPU backend, pyrosetta imports) but any real AF2 forward pass aborts with `LLVM ERROR: Unsupported rounding mode for conversion` — jaxlib 0.4.34's LLVM has no sm_121, so bf16 cannot be lowered. `install/install_aarch.sh` now installs `jax[cuda12]==0.6.2`. If you meet this error, the env predates that change: `pip install -U "jax[cuda12]==0.6.2"` in it. Set `JAX_COMPILATION_CACHE_DIR` too — first compile is ~500 s (Triton autotuning), ~177 s cached.
- **aarch64 Mosaic:** May fail because `torchtext` has no Linux aarch64 wheel.
- **aarch64 Proteina-Complexa: installs and RUNS as of 2026-10-04; still deprecated for production because throughput is unmeasured.** This entry has now been wrong three times, each time about the blocker. PyG/torchtext were never it. Nor was a missing CUDA `jaxlib` — that exists. The "~130× slower" MCTS figure has **not** been refuted — a 2026-10-04 attempt to refute it measured a run whose AF2 reward never executed (all rewards 0.0) and was retracted the same hour. The actual blockers were **five defects in our own installer** (see the aarch64-specifics entry), which between them meant the AF2 reward never got onto the GPU and the tool could not even be re-installed to receive the fix. Nothing about aarch64 prevented any of it.
- **AF2 smoke test:** Fails if `BindCraft/params/` is missing `.npz` weight files (interrupted download).

### RFD3 / foundry runtime gotchas

The configurator now generates `run_rfd3.sh` from
`binderscout_examples/run_rfd3.sh.template`. The gotchas below still apply —
they live in the template and bit me on the CALCA run before being encoded
there:

- **`infer_ori_strategy: hotspots` is LOAD-BEARING in the input YAML, and omitting it fails SILENTLY.** Without it rfd3 centres the coordinate frame on the whole fixed motif's centre of mass (`set_com()`'s `else` branch) and seeds every diffused binder atom at that origin — so the binder nucleates *inside* the target rather than at the epitope and grows as an extended coil. There is no error, no warning, and the structures still report `n_chainbreaks=0`, so every downstream guard passes. Measured on CBG/2VDY (304 backbones lost, 2026-09-16):

  | | with the key | without |
  |---|---|---|
  | `metrics.fixed_com` magnitude | **23.05 Å** | **0.008 Å** |
  | binder radius of gyration | 10.9 Å | 23.1 Å |
  | DSSP helix fraction | 0.85 | 0.27 |
  | polyproline-II | 0.001 | **0.23** |
  | long-range contacts / residue | 1.19 | 0.21 |
  | MPNN Pro+Gly (same settings) | 0.059 | **0.286** |
  | binder pLDDT after refold | 0.84–0.89 | **0.38–0.44** |

  **Check it on batch 1**: every sidecar `.json` carries `metrics.fixed_com`; a magnitude near zero means the key is missing. The *configurator* emits this key correctly — the omission was in `binderscout_examples/run_rfd3.sh.template`, so a hand-written script copied from that template inherited it. Prefer `binderscout configure`. **The ApoE4 (6NCO) RFD3 run also omitted it** (`|fixed_com|` 0.02 Å, Rg 19.5 Å) — its RFD3 designs are suspect, and that campaign has already shipped a gene order.
- **MPNN Pro/Gly collapse is a *symptom*, not a cause.** If sequences come back Pro/Gly-rich with low hydrophobic content, suspect the BACKBONE before touching MPNN settings: ProteinMPNN is correctly describing a coil. A 4-arm sweep (as-run, milder bias, MPNN default, temperature-only) all failed identically on bad backbones, while MPNN's *default* settings on good round-1 backbones gave Pro+Gly 0.059 / hydrophobic 0.658. Gate on geometry (Rg/expected ≤ 1.45, long-range contacts ≥ 0.80/res) BEFORE spending MPNN time, and gate composition on **Pro+Gly and hydrophobic fraction**, not just alanine and Shannon entropy — a Pro/Gly coil scores Ala 0.016 and H 2.47 and passes both.
- **Output format.** RFD3 writes `.cif.gz` (compressed mmCIF), NOT `.pdb`. Decompress for downstream tools that need PDB.
- **Chain IDs.** Output mmCIF labels target as chain `A` (preserved residues from the input contig) and binder as chain `B` (designed). The `label_entity_id` column shows `0`/`1`, but the actual chain IDs at `label_asym_id` are letters.
- **MPNN CLI is `mpnn`, not `foundry mpnn`.** The `foundry` umbrella CLI only has `install` / `list-available` / `list-installed` / `clean`. Sequence design is its own console-script (`mpnn`).
- **`mpnn` requires `--is_legacy_weights True`** when called directly (the legacy `.pt` format is what `foundry install proteinmpnn` ships).
- **`--designed_chains` wants a JSON list of letter strings**, e.g. `'["B"]'` — not bare `B` and not `1`. Bare digits get parsed as int and rejected with `chain-id strings, got <class 'int'>`.
- **`FOUNDRY_CHECKPOINT_DIRS` is plural-S.** Singular `FOUNDRY_CHECKPOINT_DIR` is silently ignored (foundry's `checkpoint_registry.py` reads only the plural form). Effect: `rfd3 design` aborts with `Invalid checkpoint: rfd3` even when the .ckpt sits in your weights dir.
- **ProteinMPNN weights are NOT bundled with rfd3.** `foundry install rfd3` only fetches `rfd3_latest.ckpt` (~2.5 GB). Run `foundry install proteinmpnn` separately for the ~7 MB `proteinmpnn_v_48_020.pt` file. (For ligand binders you also need `foundry install ligandmpnn`.)
- **Reinit warnings on weight load are benign.** `foundry.utils.weights: Failed to apply policy: 'copy' to 'model.token_initializer.chunked_pairwise_embedder.*': Falling back to policy: 'reinit'` — these come from the chunked low-memory code path that the v0.1.9 checkpoint wasn't trained with. Output structures verify clean (n_chainbreaks=0, n_clashing=0, helix_fraction~0.9 for our CALCA helix).
- **MPNN best-of-N filter.** `mpnn --number_of_batches 5` writes 5 sequences per backbone in one `.fa` (each header tagged with `sequence_recovery=...`). To keep "best-of-5 per backbone", post-process: pick the highest-recovery sequence per file, strip the target prefix (first `len(target_seq)` chars), the remainder is the designed binder.
- **24 GB Ampere OOM mid-run from fragmentation, not capacity.** With `diffusion_batch_size=10 low_memory_mode=true`, peak live allocation is ~15 GiB but PyTorch reserves another ~6 GiB unallocated. Around batch 7 the next 3 GiB alloc fails even though the live working set fits 24 GiB easily. Fix: `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` before launching `rfd3 design`. The configurator's `write_run_rfd3` and `binderscout_examples/run_rfd3.sh.template` set this. (An x86_64 2VDY run: died at batch 7 of try-1; relaunched with this env var, completed all 20 batches cleanly in 23 h.)
- **`Found N existing example IDs` is informational, not skip-behavior.** RFD3 prints this at startup when example IDs already exist in `out_dir`, but it then re-runs all `n_batches` anyway and overwrites the existing files. There is no built-in resume — if a run crashes mid-way, expect a full re-run, not a delta. (Workaround if you only want the missing slice: move the completed `<id>.cif.gz`/`<id>.json` pairs aside, run with smaller `n_designs`, then put them back.)

### RFD4-Proteina runtime gotchas

The ninth tool, added 2026-10-27. Installed and run on a multi-user cluster first, with every command
logged; the configurator generates `run_rfd4.sh` from
`binderscout_examples/run_rfd4.sh.template`.

- **The contig resolves on the mmCIF `label_seq_id`, NOT `auth_seq_id`. This is the
  single thing that bites.** Both of the first two timing jobs died on it. A stock RCSB
  5O45 numbers PD-L1's domain `A18-132` in author numbering, but its label numbering runs
  `2-116`, so the contig `A18-132` is refused with *"Preserved segment 'A18-132' runs
  outside chain A, whose residues are 2-116"*. TrkA failed the other way round —
  `A282-382` matched no atoms and had to become `A5-105`. **The configurator now computes
  the segment from the label column itself, so this cannot recur through `binderscout
  configure`**; it prints both ranges when they differ. A hand-written YAML still can.
- **mmCIF only.** Upstream accepts `.cif` / `.cif.gz` / `.bcif`. A `.pdb` has no label
  column at all, so the configurator refuses it at configure time rather than converting:
  writing our own mmCIF would be an untested claim about the input format. Consequence
  worth knowing — the shipped `examples/CALCA/` target is a `.pdb`, so RFD4 is excluded
  from the test that otherwise exercises every design tool.
- **`'~metrics'` is required, and it is a Hydra removal, not a flag.** The native metrics
  block wants AF2/AF3 environments that are absent here, so the invocation ends
  `'~metrics'` — single-quoted, or the shell eats the `~`. Consequence: RFD4 contributes
  **no** native metric column, so its report block has nothing of its own to order by and
  `evaluate.sh` folds back the Boltz-2 rank for it, as it already did for RFD3.
- **Backbone and sequence come out together** — there is no MPNN step, so none of the
  RFD3 Pro/Gly-collapse reasoning above applies.
- **Chain B is the designed binder, chain A the preserved target**, one uncompressed
  `.cif` per sample at `<out_dir>/.../inference_samples/<name>_<i>/<name>_<i>_generated.cif`.
  Note RFD3 writes `.cif.gz` and this writes plain `.cif`.
- **A `timing/` and a `prod/` run side by side will silently pool.** The extractor refuses
  and names both roots instead; the real run had exactly this, and pooling would have
  padded a 360-design pool with 8 throwaways.
- **`import rfd4_proteina` and `rfd4-generate --help` both pass on a GPU-less node with no
  weights at all** — measured. So neither is a smoke test. The installer asserts
  `uv pip check`, a non-null `torch.version.cuda`, and the weights' exact byte count and
  sha256; it deliberately does *not* assert `torch.cuda.is_available()`, which is
  correctly False on a login node.
- **No root, and no `python3.12-dev`:** Triton JIT-compiles a C file that includes `Python.h` on the
  first generate call. The generated script finds the headers via `sysconfig`, falls back to a
  uv-managed interpreter's headers, and refuses up front (`uv python install <ver>`) if neither
  exists. Without this the arm dies ~8 s in with `Python.h: No such file or directory`, which reads
  like a CUDA fault and is not. `install --verify` cannot see it.
- **Cost, measured on one L40S:** ~5 s per design, GPU peak ~3 GiB (360 designs in 37 min,
  330 in 27.5 min). Generation is cheap; refolding the pool is what costs.
- **Deviations recorded rather than hidden:** we install the `cu130` torch backend where
  upstream pins cu132, and the weights licence is unverified (BSD-3 covers the code only).
- **First results, in silico only:** PD-L1 360 designs, median `consensus_iptm_mean` 0.598,
  81 at or above 0.8; TrkA 330 designs, median 0.209, 8 at or above 0.8. No binding was
  measured and no hit rate is claimed. The paper's 84%-of-188-TrkA-binders figure is
  experimental and is **not** replicated here. Full write-up:
  `docs/REPORT_2026-10-27_RFD4_Proteina_pool.md`.

### Protein-Hunter / boltz_ph runtime gotchas

The configurator now generates `run_protein_hunter.sh` from
`binderscout_examples/run_protein_hunter.sh.template`. The gotchas below
still apply — they live in the template and bit me on the CALCA run before
being encoded there:

- **`--msa_mode` valid values are `single` or `mmseqs`** — NOT `single_sequence`. The literal `single_sequence` raises `argparse: invalid choice`. `single` is the no-MSA mode (fastest, what we used on CALCA); `mmseqs` calls the ColabFold server.
- **Boltz-2 cache must live at `~/.boltz/`** with three things: `boltz2_conf.ckpt` (~2.3 GB), `boltz2_aff.ckpt` (~2.1 GB), and a populated `mols/` directory (~45 k .pkl files). If `mols/ALA.pkl` is missing, `design.py` aborts on startup with `ValueError: CCD component ALA not found!` — the canonical-residue tokenizer probes the directory for every standard amino acid.
- **`download_boltz2` requires a positional `cache: pathlib.Path` argument.** Bootstrap the cache with: `python -c "from boltz.main import download_boltz2; from pathlib import Path; download_boltz2(cache=Path.home()/'.boltz')"`. Passing a `str` (or omitting `cache=`) silently no-ops on some versions.
- **`pyrosetta-installer` ≥ 0.3 renamed `download_pyrosetta` → `install_pyrosetta`.** Our installer (`install/install.sh`) was updated in `7642942`. If you stand up a fresh `binderscout_protein_hunter` env outside the installer, use the new name.
- **Output layout creates a `{name}/` subdirectory under `save_dir`.** With `--save_dir runs/CALCA_helix/protein_hunter --name CALCA_helix`, the actual CSVs are at `protein_hunter/CALCA_helix/summary_*.csv` (path printed twice in the run banner — confusing but correct).
- **`summary_high_iptm.csv` row count > num_designs is normal.** Every cycle that crosses the `--high_iptm_threshold` gets a row, so 7-cycle runs with several passing cycles produce more rows than designs (CALCA: 133 rows from 100 designs).
- **"No structure was generated for run N (no eligible best design …)" is not a failure.** It just means none of the N cycles produced a sequence under the `--percent_X` alanine cap. Final-run row may be absent from `summary_all_runs.csv` for that reason.

### BindCraft 2 runtime gotchas

The configurator generates `run_bindcraft2.sh` from
`binderscout_examples/run_bindcraft2.sh.template`, and every guard below already
lives in that template — they are written down here because each of them fails
quietly or expensively, and a hand-written campaign inherits none of them.
**Not to be confused with BindMaster 2** (`docs/bindmaster2_grafts.md`), the
abandoned agentic concept whose orchestration capabilities were grafted onto the
Evaluator as `binder-compare` subcommands — that is evaluation machinery, not a
design tool, and it shares nothing with BindCraft 2 but a number.

- **A campaign has no time limit, and `number_of_final_designs` is a quota of *accepted* designs, not an attempt budget.** `max_trajectories` is the only cap in the package — grepping the whole tree for a wall-clock setting finds nothing but a socket timeout on the weight download. Left unset, a campaign runs until it fills the quota, however long that takes, and a hard target can need very many attempts per accepted design. Every other design tool in BinderScout is bounded by attempts, so budget BindCraft 2 by setting `max_trajectories` explicitly and treat the quota as a ceiling you may not reach.
- **ALWAYS name a modality.** With none named, BindCraft 2 applies no modality layer at all — the CLI help's "(default: binder)" is misleading — and the resulting null `binder_lengths` surfaces as a bare `TypeError` traceback rather than a clean refusal, so it reads like a bug in our run script.
- **On aarch64 BOTH `--set auto_multi_gpu=false` and `--set subbatch_size=null` are needed; one is not enough.** `design_gpu_memory_gb()` calls `float()` on nvidia-smi's memory reading behind an `except (OSError, CalledProcessError)`; GB10 answers `[N/A]`, which raises `ValueError` and escapes that handler, so the campaign is refused immediately after preflight. `auto_multi_gpu=false` silences only the first of two call sites — the campaign reaches the same call again through `campaign_subbatch_size` while `subbatch_size` is at its default of `"auto"`. Both are documented settings, so nothing in BindCraft 2's source is patched. Apply them from the run script on the machine that is *running*, never bake them into `campaign.json`: configs are generated on one machine and run on another, so a baked-in value would disable multi-GPU packing on x86 whenever an aarch64 box wrote the config, and would still crash on Spark whenever an x86 box did.
- **The compile cache is per *campaign* by default, so set `JAX_COMPILATION_CACHE_DIR` per machine — and append the card name yourself.** Left unset, the cache lands under the campaign's own project folder, and every new campaign re-pays the compile of every prediction shape from cold. But an operator-set `JAX_COMPILATION_CACHE_DIR` is used **verbatim**: the lookup short-circuits on it before the card is ever consulted, so BindCraft 2's own per-card keying is skipped. A compiled executable is not portable between GPU models, so the template appends a sanitised card name (`NVIDIA GB10` → `NVIDIA_GB10`) itself. Getting this wrong on a mixed-GPU host silently feeds one card's executables to another.
- **The ranked table is rewritten on every acceptance and can *shrink* at campaign close.** `3_Ranked/!_Ranked.csv` is rebuilt each time a design is accepted, and a reconcile pass at the end drops any row whose structure is no longer on disk — so a mid-run snapshot can be superseded by a smaller one. Any `--tool-csv` snapshot for a report must therefore be taken **after** the campaign exits, or we re-enter the known stale-`tool_csvs` failure mode where a tool's native block ships short.
- **BindCraft 2's own selfcheck EXITS 1 — it does not warn — when `--no-weights` is passed and no AF2 parameters can be found.** That is why the installer passes `--no-weights` only when it has actually located a parameter cache to reuse; passing it hopefully to save the ~5.3 GB download turns a slow install into a failed one.
- **Two output layouts, and structures are mmCIF.** v1.0.0 writes `3_Ranked/!_Ranked.csv` with lowercase `rank` / `design` / `Binder_Sequence`; the pre-1.0 build that produced our archived CBG/CALCA pools writes a flat `<target>_ranked.csv` with TitleCase `Rank` / `Design` / `Sequence`. Nothing in either file records which it is, so `BindCraft2Extractor` distinguishes them by column vocabulary alone. Only the ranked table is a design pool — `1_Trajectories/` holds pre-MPNN hallucinated sequences and `2_Refolded/` mixes rejected rows in with the passes.
- **`i_pDAE` is the ranking metric, and higher is better** despite reading like an error term. The `rank` column is a plain descending sort on it — not i_pTM, not a composite — and the delivered values are rounded to two decimals, so ties are pervasive (17-way in one archived pool). Rank *within* a tie block is acceptance order, not quality order. Read the rank from the tool's own file; never recompute it.

---

## Commands

### Quick start

```bash
git clone https://github.com/damborik22/BinderScout.git ~/BinderScout
cd ~/BinderScout

./binderscout.py install         # interactive menu (auto-detects standalone mode).
                                # The FIRST command must be the script: the `binderscout`
                                # shortcut is created BY the installer, into ~/.local/bin.
                                # That directory enters PATH from ~/.profile only if it
                                # already existed at LOGIN, so on a fresh account the
                                # short form below works in the next shell, not this one
                                # — the installer prints the `export PATH=…` to use now.
binderscout configure            # interactive wizard
bash runs/<name>/run_all.sh     # run all enabled tools
bash runs/<name>/run_evaluate.sh  # rank and report (drives Evaluator/evaluate.sh)

# Add BinderScout/bin to PATH:
export PATH="$(pwd)/bin:$PATH"
```

### Install

On a fresh clone run these as `./binderscout.py install …` — the `binderscout` shortcut
does not exist until the installer has run once (see Quick start above).

```bash
binderscout install                          # interactive tool selection
binderscout install --tool all               # install all current-generation tools
# NOTE: `all` does NOT include AF3 (its weights are gated — you request them from
# Google DeepMind yourself) or TmProt. So a fresh `--tool all` gives TWO refold
# engines (Boltz-2 + ESMFold2) against the report's default `--min-engines 3`, and
# every design then fails the cross-engine gate and is ranked last. The report says
# so loudly rather than silently. Either add `--tool af3` once you have the weights,
# or pass `--min-engines 2`. Verified 2026-09-27.
binderscout install --tool mosaic            # install one tool
binderscout install --tool all --yes --skip-examples  # non-interactive (CI)
binderscout install --tool proteina-complexa # install Proteina-Complexa
binderscout install --tool protein-hunter    # install Protein-Hunter (Part L)
binderscout install --tool rfd3              # install RFD3 / foundry (Part M)
binderscout install --tool rfd4              # install RFD4-Proteina (ninth tool; opt-in,
                                             # aarch64 installable but not yet run, NOT in --tool all; weights licence unverified)
binderscout install --tool bindcraft2        # install BindCraft 2 (eighth tool), cloned from upstream
# Clones https://github.com/PacesaLab/BindCraft2 at v1.0.1. Its licence is its own
# (hosting-restricted), so BindCraft2/ stays gitignored and nothing of it is committed here.
# --bc2-source overrides with a .zip, a directory or another git URL (or export $BINDCRAFT2_SOURCE).
binderscout install --tool esmfold2          # install ESMFold2 refolder individually (default engine; also in --tool all)
binderscout install --tool soluprot          # install SoluProt screen alone (also in --tool all; x86 + aarch64)
binderscout install --tool tmprot            # install the TmProt melting-temperature screen (opt-in,
                                             # NOT in --tool all; GPL-3.0, cloned not vendored)
binderscout install --verify --tool all      # audit what is on disk and exit; installs nothing
                                             # (tools built against another commit show as STALE)
binderscout install --repair --stale --tool all  # rebuild the STALE ones; plain --repair does not
binderscout install --repair --tool all      # audit, then re-install only what failed the audit
binderscout install --uninstall --tool all   # remove envs + shortcuts (preserves runs/)
binderscout install --standalone --tool all    # force local Miniforge install
binderscout install --system-conda --tool all  # use existing system conda
```

### Configure

```bash
binderscout configure             # interactive wizard
binderscout configure --config runs/<name>/config.json   # headless replay, no prompts
binderscout configure --config run.json --run            # …and start the pipeline
binderscout configure --status    # show all runs and completion state
binderscout configure --archive <run>  # tar.gz a run directory
```

### Status

```bash
binderscout status                  # this machine + every ssh alias in $BINDERSCOUT_FLEET
binderscout status --local          # this machine only
binderscout status --watch          # redraw every 60 s
binderscout status --json           # raw document; notices go to stderr, stdout is pure JSON
binderscout status --html FILE      # self-contained page, written atomically; serve it, no push
```

Three signals per arm (design count, process/GPU liveness, log silence): designs land in batches,
so a frozen count alone cannot tell a stalled arm from a healthy one. Campaign labels and deadlines
come from a machine-local JSON file named by `$BINDERSCOUT_CAMPAIGNS`; do not commit it. Do not
list the local machine in `$BINDERSCOUT_FLEET` (it is always probed).

### Evaluate

`binderscout evaluate` is a **passthrough to `binder-compare`** (run in the
`binder-eval` conda env) — every argument goes straight to that CLI. There is no
run-directory mode and no `--metric` / `--top` / `--refold` / `--target` flag; the
first argument must be a subcommand or argparse rejects it.

```bash
# Usual path: the configurator already wrote this, and it drives Evaluator/evaluate.sh
bash runs/<name>/run_evaluate.sh

# Full pipeline in one command (extract → refold-boltz2 → report)
binderscout evaluate run --mosaic runs/<name>/mosaic --bindcraft runs/<name>/bindcraft \
                       --bindcraft2 runs/<name>/bindcraft2 \
                       --rfd3 runs/<name>/rfd3 --rfd4 runs/<name>/rfd4 \
                       --target-seq "<TARGET_SEQ>" \
                       -o runs/<name>/evaluate

# Individual steps
binderscout evaluate extract --mosaic runs/<name>/mosaic -o seqs.fasta
binderscout evaluate extract --mosaic runs/<name>/mosaic --all-mosaic-designs -o seqs.fasta
binderscout evaluate report --boltz2-results boltz2.csv --af3-results af3.csv \
                          --esmfold2-results esmfold2.csv --sequences seqs.fasta -o ./report
binderscout evaluate report --min-engines 2 …   # relax the cross-engine gate (floor 2)

# Fold bare sequences without a run directory
binderscout evaluate parse-seqs --input my_seqs.txt -o seqs.fasta
binderscout evaluate validate --sequences seqs.fasta --target-seq "<TARGET_SEQ>"

binderscout evaluate --help    # all 22 subcommands
```

### Linting and CI

```bash
# Python
ruff check .
ruff format --check .

# Shell
shellcheck --shell=bash --severity=warning \
    install/install.sh install/install_aarch.sh \
    Evaluator/evaluate.sh Evaluator/install.sh Evaluator/run.sh \
    docker-entrypoint.sh test_env.sh
```

### Testing

```bash
# Docker test environment
docker build -f Dockerfile.test --target base -t binderscout-test .
docker run --rm -it binderscout-test bash

# Dry-run (non-interactive, reports pass/fail)
./test_env.sh --dry-run

# With GPU
./test_env.sh --gpu

# Clean up test artifacts
./test_env.sh --clean
```

### Full Evaluator pipeline (Evaluator/)

```bash
# Extract sequences from all tool outputs (Mosaic: is_top=1 only by default)
conda run -n binder-eval binder-compare extract \
    --bindcraft DIR --bindcraft2 DIR --boltzgen DIR --mosaic DIR \
    --pxdesign DIR --proteina-complexa DIR \
    --protein-hunter DIR --rfd3 DIR --rfd4 DIR \
    -o seqs.fasta
# To include all Mosaic designs (not just refolded):
#   binder-compare extract --mosaic DIR --all-mosaic-designs -o seqs.fasta

# Refold with Boltz-2 (must use Mosaic venv, NOT conda)
Mosaic/.venv/bin/binder-compare refold-boltz2 \
    --sequences seqs.fasta --target-seq SEQ -o boltz2.csv

# Refold with AF3 v3.0.2 (canonical 2nd engine — Spark / H200 / 24 GB consumer GPUs)
conda run -n binder-eval-af3 binder-compare refold-af3 \
    --sequences seqs.fasta --target-seq SEQ -o af3.csv

# Generate report (any subset of refold outputs can be passed)
conda run -n binder-eval binder-compare report \
    --boltz2-results boltz2.csv \
    --af3-results af3.csv \
    --sequences seqs.fasta -o ./report
```
