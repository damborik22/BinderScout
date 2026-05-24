---
name: bindmaster-orchestrator
description: Use this skill when planning, dispatching, and evaluating a BindMaster binder-design campaign. Triggers include any mention of orchestrating a binder campaign, deciding which design tool to run on which target, writing kickoff docs for compute nodes, managing PROGRESS.md state across machines, or running the cross-engine refold + iPSAE merge after results return. Use whenever the user says "let's start a campaign on <target>", "what should we run next", "which tool fits this target", "merge the results", "evaluate the pool", or refers to BindMaster, ApoE4 binders, CBG binders, 2VDY, or similar binder-design contexts. The sibling skill `bindmaster-worker` handles the per-machine execution layer.
---

# BindMaster Campaign Orchestration — SKILL base

**Audience:** an AI agent acting as the *orchestrator* of a BindMaster binder-design campaign — typically running on Spark. The orchestrator coordinates work across multiple compute nodes (BM2, BM4, Clara, others as available); each worker is either a Claude Code instance reading the assignment locally, a remote session driven by the orchestrator over VPN/SSH, or a human. This skill is meta — for per-tool engine principles see `references/tools/`, for empirical campaign lessons see `references/learnings.md`, for the local cross-engine refold + iPSAE merge recipe see `references/evaluation.md`, and for the worker-side operational playbook see the sibling skill `bindmaster-worker`.

**When you read this:** at the start of any campaign session, after `MEMORY.md`, before touching the run dirs. It encodes patterns that took a full campaign (2VDY / human CBG, May 2026) to learn.

**What this skill is NOT:**
- Not a recipe for any single tool — engine principles live in `references/tools/<tool>.md`, operational gotchas live in `CLAUDE.md` (BindMaster repo) and the worker skill.
- Not a status report — `RESULTS/PROGRESS.md` is the live state.
- Not a substitute for thinking about the specific campaign. Adapt heuristics, don't paste them.

---

## 1. Mental model

A campaign is a **swarm of independent design jobs** running on compute nodes that don't share filesystems with each other, coordinated through two shared artifacts on muni-disk:

- **`RESULTS/PROGRESS.md`** — the single source of truth for "what's done / running / queued / failed."
- **`CLUSTER/<tool>_<machine>_SETTINGS.md`** — kickoffs you write and worker Claudes (or remote sessions) execute.

Workers report back via:
- `RESULTS/<tool>_<machine>.tar.gz` (final outputs, packaged)
- PROGRESS.md "Worker updates" appends (with SLURM IDs, wall-clocks, yield counts)

**The orchestrator runs on Spark.** The three cross-engine refolders (Boltz-2, Protenix, AlphaFold 3) all have their conda envs on Spark — refolding is done locally as code, not dispatched as jobs. Design tools that need bigger GPUs or specific architectures run on remote workers (BM2, BM4, Clara, …) and ship tarballs back to RESULTS/ on muni-disk.

**The orchestrator's job is:**
1. Read PROGRESS.md and CLUSTER/ to know the current state.
2. Decide what to run next (which tools on which machines, what settings).
3. Draft per-machine assignments in CLUSTER/.
4. Track work as it lands, merge worker updates into PROGRESS.md.
5. After tarballs return, run cross-engine refold + iPSAE merge locally on Spark (see `references/evaluation.md`).
6. Recognize when to kill, scale, pivot, or stop.

**The orchestrator's job is NOT:**
- Running the actual design jobs (that's the worker on each compute node).
- Knowing every tool's CLI flags (that's in `references/tools/`, the worker skill, and `CLAUDE.md`).
- Babysitting per-stage progress (the Monitor tool can filter that; humans don't want per-stage notifications).

---

## 2. File / location conventions

A mature 2VDY-style campaign has this layout. Reuse it for new targets.

```
muni-disk/.../<TARGET>/
├── PDB/                                       ← input structures (.pdb, .cif)
├── CLUSTER/                                   ← assignments to workers
│   ├── <TARGET>_<tool>_<machine>_SETTINGS.md  ← kickoff per tool-machine pair
│   ├── relaxed_filters_V2.json                ← stashed presets for workers to copy
│   └── default_4stage_multimer_*.json         ← stashed presets
└── RESULTS/                                   ← outputs land here
    ├── PROGRESS.md                            ← source of truth, append-only history
    ├── <TARGET>_<tool>_<machine>.tar.gz       ← packaged final outputs
    ├── <TARGET>_<tool>_<machine>.zip          ← smaller variants for finals subset
    └── <older trial dirs>                     ← keep, don't delete (negative results matter)
```

On Spark (the orchestrator's home):

```
~/dev/BindMaster/                              ← cloned repo
~/.claude/skills/bindmaster-orchestrator/      ← this skill
~/.claude/skills/bindmaster-worker/            ← sibling skill (used when Spark drives a remote worker)
Mosaic/.venv/                                  ← Boltz-2 refold env
bindmaster_pxdesign/                           ← Protenix refold env (Part J)
binder-eval-af3/                               ← AlphaFold 3 refold env (Part K, aarch64)
~/eval_workdir/                                ← local refold scratch
~/.claude/.../memory/MEMORY.md                 ← persistent cross-session lessons
```

On each worker machine (BM2, BM4, Clara, others):

```
~/dev/BindMaster/                              ← cloned repo
~/runs/<TARGET>-<machine>-<tool>/              ← per-tool run dir, mirrored to RESULTS later
```

Persistent memory at `~/.claude/projects/.../memory/` is the orchestrator's notebook across sessions. Index file is `MEMORY.md`, one file per memory.

---

## 3. State management: PROGRESS.md discipline

PROGRESS.md is append-only history *and* current-state dashboard in one file. Both functions matter; design accordingly.

### 3.1 Top-of-file fields

```markdown
# <TARGET> Binder Campaign — Progress & Plan

**Last updated:** <YYYY-MM-DD HH:MM ZONE> (one-line delta since last update)
**Target:** <name, source, chain, length>
**Goal:** <pool size → cross-engine refold → top-N for experimental testing>
**Per-tool target:** <e.g. ~50 final designs>

## <Target>-specific hotspots, MSA, etc.
<inputs that all tools share>
```

The "Last updated" line is meta: every time you edit PROGRESS, replace the timestamp and append a terse delta. Long users (and future-you) skim this to learn what happened since last session.

### 3.2 Status table — one row per tool-machine pair

| Tool | Machine | Status | Designs | Notes |
|---|---|---|---|---|
| **BindCraft (tuned)** | Clara L40S | ✅ done (SLURM 100040, 2026-05-22) | **10 accepts** | wall, settings, packaging file, top metrics, key gotchas, link to kickoff |

**Required cells per row:**
- **Tool**: name + variant in bold (e.g. "BindCraft (tuned)", "Proteina-Complexa (MCTS)")
- **Machine**: where it ran (BM2, Clara H200, Spark, …)
- **Status**: one icon — `✅` done, `🔄` running, `⏳` queued, `❌` failed/killed, `⏸` paused. Add SLURM ID, date.
- **Designs**: yield count + quality at key thresholds, packaging filename
- **Notes**: compute hours, key settings, the *why* of any non-obvious choice, link to the kickoff doc in CLUSTER/

**Don't delete failed rows** — record them with ❌ and explain the failure mode. The campaign-level lessons (e.g. "V1 defaults yields 0 on this target") come from negative results.

### 3.3 Sections beyond the status table

- **"Done — outputs available"** — numbered list of packaged outputs in RESULTS/, with one-line summaries. Cross-reference rows in the table.
- **"In progress"** — short bulleted list of what's actively running. Optional (the status table already shows 🔄), but useful for human readers.
- **"Final stage"** — cross-engine refold + ranking plan. Once tarballs are in, the orchestrator runs `references/evaluation.md` locally on Spark; this section tracks that step.
- **"Key design settings used"** — per-tool settings tables. Update when configs change.
- **"Errors observed"** — table of `machine | GPU | tool | error | resolution`. Add a row for each new error encountered.
- **"Lessons learned"** — narrative subsections (e.g. "MSA mode for known targets", "PC beam-search wedge"). These are the campaign's IP — write them when the lesson is fresh and the data supports it. Cross-campaign generalizable lessons go to `references/learnings.md`.

### 3.4 PROGRESS.md anti-patterns

- **Stale sections.** If you change BM2 from "hotspots on" to "hotspots off", grep the whole doc and update every mention. The header "Key design settings" table at the bottom went stale during the 2VDY campaign — confused everyone re-reading the doc.
- **Hand-wavy yields.** "Many designs" is useless; "22 accepted, 236 rejected, 22% of MPNN candidates accept" is actionable.
- **Missing the "why."** Every settings choice (length cap, hotspots, threshold) should have a one-clause rationale in Notes.
- **Conflating scoring engines.** "iPTM 0.85" means different things in PH (Boltz-2+MSA) and PC (AF2-multimer). Always say which engine. (See `references/tools/README.md` cross-method bias matrix.)

### 3.5 Producer-consumer file ownership

PROGRESS.md has strict per-section ownership to prevent merge conflicts when orchestrator and workers write concurrently:

- **Top of file → orchestrator-owned.** Status table, Lessons learned, Done / In progress / Final stage sections, Errors observed table. The orchestrator writes these freely. Workers read but never edit.
- **Bottom "Worker updates" section → worker append-only.** When a worker finishes (or hits a milestone), it appends a timestamped entry. The orchestrator integrates these into the canonical sections on the next read.

File structure:

```markdown
# <TARGET> Binder Campaign — Progress & Plan

[orchestrator-owned sections: header, status table, lessons, etc.]

---
## Worker updates (append-only, orchestrator merges on next read)

### 2026-05-24 14:23 — Clara L40S — BindCraft tuned
🔄 → ✅ | SLURM 100040 done. 10 accepts, 2.7 h wall.
Packaged: 2VDY_BindCraft_Clara.tar.gz at RESULTS/.
Compute: 27.5 GPU-h on L40S.
New error: <if any>.
New lesson: <if any>.
```

Each worker entry needs: timestamp, machine, tool variant, state transition, packaging filename, compute hours, optional notes for errors/lessons.

**Orchestrator's merge protocol:**
1. On read, scan worker updates section for entries newer than the last-merged timestamp.
2. For each new entry, update the corresponding status table row, append to Errors observed / Lessons learned if relevant, update Done / Final stage sections.
3. After integration, the worker entry can be deleted from the bottom section *or* kept as audit trail — orchestrator's choice per campaign.

This pattern lets multiple workers report concurrently without ever editing the same lines.

---

## 4. Lifecycle per work unit

Each work unit = (one tool) × (one machine) × (one config). Three phases:

### Phase 1 — Set up + start

Orchestrator side (you, writing the assignment):

1. **Identify the gap.** What's missing from the candidate pool? Different tool? Different config? Different architecture? Don't run duplicates without methodological justification. Cross-reference `references/tools/<tool>.md` for engine principles when deciding.
2. **Draft the kickoff doc** at `CLUSTER/<TARGET>_<tool>_<machine>_SETTINGS.md`. Required sections:
   - **Why this run** (1 paragraph — what gap it fills, what evidence supports the config)
   - **TL;DR target_settings** (the JSON or equivalent the worker will paste)
   - **Settings table** with `Param | Value | Why` columns. Every cell needs a "why."
   - **Step-by-step**: clone → install → configure → run, with concrete commands
   - **Runtime expectation** (yield × compute math, GPU-specific times)
   - **Output handoff** (tar/zip command, destination, PROGRESS update template)
   - **Critical gotchas** (the per-tool traps that have bitten us — see `references/learnings.md` and the worker skill's tool playbooks)
   - **Pinned**: BindMaster commit SHA used
3. **Stash any non-stock files** the worker will need (e.g. `relaxed_filters_V2.json`) in `CLUSTER/` next to the kickoff.
4. **Add a queued row** to PROGRESS.md status table.

Worker side (the per-machine Claude, the orchestrator driving a remote session, or a human — see the sibling `bindmaster-worker` skill for the operational playbook):

1. Pre-flight checks (env present, GPU available, disk free).
2. Set up: source env, register target, generate sbatch/run script.
3. Submit. Append a started-entry to PROGRESS.md "Worker updates" with SLURM ID and 🔄.

### Phase 2 — Monitor

The orchestrator should **not** be checking per-stage progress directly — that's the worker's responsibility, and humans don't want that noise.

Orchestrator's monitoring is **state-level**, not progress-level:

- Read the PROGRESS.md "Worker updates" section on each session. Merge new entries (§3.5).
- If a run goes silent for >1 day past its expected completion, ask the user to check.
- If the orchestrator is also driving a remote session on a worker (VPN-on-Spark mode), it can check at coarse intervals (every few hours), and only report milestones to the user (first accept, halfway, completion, crash).

Per-stage chatter (BindCraft "Stage 2 Softmax", PC checkpoint counters) belongs in the worker's monitor stream, not in your conversation with the user. Configure Monitor filters narrowly — see the `feedback_monitor_verbosity.md` memory.

### Phase 3 — Evaluate + handoff

When a run finishes (whether success, failure, or planned kill):

1. **Verify outputs.** Use the source-of-truth files per tool. Don't trust `ls Accepted/` for BindCraft — it always has 4 empty subdirs even with zero accepts; count rows in `final_design_stats.csv` instead. The worker skill's per-tool playbooks list source-of-truth files for each.
2. **Compute the deliverable metrics:** accepts vs target, top-tail at standard thresholds, length distribution, wall-clock vs expected. Compare to other runs of the same tool.
3. **Package** as `<TARGET>_<tool>_<machine>.tar.gz` (or `.zip`). Include the full run dir for evidence; for very large outputs offer a `_final` subset alongside the `_full`.
4. **Move to RESULTS/.** Worker handles SCP/rsync; if VPN switching is required (Clara→MUNI), the worker announces the switch.
5. **Worker appends to PROGRESS.md** — `🔄 → ✅` or `❌`, packaging filename, final numbers, errors, lessons (§3.5).
6. **Orchestrator merges on next read** — integrates worker entry into canonical sections.
7. **Don't delete the worker-side copy** until the user confirms the muni-disk archive is readable.

**Phase 3' — Campaign-level evaluation (orchestrator-local, on Spark).**

Once enough tools have returned tarballs to constitute a pool worth merging:

1. Stage all returned tarballs under `~/eval_workdir/<TARGET>/` on Spark.
2. Run cross-engine refold: Boltz-2 (default), Protenix (Part J), AlphaFold 3 (Part K, aarch64 only). All three are local conda envs; call them as code, not jobs. See `references/evaluation.md` for the recipe.
3. Apply the iPSAE merge: DunbrackLab 2025 `d0_res` variant, uniform 10 Å PAE cutoff, four-tier classification (High > 0.80, Medium 0.61–0.80, Low 0.40–0.61, Reject ≤ 0.40).
4. Rank by `agreement_count` desc, then `ipsae_min` desc.
5. Each tool's native metrics are preserved alongside the cross-method comparator — the evaluator is an unbiased judge across methods, not a replacement for any tool's native ranking.

---

## 5. Cross-machine patterns

The 2VDY campaign used these patterns. Reuse them or improve on them.

### 5.1 Parallel mirror (same config, different seeds)

Multiple machines running the **same** tool with the **same** settings, on different random seeds. Doubles candidate pool. Use when:
- The tool's yield is bottlenecked by exploration, not by config
- We have an unproven config that needs to be validated against statistical noise

Example: BindCraft tuned ran on BM2, BM4, Clara L40S, Spark — same V2/V4 preset, four independent seed pools.

### 5.2 A/B test (different configs, same target)

Two parallel runs differing in *one* knob. Decisive about which config to keep. Use when:
- A reasonable-looking config has unknown yield on this target
- You can't predict ahead of time which knob value will win

Example: Clara L40S ran V2+V4 (100040) and V1+default (100039) side-by-side on the same target. 10 accepts vs 0 accepts settled the question decisively in 3 days.

**Important**: have a kill criterion BEFORE launching the A/B. Otherwise the losing arm runs forever ("might yet produce one!"). Pre-commit to "kill if 0 accepts after N trajectories or T days."

### 5.3 Architectural diversity (same config, different chip)

Same tool + same config, but x86 vs aarch64 (or different CUDA archs). Floating-point ordering differs, so trajectory dynamics diverge and the accepted-design population is partially distinct.

Example: BindCraft tuned on x86 (Clara L40S) vs aarch64 (Spark GH200). Hypothesis: ~30-50% of accepts are arch-specific.

Cost: one new install on the unusual arch, plus the campaign-specific install gotchas (CLAUDE.md aarch64 section).

### 5.4 Methodological diversity (different lever)

Same tool with a different *kind* of search. Not a config tweak; a fundamentally different algorithm.

Example: PC ran best-of-n first (101082, succeeded), then beam-search (101023, wedged), then MCTS (queued). Each tests a hypothesis about whether the model has high-quality modes that the previous algorithm missed.

This is high-EV when you have a "we got median 0.15, top 0.85 but only 1" problem — best-of-n's iid sampling might be missing modes that smart search would find.

### 5.5 Reproducing a prior win

You have empirical evidence (a prior run, possibly old, that produced a high-quality result with a specific config). Reproduce that config on fresh machines to harvest more samples from the same regime.

Example: 2VDY_0002 (Feb 2026) produced 1 BindCraft accept at iPTM 0.90 with `default_filters + default_4stage_multimer_hardtarget`. Spark and Clara L40S are now queued to reproduce that preset combo, target 5 accepts each.

Honest-pushback corollary: **Don't extrapolate yield linearly from a single observation.** The 0002 result was 1/415 rejected — that yield rate is the floor of statistical confidence, not the ceiling.

### 5.6 Kill criteria

Pre-commit. Examples that worked on 2VDY:

- "Kill V1+default if <1 accept after 60 trajectories and tuned has ≥3."
- "Kill PC beam-search if 0 PDB outputs after 24h (the wedge mode)."
- "Kill BindCraft if process RSS >50 GB (JAX leak — BM4 was killed by the kernel at 58 GB after 9 days)."
- "Kill any run if it exceeds 2× its initial wall-clock budget without finishing."

Document the kill criterion in the kickoff doc, not just in your head.

---

## 6. Decision-making heuristics

### 6.1 Math first

Whenever the user proposes a new run or a new threshold, work the math before agreeing. Yield × time × compute. Be specific about:

- **Yield**: pass rate at threshold (use prior runs' empirical distribution)
- **Time**: per-trajectory or per-sample wall-clock on the target GPU
- **Compute**: total GPU-hours, days at the configured wall limit

Example exchange that saved us from a bad path:

> User: "Should I run PC again to get 50 with iPTM ≥ 0.85?"
>
> Honest math: PC 101082 yielded 1/1000 ≥ 0.85. To get 50 → ~50,000 evaluated → ~62 days H200. Not viable.
>
> Counter-proposal: lower threshold to 0.70 (current 13/1000) → 4 more runs (5 days) gives ~65 ≥ 0.70. Or switch to hotspots ON (distinct lever) — 1 run, 30 h, unknown but potentially better distribution.

User gets to choose; you provide the cost model.

### 6.2 Thresholds are tools' choices, not your aesthetic

If a user says "I want iPTM ≥ 0.85," that's a goal, not an immutable constraint. If the tool's distribution doesn't reach there, say so. Don't quietly lower the threshold; don't quietly run forever.

### 6.3 Don't compare scoring engines directly

iPTM from Boltz-2 (with target MSA) ≠ iPTM from AF2-multimer. Empirically on 2VDY, PC's top tier ≥0.70 corresponds roughly to PH's top tier ≥0.85 — different engines, different bars. Cross-engine refold + `ipsae_min` agreement is what unifies them at the campaign's final ranking. See `references/tools/README.md` cross-method bias matrix.

### 6.4 Negative results are evidence

`2VDY-Clara-BindCraft-defaults-100039.zip` packaged a 0-accept run intentionally — it's evidence that V1+default doesn't work on this target. Keep these archives. Future campaigns benefit from knowing what failed.

### 6.5 When to spawn a new machine vs. stretch the current one

- New machine: when the bottleneck is throughput AND parallel runs don't conflict (independent seeds OK)
- Stretch current: when the bottleneck is config or yield (more GPU doesn't help if the algorithm is stuck)
- Both: when there's methodological value in architectural diversity (5.3)

### 6.6 Cheap-first ordering

Try low-risk, low-compute experiments first. The 2VDY ordering ended up being:
1. PXDesign (works everywhere, fast)
2. RFD3 (cluster CLI traps but fits 24 GB)
3. BindCraft tuned (multiple machines)
4. BoltzGen (slow but reliable)
5. PH + PC + Mosaic on Clara H200 (need 80+ GB)
6. BindCraft hardtarget variant (high-quality / low-yield specialty)
7. PC MCTS, BindCraft Spark (architectural / algorithmic diversity)

Each later step builds on what's known to work from earlier ones.

### 6.7 Propose, don't decide silently

The orchestrator's "decide best settings for each tool" job is real, but the decision authority stays with the user. The pattern: read `references/tools/<tool>.md` for the engine constraints + `references/learnings.md` for campaign-tested empirical lessons, propose the settings with rationale and cost model, then let the user confirm before any compute commits. Never silently spend GPU on the orchestrator's own judgement.

---

## 7. Communicating with workers

Workers don't see your conversation history. They have:
- Their machine's local state
- The CLUSTER/ assignment doc you wrote
- PROGRESS.md (read-only for context; append-only to Worker updates section)

The worker may be a local Claude on the compute node, an orchestrator-driven remote session (VPN-on-Spark), or a human. The assignment doc is the contract regardless. The sibling `bindmaster-worker` skill handles the operational playbook on the worker side.

Assignment doc structure (repeat from §4.1 for emphasis — this is the hand-off contract):

```markdown
# <TARGET> — <Tool> <Variant> Settings (<machine>)

**Target hardware:** <GPU, memory>. <Why this hardware fits.>
**Run name:** <TARGET>-<machine>-<tool>

## 1. Why this run
<One paragraph: gap filled, evidence cited.>

## 2. Settings table
| Param | Value | Why |
|---|---|---|
<every cell justifies the choice>

## 3. target_settings.json (or equivalent)
<copy-pasteable>

## 4. Setup / install
<commands worker will run, in order>

## 5. Runtime expectation
<yield × time × compute math, ETA, kill criterion>

## 6. Output handoff
<tar/zip command, destination, PROGRESS row update template>

## 7. Critical gotchas
<tool-specific traps that have bitten this campaign>

## 8. Pinned
<BindMaster commit SHA, branch>
```

When a worker appends to PROGRESS.md (Worker updates section), expect:
- SLURM ID
- Wall-clock time
- Accepts/rejects/yield numbers at the standard thresholds
- Packaging filename + size
- Any new errors observed
- Any new lessons

If they didn't include something you need, ask in the orchestrator-owned section (write a `TODO:` line in the row).

---

## 8. When to stop and ask the user

Routine ops you can do without confirming (orchestrator side):
- Read any file, run `git status`, run `git log`, `git pull --rebase` if clean
- Edit PROGRESS.md to reflect known state (orchestrator-owned sections only)
- Write/update assignment docs in CLUSTER/
- Add a queued row to PROGRESS for a new run idea
- Tar a finished run and copy to RESULTS/ (when orchestrator is also doing worker duty)
- Run local cross-engine refold on Spark for designs already in RESULTS/

Always pause and ask before:
- **Killing a running job** (`scancel`, `kill`). Irreversible — even if it looks stuck. Could be 2 minutes from finishing.
- **Deleting any run dir or archive.** Lustre is 3 PB; muni-disk is large. Disk space is never the reason to delete.
- **Switching VPNs.** Announce explicitly: "I need to switch from X VPN to Y VPN to do Z." (Critical for Spark when driving Clara remotely.)
- **Changing campaign-level parameters mid-run.** If user said target=50 and you want to drop to 30, ask.
- **Spending >24 H200-hours on a single new experiment** without prior agreement.
- **Force-pushing or amending shared commits.**
- **Submitting jobs that would dominate a cluster partition.**
- **Triggering a campaign-level cross-engine refold** that would lock Spark's GPU for >2 h.

If unsure, ask. The cost of a 30-second confirmation is much less than the cost of a wrong destructive action.

---

## 9. Campaign-portable lessons

These have moved to `references/learnings.md`. The categories are portable; the specific 2VDY / CBG numbers are examples, not predictions for new targets. `learnings.md` flags which claims are "Likely portable" (architectural facts, infrastructure quirks) vs "Probable, test early" (config heuristics that may not generalize). Test category claims early when starting a new campaign before committing serious compute to them.

---

## 10. Persistent memory hooks (for the orchestrator's own ~/.claude/memory/)

When you encounter a lesson that's clearly cross-campaign (not just 2VDY-specific), save it as a memory and link it from MEMORY.md. Existing examples on this machine:

- `feedback_monitor_verbosity.md` — don't fire per-stage notifications for long design tools
- `feedback_boltz2_msa_known_targets.md` — use `mmseqs` MSA mode on Boltz-2 tools for known targets

When to write a new memory:
- The lesson would change behavior in a future campaign
- The reason is non-obvious or counter-intuitive
- It's not derivable from the current codebase (memories are for tribal knowledge, not for things grep can find)

When NOT to write a memory:
- Tool-specific gotcha that lives in `references/tools/<tool>.md`, `CLAUDE.md`, or the worker skill
- Status of the current campaign (that's PROGRESS.md)
- Things that will likely be irrelevant after this campaign

---

## 11. Stop conditions for the campaign as a whole

Don't run forever. A campaign has a natural end:

1. **Pool size target hit.** If goal is ~1000 candidates and you're at 1200, the marginal new run isn't worth it.
2. **Cross-engine refold completion.** Once you have refold CSVs from all engines, the design phase is over; rank and pick.
3. **Diminishing returns.** Latest tool produced 0–3 high-quality accepts after multiple runs. Time to ship what you have.
4. **Wet-lab gate.** The lab is ready to test 30 candidates. Stop expanding the pool.

Don't let the campaign drift past these. The wet-lab cost dominates total project cost; an extra week of GPU compute to find one more design is not the right trade-off unless that design clears a much higher bar than what you already have.

---

## 12. References

- `references/tools/` — engine knowledge per tool (the 10-tool DB: bindcraft, boltzgen, mosaic, proteina-complexa, protein-hunter, pxdesign, rfd3 + boltz2, protenix, alphafold3)
- `references/tools/README.md` — cross-method bias matrix, philosophy, file index
- `references/learnings.md` — empirical campaign lessons (formerly §9), distilled from 2VDY and earlier
- `references/evaluation.md` — local cross-engine refold + iPSAE merge + ranking recipe (refolders called as code on Spark) *[to be written]*
- `bindmaster-worker/` — sibling skill for the per-machine execution layer *[to be written]*
- `CLAUDE.md` (BindMaster repo root) — codebase reference, design decisions, conventions, per-tool gotchas
- `STAGES.md` — pipeline implementation milestones
- `bindmaster_examples/run_*.sh.template` — canonical patterns for tool run scripts
- `Evaluator/docs/pipeline_reference.md` — metrics, ranking formulas, refold engine specifics
- Persistent memory at `~/.claude/projects/.../memory/MEMORY.md` — cross-campaign lessons
