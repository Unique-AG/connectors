# AUTH-003: DrizzleOAuthStore built-in implementation

## Summary
Implement `DrizzleOAuthStore implements IOAuthStore` as a reusable, built-in store class within `@unique-ag/nestjs-mcp/auth`. The store provides all 18 `IOAuthStore` methods (15 required + 3 optional) using Drizzle ORM, with cache-through token lookups, encryption-at-rest for upstream provider tokens, and token family revocation. Built-in Drizzle schema definitions are exported so consumers can include them in their migrations. This eliminates ~430 lines of duplicated store implementation per service.

## Background / Context
The `IOAuthStore` interface (defined in AUTH-001) abstracts all OAuth state persistence: client management, authorization codes, OAuth sessions, access/refresh tokens, user profiles, and token family management. Without a built-in implementation, every service must implement all 18 methods from scratch.

`DrizzleOAuthStore` is the first built-in implementation, targeting teams that use Drizzle ORM. It follows the cache-through pattern for high-frequency token lookups (access/refresh token validation) and encrypts upstream provider tokens (from the OAuth provider, e.g., Microsoft Graph tokens) at rest via `IEncryptionService`.

The constructor takes three dependencies:
1. `DrizzleDatabase` — the Drizzle client instance (generic, not tied to a specific dialect)
2. `IEncryptionService` — for encrypting upstream provider tokens at rest (AES-GCM)
3. `Cache` (from `cache-manager`) — for caching token lookups with TTL matching token expiration

## Acceptance Criteria
- [ ] `DrizzleOAuthStore` class implements all `IOAuthStore` methods (15 required + 3 optional)
- [ ] Constructor signature: `new DrizzleOAuthStore(drizzle, encryptionService, cacheManager)`
- [ ] Built-in Drizzle schema definitions exported for consumers to include in their migrations: `oauthClients`, `authorizationCodes`, `oauthSessions`, `tokens`, `userProfiles`
- [ ] Case-converter utilities included: `fromDrizzleAuthCodeRow`, `fromDrizzleOAuthClientRow`, `fromDrizzleSessionRow`, `toDrizzleAuthCodeInsert`, `toDrizzleOAuthClientInsert`, `toDrizzleSessionInsert`
- [ ] Upstream provider tokens (accessToken, refreshToken in user profiles) encrypted at rest via `IEncryptionService`
- [ ] Access token lookups use cache-through pattern: check cache first, fall back to DB, cache result with TTL
- [ ] Refresh token lookups use the same cache-through pattern
- [ ] Cache invalidated on token removal and revocation
- [ ] Token family revocation removes all tokens in family from both DB and cache
- [ ] `cleanupExpiredTokens()` deletes expired tokens, auth codes, and sessions older than N days
- [ ] `generateClientId()` generates typeid-prefixed client IDs (e.g., `typeid(normalizedClientName).toString()`)
- [ ] `getAuthCode()` auto-removes expired codes and returns undefined
- [ ] `getOAuthSession()` auto-removes expired sessions and returns undefined
- [ ] Exported from `@unique-ag/nestjs-mcp/auth`
- [ ] When `cacheTtlMs` is set to `0`, caching is disabled entirely — every `findToken()` call hits the database

## BDD Scenarios

```gherkin
Feature: Drizzle-based OAuth store with caching and encryption

  Background:
    Given a Drizzle OAuth store connected to an empty database
    And an encryption service is configured
    And a cache manager is configured

  Rule: OAuth clients are persisted with typeid-prefixed identifiers

    Scenario: Registering a new OAuth client
      When a client named "test-app" is registered with redirect URI "https://example.com/callback"
      Then the client is stored in the database
      And the client receives a typeid-prefixed client ID
      And the client can be retrieved by its client ID

    Scenario: Finding a client by name
      Given a client named "test-app" has been registered
      When looking up a client by the name "test-app"
      Then the registered client is returned

    Scenario: Looking up a nonexistent client by name
      When looking up a client by the name "nonexistent"
      Then no client is returned

  Rule: Token lookups use cache-through pattern for performance

    Scenario: First access token lookup reads from the database and caches
      Given an access token has been stored for user "alice"
      When the access token is looked up for the first time
      Then the token metadata is fetched from the database
      And the result is cached with a TTL matching the token's remaining lifetime

    Scenario: Subsequent access token lookups are served from cache
      Given an access token has been stored and looked up once (cached)
      When the same access token is looked up again
      Then the result is served from cache without a database query

    Scenario: Removing a token evicts it from the cache
      Given an access token is stored and cached
      When the access token is removed
      Then the token is deleted from the database
      And the cache entry is evicted
      And subsequent lookups return nothing

    Scenario: Refresh token lookups follow the same cache-through pattern
      Given a refresh token has been stored for user "alice" in token family "fam-001"
      When the refresh token is looked up for the first time
      Then it is fetched from the database and cached
      And subsequent lookups are served from cache

    Scenario: Looking up a nonexistent token returns nothing
      Given no token with value "tok_missing" exists
      When the token is looked up
      Then nothing is returned
      And no cache entry is created

  Rule: Upstream provider tokens are encrypted at rest

    Scenario: Storing a user profile encrypts upstream tokens
      Given a Microsoft user "ms-user-001" with Graph API access and refresh tokens
      When the user profile is stored
      Then the upstream access token and refresh token are encrypted before persisting
      And the database row contains encrypted values, not plaintext

    Scenario: Retrieving a user profile decrypts upstream tokens
      Given a user profile has been stored with encrypted upstream tokens
      When the user profile is retrieved
      Then the access token and refresh token are returned decrypted
      And the email and display name are returned as-is

    Scenario: Encryption failure prevents profile storage
      Given the encryption service is unavailable
      When a user profile is stored
      Then the operation fails with an error
      And no profile is persisted in the database

  Rule: User profile upserts produce stable identifiers

    Scenario: Re-storing a user profile returns the same profile ID
      Given a Microsoft user "ms-user-001" was previously stored with profile ID "prof-abc"
      When the same user's profile is stored again with updated tokens
      Then the same profile ID "prof-abc" is returned
      And the tokens are updated in the existing row

  Rule: Token families can be revoked atomically

    Scenario: Revoking a token family removes all tokens in the family
      Given three tokens exist in token family "fam-001"
      When the token family "fam-001" is revoked
      Then all three tokens are deleted from the database
      And all corresponding cache entries are evicted

    Scenario: Marking a refresh token as used enables reuse detection
      Given a refresh token has not been used
      When the refresh token is marked as used
      Then the token is flagged with the current timestamp
      And subsequent reuse checks report the token as already used

  Rule: Expired entities are automatically cleaned up

    Scenario: Looking up an expired authorization code auto-removes it
      Given an authorization code that has expired
      When the authorization code is looked up
      Then the expired code is removed from the database
      And nothing is returned

    Scenario: Looking up an expired OAuth session auto-removes it
      Given an OAuth session that has expired
      When the OAuth session is looked up
      Then the expired session is removed from the database
      And nothing is returned

    Scenario: Bulk cleanup removes expired tokens and codes
      Given 5 expired tokens older than 7 days, 2 expired authorization codes, and 3 current tokens
      When expired entity cleanup runs with a 7-day threshold
      Then the 5 expired tokens and 2 expired codes are deleted
      And the 3 current tokens remain
```

## Dependencies
- Depends on: AUTH-001 — auth sub-entrypoint must exist; `IOAuthStore` interface must be defined
- Blocks: AUTH-004 — PrismaOAuthStore mirrors the pattern established here

## Technical Notes

### IOAuthStore methods to implement (18 total)

**Client management (4):**
1. `storeClient(client)` — insert into `oauthClients`, return mapped result
2. `getClient(clientId)` — select by `clientId`
3. `findClient(clientName)` — select by `clientName`
4. `generateClientId(client)` — `typeid(normalizedName).toString()`

**Authorization code management (3):**
5. `storeAuthCode(code)` — insert into `authorizationCodes`
6. `getAuthCode(code)` — select, check expiry, auto-remove if expired
7. `removeAuthCode(code)` — delete from `authorizationCodes`

**OAuth session management (3):**
8. `storeOAuthSession(sessionId, session)` — insert into `oauthSessions`
9. `getOAuthSession(sessionId)` — select, check expiry, auto-remove if expired
10. `removeOAuthSession(sessionId)` — delete from `oauthSessions`

**Token management (6):**
11. `storeAccessToken(token, metadata)` — insert into `tokens` + cache
12. `getAccessToken(token)` — cache-through lookup, joins `userProfiles` for `userData`
13. `removeAccessToken(token)` — delete from DB + evict cache
14. `storeRefreshToken(token, metadata)` — insert into `tokens` + cache
15. `getRefreshToken(token)` — cache-through lookup
16. `removeRefreshToken(token)` — delete from DB + evict cache

**Optional (3):**
17. `revokeTokenFamily(familyId)` — delete all tokens in family + evict cache for each
18. `markRefreshTokenAsUsed(token)` — set `usedAt` field + evict cache
19. `isRefreshTokenUsed(token)` — check `usedAt` (always DB, not cache)

**User profile (2):**
20. `upsertUserProfile(user)` — upsert with encryption, return stable `profileId`
21. `getUserProfileById(profileId)` — select + decrypt tokens, return mapped profile

**Cleanup (1):**
22. `cleanupExpiredTokens(olderThanDays)` — delete expired tokens, codes, sessions

### Schema exports
Export Drizzle table definitions so consumers include them in their migrations:
```typescript
// @unique-ag/nestjs-mcp/auth
export { oauthClients, authorizationCodes, oauthSessions, tokens, userProfiles } from './drizzle/schema';
```

### Cache key patterns
- Access tokens: `access_token:{token}`
- Refresh tokens: `refresh_token:{token}`
- TTL calculation: `Math.max(0, Math.floor((expiresAt.getTime() - Date.now()) / 1000))`

### Constructor signature
```typescript
export class DrizzleOAuthStore implements IOAuthStore {
  constructor(
    private readonly drizzle: DrizzleDatabase,         // generic Drizzle client
    private readonly encryptionService: IEncryptionService,
    private readonly cacheManager: Cache,              // from cache-manager
  ) {}
}
```

### Column naming convention
Column naming: use Drizzle's built-in `snake_case` column naming convention. TypeScript fields are camelCase (`accessToken`, `refreshToken`); database columns are snake_case (`access_token`, `refresh_token`) via `{ columnName: 'access_token' }` or a global `snake_case` plugin.

### Drizzle schema for `oauth_access_tokens` table
```typescript
import { pgTable, text, timestamp, json } from 'drizzle-orm/pg-core';

export const oauthAccessTokens = pgTable('oauth_access_tokens', {
  id: text('id').primaryKey(),
  token: text('token').notNull().unique(),
  type: text('type').notNull(),                          // 'ACCESS' | 'REFRESH'
  userId: text('user_id').notNull(),
  clientId: text('client_id').notNull(),
  scope: text('scope'),
  resource: text('resource'),
  userProfileId: text('user_profile_id').notNull(),
  familyId: text('family_id'),
  generation: integer('generation'),
  usedAt: timestamp('used_at'),
  userData: json('user_data'),                           // TokenUserData (denormalized)
  expiresAt: timestamp('expires_at').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});
```

### Key design decisions
1. **Cache-through, not cache-aside**: `getAccessToken()` and `getRefreshToken()` always check cache first, populate on miss. This is optimal for token validation which happens on every request.
2. **Encryption scope**: Only upstream provider tokens (in `userProfiles`) are encrypted — not OAuth client secrets or authorization codes. Client secrets use bcrypt hashing (one-way), not reversible encryption.
3. **Generic Drizzle client**: The constructor accepts a generic `DrizzleDatabase` type, not tied to PostgreSQL or MySQL. Consumers provide their own configured Drizzle instance.
4. **Schema is exported, not auto-applied**: Consumers include the Drizzle schema tables in their own migration setup. The store does NOT run migrations automatically.

### SDK APIs used
No `@modelcontextprotocol/sdk` APIs are directly used. This is a pure NestJS/Drizzle storage implementation.
