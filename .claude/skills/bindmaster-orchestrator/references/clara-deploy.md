# Direct cluster deployment — driving Clara over SSH

**What this is:** the playbook for when the orchestrator does **not** hand a
Clara job off to a separate worker, but instead **drives Clara itself** over a
non-interactive `ssh clara` — running the full worker loop (pre-flight → submit
→ monitor → package → transfer) remotely while staying in the orchestrator's
own session. This collapses the orchestrator/worker split into one operator for
Clara-bound work.

**When this applies:** only on a machine that has **direct, non-interactive SSH
access to Clara** (passphrase-less key, `ssh clara "true"` succeeds without a
prompt). Whether *this* machine qualifies, and the exact access setup (VPN,
DNS/`/etc/hosts` pin, key, alias), is machine-local — check the repo-root
`CLAUDE.local.md` and `docs/local/` on this machine. If `ssh clara` is not set
up here, fall back to the classic handoff-doc model (write a
`CLUSTER/<TARGET>_<tool>_clara_SETTINGS.md` and let a worker execute it).

**Full operational depth** (per-tool env activation, sbatch skeleton, gotcha
catalog, timing table) lives in the two machine-local manuals when present:
- `docs/local/BindMaster-Slurm-Orchestration-Manual.md` — per-tool recipes + gotchas
- `docs/local/Clara-Agentic-Operations-Manual.md` — three-phase lifecycle + progress-log discipline

This reference is the self-contained orchestration layer on top of them, plus
the sibling `bindmaster-worker` skill for the generic worker mechanics.

---

## 1. Decide: direct-deploy vs handoff doc

| Situation | Mode |
|---|---|
| This machine has `ssh clara` and you're actively orchestrating | **Direct deploy** (this doc) — you submit and monitor yourself |
| No SSH to Clara from here; a separate Claude/human runs on Clara | **Handoff doc** (SKILL.md §4 / worker skill) |
| Long unattended run where you want the campaign to survive your session ending | Either — but if direct-deploy, the job keeps running on Clara regardless; you just re-attach by reading `squeue`/source-of-truth files on the next session |

Direct deploy does **not** change *what* you run or *what settings* — §5–6 of
SKILL.md (methodological diversity, kill criteria, math-first) still govern the
decision. It only changes the *delivery mechanism* from "write a doc someone
else executes" to "execute it over SSH yourself."

Even in direct-deploy mode, still write the kickoff doc in `CLUSTER/` when the
run is campaign-significant — it's the durable record of *why* and *how*, and it
lets a different operator reproduce or take over. The difference is you then
execute it yourself instead of waiting for a worker.

---

## 2. Cluster facts you must respect (Clara / CIIRC)

- **Partitions:** `h200` (NVIDIA H200, 141 GB — Boltz-2 / large-memory tools:
  Mosaic, PC, PH, BoltzGen) and `l40s` (NVIDIA L40S, 48 GB — AF2-based:
  BindCraft). One GPU per job (`--gres=gpu:H200:1` / `:L40S:1`); never
  `--exclusive`. 3–6 concurrent jobs is polite (~6–13 % of the cluster).
- **No sudo, no admin.** Everything in `$HOME` (`<CLARA_HOME>`, Lustre, PB-scale).
- **No email.** `#SBATCH --mail-*` silently fails (no mail binary). Poll `squeue`, or use an `ntfy.sh` curl at the end of the sbatch.
- **Login node has no GPU** — submit/monitor there, never compute.
- **`SLURM_SUBMIT_DIR`, not `BASH_SOURCE`**, in every sbatch (Slurm copies the script to read-only scratch).
- **Slurm `.err` lies** — it shows only wrapper exits. Real tracebacks are in the tool's own inner log (see the manuals' per-tool log-path table).

Env activation differs by tool: **Mosaic and Proteina-Complexa use uv venvs**
(`source <tool>/.venv/bin/activate`); the other six use conda (`set +u; source
~/miniforge3/etc/profile.d/conda.sh; conda activate <env>; set -u`). BindCraft
additionally needs the inline `LD_LIBRARY_PATH` + `LD_PRELOAD` libgfortran trap.
Full incantations: Slurm manual §5.

---

## 3. The direct-deploy loop

All commands run from the orchestrator machine as `ssh clara "…"`. Keep each
`ssh` invocation a self-contained command (shell state does not persist between
separate `ssh` calls).

### 3.1 Pre-flight (before writing/submitting anything)

```bash
ssh clara "uptime"                                              # reachable < 5 s?
ssh clara "sinfo -p h200,l40s -o '%n %T %C %G'"                 # free GPUs, none down*
ssh clara "ls ~/miniforge3/envs/<env> 2>/dev/null || ls ~/BindMaster/<Tool>/.venv"  # env present
ssh clara "ls ~/.boltz/mols/ALA.pkl"                           # Boltz-2 cache (Mosaic/PH only)
ssh clara "df -h /mnt/home_lustre | tail -1"                   # >100 GB free for one run dir
ssh clara "cd ~/BindMaster && git rev-parse --short HEAD"      # repo at the SHA you expect
```

Any failure → don't submit. Note it in PROGRESS.md and resolve first.

### 3.2 Stage the run (deploy the scripts)

Two ways to get the run script onto Clara — pick per situation:

- **Author locally, copy up** (preferred for anything non-trivial — you get to
  lint/review it first):
  ```bash
  scp run_<tool>.sbatch run_<tool>.sh clara:~/runs/<TARGET>-clara-<tool>/
  ```
- **Heredoc over SSH** (fine for tiny edits; watch quoting — a stray unescaped
  `$` expands locally):
  ```bash
  ssh clara "mkdir -p ~/runs/<TARGET>-clara-<tool> && cat > ~/runs/<TARGET>-clara-<tool>/run_<tool>.sbatch" <<'SBATCH'
  #!/bin/bash
  #SBATCH ...
  SBATCH
  ```

Also stage inputs (target PDB, any preset JSONs, edited hallucinate script) and
do the tool-specific config (PC `complexa target add …`, PH BMDIR sed-replace,
Mosaic constants, BindCraft `target_settings.json`) — Slurm manual §1.2/§5.

### 3.3 Submit

```bash
ssh clara "cd ~/runs/<TARGET>-clara-<tool> && sbatch run_<tool>.sbatch"
# → Submitted batch job <jobid>   — capture the jobid
```

Immediately record a START row/entry in PROGRESS.md (jobid, partition, expected
runtime, kill criterion).

### 3.4 Monitor (state-level, not per-stage)

```bash
ssh clara "squeue -u <CLARA_USER> -o '%i %j %T %M %L %R'"                       # alive? state, elapsed, remaining
ssh clara "tail -50 ~/runs/<TARGET>-clara-<tool>/<job>-<jobid>.out"         # forward progress?
# deliverable count = the only truth; per-tool source-of-truth file (SKILL.md §4 Phase 3, Slurm manual §3.1), e.g. PH:
ssh clara "tail -n +2 ~/runs/<name>/protein_hunter/<N>/summary_all_runs.csv | wc -l"
```

Cadence: t+5/t+15/t+30 min early (catches env/config failures fast), then hourly
for the first hours, then every 4–6 h for long runs. You do **not** need to hold
your session open — the Slurm job runs independently; re-attach next session by
re-reading `squeue` + source-of-truth files. A long fallback `ScheduleWakeup` /
`/loop` is the right tool if you want to auto-check a run you expect to finish
overnight.

If a job goes silent past its expected end, check `sacct`:
```bash
ssh clara "sacct -j <jobid> --format=JobID,JobName,State,ExitCode,Elapsed,DerivedExitCode -P"
```
`COMPLETED` + `0:0` = clean *exit* (necessary, not sufficient — still verify
output counts). `FAILED`/`TIMEOUT`/`OUT_OF_MEMORY` → read the inner log, not `.err`.

### 3.5 Package + verify

```bash
# verify with the per-tool source-of-truth count first (don't trust ls Accepted/ for BindCraft)
ssh clara "cd ~/runs && tar czf <TARGET>_<tool>_Clara.tar.gz <TARGET>-clara-<tool>/ && ls -lh <TARGET>_<tool>_Clara.tar.gz"
ssh clara "sha256sum ~/runs/<TARGET>_<tool>_Clara.tar.gz"        # optional integrity hash
```

### 3.6 Transfer to RESULTS/ on muni-disk

Pull the tarball down, then place it on the MUNI share:

```bash
scp clara:~/runs/<TARGET>_<tool>_Clara.tar.gz <local-staging>/
# then copy <local-staging>/<archive> to muni-disk RESULTS/<TARGET>/
```

**VPN caveat is machine-dependent.** The classic model treats Clara-VPN and
MUNI-VPN as mutually exclusive (announce before switching — SKILL.md §8). On a
machine that reaches the MUNI share directly (no VPN), that switch is a no-op —
`scp` from Clara and write to the share in one go. Which applies here is in
`CLAUDE.local.md`; check it rather than assuming either way.

### 3.7 Record

Update PROGRESS.md: flip the status row to ✅/❌, packaging filename, wall-clock,
yield at standard thresholds, any new error/lesson. In direct-deploy mode you
own both the orchestrator sections and what would have been the worker append —
write the outcome straight into the canonical status table (no separate
Worker-updates handshake needed, since you're both roles). Keep a one-line audit
note of "deployed directly from <machine> via ssh clara" so a future reader
knows there was no separate worker.

---

## 4. What stays the same as classic orchestration

- **Decision logic is unchanged.** §5 (cross-machine patterns), §6 (heuristics:
  math-first, kill criteria, cheap-first), and §8 (stop-and-ask) all still apply.
  Direct deploy makes it *faster* to act on a decision, which makes the
  "propose, don't decide silently" rule (§6.7) and pre-committed kill criteria
  (§5.6) **more** important, not less — there's no worker-handoff latency acting
  as a natural checkpoint.
- **Still ask before** killing a job (`scancel`), deleting any run dir/archive,
  spending >24 H200-hours on a new experiment, or dominating a partition — even
  though you *can* now do these in one `ssh` command. The ease of execution
  does not lower the confirmation bar.
- **PROGRESS.md remains the source of truth.** Direct deploy doesn't mean
  keeping state only in your session — write it down, because the next session
  (or a different operator) reconstructs the campaign from PROGRESS.md + `squeue`.

---

## 5. Failure modes specific to direct deploy

| Symptom | Cause | Fix |
|---|---|---|
| `ssh: Could not resolve hostname <CLARA_LOGIN_HOST>` | DNS/`/etc/hosts` pin missing or cluster IP changed | Re-check the machine-local access setup (`CLAUDE.local.md`); the login-node IP is a static pin, not DNS |
| `ssh` hangs then times out | Cluster VPN down, or firewall/route dropped | Reconnect the cluster VPN (machine-local alias); confirm the tunnel routes the login-node subnet |
| Heredoc-uploaded script has wrong values | Local shell expanded `$VAR`/backticks before send | Quote the heredoc delimiter (`<<'EOF'`), or author locally and `scp` instead |
| Job submitted but you can't find its `.out` | Wrong run dir, or `%x-%j` pattern vs your assumption | `ssh clara "ls -lt ~/runs/<name>/ | head"`; the `.out` name is `<job-name>-<jobid>.out` |
| Monitoring shows RUNNING but output count flat | Real stall (node `down*`, MSA rate-limit, disk full) — Slurm manual §2.3 | `sinfo -p <p>`, check inner log, `df -h`; the `.out` tail + source-of-truth count together disambiguate |
| Session ended, worried the run died | It didn't — Slurm is independent of your SSH session | Re-attach next session via `squeue`/`sacct`; SSH is only the control channel |

---

## 6. One-liner cheat-sheet (direct deploy)

| I want to… | Command |
|---|---|
| Confirm access | `ssh clara "hostname; whoami"` |
| Free GPUs | `ssh clara "sinfo -p h200,l40s -o '%n %T %C %G'"` |
| My jobs | `ssh clara "squeue -u <CLARA_USER> -o '%i %j %T %M %L %R'"` |
| Job exit state | `ssh clara "sacct -j <jobid> --format=JobID,State,ExitCode,Elapsed -P"` |
| Tail stdout | `ssh clara "tail -100 ~/runs/<name>/<job>-<jobid>.out"` |
| Deploy scripts | `scp run_<tool>.{sbatch,sh} clara:~/runs/<name>/` |
| Submit | `ssh clara "cd ~/runs/<name> && sbatch run_<tool>.sbatch"` |
| Package | `ssh clara "cd ~/runs && tar czf <T>_<tool>_Clara.tar.gz <name>/"` |
| Pull result | `scp clara:~/runs/<T>_<tool>_Clara.tar.gz <local-staging>/` |
| Disk free | `ssh clara "df -h /mnt/home_lustre | tail -1"` |

For everything else (per-tool env activation, the sbatch skeleton, the full
gotcha catalog), the two `docs/local/` manuals are authoritative on this machine.
