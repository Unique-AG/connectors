<!-- confluence-page-id: 2744352825 -->
<!-- confluence-space-key: PUBDOC -->

## Tools

kb-mcp advertises up to four MCP tools on `/mcp`. `KB_MCP_ENABLED_TOOLS` (env) or
`mcpConfig.enabledTools` (Helm) narrows the set; unset means all four. A restart is required.

Each tool also carries an admin configuration set in the Unique admin UI, not through environment
variables. Admin values are the floor: a caller may narrow them, never widen them. See
[Permissions](./permissions.md).

### `search`

Semantic and internal search over the knowledge base.

| Argument | Purpose |
|---|---|
| `search_string` | The query |
| `folder_ids`, `include_subfolders` | Restrict to folders; subfolders included by default |
| `metadata_filter` | UniqueQL narrowing, AND-ed with the admin filter |
| `limit`, `score_threshold` | Override the admin defaults for this call |

`KB_MCP_SEARCH_SCOPE_LOOKUP_CONCURRENCY` (default `8`) bounds the parallel scope lookups used to
build citation links.

### `content_tree`

Browses, lists, and fuzzy-searches the folders and files visible to the caller. `mode` picks the
view; only that mode's arguments apply, and passing one that doesn't (e.g. `query` under
`mode='tree'`) is a tool error, not a silent no-op.

| Argument | Applies to | Purpose |
|---|---|---|
| `mode` | all (required) | `tree` for an overview, `list` for a flat listing, `search` for fuzzy filename/path lookup |
| `folder_path` | all | Scope the walk to this folder and everything under it: a path (`Contracts/2024`) or a `scope_xxx` id. Scoping the walk, not filtering it afterward, is what makes a folder-scoped call fast |
| `max_depth` | `tree` | Maximum folder depth to render (1 = top-level only) |
| `folders_only` | `tree` | Omit files, showing just the folder structure (like `tree -d`) |
| `query` | `search` (required) | Fuzzy text to match against file names and/or paths |
| `match_on` | `search` | Match against the file name (`key`), the full path (`path`), or both |
| `case_sensitive` | `search` | Whether fuzzy matching is case-sensitive |
| `min_score` | `search` | Minimum fuzzy-match score in `[0.0, 1.0]`; higher is stricter |
| `limit` | all | Maximum files/matches to return; in `mode='tree'` it caps what's rendered, and the output says so when it truncated |
| `refresh` | all | Drop this caller's cached tree and refetch (~20s); use when the user reports added/deleted/changed files |
| `timeout` | all | Seconds to wait before returning a partial tree; the walk continues in the background |
| `metadata_filter` | all | UniqueQL narrowing, AND-ed with the admin filter (see [Permissions](./permissions.md)) |

Admin defaults: `limit` 50 (1000 for `mode='tree'`), `min_score` 0.6, `match_on` `both`, and a
filter excluding `user-memory` folders.

!!! note "Incomplete vs. truncated"
    Incomplete means the walk is still running; calling again with the same arguments usually
    finishes it. Truncated means the walk finished and `mode='tree'` capped the result at `limit`;
    calling again returns the same thing, raise `limit` or narrow `folder_path` instead.

The walk can outlast one call. `KB_MCP_WALK_TIMEOUT_SECONDS` (default `30`) is when a
partial tree is returned rather than blocking; the walk continues, so a follow-up is usually
instant. `KB_MCP_WALK_MAX_TIMEOUT_SECONDS` (default `45`) caps what a caller may request.
Keep it under the MCP client's own budget, typically 60s.

Responses are cached in memory per pod, keyed on company, user, and the requested folder scope, so
a folder-scoped walk and an unscoped one never share an entry: `KB_MCP_TREE_CACHE_TTL_SECONDS`
(default `600`), `KB_MCP_TREE_CACHE_MAX_ENTRIES` (default `24`, across all callers and folder
scopes). A caller's own `metadata_filter` no longer forces a second walk: only the admin filter is
baked into the cached walk, the caller's is applied to it afterward. `refresh=true` bypasses the
cache for the caller's next call, at the cost of a slower (~20s) refetch. This cache is shared with
`content_metadata`, below.

!!! note "Multi-replica staleness"
    Because the cache is per pod, a change can take up to the TTL to appear. Lower the TTL if that
    matters more than cache-hit rate.

### `content_metadata`

Discovers what metadata fields and values exist on the knowledge base's visible content, so a
caller can build a `metadata_filter` for `search` or `content_tree` instead of guessing one.
Returns every known field with its distinct values, e.g. `[{"department": ["Legal", "Finance"]}]`.

| Argument | Purpose |
|---|---|
| `folder_ids` | Restrict the catalog to these folders; a `scope_xxx` id from `content_tree`'s output |
| `folder_paths` | Same, by exact path (e.g. `Contracts/2024`) instead of an id; mutually exclusive with `folder_ids` |
| `include_subfolders` | Whether the catalog includes files in subfolders (default `true`) |
| `refresh` | Drop this caller's cached snapshot and rescan (~20s) |
| `timeout` | Seconds to wait before returning a partial catalog |

Exhaustive by design: every known field and value in scope, not a sample, with no pagination yet.
Eight system fields (`key`, `title`, `folderId`, `mimeType`, `companyId`, `contentId`,
`validAsOf`, `folderIdPath`) are excluded by default since they're not something a caller would
filter on; admin-configurable. Unlike `search` and `content_tree`, it takes no caller
`metadata_filter`: only the admin one applies, since the tool exists to discover what a filter
could say, not to apply one.

Shares `content_tree`'s walk and cache entirely, described above: both tools are just different
views over the same visible-file snapshot.

### `read_file`

Returns file content by `content_id`, as surfaced by `content_tree` or `search`.

`max_tokens_per_call` (admin default `8000`) bounds one response. Larger files are split into
virtual pages of that size, selected with `start_page` and `end_page`. A caller may request fewer
tokens; a larger request is clamped without error.

## Related Documentation

- [Permissions](./permissions.md) - how admin and caller filters combine
- [Flows](./flows.md) - what happens during a tool call
- [Configuration](../operator/configuration.md) - deployment environment variables
