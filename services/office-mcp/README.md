# office-mcp

An MCP server for Microsoft 365 via Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes one MCP tool
so far — `get_me`, the signed-in user's own profile — and more land in later PRs, stacked on top of
this one, one tool per PR.

## Layout

```
src/office_mcp/
  app.py                 composition root — config and collaborators.
  config.py              one BaseSettings class per concern.
  auth.py                Entra auth: app registration and state location.
  logging.py metrics.py  cross-cutting utilities.
  graph_client/          Microsoft Graph transport via the official SDK.
  shared/                what two tools must not disagree about, and nothing else
  tools/                 one file per tool, plus the registry that assembles their permissions
  server/                /ready, the one exposure concern that is not a tool
```

This service owns no database schema, ORM, engine, or migrations. Its only table (oauth_kv) is
created by the OAuth state store.

**A tool is a file.** `tools/get_me.py` owns its name, the prose that teaches a model when to reach
for it, the delegated Graph permissions it calls under, its arguments and their descriptions, the
shape it answers with, the Graph request it makes and the wording of every refusal only it can
explain. Adding the second tool is adding one file and one line to the registry; reading the first
is reading one file. There is no base class, no decorator of our own and no tool-declaration module:
a tool module publishes two names, `GRAPH_PERMISSIONS` and `register`, and that is the whole of the
contract.

`tools/__init__.py` is the one piece of central machinery, and `GRAPH_SCOPES` is why it exists.
`create_app` has to hand the auth provider every Graph permission any tool might redeem, at startup,
before any tool has been called — a permission that was never consented to cannot be obtained later.
So each tool module declares its own `GRAPH_PERMISSIONS` and the registry assembles the union *from
the modules*, never by hand: a hand-written list is a list somebody forgets, and the forgotten tool
is one that fails at sign-in for a permission nobody asked for. `app.GRAPH_SCOPES` is that tuple
re-exported and not a second derivation of it. The order is stable across process starts
(`dict.fromkeys`, deliberately not a set), because the consent screen and every cached On-Behalf-Of
token key change with it.

What reaches Entra is asserted at the root as well as at the registry, in `tests/test_app.py`, and
the root assertion reads the tool *files* off disk rather than the registry: a file that was never
added to `_TOOL_MODULES` registers nothing and asks for nothing, and a registry compared against
itself would never say so. That failure is invisible — every other test still passes, while the
tool's permissions never reach the consent screen and its On-Behalf-Of exchange fails in a live
tenant.

**`shared/` is what a file-per-tool costs.** Two files are free to disagree, and this package is the
list of things they must not: `identity.py` (who the signed-in user is — `get_me` reports it, and it
is the fact every other answer gets correlated against, so a second tool asking with a `GET /me` of
its own would be a second answer to one question) and `seam.py` (the per-tool On-Behalf-Of token and
the Graph-failure-to-advice mapping, because a model reads every refusal on this server as one
voice). A thing belongs there when two tools would otherwise each need a copy *and* a difference
between the copies would be a bug a caller could see. What does not belong there is anything one
tool could own — a description, an argument, an answer shape, a request, a refusal.

The layering rules are that **`shared/` imports no tool module, and only `shared/seam.py` imports
FastMCP** — the seam is where the framework is spoken, which is what keeps it out of the rest of the
vocabulary; that **`graph_client/` imports nothing of this application at all**, taking its own
frozen `GraphSettings` instead of reading config; that **`tools/` imports `shared/`, `graph_client/`
and FastMCP and nothing else of this package** — not `server/`, or the tool file is one in name
only; that **only `create_app` constructs a config**, so nothing downstream can quietly re-read the
environment and disagree with the app it runs in; and that **a package is entered through its
`__init__`** — `graph_client/`, `server/` and `tools/` each publish an `__all__`, and `shared/`
deliberately does not, being a grouping whose modules are the units and whose consumers say which
one they depend on at the import line.

`tests/test_layering.py` enforces them, and each rule is paired with a guard that fails if the rule
has gone vacuous — an empty tree to walk, a missing file to forbid reaching past, a framework
nothing imports any more, a package with no `__all__` to insist on. Three rules of the finished set
are absent for exactly that reason and are named in that module: no tool module may import another
(nothing to confuse with one tool), one speller per handle family (nothing mints a handle yet), and
nothing may address a single meeting recording (nothing lists them yet). Each arrives with the tool
that makes it assertable, and the numbering is the finished one so that arriving costs a class.

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

**App registration requirements** (the provider refuses to start if any are missing):

- A **Web** redirect URI of exactly `$PUBLIC_BASE_URL/auth/callback`.
- An Application ID URI (defaults to `api://$ENTRA_CLIENT_ID`) exposing scope **access_as_user**.
  Entra omits OIDC scopes from the scp claim; a custom scope is the only gate.
- `"requestedAccessTokenVersion": 2` in the manifest.
- A client secret (ENTRA_CLIENT_SECRET required for On-Behalf-Of).
- A single tenant ID. The provider validates all tokens against one issuer. Multi-tenant values
  reject all of them due to issuer mismatch.

**Graph permissions** belong to the tools that need them, and `create_app` passes their union to
the provider as `additional_authorize_scopes`. They ride the authorize request only — Entra issues
one token per resource, so the code exchange asks for this API's own scope and each tool redeems a
Graph one per call via On-Behalf-Of. That redemption can only succeed for a permission already
consented to, which is why sign-in has to ask for it:

| Permission | Type | Admin consent | Used by |
| --- | --- | --- | --- |
| `User.Read` | Delegated | No | `get_me` |

`User.Read` is the least-privileged delegated permission for `/me`, and the table grows one row per
tool that needs a new one. `shared/seam.py` writes the same names out once more, by hand, as
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
