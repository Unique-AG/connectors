<!-- mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00 -->
# Polixis MCP

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: ruff, basedpyright and import-linter check most of it.

Its [Commands](../../packages/mcp-architecture/ARCHITECTURE.md#commands) install, check and
serve this MCP, with `polixis-mcp` for `<name>`.

## This MCP

Looks up organizations and people in Polixis corporate data: search, corporate profiles with their related parties, linked companies, top-down ownership and ultimate beneficial owners, sanctions and PEP flags, sanctions exposure, connections and court decisions.

- Upstream: OpenAPI. `upstream/openapi.yml` is built by `uv run poe merge-spec` from Polixis's own spec for the graph service, `spec/polixis-graph.openapi.json`, kept as they sent it, and the edits in `spec/merge_spec.py`: our operationIds, the search service, the rejection body, the corrections it notes where it makes them, and the routes Polixis does not document. Never edit `openapi.yml` by hand; add an edit to `merge_spec.py`. `spec/README.md` lists every change and says how to take a new spec from Polixis. The client exchanges `UPSTREAM_CLIENT_ID` and `UPSTREAM_CLIENT_SECRET` for a bearer token at `UPSTREAM_TOKEN_URL` and sends `UPSTREAM_API_KEY` as `x-api-key` on every request. `upstream/routes.py` lists the operations served as tools straight from the spec, and `operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`. Generate an operation and its models with `uv run poe codegen` before writing either by hand; [`guides/upstream.md`](../../packages/mcp-architecture/guides/upstream.md#openapi) says when a hand-written model is allowed.
- Persistence: Postgres, every table modelled in `persistence/models.py` and made by an Alembic migration the chart's hook runs, as in `architecture-demo-mcp`; the server makes none. Every table is reached through one `async_sessionmaker`, `Persistence.database` (`DATABASE_URL`), and its tables sit behind protocols, so the offline tests swap them for fakes. The auth provider's own key-value store (`py-key-value-aio`, its `kv_store` table modelled as the library would make it, with `auto_create=False`) keeps the Zitadel sign-in state, whose expired rows `Persistence.sign_in_state` culls through that database. In a table of their own (`persistence/response_cache.py`, behind the `ResponseCache` contract in `shared`), it holds the Polixis answers the upstream client reuses for `UPSTREAM_CACHE_TTL_SECONDS` (`upstream/cache.py`, a transport in front of the client's admission and token), 15 minutes by default and at most an hour unless `UPSTREAM_CACHE_TTL_UNCAPPED=true`, which spares the API key further requests while developing. The TTL limits reuse, not storage: the server deletes the expired entries, best-effort, at startup and once per TTL after, at least hourly, and keeps the cached answers under `UPSTREAM_CACHE_MAX_MEGABYTES` by deleting the least recently read.
- Auth: Zitadel sign-in through `mcp_auth`'s OIDC proxy, built in `mcp/auth/` and passed to `FastMCP(auth=...)`. Its clients and tokens sit encrypted in Postgres. `MCP_AUTH_MODE=none` turns sign-in off, and `run_server` then keeps the server on loopback. The Polixis credentials are not that sign-in: every admitted caller shares them.
