# Reviewing for the Unique client

As of 2026-11-18, read from the `node-chat` service in `Unique-AG/monorepo` at `526e20dad9`.
The client code changes often: re-check a behaviour in that service before asserting a
finding on it, and update the date when you do.

Findings that come from this file are class **P** (the Unique client is the provider),
unless the rule is also in the MCP spec.

## What the client is

| Aspect | Value |
|--------|-------|
| SDK | `@modelcontextprotocol/sdk` 1.3x; the SDK negotiates the revision, latest `2025-11-25` |
| Transports | Streamable HTTP first, SSE fallback only when `initialize` fails; no stdio |
| URL policy | `https:`, `wss:`, `mcps:` (`http:` in development only); no query string or fragment; admin host allow/deny lists |
| Sessions | Stateful client, see "Session model" below |
| Timeouts | connect 30 s; `tools/call` uses the SDK default 60 s; progress notifications are ignored |
| Circuit breaker | per server, default cooldown 120 s after repeated failures |

## Session model

**The client is stateful. It does not assume a stateless server, and it does not require a
stateful one.**

- It runs `initialize` once per connection and keeps one long-lived connection per server,
  company and user. Every chat of that user reuses it, and every later `tools/call` goes out
  without a new `initialize`. The connection is closed after 30 min idle, and it is
  re-established on the next call.
- If the server returns `Mcp-Session-Id`, the client stores it, sends it on every request,
  resumes the SSE stream with `Last-Event-ID`, and sends `DELETE` to end the session. A 405
  on that `DELETE` is logged and tolerated.
- If the server returns no `Mcp-Session-Id`, the client carries on without one. A stateless
  server therefore works, provided it accepts `tools/call` on a fresh HTTP request with no
  session header and no `initialize` in front of it, which is what stateless means.
- A stateful server must keep a session alive across at least 30 min of idle time and
  across many chats, and when it drops one it must answer with `404` and a body that says
  `Session not found` (or `Session expired`, `Invalid session`, `terminated`). Only those
  messages make the client reconnect and retry; any other error reaches the user as a tool
  failure.
- The `2026-07-28` stateless model (`server/discover`, no sessions) is not implemented by
  the client's SDK generation. Such a server works only through its backwards-compatible
  `initialize` path.

Review consequences: a server that stores per-session state (cursors, elicitation results,
caches) and evicts it after a few minutes fails OUT-001 and REL-001 for this client. A server
that answers a lost session with 400 or 500 instead of `404 Session not found` fails REL-001.
A stateless server has no session findings; check instead that it does not depend on
`initialize` having happened on the same request stream.

## Auth

- **OAuth only.** The server record has no static header or API-key field. Authorization
  code + PKCE through the SDK client provider, tokens per user, encrypted at rest.
- **Discovery**: RFC 9728 protected-resource metadata, then RFC 8414 / OIDC with
  path-prepended fallbacks, 5 s per request. The `iss` of the authorization response is
  validated.
- **Registration**: dynamic client registration as a public client
  (`token_endpoint_auth_method: 'none'`, grants `authorization_code` and `refresh_token`,
  scope = discovered `scopes_supported`). Without DCR an admin pastes a client id and secret.
- **401 vs 403**: an auth error is detected by string matching (`unauthorized`,
  `token expired`, `invalid token`, `http 401`, `missing_token`, ...), then refresh,
  reconnect, retry once. **403 is deliberately not an auth error.**
- The Unique user's own token is **never forwarded**. The server sees its own bearer plus,
  when an admin enabled the namespace, identity in `_meta` (below).

Review consequences: AUTH-001 applies in full (validate `aud` against the server's resource
URL). A server that answers an expired token with 403, or with 401 and an unrecognisable body,
strands the user in a reconnect loop or a permissions error. A server that needs an API key
instead of OAuth cannot be registered.

## Catalog

- **Effective tool name** the model sees is `<serverId>_<toolName>`. Server-name prefixes
  inside tool names are therefore redundant; generic verbs (`search`, `get`) still collide
  across servers in the model's eyes because the prefix is an opaque id, so TOOL-001 stands.
- **`inputSchema` passes through unchanged**; a definition is only valid when
  `inputSchema.type === 'object'`.
- **`readOnlyHint` is the only annotation acted on.** `readOnlyHint !== true` defaults the tool
  to "ask for confirmation", which blocks the call on a user elicitation. `destructiveHint`,
  `idempotentHint`, `openWorldHint` are stored but drive nothing. SAFE-002 is satisfied by
  this default; a read-only tool without the hint is a P2 usability finding, a mutating tool
  with `readOnlyHint: true` is P0.
- **`title`** resolves as admin override, then `tool.title`, then `annotations.title`, then
  `tool.name`.
- **`outputSchema` / `structuredContent`** are stored but nothing consumes them. Do not raise
  SCHEMA-001 for a missing `outputSchema` beyond P2 for this client.
- **Identity claims in descriptions are redacted** ("the current user's id is ..."). A
  description that relies on them is a finding.
- **Re-approval on drift**: new tools arrive disabled; a change to name, description,
  `inputSchema`, `outputSchema`, `annotations` or any `unique.app/*` `_meta` disables the tool
  until an admin re-approves. Flag unstable descriptions (timestamps, counts, environment
  names) as P1.
- **Cache**: tool list cached 1 h in process and in the database;
  `notifications/tools/list_changed` triggers a relist but not approval.
- **No tool-count or definition-size limit, no deferred discovery.** TOOL-005 thresholds apply
  as written. Listing a server times out after 10 s.

### `unique.app/*` extensions

Tool `_meta` keys the client reads:

| Key | Use |
|-----|-----|
| `unique.app/icon` | tool icon |
| `unique.app/system-prompt`, `unique.app/user-prompt` | prompt fragments injected when the tool is enabled |
| `unique.app/tool-format-information` | result formatting hint for the model |
| `unique.app/config-schema` (`json_schema`, `ui_schema`, `default_config`) | admin-editable per-tool config; the saved value arrives in `_meta['unique.app/config']` on each call |
| `unique.app/context-requirements` (`required`, `optional`, `accepts_custom`) | declares which forwarded context keys the tool needs; the call is refused when a required one is not forwarded |
| `unique.app/category` (prompts) | prompt-menu grouping |

`_meta` sent on `tools/call`, only for namespaces the admin enabled on the server record:
`unique.app/auth/user-id`, `unique.app/auth/company-id`, `unique.app/chat/chat-id`,
`unique.app/chat/user-message-id`, `unique.app/chat/assistant-id`, plus legacy unprefixed
`userId`, `companyId`, `chatId`, `messageId`. Treat these as **hints for logging and
correlation, not authentication**: anyone with the bearer can set them. A server that
authorizes on `_meta` identity is AUTH-004 P0.

## Results

- `isError: true`: the text blocks are joined into the failure reason shown to the model,
  default `Tool returned an error result`; logged truncated to 500 chars. ERR-001 applies as
  written.
- Content types the public API passes on: `text`, `image`, `audio`, `resource_link`,
  `resource`.
- No result-size truncation in the chat path; the Conduct sandbox path persists 64 KiB and
  previews 2000 chars. OUT-001 stands: an unbounded list result reaches the model whole.
- List results can be mapped to citations through an admin reference mapping with a list
  path, a title path and a details path. JSON results with a stable top-level list and a
  title field per item are preferred over prose.

## Other primitives

| Primitive | Supported |
|-----------|-----------|
| Prompts | yes, listed in the chat prompt menu |
| Elicitation | yes, form and URL mode; 300 s then `action: 'cancel'`; form schemas may carry `multiline`, `pattern`, `uiWidget`, `uiWidgetOptions`, `uiOrder` |
| Resources | listed and cached, read only by the mcp-hub gateway, not by chat |
| Logging notifications | received and logged |
| Sampling, roots, completions, tasks | no, the client answers `Unhandled request method` |

A server that needs sampling or tasks to complete a tool call does not work with this client.
Report that under the verdict, not as a server defect.

## Checklist to add for a Unique-facing server

1. Streamable HTTP on `https://`, path only, no query string.
2. Either stateless, or a session that survives 30 min idle and is reported lost with
   `404 Session not found`.
3. OAuth with RFC 9728 + RFC 8414 discovery, PKCE S256, public client (`none`), DCR or a
   documented client id. Audience-check the bearer (AUTH-001).
4. Expired or invalid token: 401 with `invalid_token` wording. Permission denied: 403.
5. `readOnlyHint: true` on every tool that does not mutate, and on nothing else.
6. `inputSchema.type` is `object`; names are short, domain + action, without a server prefix.
7. Descriptions are stable across deploys and never mention the calling user's identity.
8. Identity from `_meta['unique.app/auth/*']` is used for logging and context only; declare it
   in `unique.app/context-requirements` when the tool needs it.
9. `tools/call` answers within 60 s without relying on progress notifications; long work
   returns a handle for a follow-up call.
10. Failures use `isError: true` with an actionable text block.
11. List results are bounded and JSON-shaped with a stable list path and per-item title.
12. The server logs `Mcp-Session-Id`, tool name and the forwarded `_meta` ids, and no payloads
    (the monorepo's security rules forbid logging any payload).
