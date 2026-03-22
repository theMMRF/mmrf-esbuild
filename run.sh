#!/usr/bin/env bash

# shellcheck source=/dev/null
source .venv/bin/activate

pip install --no-build-isolation --editable .

ID="ia-$(date +%Y%m%d)-$(date +%H%M%S)-$(cat /dev/urandom | tr -dc 'a-z0-9' | head -c 4)"

time python -u src/esbuild/bin/single.py "$ID" > ~/logs/mmrf-esbuild/"$ID".log 2>&1
