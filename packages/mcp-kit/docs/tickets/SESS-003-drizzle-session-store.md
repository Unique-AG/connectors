# SESS-003: DrizzleSessionStore + McpSessionCleanupService

## Summary
Implement a Drizzle ORM-backed `McpSessionStore` for production use with relational databases, plus a `McpSessionCleanupService` that runs `deleteExpired()` on a cron schedule. Unlike Redis (which has native TTL), database-backed stores require periodic cleanup of expired rows.

## Background / Context
Some deployments prefer a relational database over Redis for session persistence (fewer infrastructure components, existing DB already available). Drizzle ORM is the standard ORM in the monorepo.

The store uses a `mcp_sessions` table with indexes on `user_id`, `client_id`, and `expires_at`. `save()` uses upsert (INSERT ON CONFLICT UPDATE) so reconnecting clients update their existing record. `get()` filters by `expires_at >= now()` so expired rows are invisible even before cleanup runs.

`McpSessionCleanupService` is a NestJS `@Cron` service that calls `store.deleteExpired()` hourly to reclaim database space.

## Acceptance Criteria
- [ ] Drizzle schema defined for `mcp_sessions` table with columns: `session_id` (PK), `transport_type`, `user_id`, `profile_id`, `client_id`, `scopes` (JSON), `resource`, `protocol_version`, `client_info` (JSON nullable), `server_name`, `created_at`, `last_activity_at`, `expires_at`
- [ ] Indexes on `user_id`, `client_id`, `expires_at`
- [ ] `DrizzleSessionStore` implements `McpSessionStore` interface from SESS-001
- [ ] Constructor accepts `{ db: DrizzleDatabase, ttlMs: number }`
- [ ] `save()` uses upsert (INSERT ... ON CONFLICT(session_id) DO UPDATE) -- updates all mutable fields
- [ ] `get()` returns null if no row found OR if `expires_at < now()`
- [ ] `delete()` deletes by session_id
- [ ] `findByUserId()` selects where `user_id = ? AND expires_at >= now()`
- [ ] `findByClientId()` selects where `client_id = ? AND expires_at >= now()`
- [ ] `deleteByUserId()` deletes where `user_id = ?` (all, including expired), returns count
- [ ] `touch()` updates only `last_activity_at` and `expires_at` fields
- [ ] `deleteExpired()` deletes where `expires_at < now()`, returns count
- [ ] `McpSessionCleanupService` is `@Injectable()` with `@Cron(CronExpression.EVERY_HOUR)` that calls `store.deleteExpired()`
- [ ] `McpSessionCleanupService` logs the number of expired sessions cleaned up
- [ ] `McpSessionCleanupService` is only registered when a DB-backed store is configured (not for InMemory or Redis)
- [ ] Drizzle schema is exported from the package so consumers can include it in their migrations

## Interface Contract

This ticket exports the Drizzle table schema for consumers to include in their database migrations.

```typescript
// Exported from @unique-ag/nestjs-mcp
export const mcpSessions: PgTableWithColumns<...>; // or SqliteTable for SQLite

// Column mapping: McpSessionRecord field -> DB column
// sessionId       -> session_id (PK, varchar)
// transportType   -> transport_type (varchar)
// userId          -> user_id (varchar, indexed)
// profileId       -> profile_id (varchar)
// clientId        -> client_id (varchar, indexed)
// scopes          -> scopes (json)
// resource        -> resource (varchar)
// protocolVersion -> protocol_version (varchar)
// clientInfo      -> client_info (json, nullable)
// serverName      -> server_name (varchar)
// createdAt       -> created_at (timestamp)
// lastActivityAt  -> last_activity_at (timestamp)
// expiresAt       -> expires_at (timestamp, indexed)
```

**Consumed by:** Application Drizzle migration configs that include `mcpSessions` in their schema.

## BDD Scenarios

```gherkin
Feature: Database-backed session store (Drizzle ORM)
  A production session store that persists session records in a
  relational database via Drizzle ORM, with upsert semantics and
  automatic periodic cleanup of expired sessions.

  Background:
    Given a database session store configured with a TTL of 1 hour

  Rule: Saving and retrieving sessions

    Scenario: A new session can be saved and retrieved
      When a session is saved with ID "sess-1" for user "user-1"
      Then retrieving session "sess-1" returns a matching record

    Scenario: Saving a session with an existing ID updates the record instead of duplicating it
      Given a session "sess-1" exists with server name "server-a"
      When a session is saved with ID "sess-1" and server name "server-b"
      Then retrieving session "sess-1" returns a record with server name "server-b"
      And the original creation timestamp is preserved

    Scenario: An expired session is not returned on retrieval
      Given a session "sess-1" exists with an expiration time in the past
      When session "sess-1" is retrieved
      Then no session record is returned

    Scenario: Retrieving a non-existent session returns nothing
      When session "nonexistent" is retrieved
      Then no session record is returned

  Rule: Querying sessions by user or client filters out expired ones

    Scenario: Finding sessions by user ID excludes expired sessions
      Given user "user-1" has sessions "sess-1" (active), "sess-2" (active), and "sess-3" (expired)
      When sessions are retrieved for user "user-1"
      Then 2 session records are returned

    Scenario: Finding sessions by client ID excludes expired sessions
      Given client "client-a" has sessions "sess-1" (active) and "sess-2" (expired)
      When sessions are retrieved for client "client-a"
      Then 1 session record is returned

  Rule: Deletion operations

    Scenario: Deleting all sessions for a user removes both active and expired sessions
      Given user "user-1" has 2 active sessions and 1 expired session
      When all sessions for user "user-1" are deleted
      Then the deleted count is 3
      And no sessions remain for user "user-1"

    Scenario: Purging expired sessions removes only those past their expiration
      Given the store contains 3 expired sessions and 2 active sessions
      When expired sessions are purged
      Then the purged count is 3
      And only the 2 active sessions remain retrievable

  Rule: Touching a session extends its lifetime

    Scenario: Touching a session updates its activity timestamp and expiration
      Given a session "sess-1" was last active at "2026-03-05T10:00:00Z"
      When session "sess-1" is touched at "2026-03-05T11:00:00Z"
      Then the session's last activity time is "2026-03-05T11:00:00Z"
      And the session's expiration is "2026-03-05T12:00:00Z"
      And all other session fields remain unchanged

    Scenario: Touching a non-existent session has no effect
      When session "nonexistent" is touched
      Then no error occurs
      And no new session record is created

  Rule: Periodic cleanup removes expired sessions from the database

    Scenario: The cleanup job purges expired sessions and logs the count
      Given the store contains 5 expired sessions
      When the hourly cleanup job runs
      Then 5 expired sessions are removed from the database
      And the cleanup count is logged

    Scenario: The cleanup job logs at debug level when nothing was purged
      Given no expired sessions exist in the database
      When the hourly cleanup job runs
      Then no sessions are removed
      And a debug-level log is emitted
```

## Dependencies
- Depends on: SESS-001 -- `McpSessionStore` interface and `McpSessionRecord`
- Blocks: none (optional production store)

## Technical Notes
- File locations:
  - `packages/nestjs-mcp/src/session/stores/drizzle-session.store.ts`
  - `packages/nestjs-mcp/src/session/schema/mcp-sessions.schema.ts` (Drizzle table definition)
  - `packages/nestjs-mcp/src/session/services/session-cleanup.service.ts`
- The Drizzle schema should be exported so consumers can include it in their migrations.
- Use `@nestjs/schedule` for cron -- it is already a core dep of the framework.
- `DrizzleDatabase` type should be generic enough to work with Postgres and SQLite Drizzle instances. Use the pattern: `constructor({ db }: { db: BaseSQLiteDatabase | PostgresJsDatabase })` or accept a generic `DrizzleDb` type.
- The upsert should use Drizzle's `onConflictDoUpdate()` targeting the `session_id` primary key.
- `scopes` column: use `json` type in Postgres, `text` with JSON serialization for SQLite.
- `McpSessionCleanupService` should be conditionally registered. The `McpModule` should only include it in providers when `sessionStore` is an instance of `DrizzleSessionStore`. Alternatively, the cleanup service can be a standalone export that consumers register themselves.
- TTL for `touch()` computation: the store needs a `ttlMs` config (same as InMemorySessionStore). Pass via constructor: `{ db, ttlMs }`.
- No SDK APIs are used directly -- this is a pure storage implementation of the `McpSessionStore` interface from SESS-001.
