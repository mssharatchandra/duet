#!/usr/bin/env bash
# Reproducible single-VPS deployment. Run on the VPS from a reviewed checkout.
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "deploy blocked: $*" >&2; exit 1; }
value() { sed -n "s/^$1=//p" "$2" | tail -1; }

command -v docker >/dev/null || fail "Docker Engine with Compose v2 is required"
docker info >/dev/null 2>&1 || fail "Docker daemon is not running"
[ -f .env ] || fail "copy .env.example to .env and configure provider keys"
[ -f infra/.env ] || fail "copy infra/.env.example to infra/.env and rotate every credential"

for key in GEMINI_API_KEY SARVAM_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY; do
  [ -n "$(value "$key" .env)" ] || fail "$key is missing from .env"
done
for key in DUET_DOMAIN ACME_EMAIL DUET_PG_PASSWORD GRAFANA_ADMIN_PASSWORD; do
  candidate="$(value "$key" infra/.env)"
  [ -n "$candidate" ] || fail "$key is missing from infra/.env"
  case "$candidate" in
    *example.com*|*voice.invalid*|replace-*) fail "$key still contains an example value" ;;
  esac
done

mkdir -p .local/telemetry .local/quota eval/asr/sessions
docker network inspect duet-backplane >/dev/null 2>&1 || docker network create duet-backplane >/dev/null

docker compose --env-file infra/.env -p langfuse -f infra/langfuse-compose.yml up -d --quiet-pull
docker compose --env-file infra/.env -p duet -f infra/observability-compose.yml --profile deploy up -d --build

for _ in $(seq 1 60); do
  curl -fsS http://127.0.0.1:8990/readyz >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS http://127.0.0.1:8990/readyz >/dev/null || fail "Duet did not become ready; inspect docker compose logs"
docker compose --env-file infra/.env -p duet -f infra/observability-compose.yml ps

echo "deploy healthy: https://$(value DUET_DOMAIN infra/.env)"
echo "keep Grafana, Langfuse, Prometheus and Postgres private; use the SSH tunnels in docs/VPS_DEPLOYMENT.md"
