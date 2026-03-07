# SESS-001: McpSessionStore interface + InMemorySessionStore

## Summary
Define the `McpSessionStore` interface and `McpSessionRecord` type that all session persistence backends implement, plus ship `InMemorySessionStore` as the zero-config default. This is the foundational contract for session persistence across the framework.

## Background / Context
Sessions are split into two concerns (see design artifact "Session Persistence"):
- **Serializable metadata** stored in `McpSessionStore` (survives restarts, shareable across instances).
- **Live transport objects** held in `McpSessionRegistry` (ephemeral, in-process only -- see SESS-004).

`InMemorySessionStore` is the default when no store is configured in `McpModule.forRoot()`. It is Map-based and TTL-aware: `get()` returns `null` for records whose `expiresAt < now()` and lazily deletes them. `deleteExpired()` does a full sweep.

The `MCP_SESSION_STORE` injection token lets consumers swap implementations (Redis, Drizzle) without changing any dependent code.

## Acceptance Criteria
- [ ] `McpSessionRecord` interface defined with all fields: `sessionId`, `transportType`, `userId`, `profileId`, `clientId`, `scopes`, `resource`, `protocolVersion`, `clientInfo`, `serverName`, `createdAt`, `lastActivityAt`, `expiresAt`
- [ ] `McpSessionStore` interface defined with methods: `save`, `get`, `delete`, `findByUserId`, `findByClientId`, `deleteByUserId`, `touch`, `deleteExpired`
- [ ] `MCP_SESSION_STORE` injection token exported
- [ ] `InMemorySessionStore` implements `McpSessionStore` using `Map<string, McpSessionRecord>`
- [ ] `get()` returns `undefined` for expired records and lazily deletes them
- [ ] `get()` returns `undefined` for non-existent session IDs
- [ ] `touch(sessionId)` updates only `lastActivityAt` and recomputes `expiresAt`
- [ ] `touch(sessionId)` for a non-existent session is a no-op (does not throw)
- [ ] `findByUserId` / `findByClientId` filter out expired records
- [ ] `deleteExpired()` removes all records where `expiresAt < now()` and returns count
- [ ] `deleteByUserId()` removes all records for a user and returns count
- [ ] `save()` overwrites an existing record with the same sessionId
- [ ] `InMemorySessionStore` is registered as the default provider for `MCP_SESSION_STORE` when no store is configured
- [ ] All interfaces and the token are exported from the package entrypoint

## Interface Contract

This ticket defines the core interfaces consumed by SESS-002, SESS-003, SESS-004, and all transport tickets.

```typescript
interface McpSessionRecord {
  sessionId: string;
  transportType: 'streamable-http' | 'sse' | 'stdio';
  userId: string;
  profileId: string;
  clientId: string;
  scopes: string[];
  resource: string;
  protocolVersion: string;
  clientInfo: { name: string; version: string } | null;
  serverName: string;
  createdAt: Date;
  lastActivityAt: Date;
  expiresAt: Date;
}

interface McpSessionStore {
  save(session: McpSessionRecord): Promise<void>;
  get(sessionId: string): Promise<McpSessionRecord | undefined>;
  delete(sessionId: string): Promise<void>;
  findByUserId(userId: string): Promise<McpSessionRecord[]>;
  findByClientId(clientId: string): Promise<McpSessionRecord[]>;
  deleteByUserId(userId: string): Promise<number>;
  touch(sessionId: string): Promise<void>;
  deleteExpired(): Promise<number>;
}

const MCP_SESSION_STORE: unique symbol;
```

**Consumed by:**
- SESS-002 (`RedisSessionStore` implements `McpSessionStore`)
- SESS-003 (`DrizzleSessionStore` implements `McpSessionStore`)
- SESS-004 (`McpSessionService` injects `MCP_SESSION_STORE`)
- TRANS-001/002 (indirectly via `McpSessionService`)

## BDD Scenarios

```gherkin
Feature: In-memory session store
  The default session store persists session records in memory with
  automatic TTL-based expiration. It implements the McpSessionStore
  contract used by all session persistence backends.

  Background:
    Given an in-memory session store configured with a TTL of 1 hour

  Rule: Saving and retrieving sessions

    Scenario: A saved session can be retrieved by its ID
      When a session is saved with ID "sess-1" and server name "analytics-server"
      Then retrieving session "sess-1" returns a record with server name "analytics-server"

    Scenario: Saving a session with an existing ID replaces the previous record
      Given a session "sess-1" exists with server name "server-a"
      When a session is saved with ID "sess-1" and server name "server-b"
      Then retrieving session "sess-1" returns a record with server name "server-b"

    Scenario: Retrieving a non-existent session returns undefined
      When session "unknown-session" is retrieved
      Then undefined is returned

  Rule: Expired sessions are invisible and lazily removed

    Scenario: An expired session is not returned on retrieval
      Given a session "sess-expired" exists with an expiration time in the past
      When session "sess-expired" is retrieved
      Then undefined is returned

    Scenario: Retrieving an expired session removes it from the store
      Given a session "sess-expired" exists with an expiration time in the past
      When session "sess-expired" is retrieved
      And the expiration is reset to 1 hour in the future for "sess-expired"
      Then no session record is returned
      # The lazy delete already removed it before the expiration reset

  Rule: Touching a session extends its lifetime

    Scenario: Touching a session updates its activity timestamp and expiration
      Given a session "sess-1" was last active at "2026-03-05T10:00:00Z"
      When the session "sess-1" is touched at "2026-03-05T11:00:00Z"
      Then the session's last activity time is "2026-03-05T11:00:00Z"
      And the session's expiration is "2026-03-05T12:00:00Z"

    Scenario: Touching a non-existent session has no effect
      When the session "nonexistent" is touched
      Then no error occurs

  Rule: Querying sessions by user or client filters out expired ones

    Scenario: Finding sessions by user ID excludes expired sessions
      Given user "user-1" has sessions "sess-1" (active), "sess-2" (active), and "sess-3" (expired)
      And user "user-2" has session "sess-4" (active)
      When sessions are retrieved for user "user-1"
      Then 2 session records are returned

    Scenario: Finding sessions by client ID excludes expired sessions
      Given client "client-a" has sessions "sess-1" (active) and "sess-2" (expired)
      And client "client-b" has session "sess-3" (active)
      When sessions are retrieved for client "client-a"
      Then 1 session record is returned

  Rule: Bulk deletion operations

    Scenario: Deleting all sessions for a user returns the count and removes them
      Given user "user-1" has 3 sessions
      And user "user-2" has 1 session
      When all sessions for user "user-1" are deleted
      Then the deleted count is 3
      And no sessions remain for user "user-1"
      But the session for user "user-2" is still retrievable

    Scenario: Purging expired sessions removes only those past their expiration
      Given the store contains 2 expired sessions and 1 active session
      When expired sessions are purged
      Then the purged count is 2
      And only the active session remains retrievable

    Scenario: Deleting a specific session by ID
      Given a session "sess-1" exists
      When session "sess-1" is deleted
      Then retrieving session "sess-1" returns undefined
```

## Dependencies
- Depends on: CORE-013 (McpToolsHandler/ResourcesHandler/PromptsHandler -- session store integrates after handlers are wired)
- Blocks: SESS-002 (RedisSessionStore), SESS-003 (DrizzleSessionStore), SESS-004 (McpSessionRegistry + McpSessionService)

## Technical Notes
- File locations: `packages/nestjs-mcp/src/session/interfaces/session-store.interface.ts`, `packages/nestjs-mcp/src/session/interfaces/session-record.interface.ts`, `packages/nestjs-mcp/src/session/stores/in-memory-session.store.ts`, `packages/nestjs-mcp/src/session/session.constants.ts`
- `MCP_SESSION_STORE` token: `export const MCP_SESSION_STORE = Symbol('MCP_SESSION_STORE');`
- `transportType` is a union: `'streamable-http' | 'sse' | 'stdio'`
- `InMemorySessionStore` constructor takes `{ ttlMs: number }` (default 24h). TTL is used by `touch()` to compute new `expiresAt`.
- `touch()` should be O(1) -- single map lookup + field update.
- `findByUserId` and `findByClientId` are O(n) scans -- acceptable for in-memory dev/test usage.
- Do NOT add `@Injectable()` decorator to the store class -- it is instantiated directly or via factory. The injection token is what NestJS resolves.
- No SDK APIs are directly used in this ticket -- this is a pure framework interface. The `McpSessionRecord.protocolVersion` field stores the negotiated MCP protocol version string from the SDK's initialization handshake.
