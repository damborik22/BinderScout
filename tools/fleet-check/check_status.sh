#!/usr/bin/env bash
set -euo pipefail
out=$(bash tools/fleet.sh status)
printf '%s\n' "$out"
grep -q 'bm1' <<<"$out"
grep -q 'bm4' <<<"$out"
grep -qE 'clara .*tunnel=(up|DOWN)' <<<"$out"
grep -qE 'key=(unlocked|locked)'    <<<"$out"
echo "STATUS OK"
