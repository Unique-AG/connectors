# Nextcloud MCP Server (cbcoutinho/nextcloud-mcp-server)

| Field | Value |
|---|---|
| Vendor | Chris Coutinho (cbcoutinho); community |
| Category | collaboration |
| Tier | 3 |
| Source | open (https://github.com/cbcoutinho/nextcloud-mcp-server @ 009243b) |
| Language / SDK | Python, `mcp[cli]` 2.3.0 (`>=2.3,<2.4`; `mcp.server.mcpserver.Context`) |
| Hosted endpoint | none (self-hosted) |
| Uses elicitation | yes (only in Login Flow v2 / multi-user mode, `enable_login_flow`) |
| Mechanism | legacy `elicitation/create` request (`ctx.elicit`). 2026-07-28 requests fall back to text (`NoBackChannelError`) |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `nc_auth_provision_access`: starts Nextcloud Login Flow v2 to get a per-user app password | form (carrying a URL in the message) | `auth-oauth` (third-party login: Nextcloud Login Flow v2) | "Please log in to Nextcloud to grant access: `<login_url>` ... Then check the box below and click OK." One boolean `acknowledged` (default false), "Check this box after completing login at the provided URL" | Deletes the stored login-flow session and returns `status: declined` / `cancelled` with "Call nc_auth_provision_access again to retry." On accept the result is `status: pending` and the next step is `nc_auth_check_status`, which polls for completion. Accept without ticking the box is only logged | [auth_tools.py#L173](https://github.com/cbcoutinho/nextcloud-mcp-server/blob/009243bd729c5adabc4a236ee3a9879b6f6a1ca0/nextcloud_mcp_server/server/auth_tools.py#L173), [elicitation.py#L139](https://github.com/cbcoutinho/nextcloud-mcp-server/blob/009243bd729c5adabc4a236ee3a9879b6f6a1ca0/nextcloud_mcp_server/auth/elicitation.py#L139) |
| `nc_auth_update_scopes`: restarts Login Flow v2 with a wider scope set | form | `auth-oauth` | Same login-URL message and `acknowledged` checkbox | Deletes the flow session and returns `declined` / `cancelled` with "Call nc_auth_update_scopes again to retry." | [auth_tools.py#L572](https://github.com/cbcoutinho/nextcloud-mcp-server/blob/009243bd729c5adabc4a236ee3a9879b6f6a1ca0/nextcloud_mcp_server/server/auth_tools.py#L572) |
| Any tool wrapped by `@require_scopes` (nearly all Nextcloud tools), in Login Flow mode, when the user has no stored app password | form | `auth-oauth` (provisioning prompt) | "Nextcloud access is not yet provisioned for this user. Open this URL to enable it via the Astrolabe app: `<nextcloud>/index.php/apps/astrolabe/settings` ... or ask your MCP client to call `nc_auth_provision_access` ... Then check the box below and retry the original request." (No URL variant when no browser URL is configured.) One boolean `acknowledged` | The call **always** fails with `ProvisioningRequiredError`. Only the message changes: after accept, "retry the request"; otherwise, "Please call 'nc_auth_provision_access' first." | [scope_authorization.py#L209](https://github.com/cbcoutinho/nextcloud-mcp-server/blob/009243bd729c5adabc4a236ee3a9879b6f6a1ca0/nextcloud_mcp_server/auth/scope_authorization.py#L209), [elicitation.py#L190](https://github.com/cbcoutinho/nextcloud-mcp-server/blob/009243bd729c5adabc4a236ee3a9879b6f6a1ca0/nextcloud_mcp_server/auth/elicitation.py#L190) |

## Fallback without client elicitation support

One shared helper, `_run_elicit`, calls `ctx.elicit` without checking capabilities and degrades
silently to `"message_only"` on any failure. The cases are: `NoBackChannelError` (a 2026-07-28
request, or a stateless HTTP / JSON-response server), `NotImplementedError`, no `elicit` on the
context, or any other exception. Each outcome is counted in the `mcp_elicitation_total` metric with
a reason label
([elicitation.py#L60](https://github.com/cbcoutinho/nextcloud-mcp-server/blob/009243bd729c5adabc4a236ee3a9879b6f6a1ca0/nextcloud_mcp_server/auth/elicitation.py#L60)).
In message-only mode the login URL goes back in the tool result (`status: login_required`,
`login_url`, "open this URL ... then call nc_auth_check_status"). The model then has to pass the
link to the user. For gated tools, the error text names the provisioning tool.

## Other human-in-the-loop mechanisms

- OAuth scopes as a tool allowlist. The stored app-password scopes act as a further restriction
  ("token ∩ stored scopes"), and tools are filtered by scope and by Nextcloud capability.
- `ToolAnnotations` (`read_only_hint`, `destructive_hint`, `open_world_hint`) on the tools (ADR-017).
  No `confirm` arguments and no elicitation before destructive Nextcloud operations.
- Provisioning through the Astrolabe Nextcloud app's settings UI (a browser-side consent flow).

## Notes

- Login URLs are sent in **form** mode with a "tick when done" checkbox, not in URL mode. ADR-006
  ("Progressive Consent via URL Elicitation (SEP-1036)", status "Partially Implemented (Interim
  Workaround)") plans URL mode. The form-mode workaround puts the auth URL through the client's
  form UI, which the spec discourages for sensitive flows.
- The checkbox answer is not trusted: login completion is checked by polling Login Flow v2, so
  "accept" only changes the wording of the next instruction.
- The code expects 2026-07-28 to stop this elicitation from working. Its docstring says watching
  `reason="no_back_channel"` rise against `accepted` "is how the era transition becomes visible."
  `errors.py` already types `call_tool` as returning `CallToolResult | InputRequiredResult`, but no
  first-party code produces an `InputRequiredResult` yet.
