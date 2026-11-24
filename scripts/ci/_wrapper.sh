# shellcheck shell=bash
# Sourced by the run-*.sh wrappers. Host requirements: python3 >= 3.10 with PyYAML, git, docker.
ci_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
atci() { exec python3 "$ci_dir/lib/runner.py" "$@"; }
