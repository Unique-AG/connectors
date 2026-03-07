# AUTH-004: PrismaOAuthStore built-in implementation

## Summary
Implement `PrismaOAuthStore implements IOAuthStore` with all 18 methods (15 required + 3 optional), equivalent to `DrizzleOAuthStore` (AUTH-003) but using Prisma Client. Include the required Prisma schema snippet in documentation so consumers can add the necessary models to their `schema.prisma`. This provides a second built-in store option for teams using Prisma instead of Drizzle.

## Background / Context
AUTH-003 provides a Drizzle-based implementation of `IOAuthStore`. Some teams use Prisma instead of Drizzle. Rather than forcing a Drizzle dependency, `PrismaOAuthStore` provides identical behavior using Prisma Client. The store follows the same cache-through pattern, encryption-at-rest for upstream tokens, and token family management as the Drizzle variant.

`PrismaClient` is a peer dependency — only pulled if the consumer imports and uses `PrismaOAuthStore`. The implementation mirrors `DrizzleOAuthStore` method-by-method, replacing Drizzle query builder calls with Prisma Client equivalents.

## Acceptance Criteria
- [ ] `PrismaOAuthStore` class implements all `IOAuthStore` methods (15 required + 3 optional)
- [ ] Constructor signature: `new PrismaOAuthStore(prisma, encryptionService, cacheManager)`
- [ ] Behavior identical to `DrizzleOAuthStore` for all 18 methods (same inputs produce same logical outputs)
- [ ] Required Prisma schema models documented and exported as a `.prisma` snippet file
- [ ] Upstream provider tokens (accessToken, refreshToken in user profiles) encrypted at rest via `IEncryptionService`
- [ ] Cache-through pattern for access and refresh token lookups (same key patterns as DrizzleOAuthStore)
- [ ] Cache invalidated on token removal, revocation, and `markRefreshTokenAsUsed()`
- [ ] `@prisma/client` is a peer dependency, not a hard dependency
- [ ] `PrismaClient` type accepted generically (not hard-coded to a specific generated client)
- [ ] `generateClientId()` generates typeid-prefixed client IDs (same as DrizzleOAuthStore)
- [ ] `getAuthCode()` auto-removes expired codes and returns undefined
- [ ] `getOAuthSession()` auto-removes expired sessions and returns undefined
- [ ] Exported from `@unique-ag/nestjs-mcp/auth`

## BDD Scenarios

```gherkin
Feature: Prisma-based OAuth store with caching and encryption

  Background:
    Given a Prisma OAuth store connected to an empty database
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
      Then the token metadata is fetched from the database with associated profile data
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
      Given a Microsoft user "ms-user-001" with upstream access and refresh tokens
      When the user profile is stored
      Then the upstream tokens are encrypted before persisting
      And the database contains encrypted values, not plaintext

    Scenario: Retrieving a user profile decrypts upstream tokens
      Given a user profile has been stored with encrypted upstream tokens
      When the user profile is retrieved
      Then the access token and refresh token are returned decrypted

    Scenario: Encryption failure prevents profile storage
      Given the encryption service is unavailable
      When a user profile is stored
      Then the operation fails with an error
      And no profile is persisted

  Rule: User profile upserts produce stable identifiers

    Scenario: Re-storing a user profile returns the same profile ID
      Given a Microsoft user "ms-user-001" was previously stored
      When the same user's profile is stored again with updated tokens
      Then the same profile ID is returned
      And the tokens are updated in the existing row

  Rule: Token family revocation is atomic

    Scenario: Revoking a token family removes all tokens atomically
      Given three tokens exist in token family "fam-001"
      When the token family "fam-001" is revoked
      Then all three tokens are deleted in a single transaction
      And all corresponding cache entries are evicted
      And if any deletion fails, none of the tokens are removed

    Scenario: Marking a refresh token as used enables reuse detection
      Given a refresh token has not been used
      When the refresh token is marked as used
      Then the token is flagged with the current timestamp
      And the cache entry is evicted
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
      Then the expired tokens and codes are deleted
      And the current tokens remain
```

## Dependencies
- Depends on: AUTH-001 — auth sub-entrypoint must exist; `IOAuthStore` interface must be defined
- Depends on: AUTH-003 — Drizzle version establishes the pattern (cache key formats, encryption approach, method behavior); Prisma version mirrors it

## Technical Notes

### Prisma schema models required
```prisma
model OAuthClient {
  id            String   @id @default(uuid())
  clientId      String   @unique @map("client_id")
  clientName    String   @map("client_name")
  clientSecret  String?  @map("client_secret")
  redirectUris  String[] @map("redirect_uris")
  grantTypes    String[] @map("grant_types")
  responseTypes String[] @map("response_types")
  scope         String?
  tokenEndpointAuthMethod String? @map("token_endpoint_auth_method")
  createdAt     DateTime @default(now()) @map("created_at")
  updatedAt     DateTime @updatedAt @map("updated_at")

  @@map("oauth_clients")
}

model AuthorizationCode {
  id          String   @id @default(uuid())
  code        String   @unique
  clientId    String   @map("client_id")
  userId      String   @map("user_id")
  scope       String?
  redirectUri String   @map("redirect_uri")
  expiresAt   DateTime @map("expires_at")
  codeChallenge       String? @map("code_challenge")
  codeChallengeMethod String? @map("code_challenge_method")
  createdAt   DateTime @default(now()) @map("created_at")

  @@map("authorization_codes")
}

model OAuthSession {
  id        String   @id @default(uuid())
  sessionId String   @unique @map("session_id")
  state     String?
  nonce     String?
  expiresAt DateTime? @map("expires_at")
  metadata  Json?
  createdAt DateTime @default(now()) @map("created_at")

  @@map("oauth_sessions")
}

model Token {
  id            String    @id @default(uuid())
  token         String    @unique
  type          String    // ACCESS or REFRESH
  expiresAt     DateTime  @map("expires_at")
  userId        String    @map("user_id")
  clientId      String    @map("client_id")
  scope         String?
  resource      String?
  userProfileId String    @map("user_profile_id")
  familyId      String?   @map("family_id")
  generation    Int?
  usedAt        DateTime? @map("used_at")
  userData      Json?     @map("user_data")
  createdAt     DateTime  @default(now()) @map("created_at")

  userProfile   UserProfile @relation(fields: [userProfileId], references: [id])

  @@map("tokens")
}

model UserProfile {
  id              String   @id @default(uuid())
  provider        String
  providerUserId  String   @map("provider_user_id")
  username        String?
  email           String?
  displayName     String?  @map("display_name")
  avatarUrl       String?  @map("avatar_url")
  raw             Json?
  accessToken     String   @map("access_token")  // encrypted
  refreshToken    String   @map("refresh_token")  // encrypted
  createdAt       DateTime @default(now()) @map("created_at")
  updatedAt       DateTime @updatedAt @map("updated_at")

  tokens          Token[]

  @@unique([provider, providerUserId])
  @@map("user_profiles")
}
```

### Constructor signature
```typescript
export class PrismaOAuthStore implements IOAuthStore {
  constructor(
    private readonly prisma: PrismaClient,              // generic PrismaClient type
    private readonly encryptionService: IEncryptionService,
    private readonly cacheManager: Cache,               // from cache-manager
  ) {}
}
```

### Implementation approach
- Mirror `DrizzleOAuthStore` method-by-method, replacing Drizzle query builder with Prisma Client:
  - `drizzle.select().from(table).where(eq(...))` → `prisma.model.findUnique({ where: { ... } })`
  - `drizzle.insert(table).values(...)` → `prisma.model.create({ data: { ... } })`
  - `drizzle.delete(table).where(...)` → `prisma.model.delete({ where: { ... } })`
- Use `prisma.$transaction()` where atomicity is needed (e.g., `revokeTokenFamily` — query tokens first to get cache keys, then delete all)
- Cache key patterns identical to Drizzle variant: `access_token:{token}`, `refresh_token:{token}`
- `PrismaClient` type should be accepted generically via TypeScript generics, not hard-coded to a specific generated client
- For `getAccessToken()`, use `prisma.token.findUnique({ include: { userProfile: true } })` to join profile data for `userData` field

### Cross-ticket interface contracts
- **AUTH-001 defines**: `IOAuthStore` interface (the contract PrismaOAuthStore implements)
- **AUTH-003 establishes**: The behavioral pattern (cache keys, encryption approach, auto-removal of expired entities) that PrismaOAuthStore must match
- **AUTH-002 defines**: `TokenUserData` type stored in `AccessTokenMetadata.userData` — PrismaOAuthStore's `storeAccessToken()` persists this and `getAccessToken()` returns it

### SDK APIs used
No `@modelcontextprotocol/sdk` APIs are directly used. This is a pure NestJS/Prisma storage implementation.

### Scopes serialization
`scopes` is stored as a JSON string in the database (Prisma `String` field with JSON serialization in the store layer). The store serializes `string[]` to `JSON.stringify(scopes)` on write and `JSON.parse(scopesJson)` on read.

### Transaction isolation
Transaction isolation: use Prisma's default isolation level (READ COMMITTED on PostgreSQL, REPEATABLE READ on MySQL). No explicit isolation level override is needed for upsert operations.

### PrismaClient typing
`PrismaClient` is accepted as `PrismaClient` (the generated class). Type it as `{ oauthAccessToken: { upsert: Function, findUnique: Function, delete: Function } }` if you need to avoid importing the generated client directly in the library.

### Key design decisions
1. **Peer dependency**: `@prisma/client` is a peer dependency. If a consumer doesn't use Prisma, they never install it. The import is only resolved when `PrismaOAuthStore` is actually instantiated.
2. **Schema snippet, not auto-migration**: The Prisma schema is provided as documentation/snippet. Consumers copy it into their own `schema.prisma`. The store does NOT run `prisma migrate` automatically.
3. **Token model includes `userData` column**: The `Token` model has a `userData Json?` column to store denormalized profile data (per AUTH-002). This is populated by `storeAccessToken()` and returned by `getAccessToken()`.
4. **Transaction for family revocation**: `revokeTokenFamily()` must first query all tokens in the family (to get token strings for cache eviction), then delete them all. This is wrapped in a transaction for atomicity.
