#!/bin/bash
# BindMaster test environment launcher
#
# Builds a clean Docker image (Ubuntu 24.04 + Miniforge) and drops you into
# an interactive shell where you can run ./install_aarch.sh as if on a
# fresh DGX Spark.
#
# Usage:
#   ./test_env.sh            # build image if needed, then run
#   ./test_env.sh --rebuild  # force image rebuild before running
#   ./test_env.sh --gpu      # pass GPU access to the container
#   ./test_env.sh --no-old   # don't mount the OLD tools dir (tests download fallback)
#   ./test_env.sh --clean    # remove test artifacts created in previous runs

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="bindmaster-test"
CONTAINER_NAME="bindmaster-test-run"

# Pre-cached resources (AF2 weights, ARM64 binaries) — mounted read-only
OLD_TOOLS_DIR="/home/bindmaster5/Documents/OLD/BindMaster/bindcraft-tools"

REBUILD=false
GPU=false
MOUNT_OLD=true
CLEAN=false

for arg in "$@"; do
    case "$arg" in
        --rebuild) REBUILD=true ;;
        --gpu)     GPU=true ;;
        --no-old)  MOUNT_OLD=false ;;
        --clean)   CLEAN=true ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--rebuild] [--gpu] [--no-old] [--clean]

  --rebuild   Force rebuild of the Docker image
  --gpu       Expose the GPU to the container (requires nvidia runtime)
  --no-old    Don't mount OLD tools dir (AF2 weights will be downloaded)
  --clean     Remove test artifacts left in the repo from previous runs
EOF
            exit 0 ;;
        *)
            echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# ── Clean up artifacts from previous runs ─────────────────────────────────────
if [[ "${CLEAN}" == true ]]; then
    echo "Removing test artifacts..."
    docker run --rm \
        --user root \
        --volume "${SCRIPT_DIR}:/workspace" \
        "${IMAGE_NAME}" \
        /bin/bash -c "
            rm -rf /workspace/Mosaic/.venv
            rm -rf /workspace/Mosaic/examples/bindmaster_examples
            rm -f  /workspace/install_aarch.log /workspace/install.log
            echo 'Done.'
        " 2>/dev/null \
    || sudo rm -rf \
        "${SCRIPT_DIR}/Mosaic/.venv" \
        "${SCRIPT_DIR}/Mosaic/examples/bindmaster_examples" \
        "${SCRIPT_DIR}/install_aarch.log" \
        "${SCRIPT_DIR}/install.log"
    echo "Clean."
    exit 0
fi

# ── Build image ────────────────────────────────────────────────────────────────
if [[ "${REBUILD}" == true ]] || ! docker image inspect "${IMAGE_NAME}" &>/dev/null; then
    echo "Building ${IMAGE_NAME} ..."
    docker build \
        -f "${SCRIPT_DIR}/Dockerfile.test" \
        -t "${IMAGE_NAME}" \
        "${SCRIPT_DIR}" \
        || { echo "Docker build failed."; exit 1; }
    echo "Image built."
fi

# ── Assemble docker run args ───────────────────────────────────────────────────
# Run as the current host user so files written in the container are owned
# by us — no sudo needed for cleanup afterwards.
RUN_ARGS=(
    --rm
    --interactive
    --tty
    --name "${CONTAINER_NAME}"

    # Run as the host user (no UID mismatch, files stay host-writable)
    --user "$(id -u):$(id -g)"

    # Mount installer repo at /workspace (read-write)
    --volume "${SCRIPT_DIR}:/workspace"
    --workdir /workspace
)

if [[ "${MOUNT_OLD}" == true && -d "${OLD_TOOLS_DIR}" ]]; then
    RUN_ARGS+=(--volume "${OLD_TOOLS_DIR}:/old-tools:ro")
    echo "Mounting OLD tools: ${OLD_TOOLS_DIR} → /old-tools (read-only)"
else
    echo "OLD tools dir not mounted — AF2 weights will be downloaded if needed."
fi

if [[ "${GPU}" == true ]]; then
    RUN_ARGS+=(--gpus all)
    echo "GPU access enabled."
fi

# ── Run ────────────────────────────────────────────────────────────────────────
echo ""
echo "Starting clean test environment..."
echo "─────────────────────────────────────────────────────────────"
echo "  Installer:  /workspace/install_aarch.sh"
echo "  OLD tools:  /old-tools  (pre-cached AF2 weights + binaries)"
echo ""
echo "  Quickstart:"
echo "    ./install_aarch.sh --tools-dir /old-tools"
echo "    ./install_aarch.sh --tools-dir /old-tools --tool mosaic --skip-examples"
echo ""
echo "  Cleanup after testing:"
echo "    exit   (container is deleted automatically)"
echo "    ./test_env.sh --clean   (removes artifacts from the mounted repo)"
echo "─────────────────────────────────────────────────────────────"
echo ""

docker run "${RUN_ARGS[@]}" "${IMAGE_NAME}"
