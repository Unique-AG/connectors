# Supabase MCP (hosted, mcp.supabase.com)

| Field | Value |
|---|---|
| Vendor | Supabase; official (hosted service; the open code is reviewed in `supabase.md`) |
| Category | dev-platform |
| Tier | 3 |
| Source | closed view (https://mcp.supabase.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.supabase.com/mcp |
| Uses elicitation | yes (explicit in docs) |
| Mechanism | docs don't say which wire mechanism. The docs link the [2026-07-28 elicitation spec page](https://modelcontextprotocol.io/specification/2026-07-28/client/elicitation) and name form and URL modes |
| Evidence type | docs only |

Sources:
- [Supabase MCP Server](https://supabase.com/docs/guides/ai-tools/mcp) ("MCP doc"), sections Elicitations, Configuration options, Security risks
- KB: [Cost confirmations do not appear in your MCP client](https://supabase.com/kb/troubleshooting/cost-confirmations-do-not-appear-in-your-mcp-client-mVq3Lp)

## Elicitation usages

"Elicitation lets an MCP server pause a tool call to ask you for input or confirmation. These flows require both server availability and an MCP client that supports the appropriate elicitation mode" (MCP doc, Elicitations).

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `create_project`, `create_branch` | form | confirm-cost | Client "displays the resource, the standard rate, and the billing interval, along with controls to accept or decline". A project quoted at zero cost gets no prompt. A branch is always confirmed at "the standard rate before any allowances or exemptions" | "Declining or dismissing the confirmation creates nothing, and the agent receives a result that it can relay to you." Confirmations expire ("If one expires, nothing is created"). Cost is re-checked before creation, and a changed nonzero cost gets a fresh confirmation | MCP doc, [Cost confirmation](https://supabase.com/docs/guides/ai-tools/mcp#cost-confirmation) |
| `execute_sql`, `apply_migration` when destructive SQL is detected | form | confirm-destructive | Docs don't give the form fields. `execute_sql` asks "only outside read-only mode". "SQL not classified as destructive proceeds without this additional warning" | docs don't say | MCP doc, [Destructive SQL confirmations](https://supabase.com/docs/guides/ai-tools/mcp#destructive-sql-confirmations) |
| `run_notebook` when selected database cells contain "statements other than plain reads" | form | confirm-destructive | "The form shows how many cells modify data or schema and how many are destructive." Changing the notebook or cells after approval triggers a new prompt | docs don't say | MCP doc, [Notebook confirmations](https://supabase.com/docs/guides/ai-tools/mcp#notebook-confirmations) |
| `delete_notebook` | form | confirm-destructive | "shows the notebook name and asks before deleting it for everyone with access to the project. Deletion cannot be undone." | docs don't say | same |
| `create_edge_function_secret` | url | secret-input | The tool takes the secret name and project, never the value. The user opens "the Supabase Dashboard URL presented by your MCP client", saves the value there, then confirms in the client | "If you cancel the request, this does not undo a secret you already saved in the Dashboard." | MCP doc, [Edge Function secrets](https://supabase.com/docs/guides/ai-tools/mcp#edge-function-secrets) |

Not covered by any documented elicitation: `pause_project`, `delete_branch`, `reset_branch`, `merge_branch`, `rebase_branch`, `deploy_edge_function`, `update_storage_config`, `delete_feedback`. Disambiguation (e.g. which project or organization) is not described as an elicitation. The organization is chosen at sign-in: "Be sure to choose the organization that contains the project you wish to work with."

## Fallback without client elicitation support

Each flow falls back differently (MCP doc):
- **Cost.** Falls back to the legacy two-step flow: "the agent quotes the cost in chat, uses `get_cost` and `confirm_cost`, and passes the returned `confirm_cost_id` to `create_project` or `create_branch`". These helpers are hidden in project-scoped connections. The KB says: "the agent quotes the cost in chat and asks you before creating the resource. No dialog appears, and this is the expected behavior."
- **Destructive SQL.** "SQL follows the existing execution path without an additional MCP confirmation". The query runs without a prompt.
- **Notebooks.** No silent fallback: "If your client does not support forms, `run_notebook` refuses cells that need confirmation and `delete_notebook` refuses to delete." The user is told to use read-only mode or the Dashboard instead.
- **Secrets.** The tool is offered only when the client supports URL elicitation (plus Edge Functions enabled, not read-only, and secret read/write permission).
- **Opt-out.** `?skip_elicitations=<tools>` turns off form confirmations per tool (`create_project`, `create_branch`, `execute_sql`, `apply_migration`, `run_notebook`, `delete_notebook`). There is "no boolean or `all` switch". Skipping cost confirmation "retains the legacy cost confirmation workflow". Skipping SQL or notebook confirmation "runs those tools without an additional MCP confirmation". Secret entry can't be skipped.

## Other human-in-the-loop mechanisms

- **Client approval stays primary.** "Server elicitation is separate from your MCP client's own approval of tool calls. It does not replace manual approval". "Keep manual approval enabled for interactive work". "Treat elicitations as a guardrail, not a guarantee of human review or approval. Some clients support hooks or rules that answer elicitations automatically." (MCP doc).
- **Read-only mode.** `?read_only=true` runs every query "as a read-only Postgres user", refuses `create_notebook`/`delete_notebook`, and disables the Feedback group.
- **Scoping.** `?project_ref=` limits the connection to one project and turns off account tools. `?features=` limits tool groups (Storage is off by default).
- **Sign-in.** Browser OAuth with dynamic client registration. The user grants access to an organization.
- **Unattended use.** "Approve in advance only the project-scoped, read-only tools that the routine needs. The routine must stop and report a recommendation instead of running a write operation."
- **Prompt-injection wrapping.** SQL results come wrapped "with additional instructions to discourage LLMs from following instructions" in data.

## Notes

- The hosted docs describe the same four uses as the open code: cost, destructive SQL, notebooks, and secret entry via the Dashboard. They also spell out what happens when the client lacks support, and the per-tool `skip_elicitations` opt-out.
- The docs say availability depends on "server availability" and "account feature settings". The same connection can use form-based cost confirmation for one resource type and the legacy flow for another.
- Fallbacks differ by risk. Cost falls back to a two-step chat flow. SQL runs without a prompt. Notebooks refuse.
