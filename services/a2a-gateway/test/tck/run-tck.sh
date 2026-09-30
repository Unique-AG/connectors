#!/usr/bin/env bash
# Runs the official A2A TCK (JSON-RPC, A2A 1.0) against a local gateway backed by the stub core.
#
# Requires: a built gateway (pnpm build), uv, git, a disposable PostgreSQL database in
# DATABASE_URL (migrated and absurd-initialised by this script) and AMQP_URL.
# Reports: test/tck/reports/ (compatibility.json/.html, junit).
set -euo pipefail

TCK_REPOSITORY=https://github.com/a2aproject/a2a-tck.git
TCK_COMMIT=${TCK_COMMIT:-263b9cfaf16a554bdfb166a7ba5b67716e946349}
GATEWAY_PORT=${GATEWAY_PORT:-9660}
STUB_CORE_PORT=${STUB_CORE_PORT:-9690}
HERE=$(cd "$(dirname "$0")" && pwd)
SERVICE=$(cd "$HERE/../.." && pwd)
WORK="$HERE/.work"
mkdir -p "$WORK" "$HERE/reports"

cleanup() { kill "${GATEWAY_PID:-}" "${CORE_PID:-}" 2>/dev/null || true; }
trap cleanup EXIT

if [ ! -d "$WORK/a2a-tck" ]; then
  git clone --quiet "$TCK_REPOSITORY" "$WORK/a2a-tck"
fi
git -C "$WORK/a2a-tck" fetch --quiet origin "$TCK_COMMIT" && git -C "$WORK/a2a-tck" checkout --quiet "$TCK_COMMIT"

cd "$SERVICE"
pnpm --silent db:migrate >/dev/null
uvx absurdctl init -d "$DATABASE_URL" >/dev/null 2>&1 || true
uvx absurdctl create-queue -d "$DATABASE_URL" a2a-gateway >/dev/null 2>&1 || true

STUB_CORE_PORT=$STUB_CORE_PORT node test/fixtures/stub-core.ts > "$WORK/stub-core.log" 2>&1 &
CORE_PID=$!

CORE_URL="http://127.0.0.1:$STUB_CORE_PORT"
env NODE_ENV=development AUTH_MODE=development DEVELOPMENT_IDENTITY=tck-company:tck-user \
  PORT=$GATEWAY_PORT PUBLIC_BASE_URL="http://127.0.0.1:$GATEWAY_PORT" ZITADEL_ISSUER=https://id.example.com \
  UNIQUE_CHAT_URL=$CORE_URL UNIQUE_SCOPE_MANAGEMENT_URL=$CORE_URL UNIQUE_INGESTION_URL=$CORE_URL \
  ENCRYPTION_KEY=${ENCRYPTION_KEY:-$(printf '0%.0s' $(seq 1 64))} OTEL_METRICS_EXPORTER=none OTEL_TRACES_EXPORTER=none \
  PUSH_NOTIFICATIONS_ENABLED=false node dist/main.js > "$WORK/gateway.log" 2>&1 &
GATEWAY_PID=$!

GATEWAY="http://127.0.0.1:$GATEWAY_PORT"
for _ in $(seq 1 60); do curl -fs "$GATEWAY/health/live" >/dev/null && break; sleep 1; done

PUBLICATION=$(curl -fs -X PUT "$GATEWAY/management/publications/assistant_tck" \
  -H 'content-type: application/json' \
  -d '{"enabled":true,"card":{"name":"TCK space","description":"Native space used by the A2A TCK."}}' \
  | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s).id))')

cd "$WORK/a2a-tck"
uv sync --quiet
# Documented deviations (docs/compatibility-profile.md#tck): the artifact scenarios need a scripted
# agent, and the two requirements below lack an expected error in the TCK, so any error fails them.
uv run ./run_tck.py --sut-host "$GATEWAY/a2a/agents/$PUBLICATION" --transport jsonrpc -- \
  --deselect tests/compatibility/core_operations/test_artifacts.py \
  --deselect "tests/compatibility/core_operations/test_requirements.py::test_must_requirement[CORE-SEND-003-jsonrpc]" \
  --deselect "tests/compatibility/core_operations/test_requirements.py::test_must_requirement[CORE-MULTI-002a-jsonrpc]" \
  "$@" || STATUS=$?
cp -R reports/. "$HERE/reports/"
exit "${STATUS:-0}"
