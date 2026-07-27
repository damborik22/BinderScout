#!/usr/bin/env bash
# fleet.sh — drive the BindMaster LAN fleet (BM1/BM2/BM4) from BM5.
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

# Escape a value for safe embedding inside a single-quoted argument of a
# remote-shell command string: close the quote, emit an escaped literal
# quote, reopen the quote. Without this, a job name or dir containing a
# single quote could break out of the '...' wrapper used below and inject
# arbitrary commands into the remote ssh session.
sq() { printf '%s' "$1" | sed "s/'/'\\\\''/g"; }

# Emit 10 newline-separated raw fields describing a remote machine:
# host, arch, gpu, gpu_procs, ram_gb, disk_free, envs, git_sha, git_branch, tmux.
# Raw values (not JSON) so the caller can assemble JSON with `jq --arg`, which
# escapes quotes/backslashes correctly — a hand-rolled printf %s could not.
probe_one() {
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$1" "GPU_BUSY_MIB=$GPU_BUSY_MIB bash -s" <<'REMOTE'
set -u
gpu=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)
procs=$(nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null \
        | awk -v floor="$GPU_BUSY_MIB" '$1+0 > floor' | wc -l)
envs=$(ls -1 "$HOME"/miniforge3/envs "$HOME"/miniconda3/envs "$HOME"/anaconda3/envs \
             "$HOME"/dev/BindMaster/conda/envs 2>/dev/null \
       | grep -vE '^$|:' | sort -u | paste -sd,)
sha=$(git -C "$HOME/dev/BindMaster" rev-parse --short HEAD 2>/dev/null || echo none)
br=$(git -C "$HOME/dev/BindMaster" rev-parse --abbrev-ref HEAD 2>/dev/null || echo none)
printf '%s\n' \
    "$(hostname)" "$(uname -m)" "$gpu" "${procs:-0}" \
    "$(free -g | awk '/^Mem:/{print $2}')" \
    "$(df -h "$HOME" | awk 'NR==2{print $4}')" "$envs" "$sha" "$br" \
    "$(tmux -V 2>/dev/null | awk '{print $2}')"
REMOTE
}

# Full-shape placeholder for an unreachable machine — same key set as a
# reachable one, typed defaults (null for strings, 0 for gpu_procs).
UNREACHABLE_JSON='{"reachable":false,"host":null,"arch":null,"gpu":null,"gpu_procs":0,"ram_gb":null,"disk_free":null,"envs":null,"git_sha":null,"git_branch":null,"tmux":null}'

cmd_probe() {
    mkdir -p "$FLEET_DIR"
    local args=() m out json
    local -a f
    for m in "${FLEET_MACHINES[@]}"; do
        if out=$(probe_one "$m" 2>/dev/null) && [ -n "$out" ]; then
            mapfile -t f <<<"$out"
            json=$(jq -n \
                --arg host "${f[0]}" --arg arch "${f[1]}" --arg gpu "${f[2]}" \
                --argjson gpu_procs "${f[3]:-0}" --argjson ram_gb "${f[4]:-0}" \
                --arg disk_free "${f[5]}" --arg envs "${f[6]}" \
                --arg git_sha "${f[7]}" --arg git_branch "${f[8]}" --arg tmux "${f[9]}" \
                '{reachable:true, host:$host, arch:$arch, gpu:$gpu, gpu_procs:$gpu_procs,
                  ram_gb:$ram_gb, disk_free:$disk_free, envs:$envs, git_sha:$git_sha,
                  git_branch:$git_branch, tmux:$tmux}')
        else
            json="$UNREACHABLE_JSON"
            warn "probe: $m unreachable"
        fi
        args+=(--argjson "$m" "$json")
    done
    jq -n "${args[@]}" --arg generated "$(date -Is)" \
        '{generated:$generated, machines:{bm1:$bm1, bm2:$bm2, bm4:$bm4}}' > "$INVENTORY"
    ok "wrote $INVENTORY"
}

cmd_status() {
    [ -f "$INVENTORY" ] || die "no inventory — run: fleet.sh probe"
    # Single source of truth for column widths — header and data rows both
    # render through this format, so they can never drift out of sync again.
    # MACHINE is 7 chars wide because the literal label "MACHINE" is 7 chars;
    # %s is a minimum width and would silently NOT truncate a shorter spec.
    local row_fmt='%-7s %-14s %-24.24s %-6s %-6s %-8s %s'
    # shellcheck disable=SC2059  # row_fmt is our own fixed literal, not user input
    printf '%s%s%s\n' "$BOLD" "$(printf "$row_fmt" MACHINE HOST GPU BUSY RAM DISK BRANCH)" "$RESET"
    local m
    for m in "${FLEET_MACHINES[@]}"; do
        jq -r --arg m "$m" '
            .machines[$m] as $x
            | if $x.reachable
              then [$m, $x.host, ($x.gpu // "-" | split(",")[0]), ($x.gpu_procs|tostring),
                    (($x.ram_gb|tostring) + "G"), $x.disk_free, $x.git_branch]
              else [$m, "UNREACHABLE", "-", "-", "-", "-", "-"] end
            | @tsv' "$INVENTORY" \
        | awk -F'\t' -v fmt="$row_fmt" '{printf fmt"\n", $1,$2,$3,$4,$5,$6,$7}'
    done

    local tunnel key
    if ip link show ppp0 >/dev/null 2>&1; then tunnel=up; else tunnel=DOWN; fi
    if ssh-add -l 2>/dev/null | grep -q clara; then key=unlocked; else key=locked; fi
    printf '\n%-5s %s  tunnel=%s  key=%s\n' clara <CLARA_LOGIN_HOST> "$tunnel" "$key"
    [ "$tunnel" = up ]     || warn "Clara unreachable: start FortiClient manually."
    [ "$key" = unlocked ]  || warn "Clara key not in agent: ssh-add -t 8h ~/.ssh/id_ed25519_clara"
    printf 'inventory generated: %s\n' "$(jq -r .generated "$INVENTORY")"
}

cmd_launch() {
    [ $# -eq 4 ] || die "usage: fleet.sh launch <machine> <job> <remote-dir> <script>"
    local m=$1 job=$2 rundir=$3 script=$4
    [ -f "$script" ] || die "no such script: $script"
    case " ${FLEET_MACHINES[*]} " in *" $m "*) ;; *) die "unknown machine: $m" ;; esac

    # job/rundir are attacker-shaped values (caller-supplied strings) that get
    # embedded in single-quoted remote-shell arguments below; sq() escapes them.
    local qjob qdir
    qjob=$(sq "$job")
    qdir=$(sq "$rundir")

    # Admission check 1 — job-name collision (deterministic).
    if ssh "$m" "tmux has-session -t '$qjob'" 2>/dev/null; then
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

    ssh "$m" "mkdir -p '$qdir'"
    scp -q "$script" "$m:$rundir/run.sh"
    ssh "$m" "cd '$qdir' && tmux new-session -d -s '$qjob' \
        'export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; \
         bash run.sh > run.log 2>&1'"
    ok "$m: launched '$job' in $rundir (tmux attach -t $job to watch)"
}

usage() {
    cat <<'USAGE'
usage: fleet.sh <command> [args]

  probe                                   refresh ~/.claude/fleet/inventory.json
  status                                  fleet + Clara state (uses cached inventory)
  launch <machine> <job> <remote-dir> <script>   tmux-launch a run script
USAGE
    exit 1
}

case "${1:-}" in
    probe)  shift; cmd_probe "$@" ;;
    status) shift; cmd_status "$@" ;;
    launch) shift; cmd_launch "$@" ;;
    *)      usage ;;
esac
