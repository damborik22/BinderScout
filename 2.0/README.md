# BinderScout 2.0 — handoff index

Everything needed to pick up 2.0. **You have the repo**, so this points at files already in it
rather than copying them — a second copy of `CLAUDE.md` drifts from the first within a week.
The diaries and the planning records are deliberately not in the repo (sensitive data and
unpublished results); they live only on the lab's private share.

| | |
|---|---|
| **Branch** | `v2.0.x` — all 2.0 work. `master` is a **separate `v1.2.x` line**: the two share a single merge base (`602345a`, `v1.0.3`) and have diverged since, so a fix cannot be cherry-picked between them — diff the trees and re-apply. `v1.1.x` was retired to the tag `archive/v1.1.x`. |
| **Version** | Tags `v2.0.0`, `v2.0.1` and `v2.0.2` exist; **`v2.0.3` is in preparation**. The version is carried in `binderscout.py`. |
| **Install** | One tree. `install/install.sh` on x86_64, `install/install_aarch.sh` on aarch64. There is no `aarch64` branch. |

## Read in this order

1. **`CLAUDE.md`** — the project's own memory: architecture, the one ranking, every platform and tool gotcha that cost a campaign to learn. Start here and trust it over any other summary.
2. **`CHANGELOG.md`** — what changed and why, release by release. `[Unreleased]` is the work since `v2.0.2`.
3. **`Evaluator/docs/`** — how the evaluator scores (`evaluation/ranking.md`, `evaluation/metrics.md`) and `pipeline_reference.md` (metrics, known issues, `--save-pae-bins`, the structure-path remap).
4. **`README.md`** — install, configure and evaluate, with the exact commands.
5. **`CONTRIBUTING.md`** — dev setup, lint, tests, and the *Releasing* checklist.

## Not in the repo

- **The diaries** (`DIARY_2.0.md`, historical `REPO_DIARY.md`) and the **planning records** (the 2.0 plan and its conclusion, the Part AK plan, the investigations, the pool reports). They record how each finding was reached, including the wrong turns. The planning records were removed from the tree on 2026-11-03 (the history is intentionally untouched). Ask for them on the lab's private share.

## Confirm the state before trusting any of it

```bash
git describe --tags            # nearest tag, then commits since
python -m pytest tests -q      # use the binder-eval env's interpreter
```
