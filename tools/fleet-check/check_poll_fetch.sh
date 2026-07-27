#!/usr/bin/env bash
set -euo pipefail
JOB=pf_$$
DIR=/tmp/fleet_pf_$$
printf '#!/usr/bin/env bash\necho hello > out.txt\ntar czf result.tar.gz out.txt\nsleep 5\n' > /tmp/pf_$$.sh

FLEET_FORCE=1 bash tools/fleet.sh launch bm1 "$JOB" "$DIR" /tmp/pf_$$.sh
bash tools/fleet.sh poll bm1 | grep -q "$JOB" || { echo "FAIL: poll missed running job"; exit 1; }

sleep 12
bash tools/fleet.sh poll bm1 | grep -q "$JOB" && { echo "FAIL: job still listed"; exit 1; }

bash tools/fleet.sh fetch bm1 "$DIR/result.tar.gz" /tmp/fleet_dl_$$
tar -tzf /tmp/fleet_dl_$$/result.tar.gz | grep -q out.txt

ssh bm1 "rm -rf $DIR"; rm -rf /tmp/fleet_dl_$$ /tmp/pf_$$.sh
echo "POLL/FETCH OK"
