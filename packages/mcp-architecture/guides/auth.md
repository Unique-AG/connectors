# Auth

[`ARCHITECTURE.md`](../ARCHITECTURE.md) holds the rules this guide works within.

An MCP starts without auth, and `run_server` keeps it on loopback until it has an auth provider.
Adding one:

1. Use what FastMCP provides first: `fastmcp.server.auth` has token verifiers (`JWTVerifier`,
   `StaticTokenVerifier`, introspection), `OAuthProxy`, `OIDCProxy` and, under
   `fastmcp.server.auth.providers`, providers for common identity services. A Zitadel sign-in is
   `unique_mcp.auth.zitadel.create_zitadel_oidc_proxy`, configured by the same environment as
   `ZitadelSettings` from `mcp-configs`; add `unique-mcp` to the MCP's dependencies for it, as
   `architecture-demo-mcp` does. Write code only for what neither provides.
2. Code of our own lives in `mcp/auth/`, exported from its `__init__.py`. `create_server` passes
   the provider to `FastMCP(auth=...)`.
3. The upstream never sees how the user signed in. When it needs the caller's credentials,
   `get_upstream` in `mcp/dependencies.py` reads them, such as with
   `fastmcp.server.dependencies.get_access_token()`, and hands the client either the values
   themselves or a function that returns them, through its constructor. Contexts and
   `upstream/` import nothing from `mcp/auth/`, and no token reaches a context. A type both
   sides need, such as the credentials, is a contract in `shared/` (see [shared](shared.md)).

## Users who sign in with their own upstream credentials

`mcp-scaffold <name> ... --auth credentials` writes this sign-in, and the MCP owns the code. Each
layer holds one part, so none of them reaches past the next:

| Layer | Holds |
|---|---|
| `shared/contracts/auth.py` | What the layers agree on: `UpstreamCredentials`, what the upstream needs per user; `CredentialsProvider`, a function that returns the current call's; the `AuthStore` protocol and the value models it takes and returns. Types only, see [`shared.md`](shared.md) |
| `persistence/auth/` | `SqlAuthStore`, which implements `AuthStore` over the MCP's database, and its tables. Plain columns only, Postgres and SQLite alike; passwords are encrypted with `MCP_AUTH_ENCRYPTION_KEY`, tokens kept as hashes. It imports nothing from `upstream/` or MCP |
| `upstream/credentials.py` | `auth_for`, how a request is signed with `UpstreamCredentials`, and `CredentialsAuth`, which asks a `CredentialsProvider` at send time. `sign_in.py` checks a sign-in with `verify_credentials` at `UPSTREAM_VERIFY_PATH`, which has no default: only a 2xx there signs the user in, so it must be a path that answers 401 or 403 to wrong credentials, never a public page |
| `upstream/client.py` | The client takes a `CredentialsProvider` in its constructor, or None, and signs each request with it. A custom client's `request` takes one too, in place of its own, and `current_credentials()` says whose a request would carry. An OpenAPI client signs on its shared HTTP client, so the operations served straight from the spec act as the caller as well |
| `mcp/auth/` | `CredentialsAuthProvider`, the OAuth server the clients use, on `AuthStore`: registration, the `/sign-in` page, codes, rotating refresh tokens. Each access token names the user as its subject, which FastMCP keeps for the call. `caller_credentials` is the `CredentialsProvider` that reads the subject and asks the store |
| `mcp/server.py` | The one place that knows the store is `SqlAuthStore`: it hands the store to the provider and `caller_credentials` to the upstream |
| `mcp/dependencies.py` | `get_credentials`, the caller's `CredentialsProvider` for a tool that hands a request credentials of its own. `Upstream` from `get_upstream` already signs with them |
| `contexts/` | Nothing. A context calls `Upstream` as before and never sees a token or a credential |

To send more than a username and password, such as an account id, add the field to
`UpstreamCredentials`, a column to `persistence/auth/tables.py` with a migration and to what
`SqlAuthStore` saves and reads, and an input to the sign-in form in
`mcp/auth/pages/login.html`. To keep an upstream session instead of the password, change what
`SqlAuthStore.save_credentials` keeps and what its `get_credentials` returns: the contract and
the upstream stay as they are.
