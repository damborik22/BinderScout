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

# Negative case: a truncated/corrupt .tar.gz at the remote path must be
# rejected, not silently reported as a good fetch. Written into our own
# canary dir ($DIR, created by our own launch call above) so nothing
# outside what this script owns is touched.
CORRUPT_DL=/tmp/fleet_dl_corrupt_$$
ssh bm1 "printf 'not a valid gzip archive' > '$DIR/corrupt.tar.gz'"
if out=$(bash tools/fleet.sh fetch bm1 "$DIR/corrupt.tar.gz" "$CORRUPT_DL" 2>&1); then
    echo "FAIL: fetch accepted a corrupt archive"; printf '%s\n' "$out"; exit 1
fi
printf '%s\n' "$out" | grep -q "corrupt archive" || {
    echo "FAIL: corrupt-archive rejection missing its message"; printf '%s\n' "$out"; exit 1
}
rm -rf "$CORRUPT_DL"

ssh bm1 "rm -rf $DIR"; rm -rf /tmp/fleet_dl_$$ /tmp/pf_$$.sh
echo "POLL/FETCH OK"
