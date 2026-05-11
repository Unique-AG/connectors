# Kyckr MCP Server

A NestJS-based MCP server that exposes Kyckr company registry data as MCP tools for KYC/KYB workflows.

## Overview

The service wraps Kyckr's REST API directly and exposes 7 MCP tools that let an AI agent look up company information, retrieve director and shareholder data, and order official registry documents.

See [`kyckr-mcp-docs/kyckr-mcp-implementation-scope.md`](kyckr-mcp-docs/kyckr-mcp-implementation-scope.md) for the full product context and tool specifications.

## MCP Tools

| Tool | Kyckr endpoint | Cost |
|------|---------------|------|
| `search_companies` | `GET /companies` | Free |
| `get_lite_profile` | `GET /companies/{id}/lite` | Credits |
| `get_enhanced_profile` | `GET /companies/{id}/enhanced` | Credits |
| `list_company_documents` | `GET /companies/{id}/documents` | Free |
| `create_document_order` | `POST /orders` | Credits |
| `get_order` | `GET /orders/{id}` | Free |
| `list_orders` | `GET /orders` | Free |

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

## Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KYCKR_API_KEY` | Yes | — | Kyckr API key (Bearer token) |
| `KYCKR_API_BASE_URL` | No | `https://test-api.kyckr.com/v2` | Kyckr API base URL |
| `MCP_ACCESS_TOKEN` | No | — | Shared secret to protect the `/mcp` endpoint |
| `KYCKR_DEFAULT_CUSTOMER_REFERENCE` | No | — | Default customer reference for usage reconciliation |
| `KYCKR_DEFAULT_CONTACT_EMAIL` | No | — | Default contact email for document orders |
| `PORT` | No | `9542` | HTTP port |
| `LOG_LEVEL` | No | `info` | Pino log level |

## Deployment

See the Helm chart at `deploy/helm-charts/kyckr-mcp/`. Secrets (`KYCKR_API_KEY`, `MCP_ACCESS_TOKEN`) must be injected via `server.envVars` from a Kubernetes Secret.
