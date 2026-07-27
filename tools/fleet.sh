#!/usr/bin/env bash
# fleet.sh — drive the BindMaster LAN fleet (BM1/BM2/BM4) from BM5.
# Design: docs/PLAN_fleet_orchestration.md
set -euo pipefail

FLEET_MACHINES=(bm1 bm2 bm4)
FLEET_DIR="${FLEET_DIR:-$HOME/.claude/fleet}"
INVENTORY="$FLEET_DIR/inventory.json"
GPU_BUSY_MIB=512   # ignore snapd-desktop-integration (~6 MiB) on BM4

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
# shellcheck disable=SC2034  # used by status/launch subcommands added in later tasks
BOLD=$'\033[1m'; RESET=$'\033[0m'

die()  { printf '%s%s%s\n' "$RED"    "$*" "$RESET" >&2; exit 1; }
warn() { printf '%s%s%s\n' "$YELLOW" "$*" "$RESET" >&2; }
ok()   { printf '%s%s%s\n' "$GREEN"  "$*" "$RESET"; }

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
