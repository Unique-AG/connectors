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
No base class, no decorator. A tool module publishes `GRAPH_PERMISSIONS` and `register`.

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

**App registration requirements:**
- Web redirect URI: `$PUBLIC_BASE_URL/auth/callback`
- Application ID URI: `api://$ENTRA_CLIENT_ID` with scope `access_as_user`
- Manifest: `"requestedAccessTokenVersion": 2`
- Client secret (required for On-Behalf-Of)
- Single tenant ID (multi-tenant values are rejected)

**Graph permissions.** Tools declare what they need. `create_app` passes the union to the provider as
`additional_authorize_scopes`. Entra issues one token per resource. The code exchange asks for this
service's scope only. Tools redeem Graph permissions per call via On-Behalf-Of. A permission never
requested at sign-in cannot be consented to.

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `get_me` |

**State.** Every token is re-validated on each request. FastMCP defaults to an encrypted file tree (resets
on restart, breaks at replicas). This service uses Postgres. The store creates table `oauth_kv` on first
use. The database user needs CREATE on its schema. Rows are encrypted with a key derived from the client
secret. Rotating the secret requires each user to re-login once.

## Microsoft Graph

`graph_client/` wraps the official msgraph-sdk. It does not acquire tokens. FastMCP's On-Behalf-Of
exchange hands the caller's Graph token as a string; this package sends it.

- **One transport, many callers.** `create_graph_transport(settings)` builds the `httpx.AsyncClient`
  (connection pool + SDK middleware) once. `graph_client_for(transport, token)` wraps it per call.
  Per-call clients cause TLS handshakes and leak pools.

- **Throttling is built-in.** The SDK retries on 429/503/504 with Retry-After three times. On timeout,
  callers get `GraphThrottled` with `retry_after_seconds`.

- **Errors are four types (four remedies):** `GraphThrottled` (429), `GraphForbidden` (401/403),
  `GraphNotFound` (404), `GraphUnavailable` (5xx or unreachable). Wrap Graph work with
  `with graph_errors():`.

- **Paging follows @odata.nextLink** via `collect_pages`, with item and scan caps. Search uses
  from/size offsets.

- **An empty page carrying a next link means keep going, and the walk is ours because of it.** The
  SDK's `PageIterator.enumerate` returns `False` for a page whose `value` is empty and its `iterate`
  reads that as the end of the collection — so a collection Graph answers `[1 item + nextLink]`,
  `[nothing + nextLink]`, `[3 more]` came back as one item. Every list-shaped tool here says "that
  is all of it" by coming back short of `limit`, so believing an empty page does not merely lose
  items: it turns a window with more behind it into a claim that there is not. `collect_pages` walks
  through them, bounds a *run* of them (`MAX_EMPTY_PAGES`, and it is not pooled with the scan cap:
  an empty page spends no scan budget, so a shared budget is no bound on empty pages at all), and
  raises `GraphPagingUnending` rather than answering short — because a short answer means a cap.

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

- MCP endpoint: `http://localhost:9544/mcp` (HTTP, authenticated).
- Health: `GET /health` (liveness probe).
- Probe: `GET /probe` (process-up probe).
- Ready: `GET /ready` (503 if Postgres unreachable; depends on OAuth store connection).
- Metrics: `GET /metrics` (Prometheus metrics).

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
