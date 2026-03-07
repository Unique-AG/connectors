# AUTH-006: MultiAuthProvider — Multiple Auth Sources

## Summary
Implement `MultiAuthProvider` to compose one OAuth server with multiple token verifiers. The provider tries each auth source in order — the server first, then each verifier — and the first non-null `validate()` result wins. This enables scenarios where the MCP server accepts both its own OAuth tokens (for external clients) and JWTs from internal services (for service-to-service calls).

## Background / Context
**FastMCP parity**: FastMCP's `MultiAuth` (v3.1.0+) composes one server (OAuth) with multiple verifiers (JWTVerifier). It tries each in order; the first pass wins. This is essential for production deployments where an MCP server needs to accept tokens from multiple identity providers simultaneously.

Use case example: An Outlook MCP server uses `FullOAuthProvider` with Microsoft OAuth for external MCP clients, plus a `JwtTokenVerifier` for internal Unique platform service tokens. `MultiAuthProvider` chains both so either token type is accepted.

The `server` provider handles OAuth routes (authorization endpoint, token endpoint, discovery, client registration) while verifiers are validation-only — they have no routes. When a verifier validates a token, no OAuth routes are involved for that token's issuer.

For multi-identity upstream scenarios: `ctx.identity.profileId` identifies which upstream API credentials to use — this is application-layer logic, not `MultiAuthProvider`'s concern. `MultiAuthProvider` only handles "which identity provider issued this token."

## Acceptance Criteria
- [ ] `MultiAuthProvider` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Implements `McpAuthProvider` interface: `validate(token: string): Promise<TokenValidationResult | undefined>`
- [ ] Constructor accepts: `{ server: McpAuthProvider & { readonly servesOAuthRoutes: true }, verifiers: [McpAuthProvider, ...McpAuthProvider[]] }`
- [ ] `servesOAuthRoutes` delegates to `this.options.server.servesOAuthRoutes` (NOT hardcoded `true`). Construction throws if `options.server.servesOAuthRoutes === false`.
- [ ] `validate(token)` flow: tries `server.validate(token)` first, then each verifier in order — first non-undefined result wins
- [ ] If ALL providers return `undefined` → `validate()` returns `undefined` (caller returns 401)
- [ ] `server` handles OAuth routes (authorization, token, discovery, client registration) — verifiers do not
- [ ] Each provider builds its own `TokenValidationResult` — `MultiAuthProvider` passes through whichever result is non-undefined
- [ ] Order matters: `server` is always tried first, then verifiers in array order
- [ ] `McpAuthModule.forRootAsync({ useFactory: () => ({ auth: new MultiAuthProvider({ server, verifiers }) }) })` registers OAuth controllers from the `server` provider
- [ ] `MultiAuthProviderOptions.server` is typed as `McpAuthProvider & { readonly servesOAuthRoutes: true }` to prevent passing a `JwtTokenVerifier` as the server at compile time.
- [ ] `verifiers` is typed as `[McpAuthProvider, ...McpAuthProvider[]]` (non-empty tuple). An empty array is rejected at construction.

## BDD Scenarios

```gherkin
Feature: Multi-auth composition of OAuth server with JWT verifiers

  Background:
    Given an MCP server with multi-auth mode
    And the primary OAuth server accepts opaque tokens from its own clients
    And a JWT verifier trusts tokens from "https://auth.unique.ch"

  Rule: The OAuth server is consulted first, then verifiers in order

    Scenario: Opaque token from the OAuth server is accepted immediately
      Given a client presents an opaque token issued by the OAuth server
      When the client connects to the MCP server
      Then the client is authenticated via the OAuth server
      And the JWT verifier is not consulted

    Scenario: JWT from a trusted external issuer is accepted by the verifier
      Given a client presents a JWT issued by "https://auth.unique.ch" for user "alice"
      When the client connects to the MCP server
      Then the OAuth server does not recognize the JWT
      And the JWT verifier validates the token
      And the client is authenticated as user "alice"

    Scenario: First matching verifier wins when multiple could accept
      Given two JWT verifiers are configured: verifier A for "https://auth-a.com" and verifier B for "https://auth-b.com"
      And a client presents a token valid for both verifier A and verifier B
      When the client connects to the MCP server
      Then verifier A validates the token first
      And verifier B is not consulted
      And the identity is from verifier A

  Rule: All providers rejecting a token results in 401

    Scenario: Unrecognized token is rejected by all providers
      Given a client presents a token not recognized by any configured provider
      When the client connects to the MCP server
      Then the connection is rejected with 401 Unauthorized

  Rule: Provider errors are isolated and do not block the chain

    Scenario: OAuth server error does not prevent JWT verifier from succeeding
      Given the OAuth server is experiencing a transient error
      And a client presents a valid JWT from the trusted issuer
      When the client connects to the MCP server
      Then the OAuth server error is silently caught
      And the JWT verifier validates the token
      And the client is authenticated successfully

  Rule: The verifier that matches determines the client identity

    Scenario: JWT-authenticated client identity reflects the JWT claims
      Given a client presents a JWT with subject "jwt-user", email "alice@unique.ch", and scope "admin"
      When the client is authenticated via the JWT verifier
      Then the client identity shows user ID "jwt-user", email "alice@unique.ch", and scopes "admin"

  Rule: Multi-auth with no verifiers behaves as server-only

    Scenario: No verifiers configured -- only the OAuth server validates
      Given multi-auth is configured with no additional verifiers
      And a client presents a valid opaque token
      When the client connects to the MCP server
      Then the client is authenticated via the OAuth server
```

## Dependencies
- **Depends on:** AUTH-001 — `McpAuthProvider` interface that `MultiAuthProvider` implements and composes
- **Depends on:** AUTH-005 — `JwtTokenVerifier` is the primary verifier implementation used in the chain
- **Blocks:** nothing

## Technical Notes

### Implementation
```typescript
export class MultiAuthProvider implements McpAuthProvider {
  // Delegates to server — NOT hardcoded true
  get servesOAuthRoutes(): true {
    return this.options.server.servesOAuthRoutes;
  }

  constructor(private readonly options: MultiAuthProviderOptions) {
    // Guard: server must actually serve OAuth routes (prevents passing JwtTokenVerifier as server)
    if (!options.server.servesOAuthRoutes) {
      throw new Error('MultiAuthProvider: server must have servesOAuthRoutes === true');
    }
    // Guard: verifiers must be non-empty
    if (options.verifiers.length === 0) {
      throw new Error('MultiAuthProvider: verifiers must contain at least one provider');
    }
  }

  async validate(token: string): Promise<TokenValidationResult | undefined> {
    // Try server first
    try {
      const result = await this.options.server.validate(token);
      if (result) return result;
    } catch {
      // Server error → treat as undefined, continue to verifiers
    }

    // Try each verifier in order
    for (const verifier of this.options.verifiers) {
      try {
        const result = await verifier.validate(token);
        if (result) return result;
      } catch {
        // Verifier error → treat as undefined, continue to next
      }
    }

    return undefined; // All providers returned undefined
  }
}

export interface MultiAuthProviderOptions {
  /** Primary auth provider that serves OAuth routes — must have servesOAuthRoutes: true */
  server: McpAuthProvider & { readonly servesOAuthRoutes: true };
  /** Additional token verifiers tried in order after server (non-empty tuple) */
  verifiers: [McpAuthProvider, ...McpAuthProvider[]];
}
```

### Usage example
```typescript
// Outlook MCP server: Microsoft OAuth for clients + Unique JWT for internal services
const oauthProvider = new FullOAuthProvider({
  provider: MicrosoftOAuthProvider,
  clientId: process.env.MS_CLIENT_ID,
  clientSecret: process.env.MS_CLIENT_SECRET,
  hmacSecret: process.env.HMAC_SECRET,
  serverUrl: 'https://outlook-mcp.unique.ch',
  oauthStore: drizzleOAuthStore,
  encryptionService: aesEncryptionService,
});

const internalJwtVerifier = new JwtTokenVerifier({
  jwksUri: 'https://auth.unique.ch/.well-known/jwks.json',
  issuer: 'https://auth.unique.ch',
  audience: 'outlook-mcp-server',
});

McpAuthModule.forRootAsync({
  useFactory: () => ({
    auth: new MultiAuthProvider({
      server: oauthProvider,
      verifiers: [internalJwtVerifier],
    }),
  }),
})
```

### FastMCP parity
Direct equivalent of FastMCP's `MultiAuth`:
```python
# FastMCP equivalent
server = FastMCP(auth=MultiAuth(
    server=OAuthProvider(...),
    verifiers=[JWTVerifier(jwks_uri=..., issuer=..., audience=...)],
))
```

### Key design decisions
1. **Server always first**: The OAuth server provider is tried first because opaque token lookup is typically faster than JWT cryptographic verification. Also matches FastMCP's behavior.
2. **Errors treated as null, not propagated**: If a provider throws unexpectedly, the chain continues. This prevents one provider's transient error from blocking authentication via another provider.
3. **Server serves routes, verifiers don't**: Only the `server` provider's OAuth controllers are registered. Verifiers are stateless validators — they don't expose any HTTP endpoints.
4. **No token type hints**: Unlike some multi-auth systems, we don't inspect the token format to route to the right provider. We just try each in order. This is simpler and matches FastMCP's approach.
5. **profileId for upstream identity**: When a tool needs to know which upstream API credentials to use (e.g. which Microsoft Graph token), it reads `ctx.identity.profileId`. This is application-layer logic built by the `McpIdentityResolver`, not MultiAuthProvider's concern.

### File locations
- `packages/nestjs-mcp/src/auth/providers/multi-auth-provider.ts`
- `packages/nestjs-mcp/src/auth/providers/multi-auth-provider.options.ts`
