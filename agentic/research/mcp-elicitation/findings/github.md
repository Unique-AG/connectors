# GitHub MCP Server

| Field | Value |
|---|---|
| Vendor | GitHub; official |
| Category | dev-platform |
| Tier | 1 |
| Source | open (https://github.com/github/github-mcp-server @ 0663b83) |
| Language / SDK | Go, `github.com/modelcontextprotocol/go-sdk` v1.8.0 (go.mod) |
| Hosted endpoint | https://api.githubcopilot.com/mcp/ (remote server; its code is not all in this repo) |
| Uses elicitation | yes |
| Mechanism | both (legacy `elicitation/create` for OAuth on protocol < 2026-07-28; `InputRequiredResult` / `inputRequests` + `requestState` for OAuth on >= 2026-07-28 and for `delete_repository`) |
| Evidence type | code |

## Elicitation usages

Permalink base: `https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/`

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Any tool call on the local stdio server when no token yet (OAuth login middleware), protocol < 2026-07-28, PKCE flow | url | auth-oauth | "Authorize the GitHub MCP Server in your browser to continue." + GitHub authorize URL (PKCE, loopback callback). Server-initiated `elicitation/create`, blocks until the token arrives | `res.Action != "accept"` -> `ErrPromptDeclined`, flow aborts, tool call errors "github authorization failed". A transport error is classified `ErrPromptUnavailable` and degrades to the manual tool-result message | [internal/ghmcp/oauth.go#L42](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/ghmcp/oauth.go#L42), [internal/oauth/flow.go#L143](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/oauth/flow.go#L143) |
| Same, device-code flow (Docker without callback port, headless host) | url | auth-oauth | "Enter code XXXX-XXXX to authorize the GitHub MCP Server." + verification URI | as above | [internal/oauth/flow.go#L188](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/oauth/flow.go#L188) |
| Same, device-code flow, client has form but not URL elicitation | form | auth-oauth (display a device code) | Message only: "Visit <uri> and enter the code <code> ..."; no `requestedSchema` (acknowledge-only form) | as above | [internal/ghmcp/oauth.go#L74](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/ghmcp/oauth.go#L74), [internal/oauth/flow.go#L199](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/oauth/flow.go#L199) |
| Same OAuth middleware, protocol >= 2026-07-28 (SEP-2322: server may not initiate requests) | url (form if no URL cap) | auth-oauth | Returns `CallToolResult{InputRequests: {"github_authorization:<flowID>": ElicitParams}}`; same messages as above. Flow ID in the input-request key correlates the retry | Retry with non-accept -> flow cancelled, text result "GitHub authorization was declined. Retry when you're ready to authorize."; stale flow -> "This GitHub authorization prompt has expired..." | [internal/ghmcp/oauth.go#L186](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/ghmcp/oauth.go#L186), [#L215](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/ghmcp/oauth.go#L215), [#L255](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/ghmcp/oauth.go#L255) |
| `delete_repository` | form | confirm-destructive | Message: `Type "owner/repo" to confirm permanent deletion of this repository.`; schema `{repository_name: string (required), title "Repository name"}`. Returned as `inputRequests["delete_repository_confirmation"]` with sealed `requestState` = {owner, repo, repository_id, expires_at (10 min TTL)} | Non-accept -> tool error "Repository deletion was not confirmed. The repository was not deleted." Typed name mismatch, missing/invalid/expired state, owner/repo changed, or repo id changed since the prompt -> tool error, nothing deleted | [pkg/github/repositories.go#L858](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/pkg/github/repositories.go#L858), [#L880-L921](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/pkg/github/repositories.go#L880-L921) |

## Fallback without client elicitation support

- `delete_repository` is gated, not degraded. It sets `MinimumProtocolVersion = "2026-07-28"` and `RequiredElicitationMode = form` ([repositories.go#L945](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/pkg/github/repositories.go#L945)). A receiving middleware drops it from `tools/list` for clients that negotiated an older protocol or lack form elicitation; a direct `tools/call` returns `isError` "Tool \"delete_repository\" requires client support for form elicitation." or "...requires MCP protocol version 2026-07-28 or later." ([pkg/inventory/tool_availability.go#L102](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/pkg/inventory/tool_availability.go#L102), [#L172](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/pkg/inventory/tool_availability.go#L172)). An empty `elicitation: {}` capability counts as form support. There is no `confirm` argument fallback: older clients simply cannot delete repositories.
- In HTTP mode the tool is also hidden unless `GITHUB_MCP_SERVER_MRTR_STATE_KEY` (32-byte base64 key, shared by all replicas) is set; malformed key refuses startup ([pkg/http/server.go#L283](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/pkg/http/server.go#L283), [docs/streamable-http.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/docs/streamable-http.md)). Stdio uses a random per-process key.
- OAuth login degrades through a fixed ladder: open browser -> URL elicitation -> form elicitation (device code only) -> plain text in the first tool result ("open this URL ... After authorizing, retry your request.") with an appended advisory: "Note: your MCP client does not appear to support secure URL elicitation. For improved security, consider asking your agent, CLI, or IDE to add it" ([internal/oauth/flow.go#L213](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/internal/oauth/flow.go#L213)). Capability is read from `InitializeParams().Capabilities.Elicitation`; a runtime elicitation failure also falls back to the text channel rather than aborting.

## Other human-in-the-loop mechanisms

- `--read-only` flag / `/readonly` remote URLs skip all write tools, even ones named in `--tools` (README).
- `destructiveHint: true` on `delete_repository`; tools carry `readOnlyHint` annotations generally.
- Toolset / tool allowlists (`--toolsets`, `--tools`), and scope-based tool filtering by token scopes.
- `--scope-challenge` (HTTP) returns 403 + `WWW-Authenticate` for insufficient scopes instead of a prompt.

## Notes

- The most complete SEP-2322 implementation in this batch: protocol-version-aware branching between server-initiated elicitation and `InputRequiredResult`, sealed (encrypted, TTL-bound) `requestState`, and re-verification of the repo's numeric ID on the retry to defeat a rename/recreate between prompt and confirm.
- Explicit security rationale for URL mode: keep the auth URL and codes out of the model's context. The text fallback is treated as a weaker channel, hence the advisory nudging users to pressure their client vendor.
- The form-mode OAuth prompt has no schema; it is used as a "show this code, click OK" dialog.
- Elicitation-gated tool hiding is generic (`RequiredElicitationMode` on any `ServerTool`); only `delete_repository` uses it today.
- GitHub App installation auth (`docs/github-app-auth.md`) avoids elicitation entirely for unattended use.
