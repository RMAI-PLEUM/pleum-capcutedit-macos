#!/usr/bin/env sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
echo "Project files and CapCut projects are never removed automatically."
if [ "${1:-}" = "--remove-environment" ]; then rm -rf "$ROOT/.venv"; fi
