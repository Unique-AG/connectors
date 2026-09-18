<!-- confluence-space-key: PUBDOC -->

## Overview

The Knowledge Base MCP Server (`kb-mcp`) gives MCP clients access to a tenant's Unique knowledge
base: semantic/internal search, browsing the content tree, and reading file content by id. It is a
stateless, read-only proxy: every tool call queries the Unique API (`node-chat`) live, and nothing
is written back into the knowledge base.

Authentication is its own OIDC flow against Zitadel (a public PKCE client, no client secret),
independent of the platform's normal Kong-fronted authentication. Deployed instances call
`node-chat` directly in-cluster, bypassing the Kong hairpin where possible.

For deployment, configuration, and operational details, see the
[IT Operator Guide](./operator/README.md). For the full tool reference and architecture, see the
[Technical Reference](./technical/README.md).

## Quick Summary

**What it does:** Exposes three MCP tools (`search`, `content_tree`, `read_file`) over a tenant's
Unique knowledge base, backed live by the Unique API.

**Deployment:** Kubernetes-based Python (FastMCP) microservice, shipped as a standalone Helm chart;
also runnable via Docker outside Unique's own clusters.

**Authentication:** MCP-facing OAuth2/OIDC via Zitadel (PKCE, no client secret). Identity is derived
from that session and passed through to the Unique API, which enforces it. Every tool call runs
under the calling user's own permissions, so `search`, `content_tree`, and `read_file` only ever
return knowledge-base content that user could already see.

**Processing:** Synchronous. Each tool call queries the Unique API and returns immediately.
`content_tree`'s folder/file listing is the only thing kb-mcp caches, in-memory and per pod;
search results and file content are never cached.

## Tools

| Tool | Purpose |
|------|---------|
| `search` | Semantic / internal knowledge-base search |
| `content_tree` | Browse, list, and fuzzy-search visible folders and files |
| `read_file` | Download and return file content by `content_id` |

Which tools are advertised on `/mcp` is configurable per deployment
(`mcpConfig.enabledTools` / `KB_MCP_ENABLED_TOOLS`), see
[Tools](./technical/tools.md).

## Related Documentation

### For Users
- [User Guide](./user-guide.md)
- [Connecting Clients](./connecting.md)

### For IT Operators
- [Deployment](./operator/deployment.md)
- [Configuration](./operator/configuration.md)

### Technical Reference
- [Architecture](./technical/architecture.md)
- [Flows](./technical/flows.md)
- [Permissions](./technical/permissions.md)
- [Tools](./technical/tools.md)

## Standard References

- [Model Context Protocol specification](https://modelcontextprotocol.io/)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [`unique-mcp` on PyPI](https://pypi.org/project/unique-mcp/)
- [`unique-toolkit` on PyPI](https://pypi.org/project/unique-toolkit/)
