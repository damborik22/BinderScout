#!/usr/bin/env bash
# fleet.sh — drive the BindMaster LAN fleet (BM1/BM2/BM4) from BM5.
# Design: docs/PLAN_fleet_orchestration.md
set -euo pipefail

FLEET_MACHINES=(bm1 bm2 bm4)
FLEET_DIR="${FLEET_DIR:-$HOME/.claude/fleet}"
INVENTORY="$FLEET_DIR/inventory.json"
# shellcheck disable=SC2034  # used by status/launch subcommands added in later tasks
GPU_BUSY_MIB=512   # ignore snapd-desktop-integration (~6 MiB) on BM4

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
# shellcheck disable=SC2034  # used by status/launch subcommands added in later tasks
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
             "$HOME"/dev/BindMaster/conda/envs 2>/dev/null \
       | grep -vE '^$|:' | sort -u | paste -sd,)
sha=$(git -C "$HOME/dev/BindMaster" rev-parse --short HEAD 2>/dev/null || echo none)
br=$(git -C "$HOME/dev/BindMaster" rev-parse --abbrev-ref HEAD 2>/dev/null || echo none)
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
