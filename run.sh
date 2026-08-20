#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=/dev/null
source .venv/bin/activate

pip install --no-build-isolation --editable .

RUN_ID=$(python -c 'import secrets, string; print("".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4)))')
PREFIX="ia-$(date +%Y%m%d-%H%M%S)-${RUN_ID}"
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
  tail -n 50 "$LOG_FILE" >&2 || true
  exit "$status"
fi
