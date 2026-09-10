#!/usr/bin/env bash
# measure.sh <label> -- <cmd...>
# Samples total GPU compute-app memory (NVML sees unified allocations; RSS and
# cgroups do not) and MemAvailable while <cmd> runs, then reports peaks.
set -uo pipefail
LABEL=${1:?label}; shift; [ "${1:-}" = "--" ] && shift
SAMP=$(mktemp)
gpu_total () { nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null | awk '{s+=$1} END{print s+0}'; }
mem_avail () { awk '/MemAvailable/{printf "%d", $2/1024}' /proc/meminfo; }   # MiB

BASE_GPU=$(gpu_total); BASE_MEM=$(mem_avail)
( while :; do echo "$(gpu_total) $(mem_avail)" >> "$SAMP"; sleep 1; done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

T0=$(date +%s)
"$@" > /tmp/mps5/${LABEL}.out 2>&1
RC=$?
T1=$(date +%s)
kill $SAMPLER 2>/dev/null; wait $SAMPLER 2>/dev/null

awk -v l="$LABEL" -v bg="$BASE_GPU" -v bm="$BASE_MEM" -v rc="$RC" -v dt="$((T1-T0))" '
{ if ($1>pg) pg=$1; if (nm=="" || $2<nm) nm=$2 }
END {
  printf "  %-28s peak_gpu %6d MiB (+%6d over base)   MemAvail drop %6d MiB   %4ds   rc=%d\n",
         l, pg, pg-bg, bm-nm, dt, rc
}' "$SAMP"
rm -f "$SAMP"
exit $RC
