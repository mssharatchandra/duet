#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
uv sync --project "$project_dir/web-demo"

echo "Open voice runtime ready."
echo "Run: $project_dir/web-demo/.venv/bin/python $project_dir/web-demo/server.py --mode hermes --capture"
