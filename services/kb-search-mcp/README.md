# kb-search-mcp

Knowledge Base Search MCP — search Unique knowledge bases, browse the content
tree, and read files. Migrated from `unique-ag/ai` tutorials (`mcp_search`).

Auth is Zitadel OIDC via [`unique-mcp`](https://pypi.org/project/unique-mcp/).
KB APIs come from [`unique-toolkit`](https://pypi.org/project/unique-toolkit/).

## Run locally

```bash
cd services/kb-search-mcp
cp .env.example .env
# fill in Unique + Zitadel credentials, then:
uv sync
uv run kb-search-mcp
```

HTTP MCP on `/mcp`, probe on `GET /probe`. Bind URL is `UNIQUE_MCP_LOCAL_BASE_URL`
(Helm default `http://0.0.0.0:8000`; local examples may use another port).

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
chart under `deploy/helm-charts/kb-search-mcp`, release-please + CD template.
Secrets are injected via `envVars` (Argo overlay), not baked into chart defaults.
Exposure uses Gateway API routes (no custom Ingress), matching `hello-mcp`.
