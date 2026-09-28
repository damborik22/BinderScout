# BinderScout 2.0 — handoff index

Everything needed to pick up 2.0. **You have the repo**, so most of this points
at files already in it rather than copying them — a second copy of `CLAUDE.md`
drifts from the first within a week. Only `DIARY_2.0.md` lives here, because it
is an extract that exists nowhere else as a standalone file.

| | |
|---|---|
| **Branch** | `v2.0.x` — all 2.0 work. `master` is frozen at 1.0.3, `v1.1.x` is the BindCraft 2 line |
| **Version** | **2.0.0**, carried in `binderscout.py`. **Not tagged** — newest tag is still `v1.1.1` |
| **State** | 887 tests passing, 7 skipped; ruff + shellcheck clean; working tree clean; CI green |

---

## Read in this order

### 1. Start here — what 2.0 is and where it stands
**[`docs/PLAN_2.0_CONCLUSION.md`](../docs/PLAN_2.0_CONCLUSION.md)**

Self-contained. What was done, what is left and why, the three open decisions,
the findings that cost real time, the platform reality, and what needs a machine
this one is not. If you read one file, read this.

### 2. The decisions that are waiting on a human
**[`docs/MORNING_DECISIONS.md`](../docs/MORNING_DECISIONS.md)**

Three live ones, each with the options and a standing recommendation. §1
(pre-filtered pools) blocks finishing Stage 1 and is the only one that blocks
code.

### 3. Per-stage detail
**[`docs/NEXT_STAGES.md`](../docs/NEXT_STAGES.md)**

What the conclusion compresses. Note it predates the 2026-09-27 refold session,
so a few lines in it are stale — the conclusion doc lists which.

### 4. Before touching code
**[`CLAUDE.md`](../CLAUDE.md)**

The project's canonical self-description: environment isolation (never mix
packages across envs), the ranking rules and what was removed from them, and
per-tool runtime gotchas that each cost a campaign to learn.

> **One live caveat.** Its claim that AF3 "runs fleet-wide (BM1/BM2/BM4)" is
> marked **in doubt** in place, with the measurement and the reason. It will not
> mislead you, but it is the one knowingly-uncertain statement in that file.

### 5. How the findings were reached
**[`DIARY_2.0.md`](DIARY_2.0.md)** *(in this folder)*

The 2.0 chapter of the repo diary — 8 entries, 771 lines. Records the wrong
turns as well as the conclusions, which is the part that stops them being
repeated. Extracted from `docs/REPO_DIARY.md`; the diary is the living copy.

---

## Read only if the work reaches them

| if you are working on | read |
|---|---|
| **Stage 1 / `generation_index`** | [`docs/INVESTIGATION_generation_index_2026-09-24.md`](../docs/INVESTIGATION_generation_index_2026-09-24.md) — the per-tool verdicts on what generation order can honestly be recovered. Small and load-bearing |
| **the ranking** | [`docs/INVESTIGATION_partU_cao_benchmark.md`](../docs/INVESTIGATION_partU_cao_benchmark.md) — the evidence behind "one ranking, no way to choose another", and why each removed alternative stays removed |
| **affinity ranking** | [`docs/completed_plans.md`](../docs/completed_plans.md) — archives Part N's negative result |
| **the original plan** | [`docs/PLAN_binderscout_v2.md`](../docs/PLAN_binderscout_v2.md) **together with** [`docs/PLAN_binderscout_v2_corrections.md`](../docs/PLAN_binderscout_v2_corrections.md) — **never the first alone.** The plan contains premises later measured false; the corrections file is what says which |

---

## Not part of this handoff

The repo holds ~14 other `PLAN_*` / `INVESTIGATION_*` documents — BindCraft 2
integration, the AF3 Spark runbook, fleet orchestration, SoluProt, BM5 unified
memory, the virtual-lab concept. All real, none about 2.0.

`docs/REPO_DIARY.md` in full is 2,858 lines, of which 2,098 predate 2.0.

---

## Confirm the state before trusting any of it

```bash
git rev-parse --abbrev-ref HEAD          # v2.0.x
git status --short                       # empty
./conda/envs/binder-eval/bin/python -m pytest tests/ -q   # 887 passed, 7 skipped
uvx ruff check . && uvx ruff format --check .
./install/install.sh --tool all --verify # audits what is actually on disk
```

---

## The one habit worth carrying over

2.0 spent most of its time on code that was **present, looked complete, and was
either unwired or unverified** — not on missing features. Five installer
verifiers passed environments that could not run; five test guards passed the
mutations they were written to catch.

So: write the guard as a test, then **mutate the code and confirm the test goes
red — and assert that the mutation applied.** A mutation that silently fails to
apply leaves a green test proving nothing. That happened twice here, and both
times it was caught only by checking rather than by reading.
