# kb-mcp

Knowledge Base Search MCP — search Unique knowledge bases, browse the content
tree, and read files. Migrated from `unique-ag/ai` tutorials (`mcp_search`).

Auth is Zitadel OIDC via [`unique-mcp`](https://pypi.org/project/unique-mcp/).
KB APIs come from [`unique-toolkit`](https://pypi.org/project/unique-toolkit/).

## Run locally

```bash
cd services/kb-mcp
cp .env.example .env
# fill in the Unique API and Zitadel client settings, then:
uv sync
uv run kb-mcp
```

HTTP MCP on `/mcp`, probe on `GET /probe`. Bind URL is `UNIQUE_MCP_LOCAL_BASE_URL`
(Helm default `http://0.0.0.0:8000`; local examples may use another port).

Logs are **pino-json** on stderr via `unique_mcp.configure_logging` (Loki label
`logging.unique.app/format=pino-json`). Level from `LOG_LEVEL` (default `info`).
Ops access lines for `/probe`, `/health`, and `/metrics` are silenced.

## Configuration

MCP authentication uses a public Zitadel client with OAuth PKCE, so
`ZITADEL_CLIENT_SECRET` is not required. `ZITADEL_JWT_SIGNING_KEY` replaces it
as local key material FastMCP uses to sign its own downstream OAuth-proxy
JWTs — it is never sent to Zitadel, but is required since the client is
secretless. `ENCRYPTION_KEY` is separate: it encrypts the OAuth proxy state
stored in Postgres. For local development, set
`ALLOW_EPHEMERAL_OAUTH_STORAGE=true` instead of configuring Postgres.

Set `UNIQUE_API_BASE_URL` to the internal Unique API service in Kubernetes.
Local development and Kong/public-gateway deployments also need
`UNIQUE_APP_ID` and `UNIQUE_APP_KEY`.

The optional `KB_MCP_*` variables in `.env.example` tune advertised tools,
search concurrency, content-tree cache and timeout behavior, and the outbound
HTTP connection pool. Helm deployments can set the same values under
`mcpConfig` in `deploy/helm-charts/kb-mcp/values.yaml`.

## Tools

| Tool | Purpose |
|------|---------|
| `search` | Semantic / internal KB search |
| `content_tree` | Browse / list / fuzzy-search visible folders & files |
| `read_file` | Download and return file content by `content_id` |

Which tools are advertised on `/mcp` is configurable via `KB_MCP_ENABLED_TOOLS`
(unset = all three) — see `.env.example` / `mcpConfig.enabledTools` in the Helm
chart.

## Tests

```bash
uv run pytest
uv run ruff check .
uv run basedpyright
```

## Deploy

Same path as other connectors Python services: Dockerfile under `deploy/`, Helm
chart under `deploy/helm-charts/kb-mcp`, release-please + CD template.
Secrets are injected via `envVars` (Argo overlay), not baked into chart defaults.
Exposure uses Gateway API routes (no custom Ingress), matching `hello-mcp`.
