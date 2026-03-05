#!/bin/bash
# BindMaster Installer — Lucia's custom profile
# Installs BindCraft with conda env named "BindCraft_1" and venv mode enabled.
#
# Usage:
#   bash install/install_lucia.sh [additional options...]
#
# This is a thin wrapper around install.sh with pre-configured defaults:
#   --tool bindcraft  (only BindCraft)
#   --env-name BindCraft_1
#   --venv            (no conda required)
#
# All other install.sh flags are still accepted, e.g.:
#   bash install/install_lucia.sh --cuda 12.4 --skip-examples --yes

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "${SCRIPT_DIR}/install.sh" \
    --tool bindcraft \
    --env-name BindCraft_1 \
    --venv \
    "$@"
