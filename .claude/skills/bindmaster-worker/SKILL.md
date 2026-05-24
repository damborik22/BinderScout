---
name: bindmaster-worker
description: Use this skill when running a BindMaster design job on a compute node — reading a CLUSTER/ assignment doc, doing pre-flight checks, setting up the env, submitting the job, monitoring per-tool source-of-truth files, packaging outputs into a tarball, transferring to RESULTS/ on muni-disk, and appending to PROGRESS.md Worker updates. Triggers include "run the assignment", "execute the kickoff", "check progress on Clara/BM2/BM4", "package and transfer results", "set up <tool> on <machine>", "the assignment is ready", or any time you're on a compute node executing a binder design job for BindMaster. The sibling skill `bindmaster-orchestrator` handles campaign-level decision logic; this skill is operational.
---

# BindMaster Campaign Worker — SKILL base

**Audience:** an AI agent acting as the *worker* on a BindMaster compute node — typically Clara, BM2, BM4, Spark (when Spark is doing dual duty as orchestrator + worker), or any other lab machine assigned a design job. The worker may also be the orchestrator-Claude on Spark driving a remote session over VPN/SSH, or a human following the playbook. The job: read assignment → execute → monitor → package → handoff.

**When you read this:** at the start of any worker session — when the orchestrator has placed a new assignment in `CLUSTER/`, or when an in-progress job needs attention, or when results are ready to package.

**What this skill is NOT:**
- Not the orchestrator skill — campaign-level dispatch logic and cross-engine refold live in `bindmaster-orchestrator/`. The worker takes assignments as given.
- Not a tool spec — engine principles live in `bindmaster-orchestrator/references/tools/<tool>.md`. This skill's `references/tools/` covers operational quirks only (where progress shows up, common errors, packaging).
- Not a substitute for the assignment doc — every assignment-specific setting comes from `CLUSTER/<TARGET>_<tool>_<machine>_SETTINGS.md`.

---

## 1. Mental model

The worker is part of the **swarm** described in `bindmaster-orchestrator/SKILL.md` §1. From your side, the contract is simple:

- **Input:** an assignment doc at `CLUSTER/<TARGET>_<tool>_<machine>_SETTINGS.md` on muni-disk (XBay) — written by the orchestrator, contains everything you need: setup commands, settings JSON, runtime expectation, kill criteria, packaging instructions.
- **Output:** a tarball at `RESULTS/<TARGET>_<tool>_<machine>.tar.gz` + an append-only entry in `PROGRESS.md` "Worker updates" section.

That's it. You don't decide *what* to run or *what settings* — the assignment is the contract. You decide *how* to execute it well: pre-flight properly, surface real errors fast, package cleanly, transfer reliably.

**The four phases:**

1. **Pre-flight** — read the assignment, verify environment, GPU, disk, BindMaster repo state. Refuse to start if pre-flight fails; report back through PROGRESS.md and ask.
2. **Setup + submit** — clone/update repo, activate env, register target, generate run script, submit. Append a started-entry to PROGRESS.md Worker updates with SLURM ID.
3. **Monitor** — watch source-of-truth files (NOT generic listings — see per-tool playbook), surface only milestones (first accept, halfway, completion, crash). Per-stage chatter stays local.
4. **Handoff** — verify outputs, compute deliverable metrics, package, transfer, append completion-entry to PROGRESS.md.

---

## 2. File / location conventions

On the worker machine:

```
~/dev/BindMaster/                              ← cloned repo (orchestrator pins commit SHA in assignment)
~/runs/<TARGET>-<machine>-<tool>/              ← per-tool run dir (you create)
~/runs/<TARGET>-<machine>-<tool>/.progress     ← optional local progress notes (don't ship)
```

On muni-disk (XBay, mounted or VPN-reachable):

```
muni-disk/.../<TARGET>/
├── CLUSTER/
│   └── <TARGET>_<tool>_<machine>_SETTINGS.md  ← your assignment (read this first)
│   └── <preset JSON files referenced in assignment>
└── RESULTS/
    ├── PROGRESS.md                            ← read top section for context, append to Worker updates only
    └── <TARGET>_<tool>_<machine>.tar.gz       ← where your output goes
```

**Never edit PROGRESS.md outside the "Worker updates" section.** The orchestrator owns everything above the `---` separator. You append below it. See `bindmaster-orchestrator/SKILL.md` §3.5 for the full ownership protocol.

---

## 3. Lifecycle — Phase 1: Pre-flight

When a new assignment is placed in `CLUSTER/`, the orchestrator will usually flag you by adding a queued (⏳) row to the status table. Your first action:

### 3.1 Read the assignment

The assignment doc has these sections (per `bindmaster-orchestrator/SKILL.md` §7):

1. **Why this run** — context; not action-relevant but worth reading.
2. **Settings table** — `Param | Value | Why`. Note any non-obvious choices.
3. **target_settings.json** — copy-pasteable into your config dir.
4. **Setup / install** — exact commands.
5. **Runtime expectation** — yield × time × compute math, **kill criterion** (memorize this).
6. **Output handoff** — packaging command, destination, PROGRESS update template.
7. **Critical gotchas** — tool-specific traps that have bitten the campaign. Read these *before* you start.
8. **Pinned** — BindMaster commit SHA.

If any section is missing, missing detail, or references a file that doesn't exist in CLUSTER/, **stop and ask the orchestrator via a TODO entry in PROGRESS.md Worker updates** — don't improvise.

### 3.2 Pre-flight checklist

Run these checks before touching anything. See `references/pre-flight.md` for full commands.

- **Conda env / venv exists.** The assignment names the env (e.g. `BindCraft`, `Mosaic/.venv`, `bindmaster_pxdesign`, `bindmaster_rfd3`, `bindmaster_protein_hunter`). Activate it; verify the tool's CLI runs.
- **GPU available and right class.** `nvidia-smi`. Confirm memory matches what the assignment expects (24 GB / 48 GB / 80+ GB). See `references/troubleshooting.md` §OOM-thresholds — 24 GB cards have hard ceilings on BindCraft length and some tools just won't fit large targets.
- **Disk space.** `df -h ~/runs` and the muni-disk mount. Budget 50-200 GB per run depending on tool.
- **BindMaster repo is at the pinned commit.**
  ```bash
  cd ~/dev/BindMaster
  git fetch && git checkout <pinned-SHA>
  ```
  If the pinned commit doesn't exist locally yet, `git fetch --all` first.
- **muni-disk reachable.** If your machine needs VPN to reach XBay, note this — you'll switch at handoff time.
- **Any tool-specific cache populated.** Boltz-2-based tools need `~/.boltz/`; PXDesign/Protenix need CCD cache at `${PROTENIX_DATA_ROOT_DIR}`. See per-tool playbook.

If pre-flight fails, append a failure entry to PROGRESS.md Worker updates *immediately*, don't try to muscle through. Better to get the right environment than waste 6 hours on a known-broken setup.

### 3.3 Special pre-flight: aarch64 machines

If the assignment is for an aarch64 machine (Spark, future ARM nodes), additional checks:
- **Architecture-specific binaries.** BindCraft needs ARM64 `DAlphaBall.gcc` and `dssp` — bundled in `bindmaster_examples/` and copied automatically by the run-script templates, but worth verifying.
- **Tools not yet ported.** Per CLAUDE.md known issues: Proteina-Complexa isn't aarch64-yet; check the assignment is for a tool that *is* ported (RFD3, BindCraft, PXDesign, Boltz-2, AF3 on Spark).

---

## 4. Lifecycle — Phase 2: Setup + submit

After pre-flight passes:

### 4.1 Activate env safely

```bash
set +u                # required around conda activate for envs using cuda-nvcc activate.d hooks
conda activate <env>
set -u
```

The `set +u` dance is in `references/troubleshooting.md` §6 — without it, you'll hit `unbound variable: NVCC_PREPEND_FLAGS` and spend an hour debugging it.

### 4.2 Register the target

Each tool has its own way of receiving the target structure. The assignment's "Setup / install" section names the exact command. Typical patterns:

- **BindCraft:** copy target PDB to `settings_target/<TARGET>/`, copy the target JSON the assignment provides.
- **BoltzGen:** target YAML in `example/<TARGET>/` per assignment.
- **Mosaic / Protein-Hunter:** target sequence and structure path passed as CLI args at run time.
- **PXDesign:** target CIF + hotspots in the YAML at `<task_name>.yaml`.
- **Proteina-Complexa:** target ID in `assets/target_data/` + entry in `configs/design_tasks/`.
- **RFD3:** contig + target chain spec in the JSON input file.

### 4.3 Generate the run script

**Use the template from `bindmaster_examples/run_<tool>.sh.template`. Do not hand-write.**

This is non-negotiable. The templates encode the JAX / PyRosetta env traps (`LD_LIBRARY_PATH`, `LD_PRELOAD`, `set +u`) that have cost the campaign days. See `references/troubleshooting.md` §6.

Copy the template, fill in the parameters from the assignment's settings table, save to `~/runs/<TARGET>-<machine>-<tool>/run.sh`.

### 4.4 Submit

```bash
sbatch run.sh
# Capture the SLURM ID
```

Or if no SLURM, `nohup ./run.sh > run.log 2>&1 &` and capture PID.

### 4.5 Append the started-entry to PROGRESS.md

Open `RESULTS/PROGRESS.md` on muni-disk. Scroll to the "Worker updates" section at the bottom. Append:

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
⏳ → 🔄 | SLURM <id> started. Pre-flight passed.
Run dir: ~/runs/<TARGET>-<machine>-<tool>/
Expected wall: <X h on <GPU>>.
Kill criterion: <as documented in assignment>.
```

Save and close. The orchestrator merges this on their next read.

---

## 5. Lifecycle — Phase 3: Monitor

### 5.1 What to actually watch

**Don't tail the inner logs continuously.** That's noise. Watch the **source-of-truth files** per tool — these tell you real progress in one line per accept/design/sample. See `references/tools/<tool>.md` for the exact file per tool.

Summary:

| Tool | Source-of-truth file | What "real progress" looks like |
|---|---|---|
| BindCraft | `final_design_stats.csv` | new row per accept (NOT `ls Accepted/` — always has 4 empty subdirs) |
| BoltzGen | `final_ranked_designs/final_<budget>_designs/` + `all_designs_metrics.csv` | directory populated + CSV row growth |
| Mosaic | `designs.csv` | row count growth |
| Protein-Hunter | `summary_high_iptm.csv` + `high_iptm_yaml/` | CSV row + YAML file growth (row count > num_designs is normal) |
| PXDesign | `design_outputs/<task_name>/summary.csv` | CSV row growth |
| Proteina-Complexa | `analyze/` output CSVs | analysis stage completion |
| RFD3 | `out_dir/*.cif.gz` count + per-design `.json` | one `.cif.gz` + `.json` pair per design |

### 5.2 Sample at coarse intervals

Every 1-4 hours is fine. The orchestrator doesn't want per-stage notifications; the user doesn't either. The exception is the **first accept** or **first failure** — those are real signals.

### 5.3 Detecting wedge states

Some tools have known wedge modes that need intervention:

- **PC beam-search wedge** — kill if 0 PDB outputs in `pc/output/` after 24 h (the algorithm enters an infinite loop on certain seeds).
- **BindCraft JAX RSS leak** — kill if process RSS >50 GB. BM4 hit this at 58 GB after 9 days during the 2VDY campaign and was killed by the kernel.
- **Any run that exceeds 2× its initial wall-clock budget** — kill and report.
- **RFD3 mid-run OOM on Ampere cards without `expandable_segments`** — see RFD3 playbook. Restart with the env var set.

Document the kill in PROGRESS.md Worker updates. **Killing a running job requires user confirmation** if it's not in the assignment's kill criteria — see §7.

### 5.4 Finding real errors when something breaks

Slurm `.err` only shows wrapper-level Python exceptions. Real Python tracebacks live in:

- **PC:** `$PC/logs/.../generate.log`
- **PH:** `runs/<n>/protein_hunter/.../*.log`
- **BindCraft:** `<run>/bindcraft/outputs/*.log` (inner traceback), `<run>/bindcraft.log` (outer wrapper)
- **Mosaic:** stdout in the sbatch `.out`
- **RFD3:** `<run>/foundry.log`
- **PXDesign:** kernel compilation logs on first run; sbatch `.out` for runtime

See `references/troubleshooting.md` §7 for the full table.

---

## 6. Lifecycle — Phase 4: Evaluate + handoff

When a run finishes (success, failure, or planned kill):

### 6.1 Verify outputs from the source-of-truth file

**Don't trust directory listings for completion.** Use the source-of-truth file per tool (§5.1). For BindCraft specifically: 4 subdirs always exist in `Accepted/` even with zero accepts. Count rows in `final_design_stats.csv`.

### 6.2 Compute the deliverable metrics

- **Accepts vs. assignment target.** Did we hit the per-tool design target?
- **Top-tail at standard thresholds.** For most tools, report counts at `iPTM ≥ 0.70` and `≥ 0.85` (note which engine).
- **Length distribution.** Min, median, max binder length in accepts.
- **Wall-clock vs. expected.** Did it run 2× over budget? Note in handoff.

### 6.3 Package

See `references/packaging.md` for the canonical tar / zip patterns. Naming convention:

```
<TARGET>_<tool>_<machine>.tar.gz       ← full run dir (evidence)
<TARGET>_<tool>_<machine>_final.tar.gz ← curated subset (Accepted/ + key CSVs only)
```

The `_final` subset is optional but recommended for large output directories (BoltzGen's `intermediate_designs/` can be tens of GB).

### 6.4 Transfer to muni-disk

If your machine has muni-disk mounted directly, `cp` or `mv`. If you need VPN (Clara → MUNI), **announce the switch** in your PROGRESS.md update before doing it:

```
VPN: switching from Clara-VPN to MUNI-VPN to transfer tarball to RESULTS/.
```

Then switch, transfer, switch back if you need Clara access again.

### 6.5 Append the completion-entry to PROGRESS.md

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
🔄 → ✅ | SLURM <id> done. <X> accepts at iPTM ≥ <threshold>, <Y> total designs.
Wall: <hours>. Compute: <GPU-hours> on <node-id>.
Packaged: <TARGET>_<tool>_<machine>.tar.gz (<size>) at RESULTS/.
[New error: <if any, with reproduction>]
[New lesson: <if any, candidate for learnings.md>]
```

For failures (❌) the format is the same but include the failure mode, the relevant log path, and what would need to change to retry.

### 6.6 Don't delete the worker-side copy

Until the user (or orchestrator) confirms the muni-disk archive is readable. Disk space is never the reason to delete — Lustre is 3 PB, muni-disk is large. The worker-side run dir is your local backup until the campaign closes.

---

## 7. When to stop and ask

Routine things you do without confirming:

- Read any file
- Run `git status`, `git log`, `git pull --rebase` if clean
- Update your row in PROGRESS.md Worker updates section (append-only)
- Generate run scripts from templates
- Submit jobs that match the assignment
- Tar and transfer completed run dirs

**Always ask the user (or orchestrator via PROGRESS.md TODO) before:**

- **Killing a job** that isn't covered by the assignment's documented kill criteria. Even if it looks stuck, it might be 2 minutes from finishing.
- **Deleting any run dir or archive.** Disk space is never the reason.
- **Switching VPNs.** Announce explicitly — the orchestrator may be relying on your current VPN for monitoring.
- **Deviating from the assignment.** If the assignment says "BindCraft V2+V4" and you think V1+default would be better, that's an orchestrator decision; ask, don't decide.
- **Re-running a failed assignment** without the orchestrator confirming the diagnosis. The failure might be informative.
- **Force-pushing or amending shared commits.**

The cost of a 30-second confirmation through a TODO entry in PROGRESS.md Worker updates is much less than the cost of a wrong destructive action.

---

## 8. Persistent memory hooks (worker-side)

When you encounter a per-tool operational lesson that's clearly cross-campaign (not just specific to one target), consider promoting it. Two routes:

- **Tool-level operational quirk** → propose adding it to the relevant `references/tools/<tool>.md` here in the worker skill.
- **Machine-level lesson** → propose adding to `references/troubleshooting.md` or a future `references/machines/<machine>.md`.
- **Campaign-level pattern** → flag it for the orchestrator (TODO in PROGRESS.md Worker updates → New lesson). The orchestrator decides whether it belongs in `bindmaster-orchestrator/references/learnings.md`.

When NOT to write a memory:
- Tool-specific gotcha that already lives in `references/tools/<tool>.md`
- Status of the current campaign (that's PROGRESS.md)
- Things that will likely be irrelevant after this campaign

---

## 9. References

- `references/pre-flight.md` — full pre-flight check protocol with commands
- `references/packaging.md` — tar/zip naming, what to include/exclude per tool, transfer protocol
- `references/troubleshooting.md` — env traps (JAX, PyRosetta, conda), log locations table, OOM diagnosis, common per-machine issues
- `references/tools/<tool>.md` — per-tool operational playbooks (source-of-truth file, common errors, packaging quirks, kill criteria, OOM thresholds)
- `bindmaster-orchestrator/SKILL.md` — sibling skill (campaign-level meta)
- `bindmaster-orchestrator/references/tools/<tool>.md` — engine principles (read for context, not for execution)
- `CLAUDE.md` (BindMaster repo root) — codebase reference, install instructions, design decisions
- `bindmaster_examples/run_*.sh.template` — canonical run script templates (use these, do not hand-write)
