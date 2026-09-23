# Fleet Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let BM5 dispatch, monitor and retrieve BinderScout design jobs on BM1/BM2/BM4 over direct SSH, replacing the muni-disk handoff-doc round trip.

**Architecture:** A single bash script (`tools/fleet.sh`) drives three LAN peers over multiplexed SSH. Jobs run inside `tmux` so they survive disconnects; an admission check refuses to launch onto a busy GPU rather than queueing. Results are pulled to BM5 by rsync, verified, and only then archived to muni-disk. No daemon, no root, no new services.

**Tech Stack:** bash, OpenSSH 9.6 (ControlMaster multiplexing), tmux 3.4, rsync, jq. All five are already installed on BM5 and the three peers.

**Design spec:** `docs/PLAN_fleet_orchestration.md` — read it before starting. Decisions D1–D8 there are settled; do not relitigate them.

## Global Constraints

- **No sudo anywhere** — locally or remotely. Nothing in this plan may require it.
- **No stored VPN password, no systemd unit for the tunnel.** The human starts FortiClient manually. This was explicitly reverted from an earlier proposal.
- Machines are exactly `bm1 bm2 bm4`. BM5 is the orchestrator and is never a launch target.
- `tools/fleet.sh` must pass `shellcheck --shell=bash --severity=warning` and be added to the CI list in `.github/workflows/ci.yml`.
- Shell style follows the repo: `set -euo pipefail`, ANSI colour constants, `die`/`warn` helpers.
- GPU-busy detection ignores processes under **512 MiB** — BM4 runs a 6 MiB `snapd-desktop-integration` on its GPU permanently, which is not a real workload.
- Every launch exports `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` — all three peers are 24 GB Ampere and RFD3 OOMs on fragmentation without it.
- `~/.ssh/config` and `CLAUDE.local.md` are machine-local (the latter is gitignored). Only `tools/fleet.sh`, the CI change, and `lab-deploy.md` get committed.

---

### Task 1: SSH fleet config with connection multiplexing

**Files:**
- Modify: `~/.ssh/config` (machine-local, not committed)
- Create: `~/.ssh/cm/` (control-socket directory)

**Interfaces:**
- Consumes: nothing.
- Produces: host aliases `bm1`, `bm2`, `bm4` usable as `ssh bm1 <cmd>`. Every later task depends on these names.

- [ ] **Step 1: Verify the current state fails**

Run: `ssh -o BatchMode=yes -o ConnectTimeout=5 bm1 true; echo "exit=$?"`
Expected: FAIL — `Could not resolve hostname bm1`, exit non-zero. The aliases do not exist yet.

- [ ] **Step 2: Create the control-socket directory**

```bash
mkdir -p ~/.ssh/cm && chmod 700 ~/.ssh/cm
```

- [ ] **Step 3: Append the fleet block to `~/.ssh/config`**

```
# --- BinderScout LAN fleet (Loschmidt Lab, <LAB_SUBNET>) ---
Host bm1
    HostName <BM1_IP>
    User <BM1_USER>

Host bm2
    HostName <BM2_IP>
    User <BM2_USER>

Host bm4
    HostName <BM4_IP>
    User <BM4_USER>

Host bm1 bm2 bm4
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    ControlMaster auto
    ControlPath ~/.ssh/cm/%r@%h:%p
    ControlPersist 10m
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

Ordering matters: OpenSSH takes the **first** value it finds for each keyword, so
the per-host `HostName`/`User` blocks must come before the shared options block.
The shared block carries only the multiplexing and keepalive settings, which are
identical across the three machines.

- [ ] **Step 4: Verify each alias resolves and authenticates**

```bash
for m in bm1 bm2 bm4; do
  printf '%-4s ' "$m"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$m" 'echo OK $(hostname)'
done
```
Expected: `bm1 OK BindMaster1`, `bm2 OK BindMaster2`, `bm4 OK BindMaster4`.

- [ ] **Step 5: Verify multiplexing actually engages**

```bash
ssh -O check bm1                      # expect: Master running (pid=NNNN)
time ssh bm1 true                     # second call rides the existing master
```
Expected: `Master running`, and the timed call completes in well under 100 ms
versus roughly 300–600 ms for a cold handshake. This is the efficiency claim in
the spec — confirm it rather than assuming it.

- [ ] **Step 6: No commit**

`~/.ssh/config` is machine-local and deliberately not in the repo. Nothing to commit for this task.

---

### Task 2: `fleet.sh probe` — build the inventory

**Files:**
- Create: `tools/fleet.sh`
- Create: `~/.claude/fleet/` (output directory, created at runtime)

**Interfaces:**
- Consumes: host aliases from Task 1.
- Produces: `~/.claude/fleet/inventory.json` with shape
  `{generated: string, machines: {bm1: M, bm2: M, bm4: M}}` where `M` is
  `{reachable: bool, host, arch, gpu, gpu_procs: int, ram_gb: int, disk_free, envs, git_sha, git_branch, tmux}`.
  Tasks 3–5 read this file. `probe_one()`, `die()`, `warn()` are defined here and reused by every later task.

- [ ] **Step 1: Write the failing verification**

```bash
# tools/fleet-check/check_probe.sh
set -euo pipefail
bash tools/fleet.sh probe
jq -e '.machines | keys == ["bm1","bm2","bm4"]' ~/.claude/fleet/inventory.json
jq -e '[.machines[] | select(.reachable == true)] | length == 3' ~/.claude/fleet/inventory.json
jq -e '.machines.bm1.arch == "x86_64"' ~/.claude/fleet/inventory.json
jq -e '.machines.bm1.ram_gb == 31' ~/.claude/fleet/inventory.json
echo "PROBE OK"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tools/fleet-check/check_probe.sh`
Expected: FAIL — `tools/fleet.sh: No such file or directory`.

- [ ] **Step 3: Write `tools/fleet.sh` with the `probe` subcommand**

```bash
#!/usr/bin/env bash
# fleet.sh — drive the BinderScout LAN fleet (BM1/BM2/BM4) from BM5.
# Design: docs/PLAN_fleet_orchestration.md
set -euo pipefail

FLEET_MACHINES=(bm1 bm2 bm4)
FLEET_DIR="${FLEET_DIR:-$HOME/.claude/fleet}"
INVENTORY="$FLEET_DIR/inventory.json"
GPU_BUSY_MIB=512   # ignore snapd-desktop-integration (~6 MiB) on BM4

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
BOLD=$'\033[1m'; RESET=$'\033[0m'

die()  { printf '%s%s%s\n' "$RED"    "$*" "$RESET" >&2; exit 1; }
warn() { printf '%s%s%s\n' "$YELLOW" "$*" "$RESET" >&2; }
ok()   { printf '%s%s%s\n' "$GREEN"  "$*" "$RESET"; }

# Emit one compact JSON object describing a remote machine.
probe_one() {
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$1" bash -s <<'REMOTE'
set -u
gpu=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)
procs=$(nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null \
        | awk '$1+0 > 512' | wc -l)
envs=$(ls -1 "$HOME"/miniforge3/envs "$HOME"/miniconda3/envs "$HOME"/anaconda3/envs \
             "$HOME"/dev/BinderScout/conda/envs 2>/dev/null \
       | grep -vE '^$|:' | sort -u | paste -sd,)
sha=$(git -C "$HOME/dev/BinderScout" rev-parse --short HEAD 2>/dev/null || echo none)
br=$(git -C "$HOME/dev/BinderScout" rev-parse --abbrev-ref HEAD 2>/dev/null || echo none)
printf '{"host":"%s","arch":"%s","gpu":"%s","gpu_procs":%s,"ram_gb":%s,' \
    "$(hostname)" "$(uname -m)" "$gpu" "${procs:-0}" \
    "$(free -g | awk '/^Mem:/{print $2}')"
printf '"disk_free":"%s","envs":"%s","git_sha":"%s","git_branch":"%s","tmux":"%s"}\n' \
    "$(df -h "$HOME" | awk 'NR==2{print $4}')" "$envs" "$sha" "$br" \
    "$(tmux -V 2>/dev/null | awk '{print $2}')"
REMOTE
}

cmd_probe() {
    mkdir -p "$FLEET_DIR"
    local args=() m json
    for m in "${FLEET_MACHINES[@]}"; do
        if json=$(probe_one "$m" 2>/dev/null) && [ -n "$json" ]; then
            json=$(printf '%s' "$json" | jq -c '. + {reachable:true}')
        else
            json='{"reachable":false}'
            warn "probe: $m unreachable"
        fi
        args+=(--argjson "$m" "$json")
    done
    jq -n "${args[@]}" --arg generated "$(date -Is)" \
        '{generated:$generated, machines:{bm1:$bm1, bm2:$bm2, bm4:$bm4}}' > "$INVENTORY"
    ok "wrote $INVENTORY"
}

usage() {
    cat <<'USAGE'
usage: fleet.sh <command> [args]

  probe                                   refresh ~/.claude/fleet/inventory.json
USAGE
    exit 1
}

case "${1:-}" in
    probe) shift; cmd_probe "$@" ;;
    *)     usage ;;
esac
```

- [ ] **Step 4: Run the verification to confirm it passes**

```bash
chmod +x tools/fleet.sh
bash tools/fleet-check/check_probe.sh
```
Expected: `PROBE OK`. If `ram_gb == 31` fails, re-read the value — BM1 genuinely has 31 GB and that asymmetry is load-bearing (see spec §2).

- [ ] **Step 5: Confirm shellcheck is clean**

Run: `shellcheck --shell=bash --severity=warning tools/fleet.sh`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add tools/fleet.sh tools/fleet-check/check_probe.sh
git commit -m "feat(fleet): probe BM1/BM2/BM4 into a cached inventory"
```

---

### Task 3: `fleet.sh status` — fleet and Clara state at a glance

**Files:**
- Modify: `tools/fleet.sh`
- Create: `tools/fleet-check/check_status.sh`

**Interfaces:**
- Consumes: `INVENTORY`, `die`, `ok` from Task 2.
- Produces: `cmd_status()`. No later task depends on its output format.

- [ ] **Step 1: Write the failing verification**

```bash
# tools/fleet-check/check_status.sh
set -euo pipefail
out=$(bash tools/fleet.sh status)
printf '%s\n' "$out"
grep -q 'bm1' <<<"$out"
grep -q 'bm4' <<<"$out"
grep -qE 'clara .*tunnel=(up|DOWN)' <<<"$out"
grep -qE 'key=(unlocked|locked)'    <<<"$out"
echo "STATUS OK"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tools/fleet-check/check_status.sh`
Expected: FAIL — `usage: fleet.sh <command>`, exit 1.

- [ ] **Step 3: Add `cmd_status` above `usage()`**

```bash
cmd_status() {
    [ -f "$INVENTORY" ] || die "no inventory — run: fleet.sh probe"
    printf '%s%-5s %-14s %-22s %-6s %-6s %-8s %s%s\n' "$BOLD" \
        MACHINE HOST GPU BUSY RAM DISK BRANCH "$RESET"
    local m
    for m in "${FLEET_MACHINES[@]}"; do
        jq -r --arg m "$m" '
            .machines[$m] as $x
            | if $x.reachable
              then [$m, $x.host, ($x.gpu // "-"), ($x.gpu_procs|tostring),
                    (($x.ram_gb|tostring) + "G"), $x.disk_free, $x.git_branch]
              else [$m, "UNREACHABLE", "-", "-", "-", "-", "-"] end
            | @tsv' "$INVENTORY" \
        | awk -F'\t' '{printf "%-5s %-14s %-22s %-6s %-6s %-8s %s\n",$1,$2,$3,$4,$5,$6,$7}'
    done

    local tunnel key
    if ip link show ppp0 >/dev/null 2>&1; then tunnel=up; else tunnel=DOWN; fi
    if ssh-add -l 2>/dev/null | grep -q clara; then key=unlocked; else key=locked; fi
    printf '\n%-5s %s  tunnel=%s  key=%s\n' clara <CLARA_LOGIN_HOST> "$tunnel" "$key"
    [ "$tunnel" = up ]     || warn "Clara unreachable: start FortiClient manually."
    [ "$key" = unlocked ]  || warn "Clara key not in agent: ssh-add -t 8h ~/.ssh/id_ed25519_clara"
    printf 'inventory generated: %s\n' "$(jq -r .generated "$INVENTORY")"
}
```

- [ ] **Step 4: Register the subcommand**

In the `case` block add `status) shift; cmd_status "$@" ;;` and add to `usage()`:
```
  status                                  fleet + Clara state (uses cached inventory)
```

- [ ] **Step 5: Run the verification**

Run: `bash tools/fleet-check/check_status.sh`
Expected: `STATUS OK`, with `tunnel=DOWN key=locked` and both warnings printed — the tunnel is manual and currently down, which is the correct state, not a failure.

- [ ] **Step 6: Confirm shellcheck, then commit**

```bash
shellcheck --shell=bash --severity=warning tools/fleet.sh
git add tools/fleet.sh tools/fleet-check/check_status.sh
git commit -m "feat(fleet): status view incl. Clara tunnel and agent-key state"
```

---

### Task 4: `fleet.sh launch` — admission check and tmux dispatch

**Files:**
- Modify: `tools/fleet.sh`
- Create: `tools/fleet-check/check_launch.sh`

**Interfaces:**
- Consumes: `die`, `warn`, `ok`, `GPU_BUSY_MIB` from Task 2.
- Produces: `cmd_launch <machine> <job> <remote-dir> <script>`. Task 5's poll and fetch operate on sessions this creates.

- [ ] **Step 1: Write the failing verification (canary + both refusal paths)**

```bash
# tools/fleet-check/check_launch.sh
set -euo pipefail
JOB=canary_$$
DIR=/tmp/fleet_canary_$$
printf '#!/usr/bin/env bash\nsleep 60\necho done\n' > /tmp/canary_$$.sh

# 1. a clean launch succeeds
bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/canary_$$.sh
ssh bm1 "tmux has-session -t $JOB" || { echo "FAIL: session missing"; exit 1; }

# 2. relaunching the same job name is refused (deterministic collision check)
if bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/canary_$$.sh 2>/dev/null; then
    echo "FAIL: duplicate session was not refused"; exit 1
fi

# 3. cleanup
ssh bm1 "tmux kill-session -t $JOB 2>/dev/null; rm -rf $DIR"
rm -f /tmp/canary_$$.sh
echo "LAUNCH OK"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tools/fleet-check/check_launch.sh`
Expected: FAIL — `usage: fleet.sh <command>`, exit 1.

- [ ] **Step 3: Add `cmd_launch`**

```bash
cmd_launch() {
    [ $# -eq 4 ] || die "usage: fleet.sh launch <machine> <job> <remote-dir> <script>"
    local m=$1 job=$2 rundir=$3 script=$4
    [ -f "$script" ] || die "no such script: $script"
    case " ${FLEET_MACHINES[*]} " in *" $m "*) ;; *) die "unknown machine: $m" ;; esac

    # Admission check 1 — job-name collision (deterministic).
    if ssh "$m" "tmux has-session -t '$job'" 2>/dev/null; then
        die "$m: tmux session '$job' already exists — refusing"
    fi

    # Admission check 2 — GPU occupancy, ignoring sub-threshold desktop processes.
    local busy
    busy=$(ssh "$m" "nvidia-smi --query-compute-apps=pid,used_memory \
        --format=csv,noheader,nounits 2>/dev/null | awk -F', *' '\$2+0 > $GPU_BUSY_MIB'")
    if [ -n "$busy" ] && [ "${FLEET_FORCE:-0}" != 1 ]; then
        die "$m: GPU busy (pid, MiB): $busy — refusing. FLEET_FORCE=1 overrides."
    fi
    [ -z "$busy" ] || warn "$m: GPU busy but FLEET_FORCE=1 — launching anyway"

    ssh "$m" "mkdir -p '$rundir'"
    scp -q "$script" "$m:$rundir/run.sh"
    ssh "$m" "cd '$rundir' && tmux new-session -d -s '$job' \
        'export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; \
         bash run.sh > run.log 2>&1'"
    ok "$m: launched '$job' in $rundir (tmux attach -t $job to watch)"
}
```

- [ ] **Step 4: Register the subcommand**

Add `launch) shift; cmd_launch "$@" ;;` to the `case` block and to `usage()`:
```
  launch <machine> <job> <remote-dir> <script>   tmux-launch a run script
```

- [ ] **Step 5: Run the verification**

Run: `bash tools/fleet-check/check_launch.sh`
Expected: `LAUNCH OK`.

- [ ] **Step 6: Verify the GPU-busy refusal against a genuinely busy machine**

BM4 was running `refold-boltz2` at 19 GB when this plan was written. If it is
still busy, this is a real negative test:

```bash
bash tools/fleet.sh launch bm4 gputest /tmp/gputest /tmp/canary.sh; echo "exit=$?"
```
Expected: refusal naming the holding PID, non-zero exit. If BM4 has since gone
idle, `fleet.sh status` will show `BUSY 0` — note that in the commit message and
rely on the collision check from Step 5 for coverage.

- [ ] **Step 7: Confirm shellcheck, then commit**

```bash
shellcheck --shell=bash --severity=warning tools/fleet.sh
git add tools/fleet.sh tools/fleet-check/check_launch.sh
git commit -m "feat(fleet): tmux launch with GPU and session admission checks"
```

---

### Task 5: `fleet.sh poll` and `fleet.sh fetch`

**Files:**
- Modify: `tools/fleet.sh`
- Create: `tools/fleet-check/check_poll_fetch.sh`

**Interfaces:**
- Consumes: everything from Tasks 2 and 4.
- Produces: `cmd_poll [machine]` and `cmd_fetch <machine> <remote-path> <local-dir>`. These complete the script's surface.

- [ ] **Step 1: Write the failing verification**

```bash
# tools/fleet-check/check_poll_fetch.sh
set -euo pipefail
JOB=pf_$$
DIR=/tmp/fleet_pf_$$
printf '#!/usr/bin/env bash\necho hello > out.txt\ntar czf result.tar.gz out.txt\nsleep 5\n' > /tmp/pf_$$.sh

bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/pf_$$.sh
bash tools/fleet.sh poll bm1 | grep -q "$JOB" || { echo "FAIL: poll missed running job"; exit 1; }

sleep 12
bash tools/fleet.sh poll bm1 | grep -q "$JOB" && { echo "FAIL: job still listed"; exit 1; }

bash tools/fleet.sh fetch bm1 "$DIR/result.tar.gz" /tmp/fleet_dl_$$
tar -tzf /tmp/fleet_dl_$$/result.tar.gz | grep -q out.txt

ssh bm1 "rm -rf $DIR"; rm -rf /tmp/fleet_dl_$$ /tmp/pf_$$.sh
echo "POLL/FETCH OK"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `bash tools/fleet-check/check_poll_fetch.sh`
Expected: FAIL at the `poll` step — unknown command, exit 1.

- [ ] **Step 3: Add `cmd_poll` and `cmd_fetch`**

```bash
cmd_poll() {
    local targets=("${FLEET_MACHINES[@]}")
    [ $# -eq 0 ] || targets=("$1")
    local m sessions
    for m in "${targets[@]}"; do
        if ! sessions=$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$m" \
                        "tmux ls -F '#{session_name} #{session_created}' 2>/dev/null"); then
            warn "$m: unreachable"; continue
        fi
        if [ -z "$sessions" ]; then
            printf '%-4s idle\n' "$m"
        else
            printf '%-4s %s\n' "$m" "$(printf '%s' "$sessions" | tr '\n' ' ')"
        fi
    done
}

cmd_fetch() {
    [ $# -eq 3 ] || die "usage: fleet.sh fetch <machine> <remote-path> <local-dir>"
    local m=$1 remote=$2 dest=$3
    mkdir -p "$dest"
    rsync -a --partial --append-verify --info=progress2 "$m:$remote" "$dest/"
    local f="$dest/$(basename "$remote")"
    if [ -f "$f" ] && [[ "$f" == *.tar.gz ]]; then
        tar -tzf "$f" >/dev/null 2>&1 || die "corrupt archive: $f"
        ok "verified $f ($(du -h "$f" | cut -f1))"
    else
        ok "fetched $f"
    fi
}
```

- [ ] **Step 4: Register both subcommands**

Add to the `case` block:
```bash
    poll)  shift; cmd_poll  "$@" ;;
    fetch) shift; cmd_fetch "$@" ;;
```
And to `usage()`:
```
  poll [machine]                          list running tmux jobs
  fetch <machine> <remote-path> <local-dir>   rsync a result back and verify it
```

- [ ] **Step 5: Run the verification**

Run: `bash tools/fleet-check/check_poll_fetch.sh`
Expected: `POLL/FETCH OK`.

- [ ] **Step 6: Confirm shellcheck, then commit**

```bash
shellcheck --shell=bash --severity=warning tools/fleet.sh
git add tools/fleet.sh tools/fleet-check/check_poll_fetch.sh
git commit -m "feat(fleet): poll running jobs and fetch verified results"
```

---

### Task 6: CI registration, playbook, and machine-local notes

**Files:**
- Modify: `.github/workflows/ci.yml:18-25`
- Create: `.claude/skills/binderscout-orchestrator/references/lab-deploy.md`
- Modify: `CLAUDE.local.md` (machine-local, gitignored)
- Modify: `.claude/skills/binderscout-orchestrator/SKILL.md`

**Interfaces:**
- Consumes: the finished `tools/fleet.sh`.
- Produces: documentation only.

- [ ] **Step 1: Add `tools/fleet.sh` to the CI shellcheck list**

In `.github/workflows/ci.yml`, extend the existing list:
```yaml
          shellcheck --shell=bash --severity=warning \
            install/install.sh \
            install/install_aarch.sh \
            Evaluator/evaluate.sh \
            Evaluator/install.sh \
            Evaluator/run.sh \
            tools/fleet.sh \
            docker-entrypoint.sh \
            test_env.sh
```

- [ ] **Step 2: Verify the CI command passes locally**

```bash
shellcheck --shell=bash --severity=warning \
  install/install.sh install/install_aarch.sh Evaluator/evaluate.sh \
  Evaluator/install.sh Evaluator/run.sh tools/fleet.sh \
  docker-entrypoint.sh test_env.sh
```
Expected: no output, exit 0.

- [ ] **Step 3: Write `lab-deploy.md`**

Mirror the structure of the existing `clara-deploy.md` (248 lines, numbered
sections). Required sections, with content drawn from the spec:

1. **When to use LAN deploy vs Clara** — LAN for the three x86 boxes; Clara for
   H200/L40S scale or when all three are busy.
2. **Machine facts you must respect** — the §2 inventory table; BM1's 31 GB RAM
   ceiling rules out long BindCraft runs; BM5 is aarch64 so Protein-Hunter cannot
   run there; all three peers need `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
3. **The deploy loop** — `probe` → `status` → `launch` → `poll` → `fetch`, with
   the exact commands from Tasks 2–5.
4. **What stays the same as classic orchestration** — `settings.json` per run,
   per-tool source-of-truth files for yield counts, packaging conventions,
   PROGRESS.md as the record.
5. **Failure modes** — the full §8 error-handling table from the spec.
6. **Cheat sheet** — one-liners for each subcommand.

- [ ] **Step 4: Point the orchestrator SKILL.md at the new reference**

`SKILL.md` currently says workers on BM2/BM4 are "a Claude Code instance reading
the assignment locally, a remote session driven by the orchestrator over VPN/SSH,
or a human." Add a sentence stating that BM5 now has direct LAN SSH to
BM1/BM2/BM4 and can drive them itself via `tools/fleet.sh`, pointing to
`references/lab-deploy.md` — exactly parallel to how the skill already points to
`references/clara-deploy.md` for Clara.

- [ ] **Step 5: Update `CLAUDE.local.md`**

Add a "Lab fleet" section with the §2 inventory table and the alias names, and a
"Clara unlock procedure" section:

```bash
# once, ever:
ssh-keygen -p -f ~/.ssh/id_ed25519_clara
# per working session, after starting FortiClient manually:
ssh-add -t 8h ~/.ssh/id_ed25519_clara
```

Also note that `/etc/openfortivpn/ciirc.conf` is owned by `<BM5_USER>`, not
root, so it is readable by anything running as that user — it holds no secret
today and must not be given one. Leave the existing VPN section otherwise
unchanged; it is accurate.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml \
        .claude/skills/binderscout-orchestrator/references/lab-deploy.md \
        .claude/skills/binderscout-orchestrator/SKILL.md
git commit -m "docs(fleet): lab-deploy playbook, skill pointer, CI shellcheck entry"
```

(`CLAUDE.local.md` is gitignored and is not part of this commit.)

---

## Self-Review

**Spec coverage.** D1 direct SSH → Tasks 1–5. D2 tmux → Task 4. D3 one `fleet.sh`
→ Tasks 2–5. D4 pull-then-archive → Task 5 `fetch`. D5 manual VPN → honoured by
omission; Task 3 only *detects* tunnel state. D6 bounded unlock → Task 3 detects
agent state; Task 6 Step 5 documents the procedure. D7 `authorized_keys`
restrictions → **not a code task**; it is a human step on Clara, tracked in the
spec §10 and surfaced by Task 3's `key=locked` warning. D8 LAN key unchanged →
Task 1 uses `~/.ssh/id_ed25519` as-is. Spec §5.2 inventory → Task 2. §5.4
admission → Task 4. §8 error table → Task 6 Step 3.

**Gap accepted:** the spec's §8 rows for BindCraft RSS monitoring and the Boltz-2
>820-token refusal are *documented* in `lab-deploy.md` but not *enforced* in
code. Enforcing them needs per-tool knowledge that belongs in the run scripts,
not in a generic dispatcher. Recorded here so it is a decision, not an oversight.

**Type consistency.** `probe_one`, `die`, `warn`, `ok`, `FLEET_MACHINES`,
`INVENTORY`, `GPU_BUSY_MIB`, `FLEET_FORCE` are named identically in every task.
The inventory keys used by `cmd_status` (`reachable`, `host`, `gpu`,
`gpu_procs`, `ram_gb`, `disk_free`, `git_branch`) all exist in the `probe_one`
output from Task 2.

**Placeholder scan.** The only intentional stand-in is `lab-deploy.md`'s section
list in Task 6 Step 3, which specifies required sections and their source
material rather than 250 lines of prose.
