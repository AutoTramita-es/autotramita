#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "$0")/_wrapper.sh"
atci status "$@"
