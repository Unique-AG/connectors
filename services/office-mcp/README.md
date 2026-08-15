# office-mcp

An MCP server for Microsoft 365 via Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes two MCP tools
so far — `get_me`, the signed-in user's own profile, and `list_chats`, their Microsoft Teams chats
most recently active first — each one a file of its own, and more land in later PRs, stacked on top
of this one, one tool per PR.

An operator chooses which of those tools a deployment runs, and the permissions sign-in asks every
user to consent to are exactly the union of what those tools need — see **Tool surface** below.

## Layout

```
src/office_mcp/
  app.py                 Compose the app.
  config.py              Config classes.
  auth.py                Entra auth setup.
  logging.py metrics.py  Cross-cutting utilities.
  graph_client/          Microsoft Graph transport (official SDK).
  shared/                Code that two or more tools must share.
  tools/                 One file per tool, plus the registry that selects and unions them.
  server/                /ready and /manifest endpoints (not tools).
```

This service owns no database schema or migrations. Its only table (oauth_kv) is created by the OAuth store.

**A tool is a file.** `tools/get_me.py` owns the tool name, description, Graph permissions, arguments,
output shape, Graph request, and error messages. A new tool is one file plus one line in the registry.
No base class, no decorator. A tool module publishes `TOOL_NAME`, `GRAPH_PERMISSIONS` and `register`.

`tools/__init__.py` is the central registry. `resolve()` turns an operator's selection into both
halves of one answer: the tool modules to register, and the union of their `GRAPH_PERMISSIONS` as the
scope list sign-in asks for. Both are derived from the tool modules themselves, never written by
hand. Entra must receive every Graph permission at startup—a forgotten one cannot be obtained
later—so `create_app` resolves once and hands the same `Selection` to `build_auth` and
`register_tools`. `tests/test_app.py` reads the tool *files* from disk to verify that every
registered tool's permissions reach the consent screen.

**`shared/` is what a file-per-tool costs.** Two files are free to disagree, and this package is the
list of things they must not: `handles.py` (the `teams:///` grammar — every shape this connector
mints, its parser and its speller, and the permission each Teams surface is read under),
`identity.py` (who the signed-in user is — `get_me` reports it, and it is the fact every other
answer gets correlated against, so a second tool asking with a `GET /me` of its own would be a
second answer to one question) and `seam.py` (the Graph client a tool is handed,
with the per-tool On-Behalf-Of token inside it, and the Graph-failure-to-advice mapping, because a model reads every refusal on this server as one voice). A
thing belongs there when two tools would otherwise each need a copy *and* a difference between the
copies would be a bug a caller could see — a handle one tool minted and another answers 404 to, two
answers to "who am I", a refusal that sounds like a different server. What does not belong there is
anything one tool could own — a description, an argument, an answer shape, a request, a refusal.

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

**Graph permissions.** Tools declare what they need. `create_app` passes the union of the *selected*
tools' permissions to the provider as `additional_authorize_scopes`. Entra issues one token per
resource. The code exchange asks for this service's scope only. Tools redeem Graph permissions per
call via On-Behalf-Of. A permission never requested at sign-in cannot be consented to.

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `get_me` |
| `Chat.Read` | Delegated | No | `list_chats` |

`Chat.Read` rather than the least-privileged `Chat.ReadBasic` because listing chats by recency needs
`$expand=lastMessagePreview`, and a message preview is a message — which "read the names and members
of chats" does not cover. It is spelled in `shared/handles.py` rather than in the tool file, because
which Teams surface a permission covers is the handle grammar's knowledge; the tool still declares
its own tuple, which is what its 403 is worded from. `shared/seam.py` writes the same names out once more, by hand, as
`REQUESTABLE_PERMISSIONS`: every other check compares the tool files against a list derived from
those same files, so a misspelling is on both sides of the comparison and holds — and Entra rejects
an authorize request carrying a scope it does not know, which fails every sign-in for every user.
Adding a name there is the deliberate act this table records.

**State.** Every token is a reference token re-validated on each request. State location decides
whether a restart or second replica causes loss. FastMCP defaults to an encrypted file tree in
process home. This service uses Postgres. The store creates table oauth_kv on first use. The
database user needs CREATE on its schema. No migration exists because the columns are the store
library's to define and keep in sync — a revision duplicating them would be ours to keep in sync,
which breaks when the library changes its schema. Rows are encrypted with a key derived from the
client secret. Rotating the secret requires each signed-in user to re-login once. A decryption
failure is a cache miss, not an error. Widening the tool surface costs the same re-login, for the
same reason: the authorize request changes.

## Tool surface

Which tools a deployment runs, and therefore which delegated permissions every one of its users is
asked to consent to. Set **exactly one** of:

```bash
TOOLS_PRESET=teams                       # a named surface
TOOLS_ENABLED=get_me                     # or name the tools
```

Both set is a startup error naming which to remove. Neither set is a startup error too: there is
**no default**, because a default of "every tool" would make the widest consent screen what a
deployment gets by not choosing. `TOOLS_PRESET=teams` keeps "everything" a one-word but chosen value.

| preset | tools |
| --- | --- |
| `teams` | every tool there is |

`get_me` is **always on**, whatever the selection. It is how the server resolves "me"—the identity
every other answer is correlated against—and `User.Read` is the least-privileged delegated permission
Microsoft publishes and needs no administrator. So `TOOLS_ENABLED` lists only the rest, presets need
not mention it, and **no deployment asks for zero permissions**: every one asks for at least
`User.Read`. Naming it explicitly is accepted, not an error.

An unknown tool name, an unknown preset, an empty list, both variables, or neither each aborts
startup and names the remedy. A typo never quietly costs a tool.

**The manifest.** At startup, and on `GET /manifest`, the server prints what it resolved to: the
tools, the exact delegated permissions in Entra's spelling, and which of them need admin consent.
That list is what an operator hands their Entra administrator, and it is the only place it is written
down—so it is worth reading before the first sign-in rather than after. A scope the app registration
does not carry fails at the *authorize* hop, for every user, with nothing in this service's logs:
Azure omits Graph scopes from the session token, so the server cannot check its own ask against the
registration. The manifest prints no consent URL; provisioning the registration is out of scope.

The manifest also warns when an exposed tool's description points a model at a tool this deployment
does not expose. It only warns—tool prose references its siblings densely, and requiring every
mention would drag permissions into a deployment that wanted none of them.

Narrowing a live deployment is free. Widening one adds a permission to the authorize request, so
every signed-in user meets AADSTS65001 on the new tool until they sign in again.

In Helm, this rides the chart's existing `env:` map. `values.yaml` deliberately defaults neither
variable, and `values.schema.json` requires exactly one and carries the preset names as an `enum`, so
a missing or misspelled selection fails `helm install` instead of crash-looping a pod.

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

- MCP endpoint: `http://localhost:9544/mcp` (HTTP, authenticated)
- Health: `GET /health` (liveness via unique_mcp.monitoring.setup_ops)
- Probe: `GET /probe` (process-up via setup_ops)
- Ready: `GET /ready` (503 when Postgres unreachable; asks the OAuth store, the only connection
  a sign-in depends on. A different connection could report ready while sign-in still fails.)
- Manifest: `GET /manifest` (the resolved tool surface and the exact permissions sign-in asks for;
  unauthenticated, and it leaks nothing—the same scopes are in the authorize URL already)
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
