#!/usr/bin/env bash
# Local CI profile 'security'. Options: --ref <commit>, --serial, --keep-workspace, -- <pytest args>
set -euo pipefail
. "$(dirname "$0")/_wrapper.sh"
atci run security "$@"
