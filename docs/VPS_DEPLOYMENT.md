# Deploy Aira on a single VPS

This is the deployment runbook for the current demo architecture: one Aira application process, cloud
Sarvam speech, Gemini reasoning, Caddy TLS, Duet Postgres, Grafana, Prometheus, Loki/Alloy and a separate
Langfuse stack. It is suitable for a controlled demonstration, not an outbound production campaign.

## Know the boundary first

- The app is intentionally **single-session**. A second caller is rejected instead of corrupting shared
  state. Horizontal replicas require a shared admission/quota store and per-call routing first.
- The VPS does not run a speech model or GPU. It orchestrates WebSockets and calls Sarvam/Gemini, so a
  modern 2-vCPU host is enough for the app. The complete Langfuse v3 stack is the RAM-heavy part; use at
  least 4 GB, preferably 8 GB, or leave Langfuse on a separate machine.
- A public browser microphone requires a secure context. Caddy provides HTTPS/WSS automatically after DNS
  points at the VPS and ports 80/443 are reachable.
- Gemini's limits are project-specific. The app defaults to 8 RPM, 100 requests per rolling 24 hours and
  one in-flight request. Confirm the active values in Google AI Studio and configure lower values.
- Langfuse v3 still accepts Duet's legacy batch events today, but Langfuse documents removal of that path
  in v4/November 2026. Migrating Duet's exporter to native OpenTelemetry is a recorded production follow-up.

## 1. DNS and host preparation

Create an `A` record such as `voice.example.com` pointing to the VPS. Install Docker Engine and the Compose
v2 plugin using Docker's official instructions for the VPS distribution. Permit inbound TCP 22, 80 and 443
and UDP 443. Do **not** expose 3000, 3001, 5433, 9090, 9099 or 3100 in the cloud firewall.

Clone a reviewed revision:

```bash
git clone https://github.com/mssharatchandra/duet.git
cd duet
cp .env.example .env
cp infra/.env.example infra/.env
```

## 2. Configure secrets

In `.env`, configure at least:

```dotenv
GEMINI_API_KEY=...
SARVAM_API_KEY=...
LANGFUSE_HOST=http://langfuse-web:3000
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
GEMINI_RPM_LIMIT=8
GEMINI_RPD_LIMIT=100
GEMINI_CONCURRENT_LIMIT=1
SESSION_LIMIT_PER_IP_HOUR=3
SESSION_LIMIT_PER_IP_DAY=10
SESSION_MAX_SECONDS=240
```

In `infra/.env`, set the real domain and independently generated credentials:

```dotenv
DUET_DOMAIN=voice.example.com
ACME_EMAIL=operator@example.com
DUET_PG_PASSWORD=...
GRAFANA_ADMIN_PASSWORD=...
LANGFUSE_INIT_USER_EMAIL=...
LANGFUSE_INIT_USER_PASSWORD=...
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=...
LANGFUSE_INIT_PROJECT_SECRET_KEY=...
```

Generate secrets with `openssl rand -hex 32`. Also rotate every `CHANGEME` dependency credential in
`infra/langfuse-compose.yml` through `infra/.env`: `NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY`, Postgres,
ClickHouse, Redis and MinIO credentials. The Langfuse public/secret project keys in `.env` must match the
initial project keys in `infra/.env`.

Never paste credentials into issues, chat, shell history, Dockerfiles or Compose YAML. Both environment
files are gitignored.

## 3. Preflight and deploy

```bash
chmod +x scripts/deploy-vps.sh
./scripts/deploy-vps.sh
```

The script validates required configuration, creates the private `duet-backplane`, starts Langfuse,
builds the non-root Linux application image, starts Caddy and observability, and waits for `/readyz`.

Read back the deployment:

```bash
curl -fsS https://voice.example.com/healthz | jq
curl -fsS https://voice.example.com/readyz | jq
docker compose --env-file infra/.env -p duet \
  -f infra/observability-compose.yml --profile deploy ps
```

The health response includes current process-local Gemini quota usage. A readiness success proves required
keys exist; provider reachability is proven only by a consented smoke conversation.

## 4. Reach private observability safely

From your laptop, keep this SSH tunnel open:

```bash
ssh \
  -L 3000:127.0.0.1:3000 \
  -L 3001:127.0.0.1:3001 \
  -L 9099:127.0.0.1:9099 \
  -L 5433:127.0.0.1:5433 \
  user@your-vps
```

Then open:

| Surface | URL | What to inspect |
|---|---|---|
| Langfuse | `http://localhost:3000` | `duet-live-session` trace → reasoning generation and pipeline spans |
| Grafana | `http://localhost:3001` | Dashboards → Duet; Explore → Loki or Duet Postgres |
| Prometheus | `http://localhost:9099` | raw `duet_*` metrics and scrape health |
| Postgres | tunnel on `localhost:5433` | durable `calls` rows; use Grafana or `psql` |

Loki has no separate end-user UI. Use Grafana Explore and select the Loki datasource. MinIO in this stack
belongs to Langfuse internals; Duet recordings are disabled by default and local capture is not a public
recording product.

Useful operator commands:

```bash
docker compose --env-file infra/.env -p duet -f infra/observability-compose.yml logs -f duet-web
docker compose --env-file infra/.env -p duet -f infra/observability-compose.yml logs -f caddy
docker compose --env-file infra/.env -p duet -f infra/observability-compose.yml exec duet-postgres \
  psql -U duet -d duet -c 'select ts, call_id, response_latency_ms_p95, langfuse_trace_id from calls order by ts desc limit 10;'
```

Trace content is redacted to hashes and character counts by default. Do not set `DUET_TRACE_CONTENT=true`
for public traffic.

## 5. Deploy checklist and rollback

Before a demonstration:

- [ ] Correctness and infrastructure CI are green for the exact commit.
- [ ] DNS resolves to the VPS and the TLS certificate is valid.
- [ ] `.env` and `infra/.env` contain no example/default secrets.
- [ ] Active Gemini project limits in AI Studio are above configured Duet limits.
- [ ] Sarvam and Gemini provider status are healthy.
- [ ] `/readyz`, one browser call, barge-in and one action request pass.
- [ ] The same session ID is visible in Langfuse, Loki and Postgres.
- [ ] Grafana shows live metrics and dropped-telemetry counters remain zero.
- [ ] Firewall exposes only SSH and Caddy.

Rollback triggers: repeated failed calls, p95 first-audio latency above 4 seconds, cancellation above 500 ms,
provider error rate above 5%, incorrect spoken claims, or any consent/opt-out failure.

```bash
git switch --detach <last-known-good-commit>
./scripts/deploy-vps.sh
```

For immediate containment without destroying data:

```bash
docker compose --env-file infra/.env -p duet -f infra/observability-compose.yml stop caddy duet-web
```

## What must change before multi-user production

Replace the module-global active session with per-call actors, move quotas and admission to Redis, put media
on LiveKit/WebRTC or a tested telephony adapter, issue signed short-lived session tokens, persist consent and
DNC state before dialing, add current inventory/price tools, implement human transfer, run k6 plus long-call
and reconnect tests, define provider fallbacks, and operate an on-call/error-budget process. Containerization
makes the artifact reproducible; it does not itself make the voice agent production-grade.
