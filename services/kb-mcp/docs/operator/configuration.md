<!-- confluence-page-id: 2744582189 -->
<!-- confluence-space-key: PUBDOC -->

## Configuration

`kb-mcp` reads its deployment configuration from environment variables. In Helm deployments most map
onto typed values under `mcpConfig`. See `values.schema.json` for field-level descriptions and
[Minimal Values](./deployment.md#Minimal-Values).

Tool behavior is configured separately: per-tool environment variables are documented with the
tools they affect in [Tools](../technical/tools.md). Business rules per tool are configured
differently, see Admin Configuration below.

### Admin Configuration

Business rules per tool, a `metadata_filter`, a folder allowlist, a result `limit`, live in one of
two places depending on who's calling.

#### Unique AI

Injected into every call automatically from the admin's settings in the Unique AI app. Nothing to
set here; changes take effect immediately, no restart.

#### Other Clients

A standalone deployment, Claude Desktop, Cursor: no app to inject settings, so each tool falls back
to an environment variable instead, a JSON object shaped like that tool's config. Only the fields
you set need to appear; anything left out keeps its own class default, and the variable left unset
keeps all of them.

##### `search`

`UNIQUE_MCP_TOOL_SEARCH_TOOL_CONFIG`
([`config.py`](https://github.com/Unique-AG/connectors/blob/main/services/kb-mcp/src/kb_mcp/tools/search/config.py))

Top-level defaults (`post_processing.chunk_relevancy_sort_config`'s own LLM-selection fields are
omitted here; it's disabled by default):

```json
{"service_config": {"search": {"search_type": "COMBINED", "search_language": "english", "max_search_strings": 10}, "filtering": {"score_threshold": 0.0, "limit": 200}, "scope_ids": null, "metadata_filter": {"operator": "isNotNull", "value": "", "path": ["folderId"]}, "reranker_config": null}, "post_processing": {"chunk_relevancy_sort_config": {"enabled": false}, "max_tokens_for_sources": 30000, "percentage_of_input_tokens_for_sources": 0.4, "chunked_sources": true, "metadata_chunk_sections": {}}}
```

##### `content_tree`

`UNIQUE_MCP_TOOL_CONTENT_TREE_TOOL_CONFIG`
([`config.py`](https://github.com/Unique-AG/connectors/blob/main/services/kb-mcp/src/kb_mcp/tools/content_tree/config.py))

Defaults:

```json
{"metadata_filter": null, "default_limit": 50, "default_tree_limit": 1000, "default_min_score": 0.6, "default_match_on": "both", "default_case_sensitive": false, "max_concurrent_scope_lookups": 25}
```

##### `content_metadata`

`UNIQUE_MCP_TOOL_CONTENT_METADATA_TOOL_CONFIG`
([`config.py`](https://github.com/Unique-AG/connectors/blob/main/services/kb-mcp/src/kb_mcp/tools/content_metadata/config.py))

Defaults:

```json
{"metadata_filter": null, "excluded_fields": ["key", "url", "title", "folderId", "mimeType", "companyId", "contentId", "validAsOf", "folderIdPath", "externalFileOwner"], "max_concurrent_scope_lookups": 25}
```

`excluded_fields` replaces this list rather than adding to it: repeat the entries above alongside
any of your own, or the catalog narrows to just what you passed.

##### `read_file`

`UNIQUE_MCP_TOOL_READ_FILE_TOOL_CONFIG`
([`config.py`](https://github.com/Unique-AG/connectors/blob/main/services/kb-mcp/src/kb_mcp/tools/read_file/config.py))

Default:

```json
{"max_tokens_per_call": 8000}
```

### Required

| Variable | Description |
|---|---|
| `UNIQUE_MCP_PUBLIC_BASE_URL` | Public URL MCP clients and OAuth use; must match `routes.hostname` |
| `UNIQUE_API_BASE_URL` | Base URL of the Unique API this instance calls |
| `ZITADEL_BASE_URL` | Zitadel instance base URL |
| `ZITADEL_CLIENT_ID` | Public PKCE client id, not a secret. In Helm, set `mcpConfig.zitadel.clientId` instead; the chart emits this variable from it |
| `ZITADEL_JWT_SIGNING_KEY` | Signs `kb-mcp`'s own downstream OAuth-proxy JWTs; never sent to Zitadel |
| `DATABASE_URL` | Postgres connection string for OAuth-proxy state |
| `ENCRYPTION_KEY` | Encrypts that state at rest |

`ZITADEL_JWT_SIGNING_KEY` and `ENCRYPTION_KEY` are both `openssl rand -hex 32`. They are unrelated:
one signs tokens, the other protects stored data.

`DATABASE_URL` and `ENCRYPTION_KEY` must be set together. Setting one without the other fails at
startup rather than falling back.

`DATABASE_URL` is always delivered as a Kubernetes secret, never a plaintext value, regardless of
which Postgres you're pointing at: `url.fromSecret` against the secret your own CloudNativePG
`Cluster` generates for an in-cluster database, or one you create yourself for an external one.
The chart neither creates nor owns that secret either way. See
[PostgreSQL](../operator/deployment.md#PostgreSQL) for both paths.

!!! warning "Rotating a secret logs everyone out"
    Changing `ENCRYPTION_KEY` makes every token already stored in Postgres undecryptable.
    Changing `ZITADEL_JWT_SIGNING_KEY` invalidates every downstream JWT `kb-mcp` has already issued.
    Either one forces every connected client to reconnect and sign in again; neither has a
    migration path.

### Optional

| Variable | Default | Description |
|---|---|---|
| `UNIQUE_MCP_FRONTEND_BASE_URL` | none | Web app origin for citation deep links. Without it, citations fall back to `unique://content/{id}` |
| `UNIQUE_MCP_LOCAL_BASE_URL` | `http://0.0.0.0:8000` (chart) | Bind address inside the pod |
| `LOG_LEVEL` | `info` | `DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL` |
| `KB_MCP_HTTP_MAX_CONNECTIONS` | `100` | Outbound pool to the Unique API, shared by all tools |
| `KB_MCP_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `20` | Keepalive connections in that pool |
| `KB_MCP_HTTP_POOL_TIMEOUT_SECONDS` | `60` | Pool checkout timeout, not request duration |
| `MEMORY_TRIM_INTERVAL_SECONDS` | `120` | Periodic glibc `malloc_trim` (Docker/Linux only); keeps RSS near the tested limit |
| `OTEL_SERVICE_NAME` / `OTEL_TRACES_EXPORTER` / `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | Opt-in OpenTelemetry tracing |

!!! warning "Required under a default-deny network policy"
    Set `FASTMCP_CHECK_FOR_UPDATES: "off"`. FastMCP otherwise pings `pypi.org` on startup and hangs
    when egress is blocked.

### Never Set in Production

| Variable | Why |
|---|---|
| `ALLOW_EPHEMERAL_OAUTH_STORAGE` | Replaces Postgres with a per-process file store. Every user is logged out on restart, and replicas do not share state |
| `UNIQUE_AUTH_COMPANY_ID` / `UNIQUE_AUTH_USER_ID` | Bypass OIDC entirely. Deployed identity always comes from the Zitadel session |
