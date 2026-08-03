# kb-mcp

Knowledge Base Search MCP — search Unique knowledge bases, browse the content
tree, and read files. Migrated from `unique-ag/ai` tutorials (`mcp_search`).

Auth is Zitadel OIDC via [`unique-mcp`](https://pypi.org/project/unique-mcp/).
KB APIs come from [`unique-toolkit`](https://pypi.org/project/unique-toolkit/).

## Run locally

```bash
cd services/kb-mcp
cp .env.example .env
# fill in Unique + Zitadel credentials, then:
uv sync
uv run kb-mcp
```

HTTP MCP on `/mcp`, probe on `GET /probe`. Bind URL is `UNIQUE_MCP_LOCAL_BASE_URL`
(Helm default `http://0.0.0.0:8000`; local examples may use another port).

Logs are **pino-json** on stderr via `unique_mcp.configure_logging` (Loki label
`logging.unique.app/format=pino-json`). Level from `LOG_LEVEL` (default `info`).
Ops access lines for `/probe`, `/health`, and `/metrics` are silenced.

## Tools

| Tool | Purpose |
|------|---------|
| `search` | Semantic / internal KB search |
| `content_tree` | Browse / list / fuzzy-search visible folders & files |
| `read_file` | Download and return file content by `content_id` |

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
