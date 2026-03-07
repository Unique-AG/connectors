# SESS-002: RedisSessionStore

## Summary
Implement a Redis-backed `McpSessionStore` for production use. Uses Redis Hash per session with `EXPIREAT` for automatic TTL, plus SET indexes for efficient `findByUserId` and `findByClientId` lookups. No cleanup cron needed -- Redis handles expiration natively.

## Background / Context
`InMemorySessionStore` (SESS-001) does not survive restarts and is not shared across instances. Production deployments need a durable, shared store. Redis is the natural choice: atomic operations, built-in TTL, and already present in the infrastructure of all existing MCP services.

Data structures:
- **Hash** per session: `mcp:session:{sessionId}` -- stores all `McpSessionRecord` fields as hash fields. `EXPIREAT` set to `expiresAt` timestamp.
- **SET** for userId index: `mcp:user-sessions:{userId}` -- contains session IDs. No TTL on the SET itself; stale entries are cleaned lazily on `findByUserId`.
- **SET** for clientId index: `mcp:client-sessions:{clientId}` -- same pattern as userId.

The store accepts a generic Redis client interface (compatible with `ioredis` and `@redis/client`) to avoid coupling to a specific library.

## Acceptance Criteria
- [ ] `RedisSessionStore` implements `McpSessionStore` interface from SESS-001
- [ ] Constructor accepts `{ redis: RedisClient, keyPrefix?: string, ttlMs: number }` where `keyPrefix` defaults to `"mcp:"`
- [ ] `save()` uses `HSET` for all fields + `EXPIREAT` for TTL + `SADD` to userId and clientId index SETs, all in a single pipeline
- [ ] `get()` uses `HGETALL`; returns `null` if key does not exist (Redis TTL already expired it)
- [ ] `get()` deserializes Date fields from ISO strings and `scopes`/`clientInfo` from JSON
- [ ] `delete()` uses `DEL` on hash + `SREM` from userId and clientId SETs
- [ ] `findByUserId()` uses `SMEMBERS` on `mcp:user-sessions:{userId}`, pipelines `HGETALL` for each, filters out nulls (stale), and cleans up stale SET members via `SREM`
- [ ] `findByClientId()` same pattern as `findByUserId()` with client SET
- [ ] `deleteByUserId()` finds all sessions via SET, deletes each hash + removes from client SETs, deletes user SET, returns count
- [ ] `touch()` uses single `HSET` for `lastActivityAt` + `EXPIREAT` for updated TTL -- no full record rewrite
- [ ] `deleteExpired()` is a no-op returning 0 (Redis TTL handles expiration), but SET indexes still get lazily cleaned
- [ ] Date fields are stored as ISO 8601 strings; `scopes` and `clientInfo` are JSON-serialized

## Interface Contract

This ticket defines the `RedisClient` interface that consumers must satisfy when providing a Redis instance.

```typescript
interface RedisClient {
  hset(key: string, fields: Record<string, string>): Promise<number>;
  hgetall(key: string): Promise<Record<string, string> | null>;
  del(key: string | string[]): Promise<number>;
  sadd(key: string, ...members: string[]): Promise<number>;
  srem(key: string, ...members: string[]): Promise<number>;
  smembers(key: string): Promise<string[]>;
  expireat(key: string, timestamp: number): Promise<number>;
  pipeline(): RedisPipeline;
}

interface RedisPipeline {
  hset(key: string, fields: Record<string, string>): this;
  expireat(key: string, timestamp: number): this;
  sadd(key: string, ...members: string[]): this;
  hgetall(key: string): this;
  srem(key: string, ...members: string[]): this;
  del(key: string | string[]): this;
  exec(): Promise<Array<[Error | null, unknown]>>;
}
```

**Consumed by:** Application code providing a Redis client to `McpModule.forRoot({ sessionStore: new RedisSessionStore({ redis, ttlMs }) })`

## BDD Scenarios

```gherkin
Feature: Redis-backed session store
  A production session store that persists session records in Redis
  with native TTL-based expiration. Provides indexed lookups by
  user and client with lazy cleanup of stale index entries.

  Background:
    Given a Redis session store configured with a TTL of 2 hours

  Rule: Session persistence round-trip

    Scenario: A saved session can be retrieved with all fields intact
      When a session is saved for user "user-1" with client "client-a" and scopes ["read", "write"]
      Then retrieving that session returns a record with properly typed dates, scopes as an array, and client info as an object

    Scenario: Retrieving a session that Redis has already expired returns nothing
      Given a session "sess-1" was saved with a very short TTL
      And enough time has passed for Redis to expire the key
      When session "sess-1" is retrieved
      Then no session record is returned

    Scenario: Retrieving a non-existent session returns nothing
      When session "nonexistent" is retrieved
      Then no session record is returned

  Rule: Deleting a session removes it and its index entries

    Scenario: Deleting a session makes it unretrievable and removes it from user and client indexes
      Given a session "sess-1" exists for user "user-1" and client "client-a"
      When session "sess-1" is deleted
      Then retrieving session "sess-1" returns nothing
      And querying sessions for user "user-1" does not include "sess-1"
      And querying sessions for client "client-a" does not include "sess-1"

  Rule: User and client lookups clean up stale references

    Scenario: Querying sessions by user ID returns only live sessions and cleans up stale entries
      Given user "user-1" has sessions "sess-1", "sess-2", and "sess-3"
      And session "sess-2" has been expired by Redis TTL
      When sessions are retrieved for user "user-1"
      Then 2 session records are returned for "sess-1" and "sess-3"
      And the stale reference to "sess-2" is removed from the user index

    Scenario: Querying sessions by client ID returns only live sessions and cleans up stale entries
      Given client "client-a" has sessions "sess-1" and "sess-2"
      And session "sess-1" has been expired by Redis TTL
      When sessions are retrieved for client "client-a"
      Then 1 session record is returned for "sess-2"
      And the stale reference to "sess-1" is removed from the client index

  Rule: Touching a session extends only the activity timestamp and TTL

    Scenario: Touching a session updates activity time and resets expiration
      Given a session "sess-1" exists with last activity at "2026-03-05T10:00:00Z"
      When session "sess-1" is touched at "2026-03-05T11:00:00Z"
      Then the session's last activity time is "2026-03-05T11:00:00Z"
      And the session's expiration is extended by the configured TTL
      And all other session fields remain unchanged

  Rule: Bulk deletion operations

    Scenario: Deleting all sessions for a user removes session data and all index entries
      Given user "user-1" has 3 sessions across 2 different clients
      When all sessions for user "user-1" are deleted
      Then the deleted count is 3
      And none of those sessions are retrievable
      And the user index for "user-1" is removed

    Scenario: Purging expired sessions is a no-op since Redis handles expiration natively
      When expired sessions are purged
      Then the purged count is 0

  Rule: Key prefix is applied consistently

    Scenario: A custom key prefix scopes all Redis keys
      Given a Redis session store configured with key prefix "myapp:"
      When a session "sess-1" is saved for user "user-1"
      Then the session is stored under the key prefix "myapp:"
      And the user index is stored under the key prefix "myapp:"
```

## Dependencies
- Depends on: SESS-001 -- `McpSessionStore` interface and `McpSessionRecord`
- Blocks: none (optional production store)

## Technical Notes
- File locations:
  - `packages/nestjs-mcp/src/session/stores/redis-session.store.ts`
  - `packages/nestjs-mcp/src/session/interfaces/redis-client.interface.ts`
- Use Redis `pipeline()` for atomic save operations (HSET + EXPIREAT + SADD should be in one pipeline)
- The `RedisClient` interface should be minimal so both `ioredis` and `@redis/client` satisfy it without adapters
- `findByUserId` lazy cleanup: after resolving all session IDs from the SET, any that return empty `HGETALL` results are stale and should be `SREM`ed. Use a pipeline for the batch `HGETALL` calls.
- Date serialization: store as ISO strings via `toISOString()`, parse back with `new Date(str)`
- `scopes` stored as `JSON.stringify(scopes)`, parsed back with `JSON.parse()`
- `clientInfo` stored as `JSON.stringify(clientInfo)` (nullable -- store `"null"` string)
- No SDK APIs are used directly -- this is a pure storage implementation of the `McpSessionStore` interface from SESS-001
