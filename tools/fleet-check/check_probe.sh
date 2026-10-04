#!/usr/bin/env bash
set -euo pipefail
bash tools/fleet.sh probe
jq -e '.machines | keys == ["bm1","bm2","bm4"]' ~/.claude/fleet/inventory.json
jq -e '[.machines[] | select(.reachable == true)] | length == 3' ~/.claude/fleet/inventory.json
jq -e '.machines.bm1.arch == "x86_64"' ~/.claude/fleet/inventory.json
jq -e '.machines.bm1.ram_gb == 31' ~/.claude/fleet/inventory.json
# The gap that let the 2.0 rename ship: every reachable machine answered, and every
# repo-derived field silently fell back to "none"/"" because the checkout directory was
# hardcoded to one spelling. Assert that a reachable machine resolved a REAL repo --
# a branch and a non-empty env list -- so a probe that resolves nothing fails here.
jq -e '[.machines[] | select(.reachable == true) | select(.git_branch == "none" or .git_branch == null)] | length == 0' \
   ~/.claude/fleet/inventory.json || { echo "FAIL: a reachable machine reported git_branch=none"; exit 1; }
jq -e '[.machines[] | select(.reachable == true) | select((.envs // "") == "")] | length == 0' \
   ~/.claude/fleet/inventory.json || { echo "FAIL: a reachable machine reported an empty envs list"; exit 1; }
echo "PROBE OK"
