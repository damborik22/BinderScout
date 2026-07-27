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
| DNS | `<BM5_HOST>` | `<BM1_HOST>` | `<BM2_HOST>` | `<BM4_HOST>` |
| IP | <BM5_IP> | <BM1_IP> | <BM2_IP> | <BM4_IP> |
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
(LAN + Clara) at a glance. Warns explicitly when the tunnel is down or the key
is locked, with the exact unlock command.

### 3.3 Launch — start a job under tmux

```bash
tools/fleet.sh launch bm2 2VDY_rfd3 ~/runs/2VDY-bm2-rfd3 run_rfd3.sh
#                     ^machine ^job/session name ^remote run dir  ^local script to ship
```

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
  *not* `idle`. This only means `fleet.sh` sees no tmux session it started —
  it says nothing about GPU load. All three machines can (and do) run real GPU
  work started outside `fleet.sh`; printing "idle" here would read as "safe to
  launch," which `poll` cannot promise. Use `status` (§3.2) to check actual
  GPU occupancy before launching.
- **Unreachable / indeterminate** → warns and skips that machine, distinguishing
  ssh-connection-failure (exit 255, "job state unknown") from any other
  unexpected exit ("could not determine job state").

`tmux ls` itself exits 1 when the server has zero sessions — that's a normal,
successfully-obtained "none running" answer, not a failure; only ssh's own
exit 255 means "we don't actually know."

### 3.5 Fetch — pull results back and verify

```bash
tools/fleet.sh fetch bm2 ~/runs/2VDY-bm2-rfd3/2VDY_rfd3_bm2.tar.gz ~/eval_workdir/2VDY/
```

`rsync -s -a --partial --append-verify --info=progress2 bm2:<remote> <dest>/`.
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

## 5. Failure modes

| Condition | Behaviour |
|---|---|
| Machine unreachable | Marked down in the inventory (`reachable:false`, typed nulls) and surfaced by `status`/`probe`. Never a silent skip. |
| tmux session gone, no output | Treated as a crash; pull `run.log` via `fetch` (or `ssh <m> tail run.log`) for diagnosis. |
| GPU busy at launch | Refuse, report which PID(s) hold it. No silent queueing. |
| BindCraft RSS > 50 GB | Poll-time check the operator makes by hand (`ssh <m> ps -o rss -p <pid>`) — `fleet.sh` does not enforce this. Kill and report if seen; threshold is lower on BM1 given its 31 GB RAM. |
| RFD3 OOM | Prevented at launch — `fleet.sh` exports `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` for every job it starts (§3.3), not a manual step. |
| Boltz-2 complex > ~820 tokens, launched on BM5 itself | Out of `fleet.sh`'s scope (BM5 is the orchestrator, not a fleet target) — refuse to launch locally per the standing Spark unified-memory-hang note; this hangs the whole box and needs a force-restart. |
| VPN down (Clara only) | `status` detects `ip link show ppp0` and reports `tunnel=DOWN` with a fix hint. LAN machines need no VPN — this row doesn't apply to bm1/bm2/bm4. |
| Clara key not in agent | `status` detects via `ssh-add -l`; reports `key=locked` and the exact unlock command. Not applicable to the LAN key (left passphrase-less by design — see `docs/PLAN_fleet_orchestration.md` D8). |
| rsync partial transfer | `--partial --append-verify` resumes cleanly; `fetch` verifies `.tar.gz` integrity with `tar -tzf` before declaring success — don't remove anything remote until that check passes. |
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
