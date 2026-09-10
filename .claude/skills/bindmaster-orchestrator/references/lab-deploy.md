# LAN fleet deployment — driving BM1/BM2/BM4 over direct SSH

**What this is:** the playbook for when the orchestrator does **not** hand a
design job off to a separate worker, but instead **drives a lab workstation
itself** over direct, no-VPN SSH — running the full worker loop (probe →
admission check → launch → poll → fetch) remotely while staying in the
orchestrator's own session. Same collapse of the orchestrator/worker split as
`clara-deploy.md`, for the three x86 machines on the local subnet instead of
the CIIRC cluster.

**When this applies:** only on a machine with plain SSH reachability to
BM1/BM2/BM4 — no VPN, no NAT, same subnet. Whether *this* machine qualifies is
machine-local; check the repo-root `CLAUDE.local.md`. As of 2026-07-27 that
machine is BM5. All fleet operations go through one script,
`tools/fleet.sh <probe|status|launch|poll|fetch>` (design: `docs/PLAN_fleet_orchestration.md`).

If this machine does *not* have LAN SSH to the fleet, fall back to the classic
handoff-doc model (SKILL.md §4 / the `bindmaster-worker` skill).

---

## 1. When to use LAN deploy vs Clara

| Situation | Use |
|---|---|
| Job fits a 24 GB RTX 3090 (or BM5's own GB10), and at least one of BM1/BM2/BM4 is idle | **LAN deploy** (this doc) — lower latency, no VPN dependency, no shared-account contention |
| Job needs H200/L40S-class VRAM (large-batch AF3, big Boltz-2 complexes, anything that doesn't fit 24 GB) | **Clara** (`clara-deploy.md`) |
| All three LAN machines are busy (confirmed via `fleet.sh status`) and the job can't wait | **Clara** — don't queue silently against a busy LAN box; Clara has 16 GPUs across two partitions |
| Need PyRosetta (Protein-Hunter) and the only idle box is BM5 | Neither — BM5 is aarch64 and PyRosetta has no aarch64 wheels (see §2). Route to BM1/BM2/BM4 or Clara. |

LAN deploy does **not** change *what* you run or *what settings* — SKILL.md
§5–6 (methodological diversity, kill criteria, math-first) still govern the
decision. It only changes the *delivery mechanism*.

Even in LAN-deploy mode, still write the kickoff doc in `CLUSTER/` when the
run is campaign-significant — it's the durable record of *why* and *how*, and
it lets a different operator reproduce or take over.

---

## 2. Machine facts you must respect

| | **BM5** | **BM1** | **BM2** | **BM4** |
|---|---|---|---|---|
| DNS | `ll23.sci.muni.cz` | `ll03.sci.muni.cz` | `ll02.sci.muni.cz` | `ll04.sci.muni.cz` |
| IP | 147.251.40.223 | 147.251.40.203 | 147.251.40.202 | 147.251.40.204 |
| Alias (`~/.ssh/config`) | — (orchestrator) | `bm1` | `bm2` | `bm4` |
| Arch | aarch64 | x86_64 | x86_64 | x86_64 |
| GPU | GB10 (unified) | RTX 3090 24 GB | RTX 3090 24 GB | RTX 3090 24 GB |
| RAM (total) | 121 GB | **31 GB** | 62 GB | 62 GB |
| Role | orchestrator + refold | design worker | design worker | design worker |

Full field set (also captured per-probe in `~/.claude/fleet/inventory.json`):
arch, GPU name, GPU busy-process count, total RAM, free disk, conda envs
present, BindMaster git SHA/branch, tmux version, reachability, timestamp.

**Capability constraints that follow from the hardware — these are not
enforced by `fleet.sh`, they're judgment calls at assignment time:**

- **BM1 has half the RAM of its siblings (31 GB) — no long BindCraft runs
  there.** The BindCraft JAX RSS leak killed BM4 at 58 GB after nine days; on
  BM1 the same run OOMs far sooner. The three x86 boxes are *not*
  interchangeable — BM1 gets short jobs or non-BindCraft tools.
- **BM5 is aarch64 — Protein-Hunter cannot run there.** PyRosetta has no
  aarch64 wheels. PH work must be assigned to BM1/BM2/BM4 or Clara.
- **All three x86 peers are 24 GB Ampere — RFD3 needs
  `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` on every one of them,**
  not just BM4 (where the fragmentation OOM was first observed). `fleet.sh
  launch` exports this unconditionally for every job it starts (see §3.3), so
  this is handled automatically for LAN-launched jobs — but keep it in mind if
  you ever start something outside `fleet.sh` (e.g. by hand over a raw `ssh`).
- **GPU-busy floor is 512 MiB** (`GPU_BUSY_MIB` in `fleet.sh`), to ignore
  small desktop-integration processes riding the GPU. Confirmed correct in
  practice: BM4 runs a ~294 MiB `rustdesk` process that sits below the floor
  and is correctly not reported as "busy."

---

## 3. The deploy loop

All commands run from BM5. `fleet.sh` prints in color (red=die, yellow=warn,
green=ok) and every subcommand exits non-zero on failure — check exit codes if
scripting around it.

### 3.1 Probe — refresh the inventory

```bash
tools/fleet.sh probe
```

SSHes to bm1/bm2/bm4 in turn (`BatchMode=yes`, 8 s connect timeout), pulls
GPU name/VRAM, busy-process count (>512 MiB), total RAM (`free -g` column 2,
not free — see §3.2), free disk, conda envs,
BindMaster git SHA/branch, tmux version, and writes
`~/.claude/fleet/inventory.json`. An unreachable machine gets a full-shape
placeholder row (`reachable:false`, typed nulls) rather than being dropped
from the JSON — `status` always has something to render for every machine.
Run this at the start of a session and any time you suspect state drifted.

### 3.2 Status — read the cached inventory + Clara state

```bash
tools/fleet.sh status
```

Renders one row per LAN machine (MACHINE, HOST, GPU, BUSY, RAM, DISK, BRANCH)
from the last `probe`, **not** a fresh probe — call `probe` first if the
picture might be stale. **The RAM column is the machine's total installed
RAM, not free/available memory** — `probe_one()` reads it with `free -g |
awk '/^Mem:/{print $2}'`, and column 2 of `free -g` is `total` (column 4 is
`free`). BM1's `31` is its fixed capacity, not current headroom — the DISK
column next to it, by contrast, genuinely is free space (`df -h`). Below the
table it also reports Clara tunnel state
(`ip link show ppp0`) and whether the Clara key is loaded
(`ssh-add -l | grep clara`), so one command gives you the whole fleet
(LAN + Clara) at a glance. Warns explicitly when the tunnel is down (naming
the `vpn-ciirc` command to bring it up manually) or the key is locked (naming
the exact `ssh-add` unlock command).

### 3.3 Launch — start a job under tmux

```bash
tools/fleet.sh launch bm2 2VDY_rfd3 /home/bindmaster2/runs/2VDY-bm2-rfd3 run_rfd3.sh
#                     ^machine ^job/session name ^remote run dir           ^local script to ship
```

**Remote paths must be absolute — `~` does not expand.** `launch`'s
`<remote-dir>` and `fetch`'s `<remote-path>` (§3.5) are embedded in
single-quoted remote-shell arguments (`sq()`) or handed to `rsync`'s own
`host:path` parsing; neither goes through a shell on BM5 that would expand a
leading `~`, so quoting it turns `~` into a literal directory name instead of
the target user's home. Worse, if the argument is left unquoted at the BM5
shell (as in a copy-pasted example), BM5's *own* shell expands `~` to
*BM5's* home before `fleet.sh` ever sees it — which is the wrong user
entirely (`bindmaster2`'s home on bm2 is `/home/bindmaster2`, not BM5's
`/home/bindmaster5`). Always spell out the target user's absolute home path.

Before touching anything remote, `launch` runs **two independent admission
checks**, and only proceeds if both pass:

1. **Job-name collision** (`tmux has-session -t <job>` on the target). Three
   outcomes, no override:
   - session doesn't exist (`tmux` exit 1) → proceed
   - session already exists (`tmux` exit 0) → refuse
   - can't tell — ssh itself failed (exit 255) or any other unexpected exit →
     refuse. An unreachable host means "we don't know," not "assume idle."
2. **GPU occupancy** (`nvidia-smi --query-compute-apps`, filtered to >512
   MiB). **Three distinguishable outcomes, not two:**
   - **confirmed-idle** → launches.
   - **confirmed-busy** → refuses, and names the PID(s) and MiB holding the
     GPU.
   - **could-not-determine** (ssh connection failed, or `nvidia-smi` itself
     failed on the remote) → refuses with a distinct message from
     confirmed-busy. This case is deliberately not folded into either "idle"
     or "busy" — an empty result must never be silently read as "safe."

   `FLEET_FORCE=1 tools/fleet.sh launch ...` overrides **both** confirmed-busy
   and could-not-determine (with a yellow warning naming which case was
   overridden). It does **not** override the job-name collision check in step
   1 — that one always refuses; pick a different job name instead.

Once admitted, `launch`:

- `mkdir -p` the remote run dir over SSH.
- Ships the run script with `ssh "$m" "cat > '<rundir>/run.sh'" < script`
  — **not `scp`.** This keeps one quoting model (the same single-quoted
  remote-shell convention used everywhere else in the script) instead of
  depending on which wire protocol the local `scp` binary defaults to
  (modern OpenSSH's SFTP subsystem bypasses the remote shell's quoting
  entirely, which is a version-dependent assumption this script avoids).
- Starts the job in a detached tmux session named after `<job>`:
  `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; bash run.sh >
  run.log 2>&1` — the RFD3 fragmentation-OOM fix (§2) applied unconditionally
  to every LAN-launched job, not tool-conditional.

Caller-supplied `job` and `rundir` values are shell-escaped via the script's
`sq()` helper before being embedded in the remote command strings, so a job
name or path containing a single quote can't break out of the wrapper.

Attach to watch it live: `ssh bm2 -t tmux attach -t 2VDY_rfd3`.

### 3.4 Poll — check tracked jobs

```bash
tools/fleet.sh poll          # all three
tools/fleet.sh poll bm2      # one machine
```

Lists tmux sessions on the target(s) via `tmux ls`. Three outcomes per
machine:

- **Sessions listed** → prints `<machine> <session1> <created> <session2> ...`
- **No sessions, but reachable** → prints **`no tracked job`**, deliberately
  *not* `idle`. This only means `tmux ls` returned zero sessions on that
  machine, period — `fleet.sh` doesn't filter to sessions it launched itself;
  if any session existed (from `fleet.sh` or a human), the "sessions listed"
  case above would show it regardless of who started it. It says nothing
  about GPU load. All three machines can (and do) run real GPU work started
  outside `fleet.sh`; printing "idle" here would read as "safe to launch,"
  which `poll` cannot promise. Use `status` (§3.2) to check actual GPU
  occupancy before launching.
- **Unreachable / indeterminate** → warns and skips that machine, distinguishing
  ssh-connection-failure (exit 255, "job state unknown") from any other
  unexpected exit ("could not determine job state").

`tmux ls` itself exits 1 when the server has zero sessions — that's a normal,
successfully-obtained "none running" answer, not a failure; only ssh's own
exit 255 means "we don't actually know."

### 3.5 Fetch — pull results back and verify

```bash
tools/fleet.sh fetch bm2 /home/bindmaster2/runs/2VDY-bm2-rfd3/2VDY_rfd3_bm2.tar.gz ~/eval_workdir/2VDY/
```

The remote path (2nd arg) must be absolute for the same reason as `launch`'s
`<remote-dir>` above — see the callout in §3.3. The local dest (3rd arg) is
fine as `~/...`: that path is expanded by BM5's own shell before `fleet.sh`
runs, on BM5 itself, which is exactly where it's meant to land.

`rsync -s -a --partial --info=progress2 bm2:<remote> <dest>/`.
The `-s` (`--protect-args`) flag — not the `sq()` helper used everywhere
else — is what makes this safe: rsync parses `host:path` itself before any
remote shell sees it, so manually quoting the path (as `sq()` does for
ssh/tmux commands) actively breaks it — a literal quote character becomes
part of the path rsync tries to `cd` into. `--protect-args` disables remote
wildcard/shell expansion of the path instead, so quotes/spaces/semicolons
pass through as literal path bytes.

After the transfer, `fetch` **verifies the result before declaring success**:
- if the fetched file ends in `.tar.gz`, runs `tar -tzf` on it and **dies on a
  corrupt archive** rather than reporting a false success;
- otherwise just confirms the file landed;
- if `rsync` reported success but the expected local file is missing, that's
  also a hard failure, not a silent no-op.

---

## 4. What stays the same as classic orchestration

- **`settings.json` per run.** Every tool run script still writes it before
  the heavy workload starts, per the CLAUDE.md reproducibility convention —
  `fleet.sh launch` doesn't touch this; it's inside the run script you ship.
- **Per-tool source-of-truth files for yield counts.** Don't trust `ls
  Accepted/` for BindCraft or similar directory-presence proxies; count rows
  in the tool's own summary CSV, same as any other worker (SKILL.md Phase 3
  step 1, worker skill's per-tool table).
- **Packaging conventions.** Worker-side packaging (`tar czf
  <TARGET>_<tool>_<machine>.tar.gz`) is unchanged; `fleet.sh fetch` just
  replaces the transport leg (SSH/rsync directly instead of a muni-disk
  drop).
- **PROGRESS.md as the record.** Direct LAN deploy doesn't mean keeping state
  only in the orchestrator's session — write it down, same discipline as
  `clara-deploy.md` §4: you own both the orchestrator-side and what would
  have been the worker-append sections, since you're playing both roles.
  muni-disk is demoted from coordination substrate to archive of record
  (`docs/PLAN_fleet_orchestration.md` §1), but it's still where the final
  tarball copy goes.

---

## 4bis. Two traps when you script against these machines by hand

`fleet.sh` avoids both. Anything you write yourself must too — each one produces
a **confidently wrong answer**, not an error, which is what makes them expensive.

### 4bis.1 `pgrep`/`pkill -f` over ssh matches the ssh command itself

The remote shell's own `/proc/*/cmdline` contains the pattern you just sent, so
the pattern matches it:

```bash
ssh bm1 "pgrep -f refold-boltz2 >/dev/null && echo running || echo IDLE"   # ALWAYS "running"
ssh bm4 "pkill -f cs_chain_e2.sh"     # kills the shell running this line;
                                      # everything after it silently never runs
```

Bracket the first character so the pattern cannot match its own literal text —
and note it matches locally too, if a *local* `ssh …` command line happens to
contain the string you are grepping for:

```bash
ssh bm1 "ps -eo cmd | grep -c '[r]efold-boltz2'"        # true count
ssh bm4 "pids=\$(pgrep -f '[c]s_chain_e2.sh'); kill \$pids"
```

**Cost when missed (2026-07-28):** a completion monitor keyed on
`pgrep -f refold-boltz2` never fired because it always read "running"; BM1 and
BM2 sat idle ~3 h after finishing their counter-screen arms.

**Bracketing is NOT sufficient on its own.** It only stops the pattern matching
its own literal text. If any *other* part of the command line contains the real
string, you still self-match:

```bash
# hit 2026-08-16: killed the controlling shell (exit 144), target survived
pkill -f '[c]hain_after_screens.sh'; cat > chain_after_screens.sh <<'EOF' ...
#                                          ^^^^^^^^^^^^^^^^^^^^^^ matches
```

Two habits that actually hold:
- **Kill by PID, never by pattern**, when a kill is what you mean:
  `ps -eo pid,args | grep '[t]arget'` → inspect → `kill <pid>`.
- **Give the replacement a different filename** from the thing being replaced,
  so the rewrite and the cleanup cannot share a token.

**Better still: monitor a row count, not a process.** Progress files can't
self-match. Key completion on `wc -l` of the output CSV and add a stall
detector (no new rows in N minutes ⇒ report), which also catches silent deaths
that a process check would miss.

### 4bis.2 `ssh host "cmd &"` hangs unless the child's FDs are detached

A backgrounded remote process inherits the ssh channel's stdout/stderr, so ssh
waits on it forever even with `nohup`/`setsid`. In a multi-step deploy script
this means every step after the first launch silently never executes.

```bash
ssh bm1 "setsid nohup ./job.sh &"                          # HANGS
ssh -n bm1 "setsid nohup ./job.sh >/dev/null 2>&1 </dev/null &"   # returns
```

**Cost when missed (2026-07-28):** a 4-machine shard deploy hung on its first
remote launch; the 4th machine was never started, and the operator's own hung
`ssh` command line then self-matched a local `pgrep` (§4bis.1) and read as
"running".

### 4bis.3 Corollary — after syncing a machine's BindMaster repo, patch Mosaic

Newer `Evaluator/scripts/refold_boltz2.py` passes `msa_path=` to
`TargetChain`, which only exists in a **patched** Mosaic checkout. Pulling
BindMaster without applying the patch makes every design fail its feature
build:

```bash
ssh <m> "cd ~/dev/BindMaster/Mosaic && git apply ~/dev/BindMaster/install/patches/mosaic-offline-msa.patch"
ssh <m> "grep -c msa_path ~/dev/BindMaster/Mosaic/src/mosaic/structure_prediction.py"   # must be >= 1
```

Verify with that grep as part of any sync — do not assume the checkout is
current just because the repo is.

### 4bis.4 Preflight is MANDATORY before every launch — `tools/preflight.sh`

Not once per session. Before **every** launch, including the second job you put
on a box you filled yourself ten minutes earlier.

```bash
tools/preflight.sh measure <one instance of the worker>   # peak RSS, BEFORE choosing N
tools/preflight.sh check bm5 37                           # headroom + declared floors
tools/preflight.sh declare pxd-mpnn 25                    # publish YOUR floor while you run
tools/preflight.sh release pxd-mpnn
```

Three things this exists to stop, all observed on BM5 2026-08-16:

- **GPU footprint is not host RSS.** 16 MPNN workers were sized off 339 MiB of
  *GPU* memory. Real host RSS was **3.1 GB each = 42.6 GB**. On Spark's unified
  memory, host RSS is the binding constraint — always `measure` before scaling.
- **A memory floor declared inside a script is invisible.**
  `repro_check/run_repro_capped.sh` set `FLOOR_GB=25` as a bash variable; the
  MPNN launch could not see it, drove the box from 115 GB to 24 GB available,
  and its watchdog killed **3 of 4 experiment arms** (rc=137). Long jobs must
  `declare` their floor so the next launch is refused instead of landing on it.
- **`ALL DONE` after every arm died.** That pipeline logged
  `REPRO2 ALL DONE` with three rc=137 arms above it. Check per-arm rc, never the
  tail of a log — same shape as the Mosaic 512/512-skipped incident (§4bis.3).

Corollary on cleanup: `pkill -f` against `xargs -P N` workers accomplishes
nothing — xargs immediately respawns them (observed: memory went 25 GB → 55 GB
seconds after the "kill"). Kill the process group:

```bash
ps -eo pid,pgid,args | grep '[x]args -P'      # find PGID
kill -TERM -<PGID>; sleep 4; kill -KILL -<PGID>
```

---

## 5. Failure modes

| Condition | Behaviour |
|---|---|
| `pgrep`/`pkill -f` over ssh reports everything as running / kills its own shell | Pattern self-match — bracket the first char (§4bis.1). Prefer row-count monitoring over process checks. |
| A job dies with rc=137 shortly after another launch | OOM / watchdog kill from memory contention. Preflight was skipped (§4bis.4). Size on host RSS, not GPU memory. |
| `pkill` the workers but memory goes straight back up | `xargs -P` respawned them. Kill the process group, not the pattern (§4bis.4). |
| Multi-step ssh deploy stops partway with no error | Backgrounded remote child holds the ssh channel open (§4bis.2) — redirect its FDs and use `ssh -n`. |
| Boltz-2 refold exits 0 having folded nothing | Every design hit the per-design skip — an environment fault, usually an unpatched Mosaic (§4bis.3). `refold_boltz2.py` now raises instead of reporting a clean run; older checkouts do not, so check `Processed N binder(s)` is non-zero. |
| Machine unreachable | Marked down in the inventory (`reachable:false`, typed nulls) and surfaced by `status`/`probe`. Never a silent skip. |
| tmux session gone, no output | Treated as a crash; pull `run.log` via `fetch` (or `ssh <m> tail run.log`) for diagnosis. |
| GPU busy at launch | Refuse, report which PID(s) hold it. No silent queueing. |
| BindCraft RSS > 50 GB | Poll-time check the operator makes by hand (`ssh <m> ps -o rss -p <pid>`) — `fleet.sh` does not enforce this. Kill and report if seen; threshold is lower on BM1 given its 31 GB RAM. |
| RFD3 OOM | Prevented at launch — `fleet.sh` exports `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` for every job it starts (§3.3), not a manual step. |
| Boltz-2 complex > ~820 tokens, launched on BM5 itself | Out of `fleet.sh`'s scope (BM5 is the orchestrator, not a fleet target) — refuse to launch locally per the standing Spark unified-memory-hang note; this hangs the whole box and needs a force-restart. |
| VPN down (Clara only) | `status` detects `ip link show ppp0` and reports `tunnel=DOWN` with a fix hint. LAN machines need no VPN — this row doesn't apply to bm1/bm2/bm4. |
| Clara key not in agent | `status` detects via `ssh-add -l`; reports `key=locked` and the exact unlock command. Not applicable to the LAN key (left passphrase-less by design — see `docs/PLAN_fleet_orchestration.md` D8). |
| rsync partial transfer | `--partial` resumes cleanly (`--append-verify` is deliberately NOT used — it skips a destination file whose size is already >= the source's, which would keep a stale result on re-fetch after a re-run); `fetch` verifies `.tar.gz` integrity with `tar -tzf` before declaring success — don't remove anything remote until that check passes. |
| Job-name collision | `launch` refuses outright (no `FLEET_FORCE` override) — pick a different job name. |
| Could-not-determine GPU state at launch | Refuses by default, distinct message from confirmed-busy; `FLEET_FORCE=1` overrides. |

---

## 6. Cheat sheet

| I want to… | Command |
|---|---|
| Refresh fleet + Clara state | `tools/fleet.sh probe && tools/fleet.sh status` |
| See cached state only | `tools/fleet.sh status` |
| Launch a job | `tools/fleet.sh launch <bm1\|bm2\|bm4> <job> <remote-dir> <script>` |
| Launch, overriding a busy/indeterminate GPU read | `FLEET_FORCE=1 tools/fleet.sh launch ...` |
| Attach to a running job | `ssh <bm1\|bm2\|bm4> -t tmux attach -t <job>` |
| Check all tracked jobs | `tools/fleet.sh poll` |
| Check one machine | `tools/fleet.sh poll <bm1\|bm2\|bm4>` |
| Tail remote output without attaching | `ssh <machine> tail -f <rundir>/run.log` |
| Pull + verify a result | `tools/fleet.sh fetch <machine> <remote-path> <local-dir>` |
| Kill a stuck job | `ssh <machine> tmux kill-session -t <job>` (always ask first — SKILL.md §8) |

For the design rationale behind every decision above (why tmux over Slurm,
why the LAN key stays passphrase-less, why fetch-then-archive instead of
push-to-muni), `docs/PLAN_fleet_orchestration.md` is authoritative.
