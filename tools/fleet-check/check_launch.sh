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

# 1. a clean launch succeeds (forced past the real GPU job on bm1)
FLEET_FORCE=1 bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/canary_$$.sh
ssh bm1 "tmux has-session -t $JOB" || { echo "FAIL: session missing"; exit 1; }

# 2. relaunching the same job name is refused (deterministic collision check)
if FLEET_FORCE=1 bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/canary_$$.sh 2>/dev/null; then
    echo "FAIL: duplicate session was not refused"; exit 1
fi

# 3. cleanup
ssh bm1 "tmux kill-session -t $JOB 2>/dev/null; rm -rf $DIR"
rm -f /tmp/canary_$$.sh
echo "LAUNCH OK"
