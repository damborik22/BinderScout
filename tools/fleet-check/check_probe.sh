#!/usr/bin/env bash
set -euo pipefail
bash tools/fleet.sh probe
jq -e '.machines | keys == ["bm1","bm2","bm4"]' ~/.claude/fleet/inventory.json
jq -e '[.machines[] | select(.reachable == true)] | length == 3' ~/.claude/fleet/inventory.json
jq -e '.machines.bm1.arch == "x86_64"' ~/.claude/fleet/inventory.json
jq -e '.machines.bm1.ram_gb == 31' ~/.claude/fleet/inventory.json
echo "PROBE OK"
