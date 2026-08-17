# office-mcp

An MCP server for Microsoft 365 via Microsoft Graph API.

Users sign in with their own Microsoft account. The server acts as each user. It exposes `get_me`
(the signed-in user's profile) now, with more tools in future PRs.

## Layout

```
src/office_mcp/
  app.py                 Compose the app.
  config.py              Config classes.
  auth.py                Entra auth setup.
  logging.py metrics.py  Cross-cutting utilities.
  graph_client/          Microsoft Graph transport (official SDK).
  shared/                Code that two or more tools must share.
  tools/                 One file per tool, plus permissions registry.
  server/                /ready endpoint (not a tool).
```

This service owns no database schema or migrations. Its only table (oauth_kv) is created by the OAuth store.

**A tool is a file.** `tools/get_me.py` owns the tool name, description, Graph permissions, arguments,
output shape, Graph request, and error messages. A new tool is one file plus one line in the registry.
No base class, no decorator. A tool module publishes `TOOL_NAME`, `GRAPH_PERMISSIONS` and `register`.

`tools/__init__.py` is the central registry. It assembles `GRAPH_SCOPES`—the union of every tool's
`GRAPH_PERMISSIONS`—derived from the tool modules themselves, never by hand. Entra must receive all
Graph permissions at startup. A forgotten permission cannot be obtained later. The registry reads the
tool *files* from disk to ensure every registered tool declares its permissions, and `tests/test_app.py`
verifies this.

**`shared/` is code that two tools cannot disagree on:** `identity.py` (who the signed-in user is—
every other answer correlates against this) and `seam.py` (On-Behalf-Of token and Graph error
messages). A thing belongs here when two tools need it and a difference between them breaks callers.
Nothing else belongs here.

**Layering rules:**
- `shared/` imports no tool module. Only `shared/seam.py` imports FastMCP.
- `graph_client/` imports nothing from this application.
- `tools/` imports `shared/`, `graph_client/`, and FastMCP only.
- Only `create_app` constructs config. Nothing downstream reads environment.
- Packages are entered via `__init__`. (`graph_client/`, `server/`, `tools/` publish `__all__`.)

`tests/test_layering.py` enforces these rules.

## Auth

Entra via FastMCP's AzureProvider. FastMCP handles OAuth 2.1: /authorize, PKCE, callback, refresh, and
On-Behalf-Of exchange. This service chooses the app registration and state store only.

The provider mounts these endpoints (must be reachable unauthenticated, not behind an ingress prefix):
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

**Graph permissions.** Tools declare what they need. `create_app` passes the union to the provider as
`additional_authorize_scopes`. Entra issues one token per resource. The code exchange asks for this
service's scope only. Tools redeem Graph permissions per call via On-Behalf-Of. A permission never
requested at sign-in cannot be consented to.

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `get_me` |

**State.** Every token is a reference token re-validated on each request. State location decides
whether a restart or second replica causes loss. FastMCP defaults to an encrypted file tree in
process home. This service uses Postgres. The store creates table oauth_kv on first use. The
database user needs CREATE on its schema. No migration exists because the columns are the store
library's to define and keep in sync — a revision duplicating them would be ours to keep in sync,
which breaks when the library changes its schema. Rows are encrypted with a key derived from the
client secret. Rotating the secret requires each signed-in user to re-login once. A decryption
failure is a cache miss, not an error.

## Microsoft Graph

`graph_client/` wraps the official msgraph-sdk. It does not acquire tokens. FastMCP's On-Behalf-Of
exchange hands the caller's Graph token as a string; this package sends it.

- **One transport, many callers.** `create_graph_transport(settings)` builds the `httpx.AsyncClient`
  (connection pool + SDK middleware) once. `graph_client_for(transport, token)` wraps it per call.
  Per-call clients cause TLS handshakes and leak pools.

- **Throttling is the SDK's.** Its retry middleware waits out Retry-After on 429/503/504 three
  times, on asyncio.sleep, so a wait never blocks the event loop. This is Graph's documented
  contract. Nothing here re-implements it. There is no rate limiter. What is added is the typed
  outcome: a 429 that outlasts the retries reaches callers as GraphThrottled with
  retry_after_seconds, not a status code to re-interpret. An outlasted 503 or 504 reaches them
  as GraphUnavailable.

- **Errors are four types (four remedies):** `GraphThrottled` (429), `GraphForbidden` (401/403),
  `GraphNotFound` (404), `GraphUnavailable` (5xx or unreachable). Wrap Graph work with
  `with graph_errors():`.

- **Paging follows @odata.nextLink** via `collect_pages`, with item and scan caps. Search uses
  from/size offsets.

- **Trap:** The SDK bearer provider does not validate allowed-hosts. Redirects to off-Graph URLs send
  the caller's delegated credential. Restrict to `graph.microsoft.com` only.

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
- Metrics: `GET /metrics` (Prometheus via setup_ops). Beside unique_toolkit's own HTTP series, four
  say what this connector asked Microsoft Graph for: `graph_requests_total{operation,status}`,
  `graph_request_duration_seconds{operation}`, `graph_throttled_total{operation,retried}` and
  `graph_pages_scanned{operation}`. `operation` is the tool's own name and never a URL — a label
  taken off a Graph URL would be one time series per chat. `status` is the remedy the failure needs
  (`forbidden`, `not_found`, `throttled`, `unavailable`), not the HTTP code. `retried` says whether
  the SDK spent its retries on a 429 or refused the wait Graph asked for.
- Traces: off unless an `OTEL_*` variable says where to send them. `OTEL_TRACES_EXPORTER=console`
  prints spans to stderr; an `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` sends them to a collector and
  needs nothing else. `.env.example` lists the knobs, the chart wires them from
  `internalServices.dependencies.otelTraces.enabled`. Latency stays on `/metrics` only: the ASGI
  instrumentation's own duration histogram is switched off so one series measures it. No span
  carries a Graph URL: the SDK sets the full URL as `url.full` by default in two places—the request
  span and the URL replacer's own span—and both are closed, because a Graph URL here is a chat,
  message or transcript id and almost nothing else. The request span keeps `url.uri_template`,
  which is what a latency breakdown groups by.

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
