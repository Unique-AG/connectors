# CONN-001: Upstream Connection Store

## Summary
Implement the core data model and pluggable storage interface for upstream OAuth connections. An **upstream connection** is a `(userId, providerId, encryptedTokens)` record representing a user's live OAuth session with one upstream provider. This is the shared foundation used by both the pre-auth gate (CONN-002) and the runtime reconnection guard (CONN-004/CONN-005).

## Background / Context
When a user connects to XYZ MCP server, they may need valid tokens for multiple upstream providers (e.g., Microsoft Graph and Google Drive). These are entirely separate OAuth accounts with separate tokens, scopes, and expiry windows.

The connection store is the single place where these tokens are persisted. It is:
- **Session-scoped in memory** for development/single-instance use
- **Redis- or DB-backed** for production multi-instance deployments
- **Always encrypted at rest** (AES-256-GCM) — raw tokens never stored in plaintext

The store must support:
1. Storing tokens received from an OAuth callback
2. Retrieving and auto-decrypting tokens for use in tool handlers
3. Checking whether a token is expired (with a configurable lead time for refresh)
4. Storing a refreshed token atomically (replacing the old one)
5. Revoking a connection (user disconnects a provider)

## Acceptance Criteria

### Data model
- [ ] `UpstreamConnection` interface: `{ userId, providerId, accessToken (encrypted), refreshToken? (encrypted), expiresAt, scopes, metadata? }`
- [ ] `providerId` is a free-form string — `'microsoft-graph'`, `'google-drive'`, `'slack'`, etc.
- [ ] `accessToken` and `refreshToken` are always stored encrypted; the store implementation handles encryption/decryption transparently
- [ ] `metadata` is an optional `Record<string, unknown>` for provider-specific data (e.g., tenant ID, user email on the upstream)

### McpConnectionStore interface
- [ ] `McpConnectionStore` interface exported from `@unique-ag/mcp-kit`
- [ ] `get(userId, providerId): Promise<UpstreamConnection | undefined>`
- [ ] `set(userId, providerId, connection: UpstreamConnection): Promise<void>`
- [ ] `delete(userId, providerId): Promise<void>`
- [ ] `listByUser(userId): Promise<UpstreamConnection[]>` — returns all connections for a user
- [ ] `isExpired(connection, leadTimeMs?: number): boolean` — true if `expiresAt < now + leadTime` (default lead time: 30 seconds)

### InMemoryConnectionStore (built-in)
- [ ] `InMemoryConnectionStore` implements `McpConnectionStore`
- [ ] Stores connections in a `Map<string, UpstreamConnection>` keyed by `${userId}:${providerId}`
- [ ] Connections are lost on process restart (documented limitation)
- [ ] No external dependencies

### Injection token
- [ ] `MCP_CONNECTION_STORE` symbol exported as the DI injection token
- [ ] Registered as `{ provide: MCP_CONNECTION_STORE, useClass: InMemoryConnectionStore }` by default in `McpConnectionModule`
- [ ] Consumers can override: `{ provide: MCP_CONNECTION_STORE, useClass: RedisConnectionStore }`

### Encryption service
- [ ] `TokenEncryptionService` is a `@Injectable()` singleton
- [ ] `encrypt(plaintext: string): string` — AES-256-GCM with random IV, returns base64-encoded `iv:ciphertext:tag`
- [ ] `decrypt(ciphertext: string): string`
- [ ] Key sourced from `McpConnectionModuleOptions.encryptionKey` (required, min 32 bytes, validated on module init)
- [ ] If `encryptionKey` is not set and `NODE_ENV !== 'test'`, module init throws a descriptive error

### Branded types (owned by this module)
- [ ] `ProviderId = z.string().min(1).brand('ProviderId')` — upstream provider identifier slug (e.g. `'microsoft-graph'`); prevents passing a `UserId` or `SessionId` in a provider slot
- [ ] `EncryptedToken = z.string().min(1).brand('EncryptedToken')` — AES-256-GCM ciphertext; prevents using an encrypted value as a raw access token
- [ ] `RawAccessToken = z.string().min(1).brand('RawAccessToken')` — decrypted upstream access token; prevents storing a raw token in a slot expecting encrypted data
- [ ] All three exported from `connection/types.ts` and re-exported from `src/types/index.ts`
- [ ] `UserId` is imported from `src/types/brands.ts`

### McpConnectionModule
- [ ] `McpConnectionModule.forRoot({ encryptionKey, store?: Type<McpConnectionStore> })` static factory
- [ ] `McpConnectionModule.forRootAsync({ useFactory, inject })` async factory
- [ ] Exports `McpConnectionStore` (via token) and `TokenEncryptionService`
- [ ] Module is importable standalone or as part of `McpModule`

## BDD Scenarios

```gherkin
Feature: Upstream Connection Store
  The connection store persists encrypted OAuth tokens for upstream providers
  per user, enabling both pre-auth and runtime reconnection flows.

  Rule: Connections are stored and retrieved by (userId, providerId)

    Scenario: Storing and retrieving a connection
      Given a connection store with encryption configured
      When a connection for user "alice" and provider "microsoft-graph" is stored with access token "tok_abc"
      Then retrieving "alice" + "microsoft-graph" returns a connection with the access token decrypted to "tok_abc"

    Scenario: Unknown connection returns undefined
      Given an empty connection store
      When retrieving user "alice" + provider "slack"
      Then undefined is returned

    Scenario: Overwriting a connection replaces the previous one
      Given user "alice" has a stored connection for "google-drive" with token "old_token"
      When a new connection for "alice" + "google-drive" is stored with token "new_token"
      Then retrieving "alice" + "google-drive" returns "new_token"

  Rule: Tokens are always encrypted at rest

    Scenario: Raw token is never stored in plaintext
      Given a connection store
      When a connection with access token "super_secret_token" is stored
      Then the internal store does not contain the string "super_secret_token" anywhere

    Scenario: Decryption produces the original token
      Given a stored connection with access token "tok_xyz"
      When the connection is retrieved
      Then the decrypted access token equals "tok_xyz"

  Rule: Expiry detection uses configurable lead time

    Scenario: Token expiring in 10 seconds is considered expired with default 30s lead
      Given a connection whose access token expires in 10 seconds
      When isExpired is called with the default lead time
      Then it returns true

    Scenario: Token expiring in 60 seconds is not expired with default 30s lead
      Given a connection whose access token expires in 60 seconds
      When isExpired is called with the default lead time
      Then it returns false

    Scenario: Custom lead time is respected
      Given a connection whose access token expires in 45 seconds
      When isExpired is called with a 60 second lead time
      Then it returns true

  Rule: Missing encryption key causes a startup error

    Scenario: Module init fails without encryption key outside tests
      Given NODE_ENV is set to "production"
      And McpConnectionModule is configured without an encryption key
      When the application starts
      Then an error is thrown: "McpConnectionModule: encryptionKey is required"

  Rule: Store is replaceable via DI

    Scenario: Custom Redis store is used when provided
      Given McpConnectionModule configured with a RedisConnectionStore class
      When a connection is stored
      Then the RedisConnectionStore.set method is called
      And InMemoryConnectionStore is not used
```

## FastMCP Parity
FastMCP (Python) stores upstream tokens per-user using Fernet encryption in configurable backends (disk, Redis, DynamoDB). Our `McpConnectionStore` mirrors this pattern but integrates with NestJS DI rather than FastMCP's standalone storage layer.

## Dependencies
- **Depends on:** none (foundation ticket)
- **Blocks:** CONN-002, CONN-003, CONN-004, CONN-005

## Technical Notes
- AES-256-GCM chosen over Fernet: native to Node.js `crypto` module, no extra dependency, authenticated encryption (prevents tampering)
- Encryption key rotation is out of scope for v1 — document that changing `encryptionKey` invalidates all stored connections
- `listByUser()` is used by CONN-002 to check which providers a user has already connected (for portal pre-auth status display)
- The store is intentionally simple — no TTL-based eviction. Expired tokens remain in the store; callers use `isExpired()` to decide whether to refresh or reconnect. This avoids race conditions between background eviction and concurrent refresh attempts.
