# infra

Self-hosted observability stack (all OSS): Langfuse (LLM traces/cost), Grafana + Prometheus +
Loki (dashboards/metrics/logs), and Duet's own Postgres (benchmark + call records).

## Run it

Needs Docker (macOS: OrbStack or Docker Desktop; this repo's dev Mac has neither — the stack
is verified in CI instead, see `.github/workflows/infra.yml`).

```bash
cd infra && cp .env.example .env
docker compose -p langfuse -f langfuse-compose.yml up -d       # Langfuse UI → http://localhost:3000
docker compose -p duet-obs -f observability-compose.yml up -d  # Grafana     → http://localhost:3001 · Prometheus → :9099
```

Credentials live in `infra/.env` (gitignored): `.env.example` holds dev defaults; rotate by
editing `.env` before first start (compose reads it automatically — Grafana admin password,
Langfuse login/API keys, and the Duet Postgres password are all env-parameterized). Keep the
repo-root `.env`'s `LANGFUSE_*`/`DATABASE_URL` in sync so telemetry can connect.

Shortcut for everything (start, health-check, data backfill, prints your logins):
`./scripts/local-demo.sh`. The Duet dashboard and Postgres datasource
are auto-provisioned; benchmark runs (`eval/bench/run_bench.py`) populate them when
`DATABASE_URL` and `LANGFUSE_*` are set in the repo-root `.env`.

`langfuse-compose.yml` is the pinned upstream file from langfuse/langfuse (unmodified, so
upgrades are a re-fetch); `observability-compose.yml` is ours.
