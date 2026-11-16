# Slack MCP Server (korotovsky)

| Field | Value |
|---|---|
| Vendor | korotovsky; community (not Slack) |
| Category | collaboration |
| Tier | 1 |
| Source | open (https://github.com/korotovsky/slack-mcp-server @ b88c0de) |
| Language / SDK | Go, `github.com/mark3labs/mcp-go` v0.44.0 (go.mod) |
| Hosted endpoint | none (self-hosted; stdio, SSE or HTTP; Docker/npm/DXT) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none | – | – | – | – | Grep for `elicit`, `Elicit`, `requestedSchema`, `InputRequired`, `input_requests`, `request_state` finds nothing anywhere in the repo. |

## Fallback without client elicitation support

Not applicable. The server never asks the user anything mid-call and checks no client capabilities.

## Other human-in-the-loop mechanisms

- **Posting is off by default.**
  - `conversations_add_message` is registered only when `SLACK_MCP_ADD_MESSAGE_TOOL` is set, or when the tool is named in `SLACK_MCP_ENABLED_TOOLS` ([server.go#L97-L114](https://github.com/korotovsky/slack-mcp-server/blob/b88c0de3f706f4f07337c9eda7133c736d1c9524/pkg/server/server.go#L97-L114), [server.go#L179-L183](https://github.com/korotovsky/slack-mcp-server/blob/b88c0de3f706f4f07337c9eda7133c736d1c9524/pkg/server/server.go#L179-L183)).
  - If it is called while disabled, the handler returns an error that explains how to turn it on, "to guard Slack workspaces against accidental spamming" ([conversations.go#L1748-L1762](https://github.com/korotovsky/slack-mcp-server/blob/b88c0de3f706f4f07337c9eda7133c736d1c9524/pkg/handler/conversations.go#L1748-L1762)).
- **Per-channel allowlist and denylist.** `SLACK_MCP_ADD_MESSAGE_TOOL` can be a list of channel IDs, or `!C123` to post everywhere except that channel ([conversations.go#L1485-L1487](https://github.com/korotovsky/slack-mcp-server/blob/b88c0de3f706f4f07337c9eda7133c736d1c9524/pkg/handler/conversations.go#L1485-L1487)).
- **Separate opt-ins.**
  - `SLACK_MCP_REACTION_TOOL` covers reactions, and `SLACK_MCP_ATTACHMENT_TOOL` covers attachment download.
  - `SLACK_MCP_ADD_MESSAGE_UNFURLING` controls link unfurling.
- **Annotations.** Write tools set `WithDestructiveHintAnnotation(true)`, and read tools set `WithReadOnlyHintAnnotation(true)`.
- **Ungated writes.** Some destructive tools are registered by default with no env gate: `conversations_leave` ([server.go#L368-L372](https://github.com/korotovsky/slack-mcp-server/blob/b88c0de3f706f4f07337c9eda7133c736d1c9524/pkg/server/server.go#L368-L372)), `usergroups_create`, `usergroups_update` and `usergroups_users_update`. An explicit `SLACK_MCP_ENABLED_TOOLS` list is the only way to hide them.
- **No confirm argument and no draft-then-send step.**

## Notes

- The pattern is to gate risky tools at deploy time (an env var plus a channel scope) instead of at run time (elicitation).
- It is inconsistent: sending a message needs an opt-in, but leaving channels and editing user groups does not.
