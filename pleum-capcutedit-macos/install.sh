#!/usr/bin/env sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Pleum CapCutEdit for macOS requires macOS."
  exit 1
fi

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3.10+ is required. Install it from python.org or with Homebrew."
  exit 1
fi

"$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3,10))' || {
  echo "Python 3.10+ is required."
  exit 1
}

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "FFmpeg and ffprobe are required. Homebrew users can run: brew install ffmpeg"
fi

CHECK_ONLY=0
for arg in "$@"; do
  [ "$arg" = "--check-only" ] && CHECK_ONLY=1
  [ "$arg" = "--dry-run" ] && CHECK_ONLY=1
done

if [ "$CHECK_ONLY" -eq 0 ] && [ ! -d "$ROOT/.venv" ]; then
  "$PYTHON" -m venv "$ROOT/.venv"
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  exec "$PYTHON" "$ROOT/scripts/check_macos_prereqs.py"
fi

RUNPY="$PYTHON"
[ -x "$ROOT/.venv/bin/python" ] && RUNPY="$ROOT/.venv/bin/python"

if [ "$CHECK_ONLY" -eq 0 ]; then
  REQUIREMENTS="$ROOT/requirements-lock.txt"
  [ -f "$REQUIREMENTS" ] || REQUIREMENTS="$ROOT/requirements.txt"
  "$RUNPY" -m pip install -r "$REQUIREMENTS"
  "$RUNPY" -m pip install -e "$ROOT"
fi

exec "$RUNPY" "$ROOT/scripts/bootstrap.py" "$@"
