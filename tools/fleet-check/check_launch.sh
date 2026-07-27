#!/usr/bin/env bash
set -euo pipefail
JOB=canary_$$
DIR=/tmp/fleet_canary_$$
printf '#!/usr/bin/env bash\nsleep 60\necho done\n' > /tmp/canary_$$.sh

# bm1 is a live lab machine currently running a genuine ~18 GB GPU refold
# job (see CLAUDE.local.md). The canary below is sleep-based and GPU-free,
# so it cannot disturb that job — but the admission check will (correctly)
# refuse a clean launch while bm1 is GPU-busy. FLEET_FORCE=1 overrides the
# GPU-busy refusal only; it does not touch the job-name collision check.

# 1. an UNFORCED launch is refused, because bm1's GPU is genuinely busy right
#    now (real production job) — this exercises the confirmed-busy refusal
#    path itself, which every other launch in this script masks with
#    FLEET_FORCE=1. Nothing is shipped to bm1: the admission check refuses
#    before mkdir/scp, so this touches no GPU and leaves no remote state.
UNFORCED_JOB=canary_unforced_$$
UNFORCED_DIR=/tmp/fleet_canary_unforced_$$
if err=$(bash tools/fleet.sh launch bm1 "$UNFORCED_JOB" "$UNFORCED_DIR" /tmp/canary_$$.sh 2>&1); then
    echo "FAIL: unforced launch on GPU-busy bm1 was not refused"; printf '%s\n' "$err"; exit 1
fi
printf '%s\n' "$err" | grep -q "GPU busy" || {
    echo "FAIL: refusal did not report GPU busy"; printf '%s\n' "$err"; exit 1
}

# 2. a clean launch succeeds (forced past the real GPU job on bm1)
FLEET_FORCE=1 bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/canary_$$.sh
ssh bm1 "tmux has-session -t $JOB" || { echo "FAIL: session missing"; exit 1; }

# 3. relaunching the same job name is refused (deterministic collision check)
if FLEET_FORCE=1 bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/canary_$$.sh 2>/dev/null; then
    echo "FAIL: duplicate session was not refused"; exit 1
fi

# 4. cleanup
ssh bm1 "tmux kill-session -t $JOB 2>/dev/null; rm -rf $DIR"
rm -f /tmp/canary_$$.sh
echo "LAUNCH OK"
