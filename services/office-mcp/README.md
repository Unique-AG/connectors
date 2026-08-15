# office-mcp

An MCP server for Microsoft 365 via Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes seven MCP
tools so far — `get_me`, the signed-in user's own profile; `list_chats`, their Microsoft Teams chats
most recently active first; `list_teams`, the teams they are a member of; `list_channels`, the
channels of one of those teams; `browse_channel`, what was posted in one of those channels;
`search_messages`, full-text search across every Teams message they can see; and `read_message`,
one of those messages in full — each one a file of its own, and more land in later PRs, stacked on
top of this one, one tool per PR.

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
| `ChannelMessage.Read.All` | Delegated | Yes, in most tenants | `browse_channel`, `search_messages`, `read_message` (channels) |

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

`ChannelMessage.Read.All` is the broad one, and it is requested deliberately. `Chat.Read` alone is
enough for Graph to *accept* a `chatMessage` search, but Microsoft documents that a search never
returns more than the equivalent GET would, and every channel-message GET in v1.0 requires
`ChannelMessage.Read.All` — so without it a search silently covers chats only and reports nothing
missing. Asking for it at sign-in makes a tenant that withholds it fail visibly at consent rather
than serve half an answer per query. It is also what `browse_channel` spends on its one request, and
what `read_message` needs for a channel message. It is the first permission here that needs an
administrator, and the first row where one tool needs
two: neither Graph's 403 nor Entra's AADSTS65001 says which of the two was missing, so
`search_messages` names both in every refusal — handed one name, an administrator may grant the
permission that was never missing and watch the identical failure. A search has no choice about
that, because a search happens before anything knows which surface a hit will be on; a *read* does,
which is why its 403 names one. `shared/seam.py` writes the same names out once more, by hand, as
`REQUESTABLE_PERMISSIONS`: every other check compares the tool files against a list derived from
those same files, so a misspelling is on both sides of the comparison and holds — and Entra rejects
an authorize request carrying a scope it does not know, which fails every sign-in for every user.
Adding a name there is the deliberate act this table records.

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
- **Paging follows `@odata.nextLink`** via `collect_pages`, replaying the URL verbatim, with an item
  cap, a *scan* cap — the teams-mcp lesson that a filtered collection can walk a long way for very
  few kept items — a bound on how many pages of nothing it will follow in a row, and a `capped` flag
  so a partial answer never looks complete. A channel's messages are the exception and are not
  walked at all: Graph allows about one request a second on a given channel for the whole app across
  the tenant, so `browse_channel` makes exactly one and `$top` is its window. Search is not paged
  this way either: `POST /search/query` takes stateless `from`/`size` offsets, so a search tool
  resumes by re-issuing rather than by carrying a cursor.
- **An empty page carrying a next link means keep going, and the walk is ours because of it.** The
  SDK's `PageIterator.enumerate` returns `False` for a page whose `value` is empty and its `iterate`
  reads that as the end of the collection — so a collection Graph answers `[1 item + nextLink]`,
  `[nothing + nextLink]`, `[3 more]` came back as one item. Every list-shaped tool here says "that
  is all of it" by coming back short of `limit`, so believing an empty page does not merely lose
  items: it turns a window with more behind it into a claim that there is not. `collect_pages` walks
  through them, bounds a *run* of them (`MAX_EMPTY_PAGES`, and it is not pooled with the scan cap:
  an empty page spends no scan budget, so a shared budget is no bound on empty pages at all), and
  raises `GraphPagingUnending` rather than answering short — because a short answer means a cap.
- **The caller's token goes to `graph.microsoft.com` and nowhere else.** The SDK's bearer provider
  does not check its own allowed-hosts validator, so a redirect or an off-Graph `nextLink` would
  otherwise be handed a user's delegated credential.

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
