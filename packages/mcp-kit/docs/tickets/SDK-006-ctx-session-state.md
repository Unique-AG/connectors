# SDK-006: ctx.get_state / ctx.set_state — Per-Session State

## Summary
Implement per-session key-value state accessible from within tool, resource, and prompt handlers via `McpContext`. This allows tools to accumulate state across multiple calls within the same MCP session (e.g., conversation context, shopping carts, step counters).

## Background / Context
FastMCP v3.0.0 introduces a per-session KV store accessible from within tools: `ctx.get_state(key)`, `ctx.set_state(key, value)`, `ctx.delete_state(key)`. This lets tools maintain stateful interactions across multiple calls within a single session without external storage.

In our framework, session state is tied to `McpSessionRecord` via `sessionId`. The `McpSessionStore` (SESS-001) already persists `McpSessionRecord` — this ticket adds a `state: Record<string, unknown>` field to the session record and exposes it through `McpContext` methods.

State is JSON-serializable only (for Redis/Drizzle persistence compatibility). STDIO transport has no session concept, so calling state methods on STDIO connections throws a descriptive error.

## Acceptance Criteria
- [ ] `ctx.setState(key: string, value: unknown): Promise<void>` — stores a JSON-serializable value in the session state; throws `McpError(InvalidRequest)` if value is not JSON-serializable (e.g., functions, circular refs)
- [ ] `ctx.getState(key: string): Promise<unknown | undefined>` — retrieves a value from session state; returns `undefined` for missing keys
- [ ] `ctx.deleteState(key: string): Promise<void>` — removes a key from session state; no-op if key doesn't exist
- [ ] State is session-scoped: tied to `McpSessionRecord` via `sessionId`, not request-scoped
- [ ] State persists across multiple tool calls within the same session
- [ ] State is included in `McpSessionRecord.state` field and persisted/loaded with the session via `McpSessionStore`
- [ ] `McpSessionRecord` interface updated with `state: Record<string, unknown>` field (defaults to `{}`)
- [ ] `McpSessionService` updated with `getState(sessionId, key)` and `setState(sessionId, key, value)` and `deleteState(sessionId, key)` methods
- [ ] For STDIO transport (no session): calling any state method throws `McpError(InvalidRequest)` with message "Session state is not available on STDIO transport. State methods require a session-based transport (Streamable HTTP or SSE)."
- [ ] Non-serializable values (functions, symbols, circular references) throw `McpError(InvalidParams)` at call time with descriptive message
- [ ] `setState`, `getState`, `deleteState` methods exported as part of `McpContext` interface

## BDD Scenarios

```gherkin
Feature: Per-session key-value state
  Tools can store and retrieve state within an MCP session,
  enabling stateful interactions across multiple tool calls.

  Background:
    Given an MCP server with session state support
    And a connected MCP client over Streamable HTTP

  Rule: State persists across tool calls within the same session

    Scenario: Value set in one tool call is available in the next
      Given a tool "set_counter" that stores a counter value of 1 in session state
      And a tool "get_counter" that reads the counter value from session state
      When an MCP client calls "set_counter"
      And then calls "get_counter" in the same session
      Then "get_counter" returns 1

    Scenario: Complex nested objects are stored and retrieved accurately
      Given a tool "save_data" that stores a nested object with arrays and numbers
      And a tool "load_data" that reads the stored object
      When an MCP client calls "save_data" with a deeply nested structure
      And then calls "load_data" in the same session
      Then "load_data" returns the exact same nested structure

  Rule: State operations handle missing and deleted keys

    Scenario: Reading a nonexistent key returns undefined
      Given a tool "read_key" that reads a key from session state
      When an MCP client calls "read_key" with key "nonexistent"
      Then the tool returns undefined

    Scenario: Deleting a key removes it from state
      Given session state contains key "cart" with value ["item-a"]
      And a tool "clear_cart" that deletes the "cart" key from session state
      And a tool "get_cart" that reads the "cart" key
      When an MCP client calls "clear_cart"
      And then calls "get_cart"
      Then "get_cart" returns undefined

  Rule: State is isolated between sessions

    Scenario: Two sessions maintain independent state
      Given session A stores "user" as "alice"
      And session B stores "user" as "bob"
      When a tool in session A reads "user"
      Then the result is "alice"
      When a tool in session B reads "user"
      Then the result is "bob"

  Rule: STDIO transport does not support session state

    Scenario: State access on STDIO transport produces an error
      Given a connected MCP client over STDIO transport
      And a tool "store_value" that writes to session state
      When an MCP client calls "store_value"
      Then the tool receives an error indicating state requires a session-based transport

  Rule: Non-serializable values are rejected

    Scenario: Storing a function produces a validation error
      Given a tool "store_fn" that attempts to store a function in session state
      When an MCP client calls "store_fn"
      Then the tool receives an error indicating the value must be JSON-serializable
```

## Dependencies
- **Depends on:** CORE-007 — McpContext (state methods are added to McpContext)
- **Depends on:** SESS-001 — McpSessionStore needs `state` field added to `McpSessionRecord`
- **Depends on:** SESS-004 — McpSessionService needs `getState`/`setState`/`deleteState` methods
- **Blocks:** nothing

## Technical Notes
- State is stored in `McpSessionRecord.state: Record<string, unknown>` — this field must be added to the `McpSessionRecord` interface in SESS-001
- JSON-serializability check: attempt `JSON.stringify(value)` and catch errors. If it throws (circular reference, BigInt, etc.), throw `McpError(InvalidParams)` with descriptive message
- `McpSessionService.setState()` must load the current state, merge the key, and persist back to the store atomically. For Redis/Drizzle stores, consider using per-key operations or optimistic locking to avoid race conditions
- `ctx.setState/getState/deleteState` delegate to `McpSessionService` using `this.sessionId` — the service reference is injected via `McpContextParams`
- For STDIO: check `this.sessionId === null` before any state operation and throw immediately
- **FastMCP parity:** Maps directly to FastMCP's `ctx.get_state(key)`, `ctx.set_state(key, value)`, and state deletion pattern. FastMCP stores state in-memory per session; our implementation supports pluggable persistence via `McpSessionStore`
- File location: State methods in `packages/nestjs-mcp/src/context/mcp-context.ts`; session record update in `packages/nestjs-mcp/src/session/mcp-session-record.ts`; service methods in `packages/nestjs-mcp/src/session/mcp-session.service.ts`
