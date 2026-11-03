#!/usr/bin/env bash
# `make demo-dw`: one lead goes the whole way on compose with the real model
# (leadcare ticket 02, R4). `make demo-dw-down` stops it and drops its volumes.
#
#   1. a fresh compose project `dwdemo` (postgres, api, worker, web, mailpit and
#      the data plane the api waits on), on loopback ports of its own;
#   2. scripts/demo_dw_seed.py: a tenant, its five people and the `lead_care`
#      DW, through the platform's own API;
#   3. scripts/demo_dw_run.py: a signed lead, the Validator's approval, the
#      mail, a reply, the hand-off to sales; non-zero on any deviation;
#   4. apps/web/e2e/demo-digital-worker.spec.ts: one screenshot per screen into
#      docs/demo/digital-worker/.
#
# Its own project, volumes and ports, never the dev data plane's: the dev
# stack (`COMPOSE_PROJECT_NAME` in .env) keeps running beside it untouched.
set -euo pipefail

cd "$(dirname "$0")/.."

# .env reaches this script through make (`include .env` + `export`), which
# reads a value with spaces as it is; bash `source` would not.

# Ports: every one the loopback's, each overridable. 8000/3000 and the default
# data-plane ports belong to other projects on a developer's machine.
export DW_DEMO_API_PORT="${DW_DEMO_API_PORT:-8010}"
export DW_DEMO_WEB_PORT="${DW_DEMO_WEB_PORT:-3040}"
export DW_DEMO_POSTGRES_PORT="${DW_DEMO_POSTGRES_PORT:-25445}"
export DW_DEMO_VALKEY_PORT="${DW_DEMO_VALKEY_PORT:-16445}"
export DW_DEMO_QDRANT_PORT="${DW_DEMO_QDRANT_PORT:-16446}"
export DW_DEMO_S3_PORT="${DW_DEMO_S3_PORT:-19045}"
export DW_DEMO_SMTP_PORT="${DW_DEMO_SMTP_PORT:-21045}"
export DW_DEMO_MAILPIT_PORT="${DW_DEMO_MAILPIT_PORT:-28045}"

API_URL="http://localhost:${DW_DEMO_API_PORT}"
WEB_URL="http://localhost:${DW_DEMO_WEB_PORT}"
STATE=".demo/digital-worker/state.json"

compose() {
  docker compose -p dwdemo --env-file .env \
    -f infra/compose/docker-compose.yml \
    -f infra/compose/docker-compose.dev.yml \
    -f infra/compose/docker-compose.demo.yml \
    --profile full "$@"
}

random_secret() { uv run --no-sync python -c 'import secrets; print(secrets.token_hex(32))'; }

# Values the compose files require. The demo's volumes are new on every run,
# so a secret .env leaves empty is minted here and lives as long as the run.
for var in INTAKE_SIGNING_SECRET UNSUBSCRIBE_SIGNING_SECRET QDRANT_API_KEY REDIS_PASSWORD \
  DW_DB_MONITOR_PASSWORD LANGFUSE_REDIS_PASSWORD; do
  if [ -z "${!var:-}" ]; then
    export "$var=$(random_secret)"
  fi
done
export NEXT_PUBLIC_API_BASE_URL="$API_URL"
export NEXT_PUBLIC_CHAT_BASE_URL="${NEXT_PUBLIC_CHAT_BASE_URL:-http://localhost:8100}"
export DW_PUBLIC_WEB_URL="$WEB_URL"
# The dev overlay's Keycloak needs a public name; the demo starts no Keycloak.
export KC_PUBLIC_HOSTNAME="${KC_PUBLIC_HOSTNAME:-localhost}"
# The real model (R4.1): `.env` may say mock for everything else.
export DW_MODEL_PROVIDER="${DW_DEMO_MODEL_PROVIDER:-openai}"
export DW_API_MODEL_PROFILE="${DW_DEMO_MODEL_PROFILE:-luna}"
# Vietnamese names in the scripts' output, on a Windows console too.
export PYTHONIOENCODING=utf-8

mkdir -p "$(dirname "$STATE")"
TIMINGS="$(dirname "$STATE")/timings.txt"

# The Playwright spec, in one of its two phases (`@approval` or the rest).
playwright() {
  E2E_WEB_URL="$WEB_URL" E2E_API_URL="$API_URL" DW_DEMO_STATE="$PWD/$STATE" \
    pnpm --filter @dw/web exec playwright test e2e/demo-digital-worker.spec.ts \
    --project chromium "$@"
}

case "${1:-up}" in
down)
  compose down -v --remove-orphans
  exit 0
  ;;
screens-at-approval)
  # Called by demo_dw_run while the Validator's approval waits.
  playwright --grep @approval
  exit 0
  ;;
up | again) ;;
*)
  echo "usage: scripts/demo_dw.sh [up|down|again]" >&2
  exit 2
  ;;
esac

for var in DW_API_DEV_SECRET DW_DB_MIGRATOR_PASSWORD OPENAI_API_KEY; do
  [ -n "${!var:-}" ] || {
    echo "!! $var is missing: run \`make demo-dw\`, which loads .env" >&2
    exit 1
  }
done

stage() { printf '\n== %s\n' "$1"; }
timed() {
  local name="$1" start=$SECONDS
  shift
  "$@"
  printf '>> %s: %ss\n' "$name" "$((SECONDS - start))" | tee -a "$TIMINGS"
}

: >"$TIMINGS"
SERVICES=(postgres api worker web mailpit)

up() {
  # A fresh demo each time: the Send floor allows one mail per address a day
  # and the seed creates a tenant by slug, so yesterday's volumes would refuse.
  compose down -v --remove-orphans
  compose up -d --build "${SERVICES[@]}"
  # `--wait` on the named services only: migrate runs once and exits.
  compose up -d --wait "${SERVICES[@]}"
}

seed() {
  DW_DEMO_API_URL="$API_URL" \
    DW_DATABASE_URL="postgresql+asyncpg://dw_migrator:${DW_DB_MIGRATOR_PASSWORD}@127.0.0.1:${DW_DEMO_POSTGRES_PORT}/dw" \
    uv run --no-sync python -m scripts.demo_dw_seed --state "$STATE"
}

run() {
  # While the Validator's approval waits, the run screenshots its card.
  DW_DEMO_API_URL="$API_URL" \
    uv run --no-sync python -m scripts.demo_dw_run --state "$STATE" \
    --mailpit "http://127.0.0.1:${DW_DEMO_MAILPIT_PORT}" \
    --smtp-port "$DW_DEMO_SMTP_PORT" \
    --at-approval "bash scripts/demo_dw.sh screens-at-approval"
}

screens() { playwright --grep-invert @approval; }

if [ "${1:-up}" = "up" ]; then
  stage "compose up (project dwdemo)"
  timed "compose up" up
  stage "seed"
  timed "seed" seed
fi
stage "one lead, the whole way"
timed "lead run" run
stage "screenshots"
timed "screenshots" screens

stage "done"
cat "$TIMINGS"
echo "web: $WEB_URL  api: $API_URL  mailpit: http://127.0.0.1:${DW_DEMO_MAILPIT_PORT}"
echo "stop with: make demo-dw-down"
