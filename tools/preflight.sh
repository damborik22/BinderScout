#!/usr/bin/env bash
# preflight.sh — REQUIRED before launching any job on a fleet machine.
#
# WHY THIS EXISTS (2026-08-16): 16 MPNN workers were launched on BM5 sized off
# their 339 MiB *GPU* footprint. Actual host RSS was 3.1 GB each = 42.6 GB. The
# box fell from 115 GB available to 24 GB and killed 3 of the 4 arms of a
# running reproducibility experiment, which had declared FLOOR_GB=25 inside its
# own script where nothing else could see it. The pipeline then logged
# "REPRO2 ALL DONE" and looked finished.
#
# Two failures, two guards here:
#   1. RSS was never measured before scaling  -> --measure runs ONE worker and
#      reports peak RSS, so N is sized on evidence.
#   2. A running job's memory floor was invisible -> declared floors are written
#      to /tmp/bindmaster-floors/ and this script refuses to clear a launch that
#      would breach one.
#
# Usage:
#   preflight.sh check <host> <needed_gb> [needed_vram_gb]
#   preflight.sh measure <command...>          # peak RSS of one instance
#   preflight.sh declare <name> <floor_gb>     # register a floor while you run
#   preflight.sh release <name>
set -uo pipefail
FLOORDIR=${BINDMASTER_FLOORDIR:-/tmp/bindmaster-floors}
MARGIN_GB=${MARGIN_GB:-15}          # never plan to leave less than this free
mkdir -p "$FLOORDIR"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLD=$'\033[1m'; RST=$'\033[0m'

remote () { # $1=host, rest=cmd  (empty/localhost host runs locally)
    local h=$1; shift
    if [ -z "$h" ] || [ "$h" = local ] || [ "$h" = "$(hostname -s)" ]; then
        bash -c "$*"
    else
        ssh -o ConnectTimeout=10 -n "$h" "$*"
    fi
}

cmd_check () {
    local host=${1:-local} need=${2:?need GB} vram=${3:-0} fail=0
    echo "${BLD}preflight: $host  need ${need}G RAM / ${vram}G VRAM  (margin ${MARGIN_GB}G)${RST}"

    local avail total
    avail=$(remote "$host" "awk '/MemAvailable/{print int(\$2/1048576)}' /proc/meminfo")
    total=$(remote "$host" "awk '/MemTotal/{print int(\$2/1048576)}' /proc/meminfo")
    echo "  RAM: ${avail}G available of ${total}G"

    echo "  running (>1G RSS):"
    remote "$host" "ps -eo rss,etime,args --sort=-rss | awk 'NR>1 && \$1>1048576' | head -8 | cut -c1-150" \
      | sed 's/^/    /' || true

    if remote "$host" "command -v nvidia-smi >/dev/null 2>&1"; then
        echo "  GPU:"
        remote "$host" "nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader" \
          | sed 's/^/    /' || echo "    (none)"
    fi

    # --- declared floors (the guard that was missing) ---
    local floors=0
    shopt -s nullglob
    for f in "$FLOORDIR"/*.floor; do
        local nm fl pid
        nm=$(basename "$f" .floor)
        fl=$(awk 'NR==1{print $1}' "$f"); pid=$(awk 'NR==1{print $2}' "$f")
        if [ -n "${pid:-}" ] && ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$f"; continue                 # stale: owner gone
        fi
        echo "  ${YEL}declared floor:${RST} $nm needs >= ${fl}G available (pid $pid)"
        floors=$(( floors > fl ? floors : fl ))
    done
    shopt -u nullglob

    local after=$(( avail - need ))
    echo "  after launch: ${after}G would remain"
    if [ "$after" -lt "$MARGIN_GB" ]; then
        echo "  ${RED}REFUSE${RST}: would leave ${after}G, below margin ${MARGIN_GB}G"; fail=1
    fi
    if [ "$floors" -gt 0 ] && [ "$after" -lt "$floors" ]; then
        echo "  ${RED}REFUSE${RST}: would breach a declared floor of ${floors}G"; fail=1
    fi
    [ "$fail" -eq 0 ] && echo "  ${GRN}CLEAR${RST}"
    return $fail
}

cmd_measure () {
    # Reports BOTH peak RSS and the MemAvailable drop, and plans on the LARGER.
    #
    # RSS alone is not safe on Spark: JAX preallocates unified memory that never
    # appears in RSS. Observed 2026-08-16 on BM5 -- fold_monomers.py showed
    # 8.5 GB RSS while MemAvailable fell to 15 GB of 121 GB. Sizing a worker
    # count off RSS there would understate the footprint by ~10x.
    [ $# -ge 1 ] || { echo "measure needs a command"; return 2; }
    local tmp base low; tmp=$(mktemp)
    base=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
    low=$base
    /usr/bin/time -v "$@" >/dev/null 2>"$tmp" &
    local pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        local a; a=$(awk '/MemAvailable/{print int($2/1048576)}' /proc/meminfo)
        [ "$a" -lt "$low" ] && low=$a
        sleep 1
    done
    wait "$pid" 2>/dev/null
    local kb; kb=$(awk '/Maximum resident set size/{print $NF}' "$tmp"); rm -f "$tmp"
    awk -v k="${kb:-0}" -v b="$base" -v l="$low" 'BEGIN{
        rss=k/1048576; drop=b-l; use=(drop>rss?drop:rss);
        printf "peak RSS          : %.2f GB\n", rss;
        printf "MemAvailable drop : %d GB   (%d -> %d)\n", drop, b, l;
        printf "PLAN ON           : %.2f GB per instance%s\n", use, (drop>rss?"   <-- RSS understated it":"");
        printf "  16 workers -> %.0f GB\n  12 workers -> %.0f GB\n   8 workers -> %.0f GB\n   4 workers -> %.0f GB\n",
               16*use, 12*use, 8*use, 4*use;
    }'
}

cmd_declare () {
    local name=${1:?name} floor=${2:?floor_gb}
    echo "$floor $PPID" > "$FLOORDIR/$name.floor"
    echo "declared: $name needs >= ${floor}G available (owner pid $PPID)"
}
cmd_release () { rm -f "$FLOORDIR/${1:?name}.floor"; echo "released: $1"; }

case "${1:-}" in
    check)   shift; cmd_check "$@" ;;
    measure) shift; cmd_measure "$@" ;;
    declare) shift; cmd_declare "$@" ;;
    release) shift; cmd_release "$@" ;;
    *) sed -n '1,30p' "$0"; exit 2 ;;
esac
