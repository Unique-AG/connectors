# Auth

[`ARCHITECTURE.md`](../ARCHITECTURE.md) holds the rules this guide works within.

An MCP starts without auth, and `run_server` keeps it on loopback until it has an auth provider.
Adding one:

1. Use what FastMCP provides first: `fastmcp.server.auth` has token verifiers (`JWTVerifier`,
   `StaticTokenVerifier`, introspection), `OAuthProxy`, `OIDCProxy` and, under
   `fastmcp.server.auth.providers`, providers for common identity services. A Zitadel sign-in is
   `unique_mcp.auth.zitadel.create_zitadel_oidc_proxy`, configured by the same environment as
   `ZitadelSettings` from `mcp-configs`. Write code only for what neither provides.
2. Code of our own lives in `mcp/auth/`, exported from its `__init__.py`. `create_server` passes
   the provider to `FastMCP(auth=...)`.
3. The upstream never sees how the user signed in. When it needs the caller's credentials,
   `get_upstream` in `mcp/dependencies.py` reads them, such as with
   `fastmcp.server.dependencies.get_access_token()`, and hands the client either the values
   themselves or a function that returns them, through its constructor. Contexts and
   `upstream/` import nothing from auth, and no token reaches a context.
