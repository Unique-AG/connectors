# AUTH-001: McpAuthModule restructure + sub-entrypoint

## Summary
Implement `McpAuthModule` as a **pluggable auth system** within `@unique-ag/nestjs-mcp/auth` sub-entrypoint. The module accepts different auth providers via the `McpAuthProvider` interface — not just full OAuth. Supported modes: `FullOAuthProvider` (full OAuth 2.1 Authorization Code + PKCE), `JwtTokenVerifier` (stateless JWT validation against external issuer), `OAuthProxyProvider` (bridge for providers without DCR), and `MultiAuthProvider` (compose one OAuth server with multiple verifiers). Auth-specific dependencies (bcrypt, throttler, schedule, typeid-js) are only pulled when consumers import the auth sub-entrypoint. Token revocation (in FullOAuthProvider mode) calls `McpSessionService.terminateUserSessions(userId)` directly (no EventEmitter bridge).

## Background / Context
The framework design mandates a single package (`@unique-ag/nestjs-mcp`) with two sub-entrypoints: the core entrypoint (tools, resources, prompts, pipeline, sessions) and the auth sub-entrypoint (`@unique-ag/nestjs-mcp/auth`). This pattern (like `@nestjs/core` vs `@nestjs/testing`) ensures consumers who do not need auth never pull auth dependencies.

**FastMCP parity**: FastMCP supports 4 distinct auth approaches — `JWTVerifier`, `RemoteAuthProvider`, `OAuthProxy`, `OAuthProvider`, and a `MultiAuth` compositor (v3.1.0+). Our `McpAuthModule` mirrors this by accepting a `McpAuthProvider` union type in `forRootAsync()`, enabling consumers to pick the auth mode appropriate to their deployment without changing framework code.

The auth sub-entrypoint contains:
- `McpAuthModule` — the NestJS dynamic module with `forRootAsync()` configuration accepting a `McpAuthProvider` implementation
- `McpAuthProvider` interface — the common contract all auth modes implement: `{ validate(token: string): Promise<TokenValidationResult | null> }`
- `FullOAuthProvider` — full OAuth 2.1 mode: controllers (discovery, client registration, authorization, token), `OpaqueTokenService`, and session termination on revocation
- `JwtTokenVerifier` — lightweight JWT validation mode (AUTH-005): validates bearer JWTs from an external issuer without running an OAuth server
- `MultiAuthProvider` — multi-auth compositor (AUTH-006): compose one OAuth server with multiple token verifiers, first pass wins
- `McpAuthJwtGuard` — bearer token validation guard (delegates to the configured `McpAuthProvider.validate()`)
- `IOAuthStore` interface — storage abstraction for OAuth state (used by `FullOAuthProvider` mode only)
- `IEncryptionService` interface — encryption abstraction for upstream tokens at rest (used by `FullOAuthProvider` mode only)
- OAuth provider interface — pluggable upstream OAuth providers (Microsoft, Google, etc.) for the full OAuth mode

Token revocation triggers session termination via direct injection (FullOAuthProvider mode only): `OpaqueTokenService` injects `McpSessionService` (from core) and calls `terminateUserSessions(userId)` — no EventEmitter indirection. `JwtTokenVerifier` mode is stateless and has no revocation mechanism.

## Acceptance Criteria

### McpAuthProvider interface (common contract)
- [ ] `McpAuthProvider` interface exported from `@unique-ag/nestjs-mcp/auth` with method: `validate(token: string): Promise<TokenValidationResult | undefined>`
- [ ] `validate()` returns `TokenValidationResult` on success, returns `undefined` when the token is not recognized by this provider (not `null` — follows the project undefined-only convention, enables chaining in MultiAuth)
- [ ] `TokenValidationResult` is a discriminated union on `source: 'oauth' | 'jwt'`; `resource` and `userProfileId` are non-optional in the `oauth` branch only
- [ ] All auth mode implementations (`FullOAuthProvider`, `JwtTokenVerifier`, `MultiAuthProvider`) implement `McpAuthProvider`
- [ ] `McpAuthModuleOptionsSchema` validates options at `forRoot()` time: `serverUrl` is a valid URL, `hmacSecret` is non-empty, `clientId`/`clientSecret` are non-empty strings. Invalid config throws at startup, not at first request.

### Branded types (owned by this module)
- [ ] `BearerToken = z.string().min(1).brand('BearerToken')` — the raw HTTP bearer token string; prevents passing a client secret or encrypted token where a bearer token is expected
- [ ] `HmacSecret = z.string().min(32).brand('HmacSecret')` — HMAC signing key; min(32) enforces minimum key length at parse time
- [ ] `Scope = z.string().min(1).brand('Scope')` — an OAuth scope string (e.g. `'Files.Read'`)
- [ ] All three are exported from `auth/types.ts` and re-exported from `src/types/index.ts`
- [ ] `UserId` and `ClientId` are imported from `src/types/brands.ts` (cross-cutting, defined in INFRA-001)

### McpAuthModule (pluggable auth system)
- [ ] `McpAuthModule` is a NestJS dynamic module with `forRootAsync()` configuration
- [ ] `McpAuthModule.forRootAsync()` accepts an `auth` option typed as `McpAuthProvider` — enabling any auth mode
- [ ] When `auth` is a `FullOAuthProvider`, the module registers OAuth controllers (discovery, client registration, authorization, token), `OpaqueTokenService`, `OAuthExceptionFilter`, throttler, and schedule
- [ ] When `auth` is a `JwtTokenVerifier`, the module registers ONLY the guard — no OAuth controllers, no store, no cron
- [ ] When `auth` is a `MultiAuthProvider`, the module registers OAuth controllers from the `server` provider and guard validation chains through all verifiers
- [ ] `McpAuthJwtGuard` delegates to the configured `McpAuthProvider.validate()` regardless of auth mode
- [ ] `@unique-ag/nestjs-mcp/auth` sub-entrypoint exists and exports `McpAuthModule`, `McpAuthProvider`, all auth guards, services, and interfaces
- [ ] `@unique-ag/nestjs-mcp` (core entrypoint) does NOT export `McpAuthModule` or any auth-specific symbols
- [ ] Auth-only dependencies (`bcrypt`, `@nestjs/throttler`, `nestjs-zod`, `typeid-js`) are listed in the package.json but only resolved when the auth sub-entrypoint is imported (peer or optional deps, or conditional dynamic imports)
- [ ] package.json `exports` field correctly maps `./auth` to the auth sub-entrypoint build output

### FullOAuthProvider mode (existing OAuth 2.1 behavior)
- [ ] `FullOAuthProvider` implements `McpAuthProvider` — its `validate()` delegates to `OpaqueTokenService.validateToken()`
- [ ] `McpAuthModule.forRootAsync()` with `FullOAuthProvider` accepts: `credentials` (`clientId`, `clientSecret`, `hmacSecret`), `serverUrl`, `store` (IOAuthStore instance), `encryptionService` (IEncryptionService instance), optional `metricService`
- [ ] `OpaqueTokenService.revokeToken()` looks up token metadata to retrieve `userId`, removes the token, then calls `McpSessionService.terminateUserSessions(userId)` directly
- [ ] No EventEmitter bridge between auth and sessions
- [ ] `OpaqueTokenService` has constructor dependency on `McpSessionService` (injected from core)
- [ ] Auth controllers are registered: DiscoveryController, ClientController, OAuthController, TokenController
- [ ] `OAuthExceptionFilter` is registered as `APP_FILTER` within the auth module
- [ ] `@nestjs/throttler` is configured within `McpAuthModule` (rate limiting on auth endpoints)
- [ ] `@nestjs/schedule` is imported for token cleanup cron job

## BDD Scenarios

```gherkin
Feature: Pluggable MCP auth module with sub-entrypoint isolation

  Background:
    Given the "@unique-ag/nestjs-mcp" package is installed

  Rule: Auth sub-entrypoint isolates auth-specific code from the core package

    Scenario: Core entrypoint does not expose auth symbols
      When a developer imports "@unique-ag/nestjs-mcp"
      Then the auth module, token services, and auth guards are not available
      And auth-specific dependencies like bcrypt and throttler are not loaded

    Scenario: Auth sub-entrypoint provides all auth exports
      When a developer imports "@unique-ag/nestjs-mcp/auth"
      Then the auth module, token services, auth guards, store interfaces, and encryption interfaces are available

    Scenario: Package exports correctly map sub-entrypoints
      When a bundler resolves "@unique-ag/nestjs-mcp/auth"
      Then it resolves to the auth sub-entrypoint build output
      And the core entrypoint resolves separately to the main build output

  Rule: Full OAuth mode registers complete OAuth 2.1 infrastructure

    Background:
      Given the MCP server is configured with full OAuth mode
      And an OAuth store and encryption service are provided
      And the server URL is "https://mcp.example.com"

    Scenario: Application starts successfully with full OAuth configuration
      When the application starts
      Then OAuth discovery, client registration, authorization, and token endpoints are available
      And rate limiting is active on auth endpoints
      And a scheduled token cleanup job is running

    Scenario: Full OAuth mode requires an OAuth store
      Given the OAuth store is not provided in the configuration
      When the application starts
      Then it fails with an error indicating the OAuth store is required

    Scenario: Full OAuth mode requires an encryption service
      Given the encryption service is not provided in the configuration
      When the application starts
      Then it fails with an error indicating the encryption service is required

  Rule: Access token revocation terminates active MCP sessions

    Background:
      Given the MCP server is configured with full OAuth mode

    Scenario: Revoking an access token disconnects the user's sessions
      Given user "alice" has an active MCP session
      And "alice" has a valid access token
      When the access token is revoked
      Then the token is removed from the store
      And all of "alice"'s active MCP sessions are terminated

    Scenario: Revoking a token for a user with no active sessions succeeds silently
      Given user "bob" has a valid access token but no active MCP sessions
      When the access token is revoked
      Then the token is removed from the store
      And the revocation completes without error

    Scenario: Revoking a nonexistent token is idempotent
      Given a token that does not exist in the store
      When the token is revoked
      Then the revocation completes without error
      And no session termination is attempted

    Scenario: Revoking a refresh token does not terminate sessions
      Given user "charlie" has an active MCP session and a valid refresh token
      When the refresh token is revoked
      Then the refresh token is removed from the store
      And "charlie"'s active MCP sessions remain connected

  Rule: JWT-only mode provides lightweight stateless authentication

    Scenario: Valid JWT from a trusted issuer authenticates the client
      Given the MCP server is configured with JWT-only mode
      And it trusts tokens from "https://auth.unique.ch" for audience "mcp-server"
      And a client presents a valid JWT for user "alice" with scopes "mail.read"
      When the client connects to the MCP server
      Then the connection is accepted
      And the client identity shows user "alice" with scopes "mail.read"
      And no OAuth endpoints are registered on the server

    Scenario: Expired JWT is rejected
      Given the MCP server is configured with JWT-only mode
      And a client presents an expired JWT
      When the client connects to the MCP server
      Then the connection is rejected with 401 Unauthorized

    Scenario: JWT from an untrusted issuer is rejected
      Given the MCP server is configured with JWT-only mode trusting "https://auth.unique.ch"
      And a client presents a valid JWT issued by "https://other-issuer.com"
      When the client connects to the MCP server
      Then the connection is rejected with 401 Unauthorized

    Scenario: JWT-only mode does not require a store or encryption service
      Given the MCP server is configured with JWT-only mode
      And no OAuth store or encryption service is provided
      When the application starts
      Then it starts successfully without error

  Rule: Multi-auth mode composes an OAuth server with additional JWT verifiers

    Scenario: Opaque token from the OAuth server authenticates first
      Given the MCP server is configured with multi-auth mode
      And the OAuth server and one JWT verifier are registered
      And a client presents an opaque token issued by the OAuth server
      When the client connects to the MCP server
      Then the connection is accepted via the OAuth server
      And the JWT verifier is not consulted

    Scenario: JWT from a secondary verifier authenticates when the OAuth server does not recognize it
      Given the MCP server is configured with multi-auth mode
      And the OAuth server and one JWT verifier are registered
      And a client presents a JWT issued by the trusted external issuer
      When the client connects to the MCP server
      Then the OAuth server does not recognize the token
      And the JWT verifier validates the token
      And the connection is accepted with the JWT-based identity

    Scenario: Token rejected by all providers returns 401
      Given the MCP server is configured with multi-auth mode
      And a client presents a token not recognized by any provider
      When the client connects to the MCP server
      Then the connection is rejected with 401 Unauthorized
```

## Dependencies
- Depends on: CORE-012 — `McpModule.forRoot()` must exist so that `McpSessionService` is available for injection
- Depends on: CORE-006 — `McpIdentity` interface; auth providers build `TokenValidationResult` which maps to `McpIdentity`
- Depends on: SESS-004 — `McpSessionService.terminateUserSessions()` must exist for the direct revocation call (FullOAuthProvider mode)
- Blocks: AUTH-002 — userData denormalization modifies OpaqueTokenService which must be structured first
- Blocks: AUTH-003 — DrizzleOAuthStore is exported from the auth sub-entrypoint
- Blocks: AUTH-004 — PrismaOAuthStore is exported from the auth sub-entrypoint
- Blocks: AUTH-005 — `JwtTokenVerifier` implements `McpAuthProvider` interface defined here
- Blocks: AUTH-006 — `MultiAuthProvider` composes `McpAuthProvider` implementations defined here
- Blocks: AUTH-007 — component-level auth extends auth infrastructure
- Blocks: AUTH-008 — `OAuthProxyProvider` implements `McpAuthProvider` interface defined here
- Blocks: AUTH-009 — `RemoteAuthProvider` implements `McpAuthProvider` interface defined here

## Technical Notes

### Sub-entrypoint package.json exports
```json
{
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/index.js"
    },
    "./auth": {
      "types": "./dist/auth/index.d.ts",
      "import": "./dist/auth/index.js"
    }
  }
}
```

### McpAuthProvider interface (common contract)

```typescript
// McpAuthProvider — the common contract all auth modes implement
// This is the core abstraction that enables pluggable auth in McpAuthModule
export interface McpAuthProvider {
  /**
   * Validate a bearer token and return identity information.
   * Returns TokenValidationResult on success, undefined when the token is not recognized
   * by this provider (enables chaining in MultiAuthProvider).
   * Returns undefined (not null) when token is not recognized by this provider.
   */
  validate(token: string): Promise<TokenValidationResult | undefined>;

  /**
   * Whether this provider serves OAuth endpoints (discovery, authorization, token).
   * Only FullOAuthProvider and MultiAuthProvider (via its server) return true.
   */
  readonly servesOAuthRoutes: boolean;
}

// TokenValidationResult — returned by validate() on success
// Discriminated union on `source`: oauth branch requires resource + userProfileId;
// jwt branch makes clientId optional (service tokens may omit client_id claim).
export type TokenValidationResult =
  | {
      source: 'oauth';
      userId: UserId;
      clientId: ClientId;
      scopes: Scope[];
      resource: string;
      userProfileId: UserProfileId;
      email?: string;
      displayName?: string;
      raw: unknown;                             // original opaque token metadata
    }
  | {
      source: 'jwt';
      userId: UserId;
      clientId?: ClientId;
      scopes: Scope[];
      email?: string;
      displayName?: string;
      raw: unknown;                             // original JWT payload
    };
```

### McpAuthModule.forRootAsync() — pluggable auth configuration

```typescript
// McpAuthModuleOptions — configuration accepted by forRootAsync()
// The `auth` field accepts any McpAuthProvider implementation
interface McpAuthModuleOptions {
  auth: McpAuthProvider;                        // FullOAuthProvider | JwtTokenVerifier | MultiAuthProvider
}

// FullOAuthProvider mode — full OAuth 2.1 server (existing behavior)
// Usage: McpAuthModule.forRootAsync({ useFactory: () => ({
//   auth: new FullOAuthProvider({ provider, clientId, clientSecret, ... })
// }) })
interface FullOAuthProviderOptions {
  provider: Type<IOAuthProvider>;               // e.g., MicrosoftOAuthProvider
  clientId: string;
  clientSecret: string;
  hmacSecret: string;
  serverUrl: string;
  resource?: string;                            // defaults to serverUrl
  oauthStore: IOAuthStore;
  encryptionService: IEncryptionService;
  metricService?: IMetricService;
  accessTokenExpiresIn?: number;                // seconds, default 3600
  refreshTokenExpiresIn?: number;               // seconds, default 86400
  authorizationCodeExpiresIn?: number;          // seconds, default 300
}

// JwtTokenVerifier mode — lightweight JWT validation (AUTH-005)
// Usage: McpAuthModule.forRootAsync({ useFactory: () => ({
//   auth: new JwtTokenVerifier({ jwksUri, issuer, audience })
// }) })

// MultiAuthProvider mode — compose multiple auth sources (AUTH-006)
// Usage: McpAuthModule.forRootAsync({ useFactory: () => ({
//   auth: new MultiAuthProvider({ server: fullOAuthProvider, verifiers: [jwtVerifier] })
// }) })
```

### Legacy TypeScript interfaces (FullOAuthProvider mode)

```typescript
// These interfaces are used ONLY by FullOAuthProvider mode
interface FullOAuthProviderOptions {
  provider: Type<IOAuthProvider>;               // e.g., MicrosoftOAuthProvider
  clientId: string;
  clientSecret: string;
  hmacSecret: string;
  serverUrl: string;
  resource?: string;                            // defaults to serverUrl
  oauthStore: IOAuthStore;
  encryptionService: IEncryptionService;
  metricService?: IMetricService;
  accessTokenExpiresIn?: number;                // seconds, default 3600
  refreshTokenExpiresIn?: number;               // seconds, default 86400
  authorizationCodeExpiresIn?: number;          // seconds, default 300
}

// IOAuthStore — storage abstraction (defined in AUTH-001, consumed by AUTH-003/004)
// Full interface: see io-auth-store.interface.ts — 15 required + 3 optional methods

// IEncryptionService — encryption abstraction
interface IEncryptionService {
  encryptToString(plaintext: string): Promise<string>;
  decryptFromString(ciphertext: string): Promise<string>;
}

// IOAuthProvider — pluggable upstream OAuth provider
interface IOAuthProvider {
  readonly providerName: string;
  getAuthorizationUrl(params: AuthorizationParams): string;
  exchangeCodeForTokens(code: string, redirectUri: string): Promise<ProviderTokens>;
  getUserProfile(accessToken: string): Promise<OAuthUserProfile>;
  refreshAccessToken(refreshToken: string): Promise<ProviderTokens>;
}
```

### OpaqueTokenService.revokeToken() — updated flow
```typescript
async revokeToken(token: string, tokenType: 'access' | 'refresh' = 'access'): Promise<boolean> {
  if (tokenType === 'access') {
    // Look up metadata BEFORE removal to get userId for session termination
    const metadata = await this.store.getAccessToken(token);
    await this.store.removeAccessToken(token);
    // Direct call — no EventEmitter
    if (metadata?.userId) {
      await this.sessionService.terminateUserSessions(metadata.userId);
    }
  } else {
    await this.store.removeRefreshToken(token);
    // Refresh token revocation does NOT terminate sessions
  }
  return true;
}
```

### Auth sub-entrypoint index.ts exports
The `src/auth/index.ts` barrel file exports:
- `McpAuthModule`
- `OpaqueTokenService`, `TokenPair`, `TokenValidationResult`
- `McpAuthJwtGuard`
- `IOAuthStore`, `AccessTokenMetadata`, `RefreshTokenMetadata`
- `IEncryptionService`
- `IOAuthProvider`, `OAuthUserProfile`, `OAuthSession`
- `OAuthClient`, `AuthorizationCode`
- `DrizzleOAuthStore` (AUTH-003), `PrismaOAuthStore` (AUTH-004)
- Injection tokens: `OAUTH_STORE_TOKEN`, `ENCRYPTION_SERVICE_TOKEN`

### SDK auth APIs used
- No direct `@modelcontextprotocol/sdk` auth APIs are used in this ticket. The SDK's `ProxyOAuthServerProvider` and `authMiddleware` are NOT used — the framework implements its own OAuth 2.1 server with opaque tokens, which is more flexible than the SDK's built-in auth.
- The auth guard validates bearer tokens at the HTTP level (before the MCP protocol layer), which is the correct approach per the MCP spec's OAuth 2.1 requirement.

### Design decisions
1. **Pluggable auth via McpAuthProvider interface**: Mirrors FastMCP's approach of supporting multiple auth modes (`JWTVerifier`, `OAuthProvider`, `OAuthProxy`, `MultiAuth`). The `McpAuthProvider` interface is the single abstraction — `McpAuthJwtGuard` calls `validate()` without knowing which mode is active.
2. **Guard delegates to provider, not to OpaqueTokenService directly**: `McpAuthJwtGuard.canActivate()` calls `this.authProvider.validate(token)` where `authProvider` is the configured `McpAuthProvider`. In FullOAuth mode this delegates to opaque token lookup; in JWT mode it delegates to JWT verification; in MultiAuth mode it chains through providers.
3. **Conditional module registration**: When `auth.servesOAuthRoutes` is false (JwtTokenVerifier mode), OAuth controllers, throttler, schedule, and OpaqueTokenService are NOT registered. This keeps the module lightweight for JWT-only deployments.
4. **Direct injection over EventEmitter** (FullOAuthProvider mode): `OpaqueTokenService` directly injects `McpSessionService` because both live in the same package. This eliminates the EventEmitter bridge and its associated complexity.
5. **Metadata lookup before revocation** (FullOAuthProvider mode): `revokeToken()` must call `getAccessToken()` before `removeAccessToken()` to retrieve the `userId` needed for session termination.
6. **Refresh token revocation skips session termination**: Only access token revocation triggers session cleanup. Refresh tokens are used to obtain new access tokens, not to maintain active sessions.
7. **Auth sub-entrypoint imports from core's public API only**: The auth barrel (`src/auth/index.ts`) can import `McpSessionService` from the core entrypoint, but must NOT import from core's internal modules to avoid tight coupling.

### Sub-entrypoint path mapping
Sub-entrypoint path: `@unique-ag/mcp-kit/auth` maps to `src/auth/index.ts`. The tsconfig `paths` and package.json `exports` field must both declare this path: `"./auth": "./dist/auth/index.js"`. Consumers import: `import { McpAuthModule } from '@unique-ag/mcp-kit/auth'`.

### McpSessionService injection token
`McpSessionService` is injected via `@Inject(MCP_SESSION_SERVICE)` token, not by class reference, to avoid circular dependency between the auth module and session module.

### FastMCP parity
| FastMCP auth mode | Our equivalent | Ticket |
|---|---|---|
| `OAuthProvider` (full OAuth 2.1 server) | `FullOAuthProvider` | AUTH-001 (this ticket) |
| `JWTVerifier` (stateless JWT validation) | `JwtTokenVerifier` | AUTH-005 |
| `OAuthProxy` (bridge for non-DCR providers) | `OAuthProxyProvider` | AUTH-008 |
| `RemoteAuthProvider` (delegate to external DCR provider) | `RemoteAuthProvider` | AUTH-009 |
| `MultiAuth` (compose server + verifiers) | `MultiAuthProvider` | AUTH-006 |
