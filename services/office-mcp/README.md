# office-mcp

An MCP server for Microsoft 365 via the Microsoft Graph API.

Users sign in with their own Microsoft account. The server acts as them. No MCP tools are exposed
yet. The Microsoft Graph client and feature packages land in later PRs on top of this one.

## Layout

```
src/office_mcp/
  app.py                 composition root — config and collaborators built once
  config.py              one BaseSettings class per concern
  auth.py                Entra auth: app registration and state location
  logging.py metrics.py  cross-cutting utilities
  features/              connector features — populated in later PRs
  server/                MCP surface — /ready probe today, tools in later PRs
```

This service owns no database schema, ORM, engine, or migrations. Its only table (oauth_kv)
belongs to the OAuth state store, which creates it itself (see **State** below).

Layering rules: **features/ must not import server/** (the server wires features, not the
reverse), and **only create_app constructs a config** (so nothing can quietly re-read the
environment). `tests/test_layering.py` enforces both.

## Auth

Microsoft Entra via FastMCP's `AzureProvider`. This service holds no OAuth code. The provider is
an OAuth 2.1 proxy that owns /authorize, PKCE on both hops, the redirect callback, refresh, and
the On-Behalf-Of exchange. `auth.py` only chooses which app registration and state store to use.

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

Graph permissions are not requested yet—they belong in the tools that need them.

**State.** Every token is a reference token re-validated on each request. State location decides
whether the deployment survives a restart or a second replica. FastMCP defaults to an encrypted
file tree in the process home directory. This service uses Postgres instead, in a table (oauth_kv)
the store creates itself on first use. The database user needs CREATE on its schema. No migration
exists because the columns are the store library's to define and keep in sync — a revision
duplicating them would be ours to keep in sync, which breaks when the library changes its schema.
Rows are encrypted with a key derived from the client secret. Rotating the secret costs each
signed-in user one re-login (decryption failure is treated as a cache miss, not an error).

## Run locally

```bash
cd services/office-mcp
cp .env.example .env   # fill DB_* and ENTRA_*
uv sync
uv run office-mcp
```

No migration step needed. The database needs an empty schema the app user can CREATE in. The
OAuth store creates its table on first use.

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

Integration tests start a Postgres container (Docker must be running). Nothing is applied to it.
The app under test creates the one table it needs, as in production.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
