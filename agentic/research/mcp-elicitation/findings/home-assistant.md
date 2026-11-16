# Home Assistant MCP (homeassistant-ai/ha-mcp)

| Field | Value |
|---|---|
| Vendor | homeassistant-ai org; community (not Home Assistant core) |
| Category | other (smart home / IoT) |
| Tier | 3 |
| Source | open (https://github.com/homeassistant-ai/ha-mcp @ efe985c) |
| Language / SDK | Python. Vendored `fastmcp-slim` 4.1.6 and `mcp` 2.3.0 (`src/ha_mcp/_vendor/requirements.txt`). The `mcp>=1.26,<2` in `pyproject.toml` is a test-only dependency |
| Hosted endpoint | none (self-hosted add-on / custom component / standalone) |
| Uses elicitation | yes (only when a user has set up Tool Security Policies rules) |
| Mechanism | 2026-07-28 `InputRequiredResult` (SEP-2322 multi-round-trip), with no legacy `elicitation/create` in first-party code |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Any tool call held by a **Tool Security Policies** rule (`PolicyMiddleware.on_call_tool`), that is still undecided after about 10 s (`ROUND_WAIT_SECONDS`), from a client on protocol `2026-07-28` that declares form elicitation. Code-mode / nested proxied calls are excluded | form (`inputRequests["ha_mcp_approval"]` plus a sealed `requestState`) | `other (out-of-band approval prompt: "go approve this in the settings UI", the form itself cannot approve)` | "Approve `<tool>` in ha-mcp > Tool Security Policies and Accept here (either order, within `<N>` s of the call)." One boolean `decided` (default true), "Continue once approved in the ha-mcp settings" | **decline** denies and removes the pending row, even one a human already approved, and raises the denied error. **cancel** ends with `USER_APPROVAL_REQUIRED` (dismissed) and the row stays approvable for the TTL. **accept** only resumes waiting: the call runs only if the row was approved in the settings UI / HA automation within the window. Up to 8 continuations | [mrtr.py#L96](https://github.com/homeassistant-ai/ha-mcp/blob/efe985c3bba739064ac6902b23b3d7a8dfb32d28/src/ha_mcp/policy/mrtr.py#L96), [mrtr.py#L241](https://github.com/homeassistant-ai/ha-mcp/blob/efe985c3bba739064ac6902b23b3d7a8dfb32d28/src/ha_mcp/policy/mrtr.py#L241), [middleware.py#L269](https://github.com/homeassistant-ai/ha-mcp/blob/efe985c3bba739064ac6902b23b3d7a8dfb32d28/src/ha_mcp/policy/middleware.py#L269), [middleware.py#L326](https://github.com/homeassistant-ai/ha-mcp/blob/efe985c3bba739064ac6902b23b3d7a8dfb32d28/src/ha_mcp/policy/middleware.py#L326) |

## Fallback without client elicitation support

`supports_mrtr` requires protocol `2026-07-28` **and** declared form elicitation (an empty
`elicitation: {}` counts as form). It also requires that the retry would resume this exact dispatch
([mrtr.py#L59](https://github.com/homeassistant-ai/ha-mcp/blob/efe985c3bba739064ac6902b23b3d7a8dfb32d28/src/ha_mcp/policy/mrtr.py#L59),
[mcp_client_context.py#L39](https://github.com/homeassistant-ai/ha-mcp/blob/efe985c3bba739064ac6902b23b3d7a8dfb32d28/src/ha_mcp/mcp_client_context.py#L39)).
Every other client, including all 2025-era clients, gets the **blocking wait**. The call holds for
the whole `wait_seconds` (default 60, max 600) and sends progress notifications ("Awaiting user
approval — open the ha-mcp settings UI ..."). If the user decides in time, the call finishes.
Otherwise it ends with a structured `USER_APPROVAL_REQUIRED` error that tells the agent to have the
user approve and then call again
([middleware.py#L684](https://github.com/homeassistant-ai/ha-mcp/blob/efe985c3bba739064ac6902b23b3d7a8dfb32d28/src/ha_mcp/policy/middleware.py#L684)).
The approval stays valid for `approval_ttl_minutes` (default 5), so the next identical call goes
through.

## Other human-in-the-loop mechanisms

- **Tool Security Policies** itself: per-tool rules (`require_approval`, or allow-list mode),
  `remember_minutes`, and an approval queue shown in the add-on settings UI. Each held call fires an
  `ha_mcp_approval_requested` event on the HA bus for user-built notifications. Approve/deny from an
  HA event (a phone notification) is optional, behind a switch and a PIN. The design statement:
  "nothing the AI client sends can approve a call." The default policy has no rules, so nothing is
  gated.
- `confirm=True` argument on destructive backup snapshot deletion, which is also disabled by default
  (`enable_snapshot_delete`).
- A two-step preview-then-`confirm_token` flow for YAML config edits (`enable_yaml_edit_confirm`).
- `readOnlyHint` / `destructiveHint` annotations across the tools (about 120 hits).

## Notes

- This is the most unusual pattern in the batch: the elicitation is **not** the approval. It is a
  nudge that says "go approve this elsewhere", and its answer can only stop or deny a call, never
  approve it. The trust model treats the elicitation answer as client-controlled, and so as
  untrusted for granting. Only the out-of-band channel (settings UI or a PIN-protected HA event)
  grants.
- The approval state round-trips in a sealed `requestState` (FastMCP seals it and binds it to the
  call and the principal). ha-mcp also binds the tool name, an args hash, a policy hash and the
  queue token, so a replayed or altered state is rejected ("This approval continuation is no longer
  valid").
- The GitHub code search found `ctx.elicit(`, but at this SHA it occurs only in the vendored FastMCP
  under `src/ha_mcp/_vendor/`. First-party code uses only the MRTR / `InputRequiredResult` path.
- The FAQ documents the per-client behaviour openly (docs/FAQ.md, "How the wait looks depends on the
  client").
