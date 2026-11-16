# P4 MCP Server (Perforce)

| Field | Value |
|---|---|
| Vendor | Perforce Software; official |
| Category | dev-platform |
| Tier | 3 |
| Source | open (https://github.com/perforce/p4mcp-server @ 808b328) |
| Language / SDK | Python, `fastmcp==3.4.4` (requirements.txt), MCP Python SDK transitively |
| Hosted endpoint | none (local stdio, or self-run HTTP / Docker) |
| Uses elicitation | yes |
| Mechanism | legacy `elicitation/create` request (via FastMCP `ctx.elicit`) |
| Evidence type | code |

## Elicitation usages

Permalink base: `https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/`

One shared helper, `handle_modify_with_delete_gate`, gates every `delete` / `obliterate` action. It is called from eight write tools.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `modify_changelists` action=`delete` | form | confirm-destructive | Message "⚠️ This action is irreversible. Do you want to continue?"; schema one field `select_one: enum ["PROCEED","CANCEL"]` whose title is the per-tool text, here "Requires approval to delete changelist: <id>" | Anything other than accept + PROCEED returns `{"status":"cancelled","message":"Operation cancelled by user."}` (not an error), nothing runs | [p4mcp/tools/common.py#L74](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/common.py#L74), [#L92](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/common.py#L92), [changelist_tools.py#L101](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/changelist_tools.py#L101) |
| `modify_files` action=`delete` | form | confirm-destructive | Same; title "Requires approval to delete files: <paths>" | same | [file_tools.py#L123](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/file_tools.py#L123) |
| `modify_shelves` action=`delete` | form | confirm-destructive | title "Requires approval to delete shelve for changelist: <id>" | same | [shelve_tools.py#L85](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/shelve_tools.py#L85) |
| `modify_workspaces` action=`delete` | form | confirm-destructive | title "Requires approval to delete workspace: <name>" | same | [workspace_tools.py#L113](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/workspace_tools.py#L113) |
| `modify_streams` action=`delete` | form | confirm-destructive | title "Requires approval to delete stream: <name>" | same | [stream_tools.py#L343](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/stream_tools.py#L343) |
| `modify_reviews` action=`obliterate` | form | confirm-destructive | title "Requires approval to obliterate review: <id>" | same | [review_tools.py#L374](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/review_tools.py#L374) |
| `delete_p4dam_asset_bundle` | form | confirm-destructive | title "Delete asset bundle: <id>" | same | [p4dam_tools.py#L711](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/p4dam_tools.py#L711) |
| `delete_p4dam_file_review` | form | confirm-destructive | title "Delete file review: <id>" | same | [p4dam_tools.py#L913](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/p4dam_tools.py#L913) |

The confirmation is a required enum rather than a boolean or an action-only form, so a client that auto-accepts with empty content still fails the `select_one == "PROCEED"` check.

## Fallback without client elicitation support

Fail-open, and it depends on the error code the client sends back. The server never checks the client's `elicitation` capability. It always sends `elicitation/create` (FastMCP 3.x `Context.elicit` does not check either) and catches `McpError`:

- `METHOD_NOT_FOUND` (-32601): the delete runs **without confirmation** ([common.py#L87-L89](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/common.py#L87-L89)). This is what a TypeScript-SDK client with no elicitation handler returns.
- Any other error is re-raised, and the tool call fails. The Python SDK `ClientSession` with no elicitation callback answers `INVALID_REQUEST` (-32600) "Elicitation not supported", so a Python client gets an error and nothing is deleted.

## Other human-in-the-loop mechanisms

- `--readonly` CLI flag: write tools (every `modify_*` and `delete_*`) are not registered ([file_tools.py#L79](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/tools/file_tools.py#L79)). The README says "Read-only mode by default", but the argparse default is `False` ([main.py#L34](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/main.py#L34)). Every sample config passes `--readonly` explicitly.
- `--toolsets` allowlist, and tools tagged `read` / `write`.
- Server-side admin control through P4 properties (`mcp.enabled`, `mcp.toolsets.write`, `mcp.toolsets.allowed`, `mcp.toolset.<x>.write`), enforced by `CheckPermissionMiddleware` ([check_permission.py#L75](https://github.com/perforce/p4mcp-server/blob/808b328599cbe40fd632b460997e42a35fd441d1/p4mcp/middleware/check_permission.py#L75)).
- Ownership checks before delete operations (README).
- No `readOnlyHint` / `destructiveHint` annotations. Only FastMCP `tags`.

## Notes

- The fallback on `METHOD_NOT_FOUND` is an explicit design choice: when the client cannot be asked, the destructive action goes ahead. Before the elicitation, the server logs a `{"status":"warning", ...}` record, but the caller never sees it.
- The gate is per action value inside a multi-action tool (`modify_files` also does add/edit/sync), not per tool. It is a good example of confirming only the destructive branch of a CRUD tool.
- `modify_files` `delete` is `p4 delete`, which only opens files for delete in a pending changelist. It can be reverted, but it is still gated the same way as `obliterate`.
