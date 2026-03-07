# SESS-005: Session registration + activity tracking

## Summary
Wire session lifecycle events into `McpSessionService`: register sessions on Streamable HTTP initialization, touch on every request, and clean up on transport close. This connects the transport layer to the session persistence layer.

## Background / Context
SESS-004 provides `McpSessionService` with `registerSession()`, `touchSession()`, and `unregisterSession()` methods, but nothing calls them yet. This ticket integrates those calls into the Streamable HTTP transport service at the right lifecycle points:

1. **Initialize**: when `onsessioninitialized` fires on `StreamableHTTPServerTransport`, call `registerSession()`.
2. **Every request**: when a POST arrives for an existing session, call `touchSession()`.
3. **Disconnect**: when `transport.onclose` fires, call `unregisterSession()`.

SSE transport (TRANS-002) will do the same integration separately.

## Acceptance Criteria
- [ ] When a Streamable HTTP session is initialized (`onsessioninitialized` callback), `McpSessionService.registerSession()` is called with the session ID, transport, McpServer, resolved identity, and transport metadata
- [ ] On every subsequent POST request to an existing session, `McpSessionService.touchSession(sessionId)` is called
- [ ] When a transport's `onclose` fires, `McpSessionService.unregisterSession(sessionId)` is called
- [ ] `touchSession` is fire-and-forget (awaited but failures are logged, not thrown) to avoid blocking request handling
- [ ] The session record's `expiresAt` is updated on each touch (computed by the store based on TTL)
- [ ] Identity is resolved via `McpIdentityResolver` before `registerSession()` is called (identity may be null for unauthenticated servers)
- [ ] When identity is null (unauthenticated server), `registerSession()` is still called with `identity: null`

## BDD Scenarios

```gherkin
Feature: Session registration and activity tracking
  The transport layer integrates with the session service to register
  new sessions on initialization, track activity on each request, and
  clean up on disconnect. This wiring connects MCP protocol events to
  session persistence.

  Background:
    Given an MCP server with Streamable HTTP transport in stateful mode

  Rule: New sessions are registered on initialization

    Scenario: A client's first request creates and persists a session
      When a client sends an initialize request without a session ID header
      Then a new session ID is returned in the response header
      And the session is persisted with transport type "streamable-http"
      And the session is associated with the authenticated user's identity

    Scenario: An unauthenticated client's session is registered with no identity
      Given no identity resolver is configured
      When a client sends an initialize request
      Then the session is persisted with empty user fields
      And the session ID is still returned in the response header

  Rule: Activity is tracked on every request

    Scenario: Each request to an existing session updates its last activity time
      Given client "client-a" has an active session "sess-1"
      When the client sends a tool call request with session ID "sess-1"
      Then the session's last activity time is updated
      And the session's expiration is extended

    Scenario: A failure to update activity does not block the client's request
      Given client "client-a" has an active session "sess-1"
      And the session store is temporarily unavailable
      When the client sends a tool call request with session ID "sess-1"
      Then the tool call is still processed and a response is returned
      And a warning is logged about the activity tracking failure

  Rule: Sessions are cleaned up on disconnect

    Scenario: A disconnected client's session is removed from active tracking and storage
      Given client "client-a" has an active session "sess-1"
      When the client disconnects
      Then the session is removed from the active sessions list
      And the session record is removed from the store

  Rule: Multiple clients are tracked independently

    Scenario: Two clients' sessions do not interfere with each other
      Given client "client-a" has session "sess-a" and client "client-b" has session "sess-b"
      When client "client-a" sends a request
      Then only session "sess-a" has its activity time updated
      And session "sess-b" remains unchanged
```

## Dependencies
- Depends on: SESS-004 -- `McpSessionService` API
- Blocks: SESS-006 (session resumption builds on registration), TRANS-001 (Streamable HTTP transport), TRANS-002 (SSE transport)

## Technical Notes
- This ticket defines the session lifecycle wiring pattern that TRANS-001 and TRANS-002 will implement in their respective transport services.
- `McpSessionService` must be injected into the transport service.
- Identity resolution: the `McpIdentityResolver` (REQUEST-scoped) should be resolved in the same request context as the executor. The resolved `McpIdentity` is passed to `registerSession()`.
- `touchSession` call pattern:
  ```typescript
  if (sessionId && registry.get(sessionId)) {
    // Touch session (fire-and-forget)
    this.sessionService.touchSession(sessionId).catch(err =>
      this.logger.warn(`Failed to touch session ${sessionId}`, err)
    );
    // ... handle request
  }
  ```
- For the SSE transport, the same pattern applies but is wired in TRANS-002.
- SDK APIs used:
  - `StreamableHTTPServerTransport.onsessioninitialized` callback -- fires when a new session is created
  - `Transport.onclose` -- fires when transport connection closes
