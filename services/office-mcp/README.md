# office-mcp

An MCP server over Microsoft 365, via the Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes two tools so
far — `whoami` and `list_chats` — and more land in later PRs, stacked on top of this one.

## Layout

```
src/office_mcp/
  app.py                 composition root — every config and collaborator is built here, once
  config.py              one BaseSettings class per concern, read only at the root
  auth.py                Entra auth: which app registration, and where its state lives
  logging.py metrics.py  cross-cutting, used by both sides below
  graph_client/          the Microsoft Graph transport — the official SDK, one caller's token
  features/              what the connector does — one module per slice (identity, chats)
  server/                how it's exposed over MCP — the tools, the errors they report, /ready
```

This service owns no database schema and has no ORM, no engine and no migrations. Its only table
(`oauth_kv`) belongs to the OAuth state store, which creates it itself — see **State** below.

A feature module owns three things that belong together: the Graph request it makes, the shape it
answers with, and the delegated Graph permission that request needs. `server/tools.py` declares the
MCP tools over them and is the only place that knows about MCP.

The layering rules are that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse — that **`graph_client/` imports neither `features/`
nor `config`**, taking its own frozen `GraphSettings` instead, that **`server/` does not import the
Graph SDK**, since a tool declares and exposes while the request belongs to a feature, and that
**only `create_app` constructs a config**, so nothing downstream can quietly re-read the
environment and disagree with the app it runs in. `tests/test_layering.py` enforces all of them,
and grows as each package arrives.

## Auth

Microsoft Entra, through FastMCP's own `AzureProvider`. There is no OAuth code in this service:
the provider is an OAuth 2.1 proxy that presents a DCR-capable authorization server to MCP clients
and translates it onto the app registration, so `/authorize`, PKCE on both hops, the redirect
callback, refresh, and the On-Behalf-Of exchange that turns a user's token into a Graph one are all
its own. `auth.py` decides only which app registration to use and where the state is kept.

The endpoints it mounts, all of which must be reachable unauthenticated — they *are* the
authentication — and must not be swallowed by an ingress path prefix:

```
/authorize  /token  /register  /auth/callback  /consent
/.well-known/oauth-authorization-server
/.well-known/oauth-protected-resource/mcp
```

**App registration requirements.** The provider will not start, or will reject every login, unless
all of these hold:

- a **Web** platform redirect URI of exactly `$PUBLIC_BASE_URL/auth/callback`;
- an Application ID URI (defaults to `api://$ENTRA_CLIENT_ID`) exposing a scope named
  **`access_as_user`** — Entra leaves OIDC scopes out of the `scp` claim, so a custom API scope is
  the only thing that can gate access to this server;
- `"requestedAccessTokenVersion": 2` in the manifest;
- a client secret (`ENTRA_CLIENT_SECRET`), which On-Behalf-Of cannot be done without;
- a single tenant. `ENTRA_TENANT_ID=common`/`organizations`/`consumers` is rejected at startup:
  the provider validates every token against one issuer derived from that value, so a
  multi-tenant authority would reject all of them rather than accept all tenants.

**Graph permissions** belong to the tools that need them, and `create_app` passes their union to
the provider as `additional_authorize_scopes`. They ride the authorize request only — Entra issues
one token per resource, so the code exchange asks for this API's own scope and each tool redeems a
Graph one per call via On-Behalf-Of. That redemption can only succeed for a permission already
consented to, which is why sign-in has to ask for it:

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `whoami` |
| `Chat.Read` | Delegated | No | `list_chats` |

`Chat.Read` rather than the least-privileged `Chat.ReadBasic` because listing chats by recency needs
`$expand=lastMessagePreview`, and a message preview is a message.

**State.** Every token the server issues is a reference token re-validated on each request, so
where that state lives decides whether the deployment survives a restart or a second replica.
FastMCP's default is an encrypted file tree under the process's home directory; this service uses
Postgres instead, in a table (`oauth_kv`) the store creates itself on first use — so the database
user needs `CREATE` on its schema, and there is no migration for it (the columns are the store
library's to define, and a revision duplicating them would be ours to keep in sync). The rows are
encrypted
with a key derived from the client secret, which means rotating that secret costs each signed-in
user one re-login (a failed decryption is treated as a cache miss, not an error).

## Microsoft Graph

`graph_client/` is the official `msgraph-sdk`, and nothing else. It acquires no tokens: FastMCP's
On-Behalf-Of exchange hands a tool the caller's Graph access token as a string, and this package
gets that string onto the wire.

- **One transport, many callers.** `create_graph_transport(settings)` builds the `httpx.AsyncClient`
  — connection pool plus the SDK's middleware pipeline — once, and `graph_client_for(transport,
  token)` wraps it per call. The token is the only thing that varies; a client per call would mean
  a TLS handshake per call and a leaked pool.
- **Throttling is the SDK's, deliberately.** Its retry middleware already waits out `Retry-After`
  on 429/503/504 (on `asyncio.sleep`, not a blocking one) three times, which is exactly Graph's
  documented contract. Nothing here re-implements it and there is no rate limiter. What is added is
  the *typed* outcome: when the retries are outlasted, callers get `GraphThrottled` carrying
  `retry_after_seconds`, not a status code to re-interpret.
- **Errors are four categories**, because those are the four remedies: `GraphThrottled` (429),
  `GraphForbidden` (401/403), `GraphNotFound` (404) and `GraphUnavailable` (5xx, or never reached).
  Wrap Graph work in `with graph_errors():`. Anything else stays the base `GraphFailure`.
- **Paging follows `@odata.nextLink`** via `collect_pages`, replaying the URL verbatim, with both an
  item cap and a *scan* cap — the teams-mcp lesson that a filtered collection can walk a long way
  for very few kept items — and a `truncated` flag so a partial answer never looks complete. Search
  is not paged this way: `POST /search/query` takes stateless `from`/`size` offsets, so a search
  tool resumes by re-issuing rather than by carrying a cursor.
- **The caller's token goes to `graph.microsoft.com` and nowhere else.** The SDK's bearer provider
  does not check its own allowed-hosts validator, so a redirect or an off-Graph `nextLink` would
  otherwise be handed a user's delegated credential.

## Tools

| Tool | What it answers | Graph |
| --- | --- | --- |
| `whoami` | Who the signed-in user is: `id`, `display_name`, `mail`, `user_principal_name`, `job_title` | `GET /me` |
| `list_chats` | The user's Teams chats, most recently active first | `GET /me/chats` |

Both are read-only, both take their caller's identity from the token rather than from a parameter,
and both are described to the model in prose that names the traps rather than only the fields —
`mail` is null for guests (use `user_principal_name`, which may be on a different domain), and a
chat's recency is its last message, not the `lastUpdatedDateTime` that Graph moves on a rename.

Three decisions worth knowing:

- **Every result has a declared output schema.** So `truncated` and `members_may_be_incomplete` are
  typed fields rather than prose or, worse, an extra object appended to the results array that a
  model can mistake for a result.
- **`list_chats` does not paginate.** `limit` (max 50, which is Graph's own `$top` ceiling on that
  collection) is a window on the most recent chats, and `truncated` says when there are more. A
  cursor over a collection that reorders itself on every message returns duplicates and gaps, and
  the window is what "recent chats" means; `services/teams-mcp` ships the same shape.
- **A refusal names its remedy.** `server/errors.py` maps each Graph failure onto the one thing a
  model can do about it: 401 → ask the user to sign in again, 403 → ask an administrator for *this
  named permission*, 429 → wait Graph's own `Retry-After`, 5xx → retry once. The Graph request id
  rides along, because that is what Microsoft support asks for. A permission that was never
  consented to fails earlier still — Entra refuses the On-Behalf-Of exchange (AADSTS65001) while
  FastMCP is resolving the tool's token, before the tool body runs — so `server/tools.py` wraps that
  exchange to give it the same named-permission remedy instead of "Failed to resolve dependency".

## Run locally

```bash
cd services/office-mcp
cp .env.example .env   # fill DB_* and ENTRA_*
uv sync
uv run office-mcp
```

There is no migration step: the database needs an empty schema the app's user can `CREATE` in,
and the OAuth state store makes its own table on first use.

- MCP endpoint: `http://localhost:9544/mcp` (HTTP transport, authenticated)
- Health: `GET /health` — liveness via `unique_mcp.monitoring.setup_ops`
- Probe: `GET /probe` — process-up (setup_ops)
- Ready: `GET /ready` — 503 when Postgres is unreachable. It asks the OAuth state store, which
  is the only connection a sign-in depends on; probing anything else could report ready on a
  server nobody can log in to.
- Metrics: `GET /metrics` — Prometheus (setup_ops)

## Tests

Integration tests start a Postgres container, so Docker must be running. Nothing is applied to
it — the app under test creates the one table it needs, the same way it does in production.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
