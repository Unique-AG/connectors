# Temenos MCP Server

A NestJS-based microservice that wraps the Temenos DataHub REST API and exposes operational banking data as MCP tools. It lets an AI agent read holdings, payments, party, product, and reference data from a Temenos core-banking (T24 / DataHub ODS) backend.

All tools are **read-only** (HTTP `GET`). The service follows the `kyckr-mcp` pattern: a thin HTTP client plus one tool per endpoint.

## Table of Contents

- [Quick Start](#quick-start)
- [MCP Tools](#mcp-tools)
- [Configuration](#configuration)
- [Development](#development)
- [Deployment](#deployment)
- [Observability](#observability)

## Quick Start

```bash
# Install dependencies (from the repo root)
pnpm install

# Copy environment template
cp .env.example .env
# Edit .env: set TEMENOS_API_KEY (and MCP_API_KEY)

# Start development server
pnpm dev
```

The MCP endpoint is then available at `http://localhost:9543/<MCP_API_KEY>/mcp`.

## MCP Tools

The server exposes **49** tools across five domains, each wrapping a single Temenos DataHub `GET` endpoint:

| Domain | Count | Examples |
|--------|-------|----------|
| Holdings | 17 | `get_guarantees`, `get_nostro_accounts`, `get_vostro_accounts`, `get_repo_positions`, `get_expiring_limits`, `get_shared_limits`, `get_letter_of_credit_tenors` |
| Order | 3 | `get_pending_payments`, `get_payment_fees`, `get_transaction_stop_investigations` |
| Party | 5 | `get_customer_relationships`, `get_customer_prospects`, `get_customer_secure_messages`, `get_participants`, `get_external_user_preferences` |
| Product | 1 | `get_interest_conditions` |
| Reference | 23 | `get_countries`, `get_industries`, `get_companies`, `get_sectors`, `get_account_officers`, `get_lookups`, `get_system_dates`, `get_us_states` |

On a Temenos 4xx/5xx the HTTP client raises a `TemenosApiError` carrying the upstream status, request path, and the best available error message (`message` / `detail` / `title` / `error`, else the raw body).

## Configuration

Copy `.env.example` to `.env` and configure the following.

### Required Variables

| Variable | Description |
|----------|-------------|
| `TEMENOS_API_KEY` | Temenos DataHub API key, sent as the `apikey` HTTP header on every request. |
| `MCP_API_KEY` | Shared secret protecting the MCP endpoint. The service mounts at `/<MCP_API_KEY>/mcp`, so clients must use the api-key as the URL-path prefix (Unique's connector validator rejects query/fragment, hence the path prefix). |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMENOS_API_BASE_URL` | `https://api.temenos.com/api/v1.0.0` | Base URL for the Temenos DataHub REST API. Point this at the target DataHub/T24 environment. |
| `PORT` | `9543` | HTTP port. |
| `LOG_LEVEL` | `info` | Pino log level (`fatal` / `error` / `warn` / `info` / `debug` / `trace` / `silent`). |

### Generating Secrets

```bash
# Generate a 64-char hex secret (for MCP_API_KEY)
openssl rand -hex 32
```

## Development

### Prerequisites

- Node.js >= 24
- pnpm
- A Temenos DataHub API key for the target environment

### Available Scripts

| Script | Description |
|--------|-------------|
| `pnpm dev` | Start development server |
| `pnpm build` | Build for production |
| `pnpm test` | Run unit tests |
| `pnpm test:e2e` | Run end-to-end tests |
| `pnpm test:coverage` | Run tests with coverage |
| `pnpm check-types` | Type-check with `tsc --noEmit` |
| `pnpm style` | Check code style (Biome) |
| `pnpm style:fix` | Fix code style issues |

E2E tests inject dummy env vars in `test/setup.ts`. The repo-wide `.gitignore` excludes `.env.*`, so a real `.env.test` is not committed.

### Calling `/mcp`

The MCP endpoint is mounted at `/<MCP_API_KEY>/mcp`. Clients must use the api-key as the URL-path prefix:

```bash
curl -X POST "http://localhost:9543/$MCP_API_KEY/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Deployment

### Docker Compose (Production)

```bash
docker compose -f docker-compose.prod.yaml up -d
```

### Azure Lab (Demo)

Demo deployment to the Unique [LAB](https://unique-ch.atlassian.net/wiki/spaces/DX/pages/1873739786/Labs) subscription as an App Service Web App. Demo only — no SLA, no client data, no production go-lives.

```bash
cp services/temenos-mcp/deploy/.env.deploy.example services/temenos-mcp/deploy/.env.deploy
# Fill in TEMENOS_API_KEY and MCP_API_KEY (generate: openssl rand -hex 32)
services/temenos-mcp/deploy/deploy.sh
```

The lab resource group is provisioned by the lab Terraform workflow once the matching entry in the infrastructure repo's `config/environments.yaml` is merged; `deploy.sh` will refuse to run until it exists.

## Observability

The service emits OpenTelemetry metrics via `nestjs-otel`:

- `temenos_tool_call_duration_ms` — tool call duration, labelled by `tool` and `result`
- `temenos_api_requests_total` — Temenos API requests, labelled by `path` and `status`
- `temenos_api_request_duration_ms` — Temenos API request duration, labelled by `path`
