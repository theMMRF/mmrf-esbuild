#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=/dev/null
source .venv/bin/activate

pip install --no-build-isolation --editable .

RANDOM_SUFFIX=$(printf '%04x' "$RANDOM")
PREFIX="ia-$(date +%Y%m%d-%H%M%S)-${RANDOM_SUFFIX}"
LOG_DIR="${HOME}/logs/mmrf-esbuild"
LOG_FILE="${LOG_DIR}/${PREFIX}.log"

mkdir -p "$LOG_DIR"
echo "$PREFIX"
echo "Writing build output to $LOG_FILE"

if time python -u src/esbuild/bin/single.py "$PREFIX" > "$LOG_FILE" 2>&1; then
  echo "ES build completed successfully: $PREFIX"
else
  status=$?
  echo "ES build failed with exit code $status: $PREFIX" >&2
  echo "See $LOG_FILE for details" >&2
  tail -n 50 "$LOG_FILE" >&2
  exit "$status"
fi
