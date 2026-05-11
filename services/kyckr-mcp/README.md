# Kyckr MCP Server

A NestJS-based microservice that exposes Kyckr's v2 company-registry API as MCP tools for KYC/KYB workflows. It lets an AI agent search companies, fetch profiles, list registry documents, and place document orders.

## Table of Contents

- [Quick Start](#quick-start)
- [MCP Tools](#mcp-tools)
- [Configuration](#configuration)
- [Development](#development)
- [Deployment](#deployment)
- [Observability](#observability)

## Quick Start

```bash
# Install dependencies
pnpm install

# Copy environment template
cp .env.example .env
# Edit .env: set KYCKR_API_KEY

# Start development server
pnpm dev
```

The MCP endpoint is then available at `http://localhost:9542/mcp`.

## MCP Tools

| Tool | Kyckr endpoint | Cost |
|------|----------------|------|
| `search_companies` | `GET /companies` | Free |
| `get_lite_profile` | `GET /companies/{kyckrId}/lite` | Credits |
| `get_enhanced_profile` | `GET /companies/{kyckrId}/enhanced` | Credits |
| `list_company_documents` | `GET /companies/{kyckrId}/documents` | Free |
| `create_document_order` | `POST /orders` | Credits |
| `get_order` | `GET /orders/{orderId}` | Free |
| `list_orders` | `GET /orders` | Free |

All tools return `{ success: false, statusCode, message, correlationId }` on Kyckr 4xx/5xx so the agent can branch on `success` instead of catching exceptions. Successful responses pass the Kyckr payload through under `data` unchanged.

## Configuration

Copy `.env.example` to `.env` and configure the following.

### Required Variables

| Variable | Description |
|----------|-------------|
| `KYCKR_API_KEY` | Kyckr API key, sent as `Bearer` to the Kyckr API |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KYCKR_API_BASE_URL` | `https://test-api.kyckr.com/v2` | Kyckr API base URL. Point at `https://api.kyckr.com/v2` for production. |
| `KYCKR_DEFAULT_CUSTOMER_REFERENCE` | — | Default `customerReference` forwarded on profile and order calls for usage reconciliation. Overridable per call. |
| `KYCKR_DEFAULT_CONTACT_EMAIL` | — | Default contact email used when placing document orders. Overridable per call. |
| `MCP_ACCESS_TOKEN` | — | Shared secret protecting `/mcp`. When set, requests must include `Authorization: Bearer <token>`. When unset, the endpoint is open (dev only). |
| `PORT` | `9542` | HTTP port. |
| `LOG_LEVEL` | `info` | Pino log level (`fatal` / `error` / `warn` / `info` / `debug` / `trace` / `silent`). |

### Generating Secrets

```bash
# Generate a 64-char hex secret (for MCP_ACCESS_TOKEN)
openssl rand -hex 32
```

## Development

### Prerequisites

- Node.js 20+
- pnpm
- A Kyckr API key (test or production)

### Available Scripts

| Script | Description |
|--------|-------------|
| `pnpm dev` | Start development server |
| `pnpm build` | Build for production |
| `pnpm test` | Run unit tests |
| `pnpm test:e2e` | Run end-to-end tests |
| `pnpm test:coverage` | Run tests with coverage |
| `pnpm check-types` | Type-check with `tsc --noEmit` |
| `pnpm style` | Check code style |
| `pnpm style:fix` | Fix code style issues |

E2E tests inject dummy env vars in `test/setup.ts`. The repo-wide `.gitignore` excludes `.env.*`, so a real `.env.test` is not committed.

### Calling `/mcp`

When `MCP_ACCESS_TOKEN` is set, every request must include it as a Bearer token:

```bash
curl -X POST http://localhost:9542/mcp \
  -H "Authorization: Bearer $MCP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Deployment

### Docker Compose (Production)

```bash
docker compose -f docker-compose.prod.yaml up -d
```

### Kubernetes (Helm)

```bash
helm install kyckr-mcp ./deploy/helm-charts/kyckr-mcp \
  --namespace kyckr-mcp \
  --create-namespace \
  -f values.yaml
```

Secrets (`KYCKR_API_KEY`, `MCP_ACCESS_TOKEN`) are wired through `server.envVars` from a Kubernetes Secret.

### Terraform (Azure)

Infrastructure modules in `deploy/terraform/`:
- `kyckr-mcp-secrets`: Azure Key Vault entries for the API key and MCP access token.

## Observability

The service emits:

- **Logging**: Structured JSON logs via Pino with correlation IDs.
- **Metrics**: `kyckr_api_requests_total` (counter) and `kyckr_api_request_duration_ms` (histogram), labelled with `method`, `path` (normalized so registry ids become `:id`), and `status`.
- **Tracing**: Distributed traces via `nestjs-otel` and the shared `@unique-ag/instrumentation` package.
- **Dashboards**: Grafana dashboard shipped with the Helm chart.

Configure with the standard OpenTelemetry environment variables:

```env
OTEL_SERVICE_NAME=kyckr-mcp
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
OTEL_EXPORTER_PROMETHEUS_PORT=8081
```
