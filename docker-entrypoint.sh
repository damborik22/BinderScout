#!/bin/bash
# Entrypoint for the bindmaster-test container.
# Sets up a usable home directory for whatever UID the container runs as,
# and initialises conda/mamba for the current shell session.

set -e

# ── Home directory ─────────────────────────────────────────────────────────────
# When running with a host UID (--user $(id -u):$(id -g)), $HOME may be /
# or unset. Give ourselves a real writable home inside the container.
if [[ ! -d "${HOME}" ]] || [[ "${HOME}" == "/" ]]; then
    export HOME=/home/bindmaster-user
fi
mkdir -p "${HOME}" 2>/dev/null || { export HOME=/tmp/bindmaster-home; mkdir -p "${HOME}"; }

# ── conda init ────────────────────────────────────────────────────────────────
if [[ -f /opt/miniforge3/etc/profile.d/conda.sh ]]; then
    source /opt/miniforge3/etc/profile.d/conda.sh
fi
[[ -f /opt/miniforge3/etc/profile.d/mamba.sh ]] && source /opt/miniforge3/etc/profile.d/mamba.sh
export PATH="/opt/miniforge3/bin:${HOME}/.local/bin:${PATH}"

# Ensure conda is initialised in interactive shells opened later (docker exec)
if [[ ! -f "${HOME}/.bashrc" ]]; then
    cat > "${HOME}/.bashrc" <<'RCEOF'
[[ -f /opt/miniforge3/etc/profile.d/conda.sh ]] && source /opt/miniforge3/etc/profile.d/conda.sh
[[ -f /opt/miniforge3/etc/profile.d/mamba.sh ]] && source /opt/miniforge3/etc/profile.d/mamba.sh
RCEOF
fi

exec "$@"
