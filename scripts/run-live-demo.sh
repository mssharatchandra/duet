#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_dir"

python_bin="web-demo/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  echo "Missing web-demo environment. Run: uv sync --project web-demo"
  exit 1
fi

exec "$python_bin" web-demo/server.py \
  --mode sdr \
  --voice-stack open \
  --asr sarvam \
  --tts-backend sarvam-ws \
  --barge-in
