# office-mcp

An MCP server for Microsoft 365 via Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes six MCP
tools so far — `get_me`, the signed-in user's own profile; `list_chats`, their Microsoft Teams chats
most recently active first; `list_teams`, the teams they are a member of; `list_channels`, the
channels of one of those teams; `search_messages`, full-text search across every Teams message they
can see; and `read_message`, one of those messages in full — each one a file of its own, and more
land in later PRs, stacked on top of this one, one tool per PR.

## Layout

```
src/office_mcp/
  app.py                 Build the app.
  config.py              Configuration.
  auth.py                Entra authentication.
  logging.py metrics.py  Utilities.
  graph_client/          Graph transport (official SDK).
  shared/                Code two or more tools share.
  tools/                 One file per tool. Plus registry.
  server/                Health endpoints.
```

One table: `oauth_kv` (created by the OAuth store). No migrations owned.

**A tool is one file.** The file owns its name, description, permissions, parameters, output shape,
Graph request, and error messages. One file plus one line in the registry adds a tool.
`tools/__init__.py` assembles `GRAPH_SCOPES` from modules (never by hand). All permissions reach
Entra at startup. A forgotten permission means sign-in fails. `tests/test_app.py` verifies this.

**`shared/` is the cost of file-per-tool architecture.** It holds the things two files must agree on:
`handles.py` (the `teams:///` grammar), `messages.py` (Teams message shape, sender normalization,
HTML unwinding), `identity.py` (signed-in user profile), `seam.py` (token exchange, error advice).
Use `shared/` when two tools would otherwise need identical copies and differing copies would be
visible bugs: handles one tool mints and another rejects; two answers to "who am I"; refusals that
sound inconsistent. Don't put tool-specific things there: descriptions, parameters, output, requests.

Layering rules:
- `shared/` imports no tool; only `seam.py` imports FastMCP.
- `graph_client/` imports nothing of this app.
- `tools/` imports `shared/`, `graph_client/`, FastMCP only.
- No tool imports another tool.
- Only `create_app` constructs configuration.
- Only `handles.py` builds or parses `teams:///` URIs.
- Packages entered through `__init__` (`graph_client/`, `server/`, `tools/` publish `__all__`; `shared/` does not).

`tests/test_layering.py` enforces each rule with a guard that fails if the rule is vacuous.

One planned rule is still missing. Only one module may address a single meeting recording. It
waits for a recordings-list tool to give it a surface to protect. It arrives with that tool.

## Auth

FastMCP AzureProvider handles OAuth 2.1 (authorization, PKCE, refresh, On-Behalf-Of). This service
picks the app registration and state store.

FastMCP mounts these endpoints (must be unauthenticated, not behind ingress prefix):
```
/authorize  /token  /register  /auth/callback  /consent
/.well-known/oauth-authorization-server
/.well-known/oauth-protected-resource/mcp
```

**App registration:**
- Redirect URI: `$PUBLIC_BASE_URL/auth/callback`
- App ID URI: `api://$ENTRA_CLIENT_ID` scope `access_as_user`
- Manifest: `"requestedAccessTokenVersion": 2`
- Client secret (for On-Behalf-Of)
- Single tenant (multi-tenant rejected)

**Graph permissions:** Tools declare what they need. `create_app` passes the union to the provider.
Tools redeem permissions per call via On-Behalf-Of. No permission = no consent = sign-in fails.

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `get_me` |
| `Chat.Read` | Delegated | No | `list_chats`, `search_messages`, `read_message` |
| `Team.ReadBasic.All` | Delegated | No | `list_teams` |
| `Channel.ReadBasic.All` | Delegated | No | `list_channels` |
| `ChannelMessage.Read.All` | Delegated | Usually | `search_messages`, `read_message` (channels) |

Multiple tools naming the same permission is normal. It is not duplication to remove. Each tool
declares its own tuple because that tuple words its own 403 and AADSTS65001 messages.
`tools/__init__.py` removes the duplicates when it builds `GRAPH_SCOPES`.

`Team.ReadBasic.All` is least-privileged for `/me/joinedTeams` (Microsoft's docs). Separate from
the broad channel permission: a tenant refusing `ChannelMessage.Read.All` still lists teams.
`list_teams` 403 names only its own permission.

`Chat.Read` not `Chat.ReadBasic`: listing chats by recency needs `$expand=lastMessagePreview`.
A preview is a message; "read chat names" doesn't cover it.

Per-surface permissions: `read_message` redeems both (exchange before tool sees argument), but 403
names only the surface used. Naming both there would be as unhelpful as naming none. An
administrator handed two names may grant the one that was never missing. Search can't know the
surface beforehand, so it names both. `shared/seam.py` lists both in `REQUESTABLE_PERMISSIONS`:
misspelling is on both sides.

`ChannelMessage.Read.All` requested deliberately. `Chat.Read` alone lets Graph *accept* searches
but Microsoft docs say searches never return more than GET would. All channel GET needs
`ChannelMessage.Read.All`. Without it, searches silently cover chats only. Asking at sign-in makes
tenants that withhold it fail visibly at consent, not serve incomplete results.

The channel inventory is two permissions, and they are separate scopes on purpose:
`Channel.ReadBasic.All` lists a team's channels, `ChannelMessage.Read.All` reads what was posted in
one. Each is the least-privileged permission Microsoft documents for its collection. A tenant
refusing the message permission still lists teams and channels, and each tool's 403 names only the
permission its own request needed.

**State:** Tokens revalidated per request. FastMCP's default store is an encrypted file tree. It
resets on restart. It breaks at replicas: each replica writes its own file, invisible to the
others. This service uses Postgres instead. Store creates `oauth_kv` on first use. Rows encrypted
with key from client secret. Rotating the secret requires each user to re-login once.

## Microsoft Graph

`graph_client/` wraps the official msgraph-sdk (no token acquisition; FastMCP provides token).

- **One transport, many callers:** `create_graph_transport` builds the `httpx.AsyncClient` once.
  `graph_client_for(transport, token)` wraps it per call. Per-call clients leak TLS and pools.

- **Throttling built-in:** SDK retries 429/503/504 three times. Timeouts return `GraphThrottled`.

- **Four error types:** `GraphThrottled` (429), `GraphForbidden` (401/403), `GraphNotFound` (404),
  `GraphUnavailable` (5xx/unreachable). Wrap Graph work with `with graph_errors():`.

- **Paging:** Follows `@odata.nextLink` via `collect_pages` (item/scan caps). Search uses offsets.

- **TRAP: Empty pages with `@odata.nextLink` mean keep going.** SDK's `PageIterator` treats empty
  pages as end-of-collection. A collection like `[1 item+link]`, `[empty+link]`, `[3 more]`
  becomes one item. List tools here claim "end" only by returning short of `limit`.
  `collect_pages` follows empties (bounded by `MAX_EMPTY_PAGES`, not scan budget) or raises
  `GraphPagingUnending`—short answers mean the limit applied.

- **TRAP:** SDK bearer provider doesn't validate allowed hosts. Redirects to non-Graph URLs send
  delegated credentials. Restrict to `graph.microsoft.com`.

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
