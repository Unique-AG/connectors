# office-mcp

An MCP server over Microsoft 365, via the Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes four tools
so far — `whoami`, `list_chats`, `search_messages` and `read_message` — and more land in later PRs,
stacked on top of this one.

## Layout

```
src/office_mcp/
  app.py                 composition root — every config and collaborator is built here, once
  config.py              one BaseSettings class per concern, read only at the root
  auth.py                Entra auth: which app registration, and where its state lives
  logging.py metrics.py  cross-cutting, used by both sides below
  graph_client/          the Microsoft Graph transport — the official SDK, one caller's token
  features/              what the connector does — one module per slice (identity, chats, messages)
  server/                how it's exposed over MCP — the tools, the errors they report, /ready
```

This service owns no database schema and has no ORM, no engine and no migrations. Its only table
(`oauth_kv`) belongs to the OAuth state store, which creates it itself — see **State** below.

A feature module owns three things that belong together: the Graph request it makes, the shape it
answers with, and the delegated Graph permissions that request needs. `server/tools.py` declares the
MCP tools over them and is the only place that knows about MCP.

The layering rules are that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse — nor **from FastMCP**, since deciding what an MCP client
is told (a `ToolError`, a schema, an annotation) is the tool layer's job; that **`graph_client/`
imports neither `features/` nor `config`**, taking its own frozen `GraphSettings` instead, that
**`server/` does not import the Graph SDK** — nor the `kiota_*`/`msgraph_core` request layer
underneath it, which is how a Graph call gets shaped without ever spelling `msgraph` — since a tool
declares and exposes while the request belongs to a feature, and that
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
| `Chat.Read` | Delegated | No | `list_chats`, `search_messages`, `read_message` (chats) |
| `ChannelMessage.Read.All` | Delegated | Yes, in most tenants | `search_messages`, `read_message` (channels) |

`Chat.Read` rather than the least-privileged `Chat.ReadBasic` because listing chats by recency needs
`$expand=lastMessagePreview`, and a message preview is a message.

`ChannelMessage.Read.All` is the broad one, and it is requested deliberately. `Chat.Read` alone is
enough for Graph to *accept* a `chatMessage` search, but Microsoft documents that a search never
returns more than the equivalent GET would, and every channel-message GET in v1.0 requires
`ChannelMessage.Read.All` — so without it a search silently covers chats only and reports nothing
missing. Asking for it at sign-in makes a tenant that withholds it fail visibly at consent rather
than serve half an answer per query. It is also what `read_message` needs for a channel message —
Graph's permissions for a message read are per surface, so that tool's own 403 names whichever one
the handle it was given required.

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
| `search_messages` | Teams messages matching keywords, a sender, mentions, a date range, attachment or read state | `POST /search/query` |
| `read_message` | One Teams message in full — text, sender, mentions, attachments, edits, deletion | `GET /chats/{id}/messages/{id}`, `GET /teams/{id}/channels/{id}/messages/{id}` |

All are read-only, all take their caller's identity from the token rather than from a parameter, and
all are described to the model in prose that names the traps rather than only the fields — `mail` is
null for guests (use `user_principal_name`, which may be on a different domain), a chat's recency is
its last message rather than the `lastUpdatedDateTime` that Graph moves on a rename, and a search
hit's `summary` is a snippet rather than the message.

Decisions worth knowing:

- **Every result has a declared output schema.** So `truncated` and `members_may_be_incomplete` are
  typed fields rather than prose or, worse, an extra object appended to the results array that a
  model can mistake for a result.
- **`list_chats` does not paginate.** `limit` (max 50, which is Graph's own `$top` ceiling on that
  collection) is a window on the most recent chats, and `truncated` says when there are more. A
  cursor over a collection that reorders itself on every message returns duplicates and gaps, and
  the window is what "recent chats" means; `services/teams-mcp` ships the same shape.
- **`search_messages` is one Graph request, always.** No fan-out, and specifically no per-chat scan
  when a date filter is set or a permission is missing — which is what the connector this replaces
  falls back to, up to 50 chats × 50 messages. Graph's read budget is "one request per second per
  app per tenant … on a given channel or chat", and *per app* means one user's sweep degrades every
  other user in the tenant; the connector we compared against returned zero results and a rate-limit
  note from that path in a live tenant. Date bounds go into the query string as `sent>=` / `sent<=`
  instead, where Microsoft's index applies them — inclusive, and covering channels as well as chats.
- **`search_messages` reports no result total,** because Graph does not give one: for Teams messages
  the `total` it returns is the count on the page. `more_results_available` plus `next_offset` are
  the whole of the paging contract, and a page can be shorter than `size` because system messages
  (`from: null`, a body of `<systemEventMessage/>`) are dropped and offsets index Graph's own hits.
- **`query` is words, not a phrase.** Multi-word free text reaches Microsoft's index as separate
  terms, which KQL ANDs: every word must appear, anywhere in the message and in any order. Wrapping
  the whole query in the quotes that guard a *filter value* would make it an exact-adjacency phrase
  and silently drop every match whose words are not side by side — the recall loss a caller cannot
  see, since the tool answers with fewer messages than exist and says nothing. A caller who wants
  adjacency quotes the words themselves, and that phrase is passed through as one. The injection
  guard is unweakened, only moved: it now runs a word at a time, so `from:ceo`, `sent>2026-01-01`,
  `(`, `*`, a leading `-` and a bare `OR` are each quoted into literal text rather than obeyed —
  `services/teams-mcp`'s guard, applied where a scope term's *value* is built and per word where
  the caller's own text is.
- **"At least one search criterion" is in the schema,** as an `anyOf` of one-element `required`
  lists, and re-checked at the tool boundary because FastMCP validates against the signature rather
  than the advertised schema. It is the only constraint of that kind here: nothing else about
  Microsoft's KQL scope terms makes two of these parameters genuinely incompatible, so nothing else
  is invented.
- **The reader is `read_message`, not a polymorphic `read_resource`.** It takes a URI handle, which
  pairs with a search that returns one, but its name says only what it reads. Two reasons, and the
  second is the load-bearing one. A tool called `read_resource` that serves Teams messages alone
  invites `mail:///`, `site:///` and `drive:///` — the connector we compared against exposes exactly
  that one polymorphic reader over every M365 entity — and every one of those is a failure a model
  could not have predicted from the name. More importantly, a message read's permission is per
  surface (`Chat.Read` in a chat, `ChannelMessage.Read.All` in a channel) and a token is exchanged
  per tool, so one reader over every entity type would have to redeem the union of every read
  permission on every call: a tenant unwilling to grant meeting-transcript access would break
  reading a chat message. Transcripts (which Microsoft addresses by a join-URL-derived handle) and
  recordings therefore arrive as their own handle-taking readers rather than as new schemes here.
- **A message body is normalised, never passed through as Teams HTML.** Wrapper divs, `<at>`
  mentions, `<emoji alt="👀">`, hostedContents `<img>`, `<attachment>` placeholders and adaptive-card
  JSON all become readable text (`@Name`, the emoji itself, `[image]`, `[attachment: name]`,
  `[card]`), and `mentions` / `attachments` come back resolved so the placeholders have a key. This
  is `services/teams-mcp`'s normaliser ported, not a second attempt at it.
- **A message with no text says why.** Microsoft Graph has no rendered text for a system event
  message — `from` is null and the body is the literal `<systemEventMessage/>`, because Teams writes
  "Ada joined the chat" in the client — so a read that lands on one reports the event named from
  `eventDetail` (`members joined`, `chat renamed`) and a null `text`. A deleted message reports
  `deleted_at` and a null `text` rather than a tombstone's leftovers. Both are the difference
  between "no content" and "they said nothing".
- **`read_message` keeps three failures distinct.** A malformed handle is ours to explain, so its
  error shows both readable shapes and says where a handle comes from; Graph's 404 on a well-formed
  handle says the message could not be read and explicitly *not* that it never existed (Graph
  answers deleted, invisible and absent identically); a 403 names the one permission that surface
  needs. The generic "check the id came from a tool response verbatim" advice is suppressed for the
  404 here, because the handle did come from one — that is `graph_tool_errors(..., not_found=...)`.
- **A search query is never logged.** Not in a message, not as a structured field, not as a span
  attribute — what someone searched their own messages for names people and deals. `teams-mcp` had
  to remove query terms from its spans and logs after the fact; a test here asserts they never
  arrive.
- **A refusal names its remedy.** `server/errors.py` maps each Graph failure onto the one thing a
  model can do about it: 401 → ask the user to sign in again, 403 → ask an administrator for *this
  named permission*, 429 → wait Graph's own `Retry-After`, 5xx → retry once. The Graph request id
  rides along, because that is what Microsoft support asks for. A permission that was never
  consented to fails earlier still — Entra refuses the On-Behalf-Of exchange (AADSTS65001) while
  FastMCP is resolving the tool's token, before the tool body runs — so `server/tools.py` wraps that
  exchange to give it the same named-permission remedy instead of "Failed to resolve dependency".
  Both paths name *every* permission the call was made under, which for `search_messages` is
  `Chat.Read` and `ChannelMessage.Read.All` both: neither Graph's 403 nor Entra's AADSTS65001 says
  which of the two was missing, and an administrator handed one name may grant the one that was
  already there. So the tenant that grants `Chat.Read` and withholds `ChannelMessage.Read.All` gets
  a refusal of this connector's own wording, naming both permissions and the remedy — not
  azure-identity's stack trace.

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
