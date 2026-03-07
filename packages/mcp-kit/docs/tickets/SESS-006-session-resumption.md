# SESS-006: Session resumption after server restart

## Summary
Enable clients to transparently reconnect to a persisted session after server restart. When a POST arrives with a `Mcp-Session-Id` that exists in the session store but not in the local registry, reconstruct the transport and McpServer, verify ownership, and handle the request. This enables zero-downtime deployments and horizontal scaling.

## Background / Context
If the server restarts, all in-process transports are lost and clients get a 404 for their session ID. With session persistence (SESS-001..005), the session record survives in the store, but there is no live transport to handle the request.

Resumption flow (from design artifact):
1. Client sends POST with `Mcp-Session-Id: abc-123`
2. Transport service: `abc-123` not in local registry
3. `McpSessionStore.get("abc-123")` returns record
4. Verify: `request.user.userId === sessionRecord.userId` (prevent hijacking)
5. Create new `StreamableHTTPServerTransport` with `sessionIdGenerator: () => "abc-123"`
6. Register handlers via `McpExecutorService`, register in `McpSessionService`
7. Handle the request transparently

If session ID is not in store either: return 404.
If userId mismatch: return 403.

## Acceptance Criteria
- [ ] When a POST arrives with `Mcp-Session-Id` that is NOT in the local registry but IS in the session store, the transport is reconstructed
- [ ] `StreamableHTTPServerTransport` is created with `sessionIdGenerator: () => existingSessionId` so it reuses the same session ID
- [ ] A new `McpServer` is created, connected to the transport, and handlers registered via `McpExecutorService`
- [ ] The reconstructed session is registered in `McpSessionService` (store touch + registry add)
- [ ] Security: `request.user.userId` is compared to `sessionRecord.userId`; mismatch returns 403 Forbidden
- [ ] If `Mcp-Session-Id` is not in registry AND not in store, return 404 with error "Session not found"
- [ ] After resumption, subsequent requests to the same session work normally (no re-initialization needed)
- [ ] Resumed transport has `onclose` handler wired to `McpSessionService.unregisterSession()`
- [ ] For unauthenticated servers (no identity resolver), the userId check is skipped

## BDD Scenarios

```gherkin
Feature: Session resumption after server restart
  Clients can transparently reconnect to a persisted session after
  a server restart or when load-balanced to a different instance.
  The server reconstructs the transport and verifies ownership
  before resuming the session.

  Rule: Successful session resumption

    Scenario: A client reconnects to its session after a server restart
      Given user "user-1" had an active session "sess-1" before the server restarted
      And the session record is still persisted in the store
      When the client sends a request with session ID "sess-1" authenticated as "user-1"
      Then the request is handled successfully
      And subsequent tool calls using session "sess-1" continue to work

    Scenario: A resumed session tracks activity like a normal session
      Given session "sess-1" has been resumed after a server restart
      When the client sends another request using session "sess-1"
      Then the session's last activity time is updated

    Scenario: A resumed session is cleaned up when the client disconnects
      Given session "sess-1" has been resumed after a server restart
      When the client disconnects
      Then the session is removed from active tracking and from the store

  Rule: Session ownership is verified before resumption

    Scenario: A different user cannot hijack another user's session
      Given user "user-1" has a persisted session "sess-1"
      And the server has restarted
      When a request arrives with session ID "sess-1" authenticated as "user-2"
      Then a 403 Forbidden response is returned
      And the session is not reconstructed
      And the stored session record is preserved

    Scenario: An unauthenticated server skips ownership verification
      Given an MCP server with no authentication configured
      And a persisted session "sess-1" exists in the store
      And the server has restarted
      When a request arrives with session ID "sess-1" and no credentials
      Then the session is resumed successfully

  Rule: Unknown or expired sessions are rejected

    Scenario: A request with a completely unknown session ID returns 404
      Given no session "nonexistent" exists in the store or in active tracking
      When a request arrives with session ID "nonexistent"
      Then a 404 response is returned with error "Session not found"

    Scenario: A request for an expired session returns 404
      Given session "sess-1" exists in the store but its expiration has passed
      When a request arrives with session ID "sess-1"
      Then a 404 response is returned
```

## Dependencies
- Depends on: SESS-004 -- `McpSessionService` and `McpSessionRegistry`
- Depends on: SESS-005 -- session registration wiring
- Blocks: TRANS-001 (Streamable HTTP transport integrates resumption logic)

## Technical Notes
- This ticket defines the session resumption logic that TRANS-001 will implement in the Streamable HTTP transport service's `handleStatefulRequest` method.
- Resumption flow in `handleStatefulRequest`:
  ```typescript
  } else if (sessionId && !this.registry.get(sessionId)) {
    // Session not in local registry -- try store
    const record = await this.sessionService.getSession(sessionId);
    if (!record) {
      return res.status(404).json({ error: 'Session not found' });
    }
    // Security check (skip if no identity resolver)
    const identity = this.identityResolver ? await this.identityResolver.resolve(req) : null;
    if (identity && record.userId !== identity.userId) {
      return res.status(403).json({ error: 'Session ownership mismatch' });
    }
    // Reconstruct transport
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => sessionId,
      enableJsonResponse: this.options.streamableHttp?.enableJsonResponse || false,
    });
    // Create McpServer, connect, register handlers...
    await this.sessionService.registerSession(sessionId, transport, mcpServer, identity, { ... });
    await transport.handleRequest(req, res);
    return;
  }
  ```
- For unauthenticated servers (no identity resolver), skip the userId check.
- The `onsessioninitialized` callback is NOT needed for reconstructed transports (session ID is already known).
- Consider extracting session reconstruction into a private method `reconstructSession(sessionId, req, res)` to keep `handleStatefulRequest` readable.
- SDK APIs used:
  - `StreamableHTTPServerTransport` constructor with `sessionIdGenerator` option -- forces reuse of existing session ID
  - `McpServer` from `@modelcontextprotocol/sdk/server/mcp.js` -- created fresh for resumed session
  - `Transport.onclose` -- wired to `unregisterSession`
