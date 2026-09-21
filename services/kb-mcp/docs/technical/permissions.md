<!-- confluence-page-id: 2744614980 -->
<!-- confluence-space-key: PUBDOC -->

kb-mcp has no access of its own. It authenticates the caller against Zitadel, then passes that
identity to the Unique API on every call. The Unique API enforces it. A `search`, `content_tree`,
`content_metadata`, or `read_file` result therefore only ever contains knowledge-base content the
calling user could already open in the web app.

This is why kb-mcp requests no knowledge-base scopes: there are none to request. It holds no
service-wide credential that could read another user's content.

## Zitadel Scopes

kb-mcp requests three scopes, all identity-only.

| Scope | Purpose |
|---|---|
| `openid` | Standard OIDC subject claim |
| `profile` | Basic profile claims |
| `urn:zitadel:iam:user:resourceowner` | Resolves the user's owning organisation, which becomes the company id |

`mcp:*` scopes are advertised on the OAuth metadata endpoint but never required: standard OAuth
authorization-server metadata behavior (RFC 8414), not a kb-mcp-specific gap. Zitadel decides
which of them to grant, and a scope it withholds is rejected at the middleware rather than silently
honoured.

## How a Call Is Scoped

Identity is resolved per call from the OIDC session, never from a tool argument. An MCP client
cannot ask kb-mcp to act as somebody else.

On top of that identity, four filters are combined with `AND` before the query reaches the Unique
API:

| Filter | Set by | Optional |
|---|---|---|
| Admin `metadata_filter` (UniqueQL) | Unique admin UI, per tool | Yes |
| Admin `scope_ids` | Unique admin UI, folder allowlist | Yes |
| `folder_ids` | The calling LLM, per call | Yes |
| `metadata_filter` (UniqueQL) | The calling LLM, per call | Yes |

Because the combination is an `AND`, every filter can only ever narrow the result set. An LLM
cannot widen its own reach by supplying a permissive filter, and it cannot reach outside the user's
permissions in the first place: those are enforced upstream, not by these filters.

`content_metadata` is the one exception to the last row: it takes `folder_ids`/`folder_paths` but
no caller `metadata_filter`, only the admin one. It exists to discover what a filter could say, not
to apply one.

!!! note "An empty result is ambiguous"
    A search returning nothing may mean the user has no matching content, or that an admin
    `metadata_filter` excluded it. `content_tree` and `search` return a hint suggesting the caller
    drop its own `metadata_filter` and retry, which distinguishes the two cases.

## Per-User Isolation

`content_tree` and `content_metadata` share one cache, keyed on `(company_id, user_id, folder
scope)`. Two users never share a cache entry, and the cache is per pod. It is not a shared store.

## Related Documentation

- [Architecture](./architecture.md) - components and the authentication flow
- [Flows](./flows.md) - connection and tool-call sequences
- [Tools](./tools.md) - what each tool accepts and returns
- [Configuration](../operator/configuration.md) - environment variable reference
