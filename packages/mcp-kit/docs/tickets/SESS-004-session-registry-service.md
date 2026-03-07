# SESS-004: McpSessionRegistry + McpSessionService

## Summary
Implement `McpSessionRegistry` (singleton, holds live in-process transport/server references) and `McpSessionService` (public API that unifies persistent store access with live transport management). Together they provide the complete session management surface: querying sessions, terminating sessions (both live connections and stored records), and broadcasting list-changed notifications.

## Background / Context
The design separates session concerns into two layers:
1. **McpSessionRegistry** -- in-process `Map<sessionId, { transport, mcpServer }>`. Ephemeral: lost on restart, rebuilt on reconnect. Used to close live connections and send notifications.
2. **McpSessionService** -- the public API that delegates to `McpSessionStore` (persistence) and `McpSessionRegistry` (live state). This is what tool code, auth code, and admin endpoints call.

`McpSessionService` is the integration point for token revocation: `OpaqueTokenService.revokeAccessToken()` calls `McpSessionService.terminateUserSessions(userId)` directly (no EventEmitter -- packages are merged).

## Acceptance Criteria
- [ ] `McpSessionRegistry` is `@Injectable()` singleton with methods:
  - `register(sessionId: string, transport: ServerTransport, mcpServer: McpServer): void`
  - `unregister(sessionId: string): void`
  - `get(sessionId: string): { transport: ServerTransport; mcpServer: McpServer } | undefined`
  - `getBySessionIds(ids: string[]): Map<string, { transport; mcpServer }>`
  - `getAllSessionIds(): string[]`
  - `closeTransport(sessionId: string): Promise<void>` -- calls `transport.close()`
- [ ] `McpSessionService` is `@Injectable()` singleton with public API:
  - `registerSession(sessionId, transport, mcpServer, identity, metadata): Promise<void>` -- saves to store + registers in registry
  - `getActiveSessions(): Promise<McpSessionRecord[]>` -- delegates to store
  - `getSessionsByUser(userId): Promise<McpSessionRecord[]>` -- delegates to store's `findByUserId`
  - `getSession(sessionId): Promise<McpSessionRecord | null>` -- delegates to store's `get`
  - `terminateSession(sessionId): Promise<boolean>` -- closes live transport (if in registry) AND deletes from store
  - `terminateUserSessions(userId): Promise<number>` -- finds all sessions for user, terminates each, returns count
  - `touchSession(sessionId): Promise<void>` -- delegates to store's `touch`
  - `unregisterSession(sessionId): Promise<void>` -- removes from registry and store (for transport close events)
  - `notifyToolsChanged(): void` -- iterates all live sessions in registry and calls `mcpServer.sendToolListChanged()` on each
- [ ] `McpSessionService` injects `MCP_SESSION_STORE` token and `McpSessionRegistry`
- [ ] `terminateSession` returns `true` if session existed, `false` if not found
- [ ] `terminateUserSessions` is safe to call even if some sessions are not in the local registry (store-only sessions from other instances) -- it deletes from store regardless
- [ ] `notifyToolsChanged` does not throw if a send fails on one session -- logs warning and continues

## Interface Contract

This ticket defines the public session management API consumed by SESS-005, SESS-006, TRANS-001, TRANS-002, and AUTH (token revocation).

```typescript
@Injectable()
class McpSessionRegistry {
  register(sessionId: string, transport: ServerTransport, mcpServer: McpServer): void;
  unregister(sessionId: string): void;
  get(sessionId: string): { transport: ServerTransport; mcpServer: McpServer } | undefined;
  getBySessionIds(ids: string[]): Map<string, { transport: ServerTransport; mcpServer: McpServer }>;
  getAllSessionIds(): string[];
  closeTransport(sessionId: string): Promise<void>;
}

@Injectable()
class McpSessionService {
  constructor(
    @Inject(MCP_SESSION_STORE) private readonly store: McpSessionStore,
    private readonly registry: McpSessionRegistry,
  );

  registerSession(
    sessionId: string,
    transport: ServerTransport,
    mcpServer: McpServer,
    identity: McpIdentity | null,
    metadata: {
      transportType: McpSessionRecord['transportType'];
      protocolVersion: string;
      clientInfo: McpSessionRecord['clientInfo'];
      serverName: string;
    },
  ): Promise<void>;

  getActiveSessions(): Promise<McpSessionRecord[]>;
  getSessionsByUser(userId: string): Promise<McpSessionRecord[]>;
  getSession(sessionId: string): Promise<McpSessionRecord | null>;
  terminateSession(sessionId: string): Promise<boolean>;
  terminateUserSessions(userId: string): Promise<number>;
  touchSession(sessionId: string): Promise<void>;
  unregisterSession(sessionId: string): Promise<void>;
  notifyToolsChanged(): void;
}
```

**Consumed by:**
- SESS-005 (session registration wiring calls `registerSession`, `touchSession`, `unregisterSession`)
- SESS-006 (session resumption calls `getSession`, `registerSession`)
- TRANS-001 (injects `McpSessionService` for lifecycle management)
- TRANS-002 (injects `McpSessionService` for lifecycle management)
- AUTH token revocation (calls `terminateUserSessions`)
- SDK-004/005 (list change notifications via `notifyToolsChanged`)

## BDD Scenarios

```gherkin
Feature: Session registry and session service
  The session service provides the unified API for session lifecycle
  management, combining persistent storage with live in-process
  transport tracking. It is the integration point for authentication,
  token revocation, and capability notifications.

  Background:
    Given an MCP server with session management enabled

  Rule: Registering a session persists it and tracks the live connection

    Scenario: A new session is persisted and its connection tracked
      When a client establishes session "sess-1" as user "user-1" on the "streamable-http" transport
      Then the session record is retrievable by ID "sess-1"
      And the live connection for "sess-1" is tracked in the local process

    Scenario: An unauthenticated session is registered with empty identity fields
      Given an MCP server with no authentication configured
      When a client establishes session "sess-1"
      Then the session record has empty user, profile, and client fields
      And the live connection for "sess-1" is still tracked

  Rule: Terminating sessions closes connections and removes records

    Scenario: Terminating a live session closes its connection and removes its record
      Given client "sess-1" has an active session with a live connection
      When session "sess-1" is terminated
      Then the client's connection is closed
      And the session record is no longer retrievable
      And the termination reports success

    Scenario: Terminating a non-existent session reports failure
      When session "nonexistent" is terminated
      Then the termination reports that no session was found

    Scenario: Terminating all sessions for a user closes live connections and removes all records
      Given user "user-1" has 3 sessions: 2 with live connections and 1 persisted from another server instance
      When all sessions for user "user-1" are terminated
      Then both live connections are closed
      And all 3 session records are removed
      And the terminated count is 3

  Rule: Querying sessions

    Scenario: Retrieving a session by ID
      Given session "sess-1" is registered
      When session "sess-1" is looked up
      Then the session record is returned

    Scenario: Looking up a non-existent session returns nothing
      When session "nonexistent" is looked up
      Then no session record is returned

    Scenario: Retrieving sessions by user ID
      Given user "user-1" has 2 active sessions
      When sessions for user "user-1" are queried
      Then 2 session records are returned

    Scenario: Listing all active sessions excludes expired ones
      Given there are 3 active sessions and 1 expired session
      When all active sessions are listed
      Then 3 session records are returned

  Rule: Session activity tracking

    Scenario: Touching a session extends its lifetime in the store
      Given session "sess-1" is registered
      When session "sess-1" is touched
      Then the session's last activity time and expiration are updated in the store

  Rule: Unregistering a session on disconnect

    Scenario: Unregistering a session removes it from both live tracking and persistent storage
      Given session "sess-1" has a live connection and a persisted record
      When session "sess-1" is unregistered
      Then the live connection is no longer tracked
      And the session record is removed from the store

  Rule: Broadcasting capability changes to connected clients

    Scenario: Tool list changes are broadcast to all connected clients
      Given 3 clients have active sessions with live connections
      When the tool list changes
      Then all 3 connected clients are notified of the change

    Scenario: A notification failure for one client does not affect others
      Given 3 clients have active sessions with live connections
      And one client's connection is degraded
      When the tool list changes
      Then the healthy clients still receive the notification
      And a warning is logged for the degraded client
```

## Dependencies
- Depends on: SESS-001 -- `McpSessionStore` interface and `MCP_SESSION_STORE` token
- Blocks: SESS-005 (session registration in transports), SESS-006 (session resumption), SDK-004 (resource subscriptions), SDK-005 (list change notifications)

## Technical Notes
- File locations:
  - `packages/nestjs-mcp/src/session/session-registry.ts`
  - `packages/nestjs-mcp/src/session/session.service.ts`
- `McpSessionRegistry` is purely in-process -- no async operations, no DI dependencies beyond being a singleton.
- `McpSessionService.registerSession()` builds the `McpSessionRecord` from the provided identity + metadata arguments.
- `terminateUserSessions` flow: `store.findByUserId(userId)` -> for each session, `registry.closeTransport(sessionId)` (may no-op if not local) -> `store.deleteByUserId(userId)`.
- `notifyToolsChanged` uses `for...of` over registry entries, wrapping each `sendToolListChanged()` in try/catch.
- SDK APIs used:
  - `ServerTransport` type from `@modelcontextprotocol/sdk/server/index.js` -- base transport interface
  - `McpServer` from `@modelcontextprotocol/sdk/server/mcp.js` -- `sendToolListChanged()` method
  - `Transport.close()` -- to terminate live connections
- `getActiveSessions()` implementation note: there is no `findAll()` on `McpSessionStore`. For InMemory/Redis this could scan all entries; for Drizzle it queries all non-expired rows. Consider adding a `findAll()` method to the store interface, or have `getActiveSessions` iterate known session IDs from the registry + store. This is a design decision to resolve during implementation.
