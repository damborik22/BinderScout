---
name: bindmaster-worker
description: Use this skill when running a BindMaster design job on a compute node — either reading a CLUSTER/ assignment doc (Clara and other non-LAN machines) or receiving a job pushed remotely by `tools/fleet.sh` into a tmux session (BM1/BM2/BM4 on the local LAN, driven from BM5) — doing pre-flight checks, setting up the env, submitting the job, monitoring per-tool source-of-truth files, packaging outputs (locally for LAN machines, pulled back with `fleet.sh fetch`; pushed to RESULTS/ on muni-disk for Clara/non-LAN machines), and appending to PROGRESS.md Worker updates. Triggers include "run the assignment", "execute the kickoff", "check progress on Clara/BM1/BM2/BM4", "package and transfer results", "set up <tool> on <machine>", "the assignment is ready", "poll the fleet job", or any time you're on a compute node (or driving one via fleet.sh) executing a binder design job for BindMaster. The sibling skill `bindmaster-orchestrator` handles campaign-level decision logic; this skill is operational.
---

# BindMaster Campaign Worker — SKILL base

**Audience:** an AI agent acting as the *worker* on a BindMaster compute node — typically Clara, BM1/BM2/BM4, or BM5 (DGX Spark) itself when it's doing multiple duty as orchestrator + refold host + worker. The worker may be literally logged into the compute node, or it may be BM5 driving BM1/BM2/BM4 remotely over direct LAN SSH via `tools/fleet.sh` (no VPN, no CLUSTER/ doc — see §1.2), or the orchestrator-Claude on BM5 driving Clara over VPN/SSH per the handoff-doc model, or a human following the playbook. The job: read the assignment (or receive a fleet-pushed job) → execute → monitor → package → handoff.

**When you read this:** at the start of any worker session — when the orchestrator has placed a new assignment in `CLUSTER/`, when BM5 has pushed a job to you via `fleet.sh launch` (driven mode, §1.2), when an in-progress job needs attention, or when results are ready to package.

**What this skill is NOT:**
- Not the orchestrator skill — campaign-level dispatch logic and cross-engine refold live in `bindmaster-orchestrator/`. The worker takes assignments as given.
- Not a tool spec — engine principles live in `bindmaster-orchestrator/references/tools/<tool>.md`. This skill's `references/tools/` covers operational quirks only (where progress shows up, common errors, packaging).
- Not a substitute for the assignment doc — every assignment-specific setting comes from `CLUSTER/<TARGET>_<tool>_<machine>_SETTINGS.md`.

---

## 1. Mental model

The worker is part of the **swarm** described in `bindmaster-orchestrator/SKILL.md` §1. There are two ways a job reaches you, and the input/output contract differs by mode.

### 1.1 Assignment mode (Clara, or any machine off the local LAN)

- **Input:** an assignment doc at `CLUSTER/<TARGET>_<tool>_<machine>_SETTINGS.md` on muni-disk (XBay) — written by the orchestrator, contains everything you need: setup commands, settings JSON, runtime expectation, kill criteria, packaging instructions.
- **Output:** a tarball pushed by you to `RESULTS/<TARGET>_<tool>_<machine>.tar.gz` on muni-disk + an append-only entry in `PROGRESS.md` "Worker updates" section.

### 1.2 Driven mode (BM1/BM2/BM4, launched from BM5 over `tools/fleet.sh`)

BM5 shares a LAN subnet with BM1/BM2/BM4 and drives them by direct SSH — no VPN, no `CLUSTER/` doc. Nobody is sitting on the worker machine; the job runs under tmux and survives disconnects. Full playbook: `bindmaster-orchestrator/references/lab-deploy.md`.

- **Input:** a run script pushed by `fleet.sh launch` into `<remote-dir>/run.sh` and started in a detached tmux session named `<job>` (by convention `<TARGET>_<tool>`). The script itself still carries every setting — generated the same way as an assignment-mode script (`bindmaster configure` or the template, §4.3) — only the *delivery* differs, not the content.
- **Output:** package **locally** on the worker machine (§6.3); BM5 pulls it with `fleet.sh fetch` (rsync, `.tar.gz` integrity-verified) and archives one copy to muni-disk itself. The worker does not push to muni-disk directly in this mode.

Either mode: you don't decide *what* to run or *what settings* — the assignment (or pushed script) is the contract. You decide *how* to execute it well: pre-flight properly, surface real errors fast, package cleanly, transfer reliably. In driven mode you're also standing in for the orchestrator side of the PROGRESS.md record, same as the Clara direct-deploy model — see `bindmaster-orchestrator/references/clara-deploy.md` §4.

**The four phases:**

1. **Pre-flight** — read the assignment (or the pushed run script, in driven mode), verify environment, GPU, disk, BindMaster repo state. Refuse to start if pre-flight fails; report back through PROGRESS.md and ask.
2. **Setup + submit** — clone/update repo, activate env, register target, generate run script, submit. Append a started-entry to PROGRESS.md Worker updates with the SLURM ID (or tmux job name, in driven mode).
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

**Driven-mode addendum:** `fleet.sh launch`'s `<remote-dir>` must be an absolute path — `~` does not expand across the ssh/tmux boundary `fleet.sh` uses (it's embedded in a single-quoted remote-shell argument, not evaluated by a shell that would expand it). Use the same `~/runs/<TARGET>-<machine>-<tool>/` convention, just spelled out with the target user's actual home, e.g. `<BM2_HOME>/runs/2VDY-bm2-rfd3` — not `~/runs/...`. BM5-side, the local destination for `fleet.sh fetch` *is* `~`-expandable (that expansion happens on BM5's own shell) — typically an eval-workdir, not a `CLUSTER`/`RESULTS` pair. See `bindmaster-orchestrator/references/lab-deploy.md` §3.3.

**Never edit PROGRESS.md outside the "Worker updates" section.** The orchestrator owns everything above the `---` separator. You append below it. See `bindmaster-orchestrator/SKILL.md` §3.5 for the full ownership protocol.

---

## 3. Lifecycle — Phase 1: Pre-flight

When a new assignment is placed in `CLUSTER/`, the orchestrator will usually flag you by adding a queued (⏳) row to the status table. (Driven mode: there's no queued-row flag — `fleet.sh launch` starting the tmux session *is* the signal that a job has begun; pre-flight for a driven-mode job happens before you call `launch`, on the same BM5 session.) Your first action:

### 3.1 Read the assignment

**Driven mode:** there's no `CLUSTER/` doc to read. The equivalent is the run script `fleet.sh launch` dropped at `<remote-dir>/run.sh` — read that instead; it's the same content an assignment doc's "Setup / install" section would give you, just delivered as a finished script rather than a doc to transcribe from.

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

- **Conda env / venv exists.** The assignment names the env (e.g. `BindCraft`, `Mosaic/.venv`, `bindmaster_pxdesign`, `bindmaster_rfd3`, `bindmaster_protein_hunter`). Activate it; verify the tool's CLI runs. If the env is missing, the canonical way to create it is `bindmaster install --tool <tool> --yes` (BindMaster's CLI installer — handles standalone Miniforge if no system conda is writable, applies the per-tool post-install patches PXDesign / aarch64 / etc. need, fetches pinned commits, and pins versions to BindMaster's `<TOOL>_COMMIT` records). Re-running install on an existing env is a no-op for already-built environments, so it doubles as a "verify install is sound" check. Do NOT hand-build envs from upstream READMEs — the installer encodes patches that the upstream docs miss.
- **GPU available and right class.** `nvidia-smi`. Confirm memory matches what the assignment expects (24 GB / 48 GB / 80+ GB). See `references/troubleshooting.md` §OOM-thresholds — 24 GB cards have hard ceilings on BindCraft length and some tools just won't fit large targets.
- **Disk space.** `df -h ~/runs` and the muni-disk mount. Budget 50-200 GB per run depending on tool.
- **BindMaster repo is at the pinned commit.**
  ```bash
  cd ~/dev/BindMaster
  git fetch && git checkout <pinned-SHA>
  ```
  If the pinned commit doesn't exist locally yet, `git fetch --all` first.
- **muni-disk reachable — assignment mode / Clara / non-LAN machines only.** If your machine needs VPN to reach XBay, note this — you'll switch at handoff time. **LAN machines (BM1/BM2/BM4)** mount muni-disk directly, no VPN — but in driven mode (§1.2) you don't need muni-disk at all: BM5 pulls your local tarball with `fleet.sh fetch` and archives to muni-disk itself.
- **GPU-busy floor and per-machine RAM (BM1/BM2/BM4 specifics).** See `references/pre-flight.md` §3 for the >512 MiB GPU-busy floor and the BM1 31 GB RAM ceiling — both matter before you launch anything there.
- **Any tool-specific cache populated.** Boltz-2-based tools need `~/.boltz/`; PXDesign/Protenix need CCD cache at `${PROTENIX_DATA_ROOT_DIR}`. See per-tool playbook.

If pre-flight fails, append a failure entry to PROGRESS.md Worker updates *immediately*, don't try to muscle through. Better to get the right environment than waste 6 hours on a known-broken setup.

### 3.3 Special pre-flight: aarch64 machines

If the assignment is for an aarch64 machine (Spark, future ARM nodes), additional checks:
- **Architecture-specific binaries.** BindCraft needs ARM64 `DAlphaBall.gcc` and `dssp` — bundled in `bindmaster_examples/` and copied automatically by the run-script templates, but worth verifying.
- **Tools not yet ported.** Per CLAUDE.md known issues: Proteina-Complexa isn't aarch64-yet; check the assignment is for a tool that *is* ported (RFD3, BindCraft, PXDesign, Boltz-2, AF3 on Spark).
- **Protein-Hunter is permanently blocked on aarch64**, not just "not yet ported" — PyRosetta has no aarch64 wheels. If a PH job lands on BM5/Spark, refuse and ask the orchestrator to route it to BM1/BM2/BM4 or Clara instead.

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

**Preferred path: `bindmaster configure`** — BindMaster's interactive wizard (steps 1–7; step 6 expands into per-tool sub-steps 6a–6g). It (a) writes the target_settings JSON into the right per-tool location, (b) generates the run script from `bindmaster_examples/run_<tool>.sh.template` with the settings filled in, (c) writes the per-run `settings.json` reproducibility manifest the campaign relies on, and (d) creates a single `run_all.sh` to dispatch enabled tools. Use this whenever the assignment's settings map cleanly to the wizard's flow. The wizard's output lives at `~/runs/<TARGET>-<machine>-<tool>/` — same convention this skill assumes for the run dir.

**Fall-back path: hand-copy the template.** If the assignment specifies a setting the wizard doesn't expose (e.g. an experimental flag, a non-stock filter preset), copy `bindmaster_examples/run_<tool>.sh.template` directly to `~/runs/<TARGET>-<machine>-<tool>/run.sh` and edit. Do not hand-write a run script from scratch — the templates encode the JAX / PyRosetta env traps (`LD_LIBRARY_PATH`, `LD_PRELOAD`, `set +u`) that have cost the campaign days. See `references/troubleshooting.md` §6.

Either path: never edit run scripts under an old run dir to re-launch a new variant. Configure (or hand-copy the template) into a fresh `~/runs/.../` so the prior `settings.json` + outputs stay intact as audit trail.

### 4.4 Submit

```bash
sbatch run.sh
# Capture the SLURM ID
```

Or if no SLURM, `nohup ./run.sh > run.log 2>&1 &` and capture PID.

**Driven mode (BM1/BM2/BM4 via `fleet.sh`):** submission is `tools/fleet.sh launch <machine> <job> <remote-dir> <script>` run from BM5 — you don't `sbatch` or `nohup` yourself. `launch` runs two admission checks first (job-name collision via `tmux has-session`, GPU occupancy with a >512 MiB busy floor) and refuses if either fails — a confirmed-busy GPU or an indeterminate state (ssh/nvidia-smi failure) both refuse by default; `FLEET_FORCE=1` overrides the GPU checks (never the name-collision check). It ships the script, starts it in a detached tmux session named `<job>`, and exports `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` unconditionally — mandatory on these 24 GB Ampere cards for RFD3 (see `references/pre-flight.md` §3), harmless for anything else. Capture the job/session name (not a PID or SLURM ID) for PROGRESS.md.

### 4.5 Append the started-entry to PROGRESS.md

Open `RESULTS/PROGRESS.md` on muni-disk. Scroll to the "Worker updates" section at the bottom. Append:

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
⏳ → 🔄 | SLURM <id> started. Pre-flight passed.
Run dir: ~/runs/<TARGET>-<machine>-<tool>/
Expected wall: <X h on <GPU>>.
Kill criterion: <as documented in assignment>.
```

**Driven mode:** replace `SLURM <id>` with the tmux job/session name `fleet.sh launch` printed, and use the absolute remote run dir (§2 addendum) instead of `~/runs/...`. Since BM5 is playing the orchestrator role too, you're writing this entry yourself rather than waiting for a separate orchestrator session to read it back.

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

**Driven mode:** `tools/fleet.sh poll [machine]` lists tracked tmux sessions — it tells you a session exists, not whether the GPU inside it is actually making progress; pair it with the tool's source-of-truth file (§5.1) for real signal. `ssh <machine> tail -f <rundir>/run.log` tails live output without attaching; `ssh <machine> -t tmux attach -t <job>` attaches directly (detach with `Ctrl-b d` to leave it running).

### 5.3 Detecting wedge states

Some tools have known wedge modes that need intervention:

- **PC beam-search wedge** — kill if 0 PDB outputs in `pc/output/` after 24 h (the algorithm enters an infinite loop on certain seeds).
- **BindCraft JAX RSS leak** — kill if process RSS >50 GB. BM4 hit this at 58 GB after 9 days during the 2VDY campaign and was killed by the kernel. **BM1 has only 31 GB RAM** (vs. BM2/BM4's 62 GB) — the same run OOMs far sooner there, well before the 50 GB threshold means anything. Don't route long BindCraft runs to BM1 in the first place (a pre-flight call, see `references/pre-flight.md` §3); if one lands there anyway, watch RSS much more closely.
- **Any run that exceeds 2× its initial wall-clock budget** — kill and report.
- **RFD3 mid-run OOM on Ampere cards without `expandable_segments`** — see RFD3 playbook. Restart with the env var set.

Document the kill in PROGRESS.md Worker updates. **Killing a running job requires user confirmation** if it's not in the assignment's kill criteria — see §7.

### 5.4 Finding real errors when something breaks

**Driven mode:** there's no sbatch `.out`/`.err` — `fleet.sh launch` redirects both stdout and stderr into `<rundir>/run.log`. That's the one file to check (via `fleet.sh fetch` or `ssh <machine> tail`); wherever the table below says "sbatch `.out`" for a given tool, read `run.log` instead.

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

### 6.4 Transfer

**Assignment mode (Clara, non-LAN machines):** if your machine has muni-disk mounted directly, `cp` or `mv`. If you need VPN (Clara → MUNI), **announce the switch** in your PROGRESS.md update before doing it:

```
VPN: switching from Clara-VPN to MUNI-VPN to transfer tarball to RESULTS/.
```

Then switch, transfer, switch back if you need Clara access again.

**Driven mode (BM1/BM2/BM4):** leave the tarball where you packaged it, in the run dir on the worker machine — you don't push to muni-disk yourself. BM5 pulls it:

```bash
tools/fleet.sh fetch <machine> <remote-dir>/<TARGET>_<tool>_<machine>.tar.gz ~/eval_workdir/<TARGET>/
```

`fetch` runs `rsync -s -a --partial` and, for a `.tar.gz`, verifies the archive with `tar -tzf` before declaring success — a corrupt or partial transfer dies loudly instead of reporting a false green. BM5 then archives one copy to muni-disk RESULTS/ itself; that archived copy — not your worker-side tarball — is what closes the campaign record. See `bindmaster-orchestrator/references/lab-deploy.md` §3.5.

### 6.5 Append the completion-entry to PROGRESS.md

```markdown
### 2026-MM-DD HH:MM — <machine> — <Tool> <variant>
🔄 → ✅ | SLURM <id> done. <X> accepts at iPTM ≥ <threshold>, <Y> total designs.
Wall: <hours>. Compute: <GPU-hours> on <node-id>.
Packaged: <TARGET>_<tool>_<machine>.tar.gz (<size>) at RESULTS/.
[New error: <if any, with reproduction>]
[New lesson: <if any, candidate for learnings.md>]
```

**Driven mode:** replace `SLURM <id>` with the tmux job name, and note "packaged locally, ready for `fleet.sh fetch`" in place of a muni-disk path — the archived-to-muni-disk confirmation comes from BM5 after the fetch succeeds, not from you.

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
- `bindmaster-orchestrator/references/lab-deploy.md` — driven-mode playbook (fleet.sh probe/status/launch/poll/fetch) for BM1/BM2/BM4 when driven from BM5
- `tools/fleet.sh` — the script that drives LAN workers in driven mode
- `CLAUDE.md` (BindMaster repo root) — codebase reference, install instructions, design decisions
- `bindmaster_examples/run_*.sh.template` — canonical run script templates (use these, do not hand-write)
