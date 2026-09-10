#!/usr/bin/env bash
# A/B: staggered-concurrent vs sequential refolding on a realistic pool.
# Concurrent runs FIRST on purpose: the sequential arm then benefits from the warm
# JAX compile cache, biasing the comparison AGAINST concurrency. If concurrency
# still wins under that handicap, the result is trustworthy.
set -uo pipefail
W=~/bm5_throughput_test
R=/home/bindmaster5/dev/BindMaster
P=$W/pools/tp6
TGT=$(cat $P.target)
: > $W/ab_results.txt

# NOTE: the background loop MUST have its stdout redirected. Without it the loop
# inherits the stdout pipe of the enclosing $( ), and command substitution blocks
# until every writer closes that pipe -- so `pid=$(sample_start ...)` hangs forever
# on an infinite sampler. Cost us one dead run.
sample_start () { : > "$W/samp_$1.csv"
  ( while :; do
      echo "$(date +%s),$(awk '/MemAvailable/{printf "%d",$2/1024}' /proc/meminfo),$(nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null | awk '{s+=$1}END{print s+0}')" >> "$W/samp_$1.csv"
      sleep 2
    done ) >/dev/null 2>&1 & echo $!; }

run_arm () {
  local arm=$1; shift
  local nvrm0 pid t0 t1 rc
  nvrm0=$(journalctl -k -b --no-pager 2>/dev/null | grep -i nvrm | grep -vci 'loading NVIDIA UNIX')
  pid=$(sample_start "$arm")
  t0=$(date +%s)
  bash "$R/Evaluator/evaluate.sh" --sequences $P.fasta --target-seq "$TGT" \
      --skip-soluprot --output "$W/out_$arm" "$@" > "$W/log_$arm.txt" 2>&1
  rc=$?
  t1=$(date +%s)
  kill "$pid" 2>/dev/null
  local nvrm1; nvrm1=$(journalctl -k -b --no-pager 2>/dev/null | grep -i nvrm | grep -vci 'loading NVIDIA UNIX')
  # VALIDATE EVERY ENGINE. rc=0 is NOT evidence an engine ran: on 2026-08-20 AF3
  # wrote 6 empty rows, exited 0, and the whole A/B was scored as valid.
  local val; val=$(/usr/bin/python3 - "$W/out_$arm" <<'PYV'
import csv, pathlib, sys
d = pathlib.Path(sys.argv[1]); out = []
for name, want in (("boltz2_results.csv","iptm_aux"),("af3_results.csv","iptm"),("esmfold2_results.csv","iptm")):
    p = d / name
    if not p.exists():
        out.append(f"{name.split('_')[0]}=MISSING"); continue
    rows = list(csv.DictReader(p.open()))
    col = want if rows and want in rows[0] else next((k for k in (rows[0] if rows else {}) if "iptm" in k), None)
    n = sum(1 for r in rows if col and (r[col] or "").strip() not in ("", "nan"))
    out.append(f"{name.split('_')[0]}={n}/{len(rows)}")
print(" ".join(out))
PYV
)
  awk -F, -v a="$arm" -v w="$((t1-t0))" -v rc="$rc" -v nv="$((nvrm1-nvrm0))" -v val="$val" '
    {if(nm==""||$2<nm)nm=$2; if($3>pg)pg=$3}
    END{printf "%s wall=%ds rc=%d minMemAvail=%dMiB peakGPU=%dMiB nvrm=%d  ENGINES[%s]\n", a, w, rc, nm, pg, nv, val}
  ' "$W/samp_$arm.csv" >> $W/ab_results.txt
  cat $W/ab_results.txt
}

echo "=== ARM B: --concurrent --stagger 30 (runs first; cold caches) ==="
run_arm conc --concurrent --stagger 30
echo "=== ARM A: sequential (warm caches — handicap favours this arm) ==="
run_arm seq
echo "=== DONE ==="
