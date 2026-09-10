#!/usr/bin/env bash
# Run all three refold engines simultaneously on the SAME 340-token complex.
set -uo pipefail
P=/tmp/mps5/pools/L2_pdl1_340
TGT=$(cat $P.target)
BOLTZ=/home/bindmaster5/dev/BindMaster/Mosaic/.venv/bin/binder-compare
SAMP=/tmp/mps5/conc_samples.csv
: > "$SAMP"

sample () {
  while :; do
    local g n a
    g=$(nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null | awk '{s+=$1} END{print s+0}')
    n=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c . )
    a=$(awk '/MemAvailable/{printf "%d", $2/1024}' /proc/meminfo)
    echo "$(date +%s),$g,$n,$a" >> "$SAMP"
    sleep 1
  done
}
sample & SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null' EXIT

t () { local s=$1; shift; local b=$(date +%s); "$@" >/tmp/mps5/conc_$s.out 2>&1; echo "$s $? $(( $(date +%s) - b ))" >> /tmp/mps5/conc_rc.txt; }
: > /tmp/mps5/conc_rc.txt

echo "  launching all three at $(date +%T) ..."
t af3 env CUDA_MPS_PINNED_DEVICE_MEM_LIMIT="0=12G" AF3_XLA_MEM_FRACTION=0.099 \
    timeout 2400 conda run -n binder-eval-af3 binder-compare refold-af3 \
      --sequences $P.fasta --target-seq "$TGT" \
      --output /tmp/mps5/conc_af3.csv --output-dir /tmp/mps5/conc_af3_out &
t boltz2 env CUDA_MPS_PINNED_DEVICE_MEM_LIMIT="0=24G" BOLTZ2_XLA_MEM_FRACTION=0.197 \
    timeout 2400 $BOLTZ refold-boltz2 \
      --sequences $P.fasta --target-seq "$TGT" \
      --output /tmp/mps5/conc_boltz2.csv --output-dir /tmp/mps5/conc_boltz2_out &
t esmfold2 env CUDA_MPS_PINNED_DEVICE_MEM_LIMIT="0=24G" \
    timeout 2400 conda run -n binder-eval-esmfold2 binder-compare refold-esmfold2 --model full \
      --sequences $P.fasta --target-seq "$TGT" \
      --output /tmp/mps5/conc_esm.csv --output-dir /tmp/mps5/conc_esm_out &
wait
kill $SAMPLER 2>/dev/null
echo "  all finished at $(date +%T)"
