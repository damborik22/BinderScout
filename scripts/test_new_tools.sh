#!/usr/bin/env bash
# scripts/test_new_tools.sh
# Runs all non-GPU tests for the new integrations.
# Safe to run on any machine — does not submit any GPU jobs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== BindMaster Integration Test Suite ==="
echo "Project: $PROJECT_DIR"
echo "Branch: $(git -C "$PROJECT_DIR" branch --show-current)"
echo "Date: $(date)"
echo ""

# 1. Confirm we are NOT on master
BRANCH=$(git -C "$PROJECT_DIR" branch --show-current)
if [ "$BRANCH" = "master" ] || [ "$BRANCH" = "main" ]; then
    echo "ERROR: Do not run integration tests on $BRANCH branch!"
    echo "   Switch to: git checkout feature/rfaa-pxdesign-integration"
    exit 1
fi

# 2. Run RFAA config tests
echo ">>> [1/3] Running RFAA config tests (no GPU)..."
cd "$PROJECT_DIR"
python -m pytest tests/tools/rfaa/ -v --tb=short
echo "RFAA config tests passed"
echo ""

# 3. Run PXDesign config/parser tests
echo ">>> [2/3] Running PXDesign config/parser tests (no GPU)..."
python -m pytest tests/tools/pxdesign/ -v --tb=short
echo "PXDesign config tests passed"
echo ""

# 4. Run unified scoring tests
echo ">>> [3/3] Running unified scoring tests (no GPU)..."
python -m pytest tests/scoring/ -v --tb=short
echo "Scoring tests passed"
echo ""

echo "=========================================="
echo "ALL TESTS PASSED"
echo "=========================================="
