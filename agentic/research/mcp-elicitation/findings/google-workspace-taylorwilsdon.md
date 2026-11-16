# Google Workspace MCP (taylorwilsdon)

| Field | Value |
|---|---|
| Vendor | taylorwilsdon; community (not Google) |
| Category | collaboration |
| Tier | 2 |
| Source | open (https://github.com/taylorwilsdon/google_workspace_mcp @ 43b662a) |
| Language / SDK | Python, FastMCP 4.1.4 on `mcp` 2.3.0 (uv.lock); pyproject pins `fastmcp>=4.1.2` |
| Hosted endpoint | none (self-hosted; stdio or streamable HTTP; Helm chart in repo) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none | – | – | – | – | Grep for `elicit`, `requestedSchema`, `InputRequired`, `input_requests`, `ctx.elicit`, `client_capabilities` finds nothing. The `request_state` hits are FastMCP's `Context._request_state`, used to scope identity per request ([request_identity.py#L5](https://github.com/taylorwilsdon/google_workspace_mcp/blob/43b662a938ef002626ac269451c469b91979bd9a/auth/request_identity.py#L5)), not SEP-2322. |

## Fallback without client elicitation support

Not applicable. The server never asks the user anything mid-call.

## Other human-in-the-loop mechanisms

- **OAuth through tool text instead of URL-mode elicitation.**
  - In legacy OAuth 2.0 mode, a tool that needs credentials, or the `start_google_auth` tool, returns a markdown block that starts "**ACTION REQUIRED: Google Authentication Needed…**". It carries the authorization URL and tells the model to "retry their original command" ([google_auth.py#L676-L713](https://github.com/taylorwilsdon/google_workspace_mcp/blob/43b662a938ef002626ac269451c469b91979bd9a/auth/google_auth.py#L676-L713), [server.py#L1100-L1110](https://github.com/taylorwilsdon/google_workspace_mcp/blob/43b662a938ef002626ac269451c469b91979bd9a/core/server.py#L1100-L1110)).
  - When the email is unknown, the message says "**LLM: Instruct the user to provide you with this email address.**". The model is used as a fill-missing-param channel, which a form elicitation would otherwise do.
  - Under stdio the server also tries `webbrowser.open`.
  - In OAuth 2.1 mode the MCP client's own OAuth handles sign-in, and `start_google_auth` is disabled.
- **Read-only mode.** `--read-only` / `WORKSPACE_MCP_READ_ONLY` asks for read-only scopes only and drops write tools ([tool_registry.py#L160-L177](https://github.com/taylorwilsdon/google_workspace_mcp/blob/43b662a938ef002626ac269451c469b91979bd9a/core/tool_registry.py#L160-L177)).
- **Scope-based permissions.**
  - `--permissions service:level` grants scopes per service. Gmail has the levels readonly, organize, drafts, send and full ([main.py#L577-L590](https://github.com/taylorwilsdon/google_workspace_mcp/blob/43b662a938ef002626ac269451c469b91979bd9a/main.py#L577-L590)).
  - With these levels an operator can allow drafting mail but not sending it.
- **Tool selection.** `--tools` and `--tool-tier` decide which tools are loaded.
- **Annotations.** Every tool has explicit `ToolAnnotations`: 38 have `destructiveHint=True`, for example `send_gmail_message` ([gmail_tools.py#L2602-L2613](https://github.com/taylorwilsdon/google_workspace_mcp/blob/43b662a938ef002626ac269451c469b91979bd9a/gmail/gmail_tools.py#L2602-L2613)), and 52 have `readOnlyHint=True`.
- **Draft as an alternative to sending.** `draft_gmail_message` exists. Nothing makes a draft step mandatory, and no tool takes a confirm argument.

## Notes

- This is the only server in the batch already on the `mcp` 2.x Python SDK and FastMCP 4. It still uses neither `ctx.elicit` nor the 2026-07-28 `InputRequiredResult`.
- The "ACTION REQUIRED + URL + retry" text is a model-mediated stand-in for URL-mode elicitation, so it works on any client.
