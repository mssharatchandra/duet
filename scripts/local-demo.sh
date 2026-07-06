#!/usr/bin/env bash
# One command to bring the full local Duet demo up: observability stacks,
# health checks, benchmark data backfill, and where to click/talk.
# Requires: Docker running (Docker Desktop or `colima start`), infra/.env
# (cp infra/.env.example infra/.env for dev defaults).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v docker >/dev/null || { echo "docker not found — start Docker Desktop or colima"; exit 1; }
docker info >/dev/null 2>&1 || { echo "docker daemon not running — start Docker Desktop or 'colima start'"; exit 1; }
[ -f infra/.env ] || cp infra/.env.example infra/.env

echo "▸ starting stacks…"
(cd infra && docker compose -p langfuse -f langfuse-compose.yml up -d --quiet-pull)
(cd infra && docker compose -p duet-obs -f observability-compose.yml up -d --quiet-pull)

echo "▸ waiting for Langfuse…"
for _ in $(seq 1 60); do curl -sf http://localhost:3000/api/public/health >/dev/null && break; sleep 5; done
curl -sf http://localhost:3000/api/public/health >/dev/null || { echo "Langfuse failed to start"; exit 1; }

# backfill benchmark results if the calls table is empty
if [ -f eval/bench/out/calls.jsonl ] && [ -x agent/.venv/bin/python ]; then
  echo "▸ backfilling benchmark data…"
  set -a; source .env 2>/dev/null || true; set +a
  (cd agent && .venv/bin/python -c "
import json, sys
sys.path.insert(0, '.')
from duet_agent.telemetry import CallStore
s = CallStore()
n = sum(s.insert({k: v for k, v in json.loads(l).items() if not k.startswith('_')}) for l in open('../eval/bench/out/calls.jsonl'))
print(f'  {n} new rows (0 = already loaded)')" ) || true
fi

GRAF_PW=$(grep '^GRAFANA_ADMIN_PASSWORD=' infra/.env | cut -d= -f2 || echo duet)
LF_PW=$(grep '^LANGFUSE_INIT_USER_PASSWORD=' infra/.env | cut -d= -f2 || echo duet-dev-password-1)
cat << EOF

✅ Duet local demo is up
  Grafana     http://localhost:3001   admin / ${GRAF_PW:-duet}   → Dashboards ▸ Duet
  Langfuse    http://localhost:3000   dev@duet.local / ${LF_PW}
  Prometheus  http://localhost:9099   (no auth)

Voice demos (Apple Silicon, wear headphones):
  cd agent && uv run duet-local        # talk to raw full-duplex Moshi, interrupt it
  cd agent && uv run duet-sdr --live   # the SDR agent with the Gemini brain
  cd agent && uv run duet-sdr          # no-mic scripted version of the same

Web demo (browser UI, echo-cancelled): agent/.venv/bin/python web-demo/server.py → http://localhost:8990
  ⚠ voice quality tip: the model needs a quiet machine — stop the Langfuse stack first
    (cd infra && docker compose -p langfuse -f langfuse-compose.yml stop) and restart it after.

Benchmark clips for blind listening: eval/bench/out/clips/
EOF
