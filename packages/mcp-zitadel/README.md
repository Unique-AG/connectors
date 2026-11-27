# mcp-zitadel

Zitadel sign-in for a Python MCP. `create_zitadel_oidc_proxy` builds the OIDC proxy from
`ZitadelSettings` in `mcp-configs`.

[`guides/auth.md`](../mcp-architecture/guides/auth.md) says which scopes are required, how
`ZITADEL_ORG_ID` is checked, and where the proxy sits in an MCP. `kyckr-mcp` is the caller.

## Install

```toml
dependencies = ["mcp-zitadel==0.1.0"]

[tool.uv.sources]
mcp-zitadel = { path = "../../packages/mcp-zitadel" }
```

The service Dockerfile has to `COPY packages/mcp-zitadel` before `uv sync`. The scaffold does not
add the package. Add it when the MCP signs users in with Zitadel.
