# office-mcp

An MCP server for Microsoft 365 via Microsoft Graph API.

Users sign in with their own Microsoft account. The server acts as them. No MCP tools are
exposed yet. Feature packages and tools land in later PRs.

## Layout

```
src/office_mcp/
  app.py                 composition root — config and collaborators.
  config.py              one BaseSettings class per concern.
  auth.py                Entra auth: app registration and state location.
  logging.py metrics.py  cross-cutting utilities.
  graph_client/          Microsoft Graph transport via the official SDK.
  features/              connector features (later PRs).
  server/                MCP surface (/ready probe today, tools later).
```

This service owns no database schema, ORM, engine, or migrations. Its only table (oauth_kv) is
created by the OAuth state store.

Layering rules: **features/ must not import server/** (server wires features, not the reverse);
**graph_client/ must import neither features/ nor config** (it takes frozen GraphSettings);
**only create_app constructs a config** (nothing re-reads the environment). tests/test_layering.py
enforces all three.

## Auth

Microsoft Entra via FastMCP's AzureProvider. This service holds no OAuth code. The provider is
an OAuth 2.1 proxy owning /authorize, PKCE on both hops, the callback, refresh, and
On-Behalf-Of exchange. auth.py only chooses the app registration and state store.

The provider mounts these endpoints. They must be reachable unauthenticated (they ARE the
authentication) and not hidden behind an ingress path prefix:

```
/authorize  /token  /register  /auth/callback  /consent
/.well-known/oauth-authorization-server
/.well-known/oauth-protected-resource/mcp
```

**App registration requirements.** Missing values here do not always stop the provider from
starting. Some only make every login fail, with no startup error:

- A **Web platform** redirect URI of exactly `$PUBLIC_BASE_URL/auth/callback`
- An Application ID URI (defaults to `api://$ENTRA_CLIENT_ID`) exposing the scope **access_as_user**
  (Entra omits OIDC scopes from the scp claim, so a custom scope is the only gate)
- `"requestedAccessTokenVersion": 2` in the manifest
- A client secret (ENTRA_CLIENT_SECRET required for On-Behalf-Of)
- A single tenant ID (common/organizations/consumers rejected at startup; the provider validates
  all tokens against one issuer derived from this value, so multi-tenant values would reject all of
  them rather than accept all tenants due to issuer mismatch)

Graph permissions are not requested yet. They belong in the tools that need them.

**State.** Every token is a reference token re-validated on each request. State location decides
whether a restart or second replica causes loss. FastMCP defaults to an encrypted file tree in
process home. This service uses Postgres. The store creates table oauth_kv on first use. The
database user needs CREATE on its schema. No migration exists because the columns are the store
library's to define and keep in sync — a revision duplicating them would be ours to keep in sync,
which breaks when the library changes its schema. Rows are encrypted with a key derived from the
client secret. Rotating the secret requires each signed-in user to re-login once (decryption
failure is treated as a cache miss).

## Microsoft Graph

graph_client/ is the official msgraph-sdk, nothing else. It does not acquire tokens. FastMCP's
On-Behalf-Of exchange hands tools the caller's Graph token as a string; this package sends it.

- **One transport, many callers.** create_graph_transport(settings) builds the httpx.AsyncClient
  (connection pool + SDK middleware) once. graph_client_for(transport, token) wraps it per
  call. The token is the only thing that varies. A client per call means a TLS handshake per
  call and a leaked pool.

- **Throttling is the SDK's.** Its retry middleware waits out Retry-After on 429/503/504 three
  times, which is Graph's documented contract. Nothing here re-implements it. What is added is
  the typed outcome: when retries are outlasted, callers get GraphThrottled with
  retry_after_seconds, not a status code to re-interpret.

- **Errors are four categories**, because those are the four remedies: GraphThrottled (429),
  GraphForbidden (401/403), GraphNotFound (404), GraphUnavailable (5xx or unreachable). Wrap
  Graph work in `with graph_errors():`. Anything else stays base GraphFailure.

- **Paging follows @odata.nextLink** via collect_pages, replaying the URL verbatim, with both
  item cap and scan cap. The scan cap stops long walks through filtered collections (the
  teams-mcp lesson). Truncation signalling prevents partial answers from looking complete.
  Search is not paged this way; POST /search/query takes from/size offsets, so tools resume
  by re-issuing, not carrying a cursor.

- **The caller's token goes to graph.microsoft.com and nowhere else.** The SDK's bearer
  provider does not check its allowed-hosts validator. Without this, redirects or off-Graph
  @odata.nextLink URLs receive the user's delegated credential.

## Run locally

```bash
cd services/office-mcp
cp .env.example .env   # fill DB_* and ENTRA_*
uv sync
uv run office-mcp
```

No migration needed. The database needs an empty schema the app user can CREATE in. The OAuth
store creates its table on first use.

- MCP endpoint: `http://localhost:9544/mcp` (HTTP, authenticated)
- Health: `GET /health` (liveness via unique_mcp.monitoring.setup_ops)
- Probe: `GET /probe` (process-up via setup_ops)
- Ready: `GET /ready` (503 when Postgres unreachable; asks the OAuth store, the only connection
  a sign-in depends on. A different connection could report ready while sign-in still fails.)
- Metrics: `GET /metrics` (Prometheus via setup_ops)
- Traces: off unless an `OTEL_*` variable says where to send them. `OTEL_TRACES_EXPORTER=console`
  prints spans to stderr; an `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` sends them to a collector and
  needs nothing else. `.env.example` lists the knobs, the chart wires them from
  `internalServices.dependencies.otelTraces.enabled`. Latency stays on `/metrics` only: the ASGI
  instrumentation's own duration histogram is switched off so one series measures it.

## Tests

Integration tests start a Postgres container (Docker must be running). The app under test
creates the one table it needs, as in production.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
