# office-mcp

An MCP server over Microsoft 365, via the Microsoft Graph API.

Users sign in with their own Microsoft account and the server acts as them. It exposes no MCP
tools yet: the Microsoft Graph client and the feature packages and tools that use it land in later
PRs, stacked on top of this one.

## Layout

```
src/office_mcp/
  app.py                 composition root — every config and collaborator is built here, once
  config.py              one BaseSettings class per concern, read only at the root
  auth.py                Entra auth: which app registration, and where its state lives
  logging.py metrics.py  cross-cutting, used by both sides below
  features/              what the connector does — empty until the first feature lands
  server/                how it's exposed over MCP — the /ready probe today, tools when they land
```

This service owns no database schema and has no ORM, no engine and no migrations. Its only table
(`oauth_kv`) belongs to the OAuth state store, which creates it itself — see **State** below.

The layering rule is that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse — and that **only `create_app` constructs a config**,
so nothing downstream can quietly re-read the environment and disagree with the app it runs in.
`tests/test_layering.py` enforces both, and grows as each package arrives.

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

Graph permissions are deliberately not requested yet — they belong to the tools that need them.

**State.** Every token the server issues is a reference token re-validated on each request, so
where that state lives decides whether the deployment survives a restart or a second replica.
FastMCP's default is an encrypted file tree under the process's home directory; this service uses
Postgres instead, in a table (`oauth_kv`) the store creates itself on first use — so the database
user needs `CREATE` on its schema, and there is no migration for it (the columns are the store
library's to define, and a revision duplicating them would be ours to keep in sync). The rows are
encrypted
with a key derived from the client secret, which means rotating that secret costs each signed-in
user one re-login (a failed decryption is treated as a cache miss, not an error).

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
