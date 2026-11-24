#!/usr/bin/env bash
# Compare a clean full local run with the GitHub run of the same commit.
# Usage: compare-github.sh [.ci-results/<run>] [--run <github run id>]
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$(dirname "$0")/lib/compare.py" "$@"
