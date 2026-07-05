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

Logins (dev defaults, rotate for any shared deploy): Langfuse `dev@duet.local` /
`duet-dev-password-1` · Grafana `admin` / `duet`. The Duet dashboard and Postgres datasource
are auto-provisioned; benchmark runs (`eval/bench/run_bench.py`) populate them when
`DATABASE_URL` and `LANGFUSE_*` are set in the repo-root `.env`.

`langfuse-compose.yml` is the pinned upstream file from langfuse/langfuse (unmodified, so
upgrades are a re-fetch); `observability-compose.yml` is ours.
