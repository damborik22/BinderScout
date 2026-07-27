#!/usr/bin/env bash
set -euo pipefail
out=$(bash tools/fleet.sh status)
printf '%s\n' "$out"
grep -q 'bm1' <<<"$out"
grep -q 'bm2' <<<"$out"
grep -q 'bm4' <<<"$out"

# Tunnel/key assertions must check the SPECIFIC expected value, not just that
# the printed value is one of the possible ones — grep -qE '(up|DOWN)' would
# still pass even if the up/down logic in fleet.sh were reversed. Compute the
# expectation independently, the same way fleet.sh itself does, and assert
# that exact value.
if ip link show ppp0 >/dev/null 2>&1; then exp_tunnel=up; else exp_tunnel=DOWN; fi
if ssh-add -l 2>/dev/null | grep -q clara; then exp_key=unlocked; else exp_key=locked; fi
grep -q "tunnel=$exp_tunnel" <<<"$out" || { echo "FAIL: expected tunnel=$exp_tunnel"; exit 1; }
grep -q "key=$exp_key"       <<<"$out" || { echo "FAIL: expected key=$exp_key"; exit 1; }

# Column-alignment regression test: the header/data desync bug took two
# review rounds to fix and had no test. Strip ANSI color codes, then assert
# that every header label's character offset is where the first data row
# actually starts a field (non-space) — if a column were shifted, the data
# row would have a space (or the wrong field) at the header's label offset.
plain=$(printf '%s\n' "$out" | sed -E 's/\x1b\[[0-9;]*m//g')
header_line=$(printf '%s\n' "$plain" | grep -m1 '^MACHINE')
row_line=$(printf '%s\n' "$plain" | grep -m1 -E '^bm1 ')
[ -n "$header_line" ] || { echo "FAIL: no header line found"; exit 1; }
[ -n "$row_line" ]    || { echo "FAIL: no bm1 data row found"; exit 1; }
for label in MACHINE HOST GPU BUSY RAM DISK BRANCH; do
    off=$(awk -v w="$label" '{print index($0,w)}' <<<"$header_line")
    [ "$off" -gt 0 ] || { echo "FAIL: header missing $label"; exit 1; }
    ch=$(cut -c"$off" <<<"$row_line")
    [ "$ch" != " " ] || {
        echo "FAIL: column $label not aligned in data row (offset $off is blank)"
        printf 'header: %s\n' "$header_line"
        printf 'row:    %s\n' "$row_line"
        exit 1
    }
done

echo "STATUS OK"
