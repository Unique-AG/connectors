# Context7 (upstash/context7): docs MCP and admin MCP

| Field | Value |
|---|---|
| Vendor | Upstash; official |
| Category | dev-platform |
| Tier | 3 |
| Source | open (https://github.com/upstash/context7 @ 4087030) |
| Language / SDK | TypeScript. `packages/mcp` (`@upstash/context7-mcp` 4.7.0) uses `@modelcontextprotocol/server` 2.4.0. `packages/admin-mcp` (`@upstash/context7-admin-mcp` 0.1.0) uses `@modelcontextprotocol/server` 2.3.1 |
| Hosted endpoint | https://mcp.context7.com/mcp (docs) and https://admin.mcp.context7.com/mcp (admin) |
| Uses elicitation | yes |
| Mechanism | both. The docs MCP uses legacy `elicitation/create` only, over stdio. The admin MCP uses only the 2026-07-28 `InputRequiredResult` |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `resolve-library-id` and `query-docs` (docs MCP), after the result is built, when the caller is anonymous and the backend sent `X-Context7-Auth-Prompt: 1` (an IP-threshold nudge, at most once per session, decided by the backend) | form | `other (sign-in / upsell nudge for higher rate limits)` | "You're using Context7 anonymously. To unlock free higher rate limits, run this in your terminal: `npx ctx7 setup --<client> --mcp ...`". One enum field `choice`: "I'll run the command to sign in" / "Continue anonymously with smaller limits" | Ignored. The call is fire-and-forget (`void ... .catch(() => {})`), the answer is never read, and the tool result goes back unchanged | [auth-prompt.ts#L76](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/mcp/src/lib/auth/auth-prompt.ts#L76), [index.ts#L389](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/mcp/src/index.ts#L389), [index.ts#L448](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/mcp/src/index.ts#L448) |
| Every destructive action in the admin MCP: `remove_library`, `manage_members` remove, `manage_library_versions` remove, `manage_rules` delete, `manage_owned_library` block / transfer, `docs7_manage_feature_requests` delete, `docs7_remove_preview`, `ask_delete_site`. Applied centrally in `runTool` for any action of kind `destructive` | form (as an `inputRequests` entry, key `confirm`) | `confirm-destructive` | "`<action>`? Type `<what>` to confirm: `<expected>`", for example "Remove the library /org/x from the teamspace? Type the library id to confirm: /org/x". One required string field `answer` (title = what, description = expected value). The user must type the exact target | `decline` gives the tool error "Not done: the user declined." `accept` with the wrong text gives "Not done: what the user typed is not ...". `cancel`, or a client that could not show the form, gives "Not done: the confirmation was cancelled ... the user has not agreed" | [confirm.ts#L55](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/admin-mcp/src/confirm.ts#L55), [confirm.ts#L78](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/admin-mcp/src/confirm.ts#L78), [server.ts#L321](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/admin-mcp/src/server.ts#L321) |

## Fallback without client elicitation support

- **Docs MCP:** silent no-op. It is gated on `server.server.getClientCapabilities()?.elicitation`,
  which is only set after a 2025-era `initialize`. On stateless HTTP and on 2026-07-28 connections
  that is undefined, so the nudge never fires
  ([auth-prompt.ts#L78](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/mcp/src/lib/auth/auth-prompt.ts#L78)).
  In practice the hosted HTTP endpoint never elicits; only stdio clients see the dialog.
- **Admin MCP:** if the per-request 2026-07-28 client-capabilities envelope does not declare form
  elicitation (`canElicit`, which counts an empty `elicitation: {}` as form), the tool needs a
  `confirm` argument equal to the exact target. Without it, the tool errors with "Not done: this
  change needs the user's confirmation. Ask the user to confirm. Only after they agree, call again
  with `confirm` set to ..."
  ([confirm.ts#L65](https://github.com/upstash/context7/blob/4087030ad2dc16578130e2dab1e48ba735f8ea38/packages/admin-mcp/src/confirm.ts#L65)).
  2025-era clients always take this path, because the server deliberately does not use
  `elicitInput`.

## Other human-in-the-loop mechanisms

- Admin tools set `destructiveHint` / `readOnlyHint` / `idempotentHint`. The README says the
  client's own approval prompt for destructive tools "is the guard".
- The `confirm` argument (above). Its description tells the model never to fill it in by itself.
- API keys are read-only unless created with "Write access". The management API enforces the
  caller's permissions.
- Docs-MCP tools are `readOnlyHint: true, destructiveHint: false`.

## Notes

- This is the only server in this batch that ships the SEP-2322 `InputRequiredResult` in
  production, and it uses it **only** there. The code comment explains why: the server is
  stateless, so a 2025 `elicitInput` answer "could reach an instance that never asked."
- Evidence-based design: the comment in `confirm.ts` cites an internal agent eval (2026-10)
  that found "a `confirm` argument does not stop strong models: they fill it in from the user's
  request without asking." So in an eliciting client the agent's `confirm` argument is ignored,
  and only the typed form answer counts.
- Type-the-name confirmation (GitHub-style "type the repo name") turns a yes/no into a check the
  model cannot answer for the user.
- The docs-MCP nudge moved from text injected into the tool result to elicitation because agents
  treated the injected text as untrusted instructions (CHANGELOG 3.2.0). That made elicitation an
  out-of-band channel to the human for a marketing / upsell message. The authors also chose not to
  port it to `InputRequiredResult`, because that would gate the tool result behind the nudge.
- `set_spending_limit` is a `write`, not `destructive`, so it is not confirmed. There is no
  `confirm-cost` usage.
