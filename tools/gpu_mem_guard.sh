#!/usr/bin/env bash
# gpu_mem_guard.sh — give a unified-memory host (DGX Spark / GB10) the device
# boundary it does not have, so a runaway GPU job dies instead of the machine.
#
# WHY THIS EXISTS (2026-08-18/19): on GB10 `cudaMemGetInfo` reports
# total == SC_PHYS_PAGES == 121.69 GiB. Every allocator knob in JAX and PyTorch
# is a *fraction of device total*, so JAX's default 0.75 reserves 91 GB of the
# machine's own RAM. That hard-rebooted BM5 once (AF3 at 0.8 -> 97.4 GiB) and
# nearly again the next day (Boltz-2 at the 0.75 default -> 91.3 GiB).
#
# cgroups DO NOT help: measured here, 12 GiB of cudaMalloc inside an 8 GiB
# memory.max, with memory.current rising 87 MiB and memory.events max=0. Root
# cause is in NVIDIA's source -- the driver only wires up the `dmem` cgroup
# controller from 610.43.02; on 580.x `os_dmem_cgroup_try_charge()` is a stub
# returning NV_OK. CUDA MPS per-client limits DO work (verified on 580.159.03).
#
# Usage:
#   gpu_mem_guard.sh is-up                  # exit 0 iff MPS is up (for scripts)
#   gpu_mem_guard.sh verify                 # ~60s: prove MPS enforcement works HERE
#   gpu_mem_guard.sh start [cap]            # start MPS daemon w/ default cap (16G)
#   gpu_mem_guard.sh stop
#   gpu_mem_guard.sh status
#   gpu_mem_guard.sh run <cap> -- <cmd...>  # run one job under a per-client cap
#   gpu_mem_guard.sh watch <floor_gb>       # backstop: kill the GPU hog, not the box
#
# Re-run `verify` after EVERY driver / kernel / firmware change. MPS pinned
# limits are reported silently non-enforcing on some builds (k8s-device-plugin
# #467, #764) -- enforcement is re-established, never assumed.
set -uo pipefail

# Socket dir must be SHORT: AF_UNIX sun_path caps at 108 bytes and a long path
# makes the daemon log "Starting control daemon" and then die silently.
MPS_DIR=${BINDMASTER_MPS_DIR:-/tmp/bindmaster-mps}
export CUDA_MPS_PIPE_DIRECTORY="$MPS_DIR/pipe"
export CUDA_MPS_LOG_DIRECTORY="$MPS_DIR/log"
DEFAULT_CAP=${BINDMASTER_GPU_CAP:-16G}

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLD=$'\033[1m'; RST=$'\033[0m'

# NOTE: never `pgrep -x nvidia-cuda-mps-control` (name >15 chars, kernel comm
# limit -> always zero matches) and never `pkill -f nvidia-cuda-mps` (matches
# your own shell's command line and kills the caller). Use the control channel.
ctl () { echo "$1" | timeout 20 nvidia-cuda-mps-control 2>&1; }

# If the systemd --user unit owns the daemon, start/stop MUST go through systemd.
# Otherwise `verify` stops the unit's daemon, starts its own replacement, and
# `systemctl stop` then no longer tracks it -- leaving a stray daemon holding
# machine-wide MPS state. Observed 2026-08-20.
UNIT=bindmaster-mps
unit_active () { systemctl --user is-active --quiet "$UNIT" 2>/dev/null; }
# NB: capture into a variable and match the string -- do NOT pipe into grep.
# `set -o pipefail` is on, and nvidia-cuda-mps-control exits 1 when the daemon is
# down, so a pipeline would return 1 regardless of what grep found and `!` would
# invert it into a false "MPS is up".
mps_up () { local out; out=$(ctl get_server_list); [[ "$out" != *"Cannot find"* ]]; }

mem_avail_gb () { awk '/MemAvailable/{printf "%d", $2/1048576}' /proc/meminfo; }

cmd_start () {
    local cap=${1:-$DEFAULT_CAP}
    mkdir -p "$CUDA_MPS_PIPE_DIRECTORY" "$CUDA_MPS_LOG_DIRECTORY"
    if unit_active; then
        echo "${YEL}MPS is managed by systemd unit $UNIT -- restarting through it${RST}"
        systemctl --user restart "$UNIT"; sleep 3
        ctl "set_default_device_pinned_mem_limit 0 $cap" >/dev/null
        echo "${GRN}MPS up${RST} (systemd), cap = $(ctl 'get_default_device_pinned_mem_limit 0')"
        return 0
    fi
    if mps_up; then echo "MPS already running"; else
        nvidia-cuda-mps-control -d >/dev/null 2>&1; sleep 3
        mps_up || { echo "${RED}failed to start MPS${RST}"; sed 's/^/  /' "$CUDA_MPS_LOG_DIRECTORY/control.log" 2>/dev/null; return 1; }
    fi
    ctl "set_default_device_pinned_mem_limit 0 $cap" >/dev/null
    echo "${GRN}MPS up${RST}, default device pinned mem limit = $(ctl 'get_default_device_pinned_mem_limit 0')"
}

cmd_stop () {
    if unit_active; then systemctl --user stop "$UNIT"; sleep 2; echo "MPS stopped (systemd)"; return 0; fi
    mps_up || { echo "MPS not running"; return 0; }
    ctl quit >/dev/null 2>&1; sleep 2
    mps_up && echo "${RED}MPS still up${RST}" || echo "MPS stopped"
}

cmd_status () {
    echo "${BLD}gpu_mem_guard status${RST}"
    if mps_up; then
        echo "  MPS:  ${GRN}up${RST}  servers: $(ctl get_server_list | tr '\n' ' ')"
        echo "  cap:  $(ctl 'get_default_device_pinned_mem_limit 0')"
    else
        echo "  MPS:  ${RED}DOWN${RST}  -- clients run UNCAPPED against the whole 121.7 GiB pool"
    fi
    echo "  MemAvailable: $(mem_avail_gb) GB"
    echo "  GPU clients:"
    nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null \
        | sed 's/^/    /' || echo "    (none)"
}

cmd_run () {
    local cap=${1:?need a cap, e.g. 16G}; shift
    [ "${1:-}" = "--" ] && shift
    [ $# -ge 1 ] || { echo "run needs a command"; return 2; }
    mps_up || cmd_start "$cap" >/dev/null || return 1
    CUDA_MPS_PINNED_DEVICE_MEM_LIMIT="0=$cap" exec "$@"
}

cmd_verify () {
    local cap_gib=2 try_gib=4 probe rc
    echo "${BLD}verifying MPS device-memory enforcement on this driver${RST}"
    echo "  driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null)"
    # Preserve the caller's cap: restoring the *default* would silently shrink a
    # deliberately-sized budget and make later measurements untrustworthy.
    # Also remember whether SYSTEMD owned the daemon -- verify runs its own daemon for
    # the test, and restoring via the direct path would leave that one running untracked.
    local was_up=0 prev_cap="" unit_owned=0
    unit_active && unit_owned=1
    if mps_up; then
        was_up=1
        prev_cap=$(ctl 'get_default_device_pinned_mem_limit 0' | tr -d '[:space:]')
        echo "  ${YEL}MPS already running (cap ${prev_cap:-?}) -- stopping for a clean test${RST}"
        cmd_stop >/dev/null
    fi

    probe=$(mktemp /tmp/gmg_probe_XXXX.py)
    cat > "$probe" <<'PY'
import ctypes, sys
gib = int(sys.argv[1])
rt = ctypes.CDLL("libcudart.so")
rt.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
rt.cudaMalloc.restype = ctypes.c_int
p = ctypes.c_void_p()
sys.exit(0 if rt.cudaMalloc(ctypes.byref(p), gib * 2**30) == 0 else 1)
PY
    mkdir -p "$CUDA_MPS_PIPE_DIRECTORY" "$CUDA_MPS_LOG_DIRECTORY"
    nvidia-cuda-mps-control -d >/dev/null 2>&1; sleep 3
    if ! mps_up; then echo "  ${RED}FAIL${RST}: MPS daemon would not start"; rm -f "$probe"; return 1; fi
    ctl "set_default_device_pinned_mem_limit 0 ${cap_gib}G" >/dev/null
    echo "  cap set to $(ctl "get_default_device_pinned_mem_limit 0"); attempting a ${try_gib} GiB allocation"
    CUDA_MPS_PINNED_DEVICE_MEM_LIMIT="0=${cap_gib}G" timeout 120 /usr/bin/python3 "$probe" "$try_gib"
    rc=$?
    rm -f "$probe"; cmd_stop >/dev/null
    if [ $unit_owned -eq 1 ]; then
        systemctl --user start "$UNIT"; sleep 3
    elif [ $was_up -eq 1 ]; then
        cmd_start "${prev_cap:-$DEFAULT_CAP}" >/dev/null
    fi

    if [ $rc -eq 1 ]; then
        echo "  ${GRN}PASS${RST}: ${try_gib} GiB refused under a ${cap_gib} GiB cap -- MPS enforcement is live"
        return 0
    fi
    echo "  ${RED}FAIL${RST}: ${try_gib} GiB was ALLOWED under a ${cap_gib} GiB cap (rc=$rc)."
    echo "  ${RED}MPS is NOT enforcing on this driver. Do not rely on Layer 1.${RST}"
    return 1
}

cmd_watch () {
    # Backstop for what MPS does not cover: host RSS, non-CUDA memory, MPS down.
    # Victim selection MUST come from NVML, not RSS: GPU pages do not inflate a
    # process's RSS, so the kernel OOM killer and earlyoom fire at the right TIME
    # but can aim at the wrong PROCESS.
    local floor=${1:?need floor_gb} interval=${2:-2}
    echo "watching: kill the largest GPU client if MemAvailable < ${floor} GB (every ${interval}s)"
    while :; do
        local avail; avail=$(mem_avail_gb)
        if [ "$avail" -lt "$floor" ]; then
            local victim
            victim=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null \
                     | sort -t, -k2 -n | tail -1 | cut -d, -f1 | tr -d ' ')
            if [ -n "$victim" ]; then
                echo "$(date -Is) MemAvailable=${avail}G < ${floor}G -- killing GPU client $victim"
                kill -TERM "$victim" 2>/dev/null; sleep 5; kill -KILL "$victim" 2>/dev/null
            else
                echo "$(date -Is) MemAvailable=${avail}G < ${floor}G but no GPU client found"
            fi
        fi
        sleep "$interval"
    done
}

case "${1:-}" in
    is-up)   mps_up ;;                      # exit 0 if MPS is enforcing; for scripts
    verify)  shift; cmd_verify "$@" ;;
    start)   shift; cmd_start  "$@" ;;
    stop)    shift; cmd_stop   "$@" ;;
    status)  shift; cmd_status "$@" ;;
    run)     shift; cmd_run    "$@" ;;
    watch)   shift; cmd_watch  "$@" ;;
    *) sed -n '2,28p' "$0"; exit 2 ;;
esac
