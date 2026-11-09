# Polixis MCP

Looks up organizations and people in Polixis corporate data: search, corporate profiles with
their related parties, relationship graphs, top-down ownership and ultimate beneficial owners,
and sanctions and PEP flags.

## Tools

| Tool | Polixis endpoint | Kind |
|---|---|---|
| `search_entities` | `POST /search/api` | Our own: returns `EntityMatch`, mapped in `contexts/entities/` |
| `get_corporate_profile` | `POST /api/corporate/byPublisher` | Served from the spec |
| `get_smart_graph` | `POST /api/graph/smart` | Served from the spec |
| `get_subgraph` | `POST /api/graph/subgraph` | Served from the spec |
| `get_top_down_ownership` | `GET /api/graph/topdown/{id}` | Served from the spec |
| `get_ultimate_beneficial_owners` | `GET /api/graph/ubo/{id}` | Served from the spec |
| `list_completion_fields` | `GET /api/completion/fields` | Served from the spec |
| `get_profile_fields` | `POST /api/completion/{id}` | Served from the spec |
| `get_basic_identifiers` | `GET /api/basic-identifiers/{id}` | Served from the spec |
| `get_key_identifiers` | `GET /api/key-identifiers/{id}` | Served from the spec |
| `resolve_permanent_id` | `GET /api/graph/pid/{pid}` | Served from the spec |

Every tool only reads. A served tool's name, arguments and output come from
`src/polixis_mcp/upstream/openapi.yml`, and `upstream/routes.py` lists them.

## The spec is ours, for now

Polixis has no working OpenAPI spec yet, so `upstream/openapi.yml` was written by hand from
their PDF documentation (version 3). No response has been checked against the live API, so:

- every response field is optional, and a field the documentation gives no shape for, such as
  `finance`, `stocks` or `meta`, is left out of the spec. The generated models ignore it, and a
  served tool still passes it through to the client;
- the operationIds are ours, since the documentation has none.

### Switching to the vendor's spec

1. Save their spec over `src/polixis_mcp/upstream/openapi.yml`. It must be OpenAPI 3.0; convert a
   Swagger 2.0 file first. If it is served at a URL, set `spec-source` in `[tool.mcp-openapi]`
   and run `uv run poe codegen --refresh-spec` instead, which also lists the operationIds added
   and removed.
2. Rename the operationIds in `operation-ids` (`pyproject.toml`) and `EXPOSED`
   (`upstream/routes.py`) to theirs, then run `uv run poe codegen`.
3. `uv run poe typecheck` names every place a changed model breaks. Only
   `contexts/entities/search_entities.py` maps a vendor model, so fix the mapping there and the
   `search_entities` tool keeps its shape.
4. `uv run poe architecture` shows how each served tool's arguments and output changed. Read the
   diff, then accept it with `uv run poe surface`.

A tool that must keep its shape whatever Polixis changes is promoted the same way as
`search_entities`: drop its operationId from `EXPOSED`, map the generated model to our own in a
context, and write a tool over it.

## Environment

`.env.example` lists every variable. Besides the server's own:

| Variable | |
|---|---|
| `UPSTREAM_CLIENT_ID`, `UPSTREAM_CLIENT_SECRET` | Polixis client credentials, exchanged for a bearer token at `UPSTREAM_TOKEN_URL` |
| `UPSTREAM_API_KEY` | Sent as `x-api-key` on every request |
| `UPSTREAM_API_URL`, `UPSTREAM_TOKEN_URL` | Default to Polixis production |
| `UPSTREAM_RETRY_*` | Retries any request on a 429, and a GET on a 503. Which status Polixis' circuit breaker sends is not documented; add it to `statuses` once known |
| `MCP_AUTH_MODE` | `zitadel` in a deployment, `none` locally |
| `ZITADEL_*` | Zitadel sign-in for the MCP's users |
| `DATABASE_URL` | Postgres, which holds only the encrypted Zitadel sign-in state |

Every signed-in user shares the one set of Polixis credentials. A user's Zitadel token never
reaches Polixis.

## Deploy

`deploy/terraform/azure/polixis-mcp-secrets` creates the Key Vault placeholders for the Polixis
credentials, valued `<TO BE SET MANUALLY>`. Set each one by hand, then map it in the overlay's
ExternalSecret:

| Key Vault secret | Variable |
|---|---|
| `manual-polixis-mcp-client-id` | `UPSTREAM_CLIENT_ID` |
| `manual-polixis-mcp-client-secret` | `UPSTREAM_CLIENT_SECRET` |
| `manual-polixis-mcp-api-key` | `UPSTREAM_API_KEY` |

A placeholder with `create = false` in `secrets_placeholders` is skipped, for a secret that
already exists.

## Run it locally

```bash
cp .env.example .env    # fill in the UPSTREAM_ credentials
uv sync
uv run polixis-mcp      # http://127.0.0.1:8000/mcp, without sign-in
```

It opens Postgres at `DATABASE_URL` even without sign-in, so start one first, for example
`docker run -e POSTGRES_PASSWORD=dummy-password -e POSTGRES_USER=dummy-user -e POSTGRES_DB=polixis_mcp -p 5432:5432 postgres:17`.

`uv run poe ci` runs every check CI runs.
