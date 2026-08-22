# infra

Self-hosted observability stack (all OSS): Langfuse (per-session reasoning traces), Grafana +
Prometheus (live metrics), Loki + Alloy (correlated JSON logs), and Duet's own Postgres
(durable benchmark and call summaries).

## Run it

Needs Docker (macOS: Docker Desktop or OrbStack). The stack is also booted and smoke-tested in CI;
see `.github/workflows/infra.yml`.

```bash
cd infra && cp .env.example .env
docker compose -p langfuse -f langfuse-compose.yml up -d       # Langfuse UI → http://localhost:3000
docker compose -p duet-obs -f observability-compose.yml up -d  # Grafana     → http://localhost:3001 · Prometheus → :9099
```

Credentials live in `infra/.env` (gitignored): `.env.example` holds dev defaults; rotate by
editing `.env` before first start (compose reads it automatically — Grafana admin password,
Langfuse login/API keys, and the Duet Postgres password are all env-parameterized). Keep the
repo-root `.env`'s `LANGFUSE_*`/`DATABASE_URL` in sync so telemetry can connect.

Start the voice server on port 8990 after the stacks. Prometheus scrapes `/metrics` through
Docker's host gateway, while Alloy tails `.local/telemetry/*.jsonl` and sends it to Loki. Every
event carries the same `session_id` and `trace_id` used by Langfuse and Postgres. Content is
redacted by default; set `DUET_TRACE_CONTENT=true` only for a consented local evaluation.

Shortcut for everything (start, health-check, data backfill, prints your logins):
`./scripts/local-demo.sh`. The Duet dashboard and Postgres datasource
are auto-provisioned; benchmark runs (`eval/bench/run_bench.py`) populate them when
`DATABASE_URL` and `LANGFUSE_*` are set in the repo-root `.env`.

Health/readiness: `http://localhost:8990/healthz` and `/readyz`. Raw application metrics:
`http://localhost:8990/metrics`. Alloy status: `http://localhost:12345`.

`langfuse-compose.yml` is the pinned upstream file from langfuse/langfuse (unmodified, so
upgrades are a re-fetch); `observability-compose.yml` and `alloy.alloy` are ours. Telemetry is
fail-silent and bounded: a slow/down observability backend may lose telemetry, but cannot block
the audio path. Production alerting must make dropped telemetry visible.
