# Notion MCP (hosted, mcp.notion.com)

| Field | Value |
|---|---|
| Vendor | Notion; official |
| Category | collaboration |
| Tier | 1 |
| Source | closed (https://mcp.notion.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.notion.com/mcp |
| Uses elicitation | no mention |
| Mechanism | n/a. Deletion is gated by a `user_confirmed` argument plus `destructiveHint`, not by elicitation |
| Evidence type | docs only |

`notion-official.md` covers Notion's open-source server, which is a separate product. This file covers only the hosted server.

## Elicitation usages

The docs don't describe server-initiated prompts. Confirmation before a delete works through a tool argument: the client or model must ask the user and then call the tool again.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `notion-delete-pages` | n/a (argument `user_confirmed: true`) | confirm-destructive | Whether to move up to 20 pages to Trash. "The call must set `user_confirmed: true`." The tool is annotated so that "MCP clients that honor tool annotations ask before running it" | "Without it, nothing is moved to Trash". Trashed items "can be restored with `notion-restore-pages`" | [pages reference](https://developers.notion.com/guides/mcp/tools-pages-reference) |
| `notion-delete-databases` | n/a (argument `user_confirmed: true`, `destructiveHint: true`) | confirm-destructive | Whether to move up to 20 databases, "with all of their rows", to Trash | Without the flag, nothing is trashed and "the error lists the databases and their row counts", which lets the client check with the user first | [databases reference](https://developers.notion.com/guides/mcp/tools-databases-reference) |
| Connecting a client | n/a (client-run OAuth, not described as elicitation) | auth-oauth | "follow the prompts to authorize access to your Notion workspace". Some clients open "your browser to complete the OAuth flow" | A guest "sees a message that guests can't connect, and Notion refuses the authorization" | [get started](https://developers.notion.com/guides/mcp/get-started-with-mcp) |

## Fallback without client elicitation support

Not applicable, because the docs don't describe any use of elicitation. The `user_confirmed` gate works with any client. A client that ignores annotations can still pass `user_confirmed: true` without asking the user, and the docs describe nothing that prevents this.

## Other human-in-the-loop mechanisms

- **Recoverable deletes.** Both delete tools move items to Trash. "Items in Trash can be restored with `notion-restore-pages` or from Trash in Notion." "Locked pages can't be moved to Trash; unlock them in Notion first" ([pages reference](https://developers.notion.com/guides/mcp/tools-pages-reference)).
- **Moves change who can see a page, with no documented confirmation.** For `notion-move-pages`: "People can gain or lose access because moved items inherit access from the new parent" ([pages reference](https://developers.notion.com/guides/mcp/tools-pages-reference)). The docs describe no confirmation for it.
- **Admin tool selection.** "An admin may limit the tools in a workspace-owned connection." `notion-get-tool-access` shows "which tools and options your connection can use" ([tools FAQ](https://developers.notion.com/guides/mcp/tools-faqs)).
- **Client allowlist (Enterprise).** "Admins on the Enterprise plan can manage which MCP clients and AI apps are allowed to connect" and can choose "Approved MCP clients only" ([help center](https://www.notion.com/help/notion-mcp)).
- **Permissions.** "MCP tools act with your full Notion permissions" and "MCP does not bypass Notion permissions" ([help center](https://www.notion.com/help/notion-mcp)).
- **Sign-in without a prompt.** Enterprise workspaces with SAML SSO can use enterprise-managed authorization, where the identity provider grants access "without a consent screen". Business and Enterprise owners can also issue MCP tokens that are sent as bearer tokens, so no browser sign-in is needed ([get started](https://developers.notion.com/guides/mcp/get-started-with-mcp)).
- **Workspace selection.** Authorization gives access to "content that you can access in the selected workspace" ([get started](https://developers.notion.com/guides/mcp/get-started-with-mcp)). The docs don't describe the picker or how several workspaces are handled.
- **Disambiguation.** Docs don't say.

## Notes

- The help center's "your agent asks before it creates or changes anything" ([help center](https://www.notion.com/help/notion-mcp)) refers to a setup prompt. It does not describe a per-tool-call confirmation.
