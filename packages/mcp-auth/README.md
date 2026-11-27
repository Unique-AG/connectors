# mcp-auth

User sign-in for a Python MCP. Zitadel is `mcp_auth.zitadel.create_zitadel_oidc_proxy`, built from
`ZitadelSettings` in `mcp-configs`. Another identity provider is a module next to `zitadel`.

[`guides/auth.md`](../mcp-architecture/guides/auth.md) says which scopes are required, how
`ZITADEL_ORG_ID` is checked, and where the proxy sits in an MCP. `kyckr-mcp` is the caller.

## Install

```toml
dependencies = ["mcp-auth==0.1.0"]

[tool.uv.sources]
mcp-auth = { path = "../../packages/mcp-auth" }
```

The service Dockerfile has to `COPY packages/mcp-auth` before `uv sync`. The scaffold does not
add the package. Add it when the MCP signs users in.
