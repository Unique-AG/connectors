# Kyckr MCP Server

A NestJS-based MCP server that exposes Kyckr company registry data as MCP tools for KYC/KYB workflows.

## Overview

The service wraps Kyckr's v2 REST API and exposes a set of MCP tools that let an AI agent look up company information, retrieve director and shareholder data, and order official registry documents.

See [`kyckr-mcp-docs/kyckr-mcp-implementation-scope.md`](kyckr-mcp-docs/kyckr-mcp-implementation-scope.md) for the full product context and tool specifications.

## MCP Tools

Status legend: shipped — implemented and verified end-to-end against the Kyckr test API. pending — planned, not yet implemented.

| Tool | Kyckr endpoint | Cost | Status |
|------|---------------|------|--------|
| `search_companies` | `GET /companies` | Free | shipped |
| `get_lite_profile` | `GET /companies/{kyckrId}/lite` | Credits | shipped |
| `get_enhanced_profile` | `GET /companies/{kyckrId}/enhanced` | Credits | shipped |
| `list_company_documents` | `GET /companies/{kyckrId}/documents` | Free | shipped |
| `create_document_order` | `POST /orders` | Credits | shipped |
| `get_order` | `GET /orders/{orderId}` | Free | shipped |
| `list_orders` | `GET /orders` | Free | shipped |

### Tool behavior conventions

- **Errors are returned, not thrown.** Every tool returns `{ success: false, statusCode, message, correlationId }` on a Kyckr 4xx/5xx. The agent should always check `success` before reading `data`.
- **Output schemas are loose.** Tools return Kyckr's response verbatim under `data` plus the upstream envelope fields (`correlationId`, `cost`, `timeStamp`, `details`). New fields added by Kyckr flow through to the client without requiring a release.
- **Inputs are trimmed and normalized.** String inputs are `.trim()`-ed; `isoCode` is uppercased and validated against `^[A-Z]{2}$`.
- **Annotations track cost.** Billed tools are marked `idempotentHint: false` so clients/agents do not retry or re-call them speculatively. Free tools are `idempotentHint: true`.

## Local Development

Copy `.env.example` to `.env` and fill in your Kyckr API key:

```bash
cp .env.example .env
# Edit .env: set KYCKR_API_KEY
pnpm dev
```

The MCP endpoint is available at `http://localhost:9542/mcp`.

## Calling the `/mcp` endpoint

When `MCP_ACCESS_TOKEN` is set, every request to `/mcp` must include it as a Bearer token in the `Authorization` header:

```bash
curl -X POST http://localhost:9542/mcp \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

If `MCP_ACCESS_TOKEN` is unset, the endpoint is open and no header is required (only intended for local development).

### Example: end-to-end Streamable HTTP session

```bash
TOKEN="my-demo-access-token"

# 1) initialize — captures the mcp-session-id header
curl -s -D /tmp/h -o /dev/null -X POST http://localhost:9542/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"demo","version":"0"}}}'
SID=$(grep -i "mcp-session-id" /tmp/h | awk '{print $2}' | tr -d '\r\n')

# 2) notifications/initialized — required handshake step
curl -s -X POST http://localhost:9542/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# 3) tools/call: search_companies
curl -s -X POST http://localhost:9542/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_companies","arguments":{"name":"Kyckr","isoCode":"GB"}}}'

# 4) tools/call: get_lite_profile (PAID — spends credits)
curl -s -X POST http://localhost:9542/mcp \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_lite_profile","arguments":{"kyckrId":"GB|MTE2NTUyOTA"}}}'
```

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KYCKR_API_KEY` | Yes | — | Kyckr API key (sent as Bearer to Kyckr) |
| `KYCKR_API_BASE_URL` | No | `https://test-api.kyckr.com/v2` | Kyckr API base URL |
| `KYCKR_DEFAULT_CUSTOMER_REFERENCE` | No | — | Default customer reference forwarded on profile / order calls for usage reconciliation. Can be overridden per tool call. |
| `KYCKR_DEFAULT_CONTACT_EMAIL` | No | — | Default contact email for document orders. Can be overridden per tool call. |
| `MCP_ACCESS_TOKEN` | No | — | Shared secret protecting the `/mcp` endpoint. When set, requests must include `Authorization: Bearer <token>`. When unset, the endpoint is open (dev only). |
| `PORT` | No | `9542` | HTTP port |
| `LOG_LEVEL` | No | `info` | Pino log level (`fatal` / `error` / `warn` / `info` / `debug` / `trace` / `silent`) |
| `LOGS_DIAGNOSTICS_DATA_POLICY` | No | `conceal` | Whether diagnostic data is concealed or exposed in logs. |

## Architecture

```
src/
  config/                       app, kyckr, logs configs (zod-validated)
  kyckr/
    kyckr-http.client.ts        thin undici wrapper — bearer auth, metrics, error envelope
    kyckr.module.ts             registers the http client and all tools
    schemas/
      kyckr.schemas.ts          shared Zod schemas for the Kyckr v2 wire shapes
    tools/
      search-companies/         search_companies tool (3 files: tool, query, meta)
      get-lite-profile/         get_lite_profile tool
  mcp-access-token.guard.ts     Bearer-token guard for /mcp when MCP_ACCESS_TOKEN is set
  manifest.controller.ts        GET / — server manifest
  server.instructions.ts        MCP server instructions returned during `initialize`
  app.module.ts                 Nest root module wiring
  main.ts                       bootstrap + OTel initialization
```

Each tool follows the same three-file pattern:

- `*.tool.ts` — `@Tool({...})` decorator + thin handler delegating to the query.
- `*.query.ts` — input/output Zod schemas + the call to `KyckrHttpClient` + error mapping.
- `*-tool.meta.ts` — `createMeta({ icon, systemPrompt })` for client UI hints.

## Observability

The service emits:

- `kyckr_api_requests_total` — counter labelled with `method`, `path` (normalized; ids replaced by `:id`), `status`.
- `kyckr_api_request_duration_ms` — histogram labelled with `method`, `path`.

Traces are produced via `nestjs-otel` and the shared `@unique-ag/instrumentation` package. The standard OTel env vars (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_METRICS_EXPORTER`, …) apply.

## Testing

```bash
pnpm test         # unit tests (vitest)
pnpm test:e2e     # boots AppModule against in-process Nest
pnpm check-types  # tsc --noEmit
pnpm style        # biome check
```

E2E tests inject dummy env vars in `test/setup.ts` (`.env.test` is gitignored repo-wide).

## Deployment

See the Helm chart at `deploy/helm-charts/kyckr-mcp/`. Secrets (`KYCKR_API_KEY`, `MCP_ACCESS_TOKEN`) are wired through `server.envVars` from a Kubernetes Secret. Terraform for the Azure Key Vault secret is at `deploy/terraform/azure/kyckr-mcp-secrets/`.
