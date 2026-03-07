# AUTH-005: JwtTokenVerifier — Lightweight JWT Validation Mode

## Summary
Implement `JwtTokenVerifier` as a lightweight auth mode that validates bearer JWTs from an external issuer (e.g. Unique platform, Auth0, Okta) without running an OAuth server. This is the simplest auth mode — purely stateless token validation using JWKS key discovery. Implements the `McpAuthProvider` interface from AUTH-001.

## Background / Context
**FastMCP parity**: FastMCP's `JWTVerifier` mode validates bearer tokens against a JWKS endpoint with configurable `issuer` and `audience` claims. No OAuth server, no client registration, no token endpoint — the server just verifies that incoming JWTs were issued by a trusted authority.

This mode is ideal for MCP servers deployed behind an existing identity platform (e.g. Unique's own JWT-issuing platform, corporate SSO). The external system handles user authentication and token issuance; the MCP server only needs to verify the token's signature, expiry, issuer, and audience.

`JwtTokenVerifier` builds a `TokenValidationResult` (and ultimately `McpIdentity` via CORE-006) from standard JWT claims, enabling tools to access `ctx.identity.userId`, `ctx.identity.scopes`, etc. without any OAuth state.

## Acceptance Criteria
- [ ] `JwtTokenVerifier` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Implements `McpAuthProvider` interface: `validate(token: string): Promise<TokenValidationResult | null>`
- [ ] Constructor accepts: `{ jwksUri: string, issuer: string, audience: string | string[], algorithms?: string[] }`
- [ ] `servesOAuthRoutes` property returns `false` — no OAuth controllers needed
- [ ] Uses `jose` library for JWKS key fetching and JWT verification (NOT `jsonwebtoken` — it lacks JWKS support)
- [ ] JWKS keys are cached with a configurable TTL (default 5 minutes)
- [ ] Cache is invalidated on unknown `kid` — triggers JWKS re-fetch from the endpoint
- [ ] JWT claims mapped to `TokenValidationResult`:
  - `sub` claim → `userId`
  - `client_id` claim → `clientId`
  - `scope` claim (space-separated string) → `scopes[]`
  - `email` claim → `email`
  - `name` claim → `displayName`
  - Full payload → `raw`
- [ ] Returns `null` (not throw) when token is invalid, expired, wrong issuer, or wrong audience — caller (guard or MultiAuthProvider) decides the response
- [ ] No `IOAuthStore` interaction — purely stateless validation
- [ ] No session termination on revocation — stateless JWT has no revocation mechanism
- [ ] `McpAuthModule.forRootAsync({ useFactory: () => ({ auth: new JwtTokenVerifier({ jwksUri, issuer, audience }) }) })` works without providing `oauthStore` or `encryptionService`

## BDD Scenarios

```gherkin
Feature: Lightweight JWT validation against an external identity provider

  Background:
    Given the JWT verifier trusts issuer "https://auth.unique.ch"
    And the expected audience is "mcp-server"
    And the JWKS endpoint is "https://auth.unique.ch/.well-known/jwks.json"

  Rule: Valid JWTs from the trusted issuer produce a complete identity

    Scenario: JWT with all standard claims maps to a full identity
      Given a valid JWT for user "alice" with email "alice@unique.ch", scopes "mail.read mail.send", and client "app-1"
      When the token is validated
      Then the identity contains user ID "alice", client "app-1", scopes "mail.read" and "mail.send", email "alice@unique.ch"
      And the full JWT payload is available as raw claims

    Scenario: JWT with only required claims maps to a partial identity
      Given a valid JWT with only subject "user-1" and no email, name, client ID, or scopes
      When the token is validated
      Then the identity contains user ID "user-1" with no email, no display name, no client ID, and empty scopes

  Rule: Invalid tokens are silently rejected without throwing

    Scenario: Expired JWT is rejected
      Given a JWT that has expired
      When the token is validated
      Then no identity is returned
      And no error is thrown

    Scenario: JWT for the wrong audience is rejected
      Given a valid JWT with audience "different-server" instead of "mcp-server"
      When the token is validated
      Then no identity is returned

    Scenario: JWT from an untrusted issuer is rejected
      Given a valid JWT issued by "https://other-issuer.com"
      When the token is validated
      Then no identity is returned

    Scenario: Empty or missing token is rejected
      When an empty string is validated
      Then no identity is returned

    Scenario: Malformed token string is rejected
      When the string "not-a-jwt" is validated
      Then no identity is returned

  Rule: JWKS keys are cached and automatically refreshed on key rotation

    Scenario: Cached JWKS keys are reused within the TTL
      Given the JWKS keys were fetched 3 minutes ago
      And the cache TTL is 5 minutes
      When a token with a known key ID is validated
      Then the cached keys are used without a network request

    Scenario: Unknown key ID triggers a JWKS refresh
      Given the JWKS keys are cached
      And a valid JWT is signed with a key ID not in the cache
      When the token is validated
      Then fresh JWKS keys are fetched from the endpoint
      And if the new key set contains the key ID, validation succeeds

    Scenario: JWKS keys are refreshed after the cache TTL expires
      Given the JWKS keys were fetched more than 5 minutes ago
      When a token is validated
      Then fresh JWKS keys are fetched from the endpoint
```

## Dependencies
- **Depends on:** AUTH-001 — `McpAuthProvider` interface that `JwtTokenVerifier` implements
- **Depends on:** CORE-006 — `McpIdentity` interface; `JwtTokenVerifier` produces `TokenValidationResult` which maps to `McpIdentity` via `McpIdentityResolver`
- **Blocks:** AUTH-006 — `MultiAuthProvider` uses `JwtTokenVerifier` as a verifier in its chain

## Technical Notes

### jose library usage
```typescript
import { createRemoteJWKSet, jwtVerify, type JWTPayload } from 'jose';

export class JwtTokenVerifier implements McpAuthProvider {
  readonly servesOAuthRoutes = false;

  private jwks: ReturnType<typeof createRemoteJWKSet>;

  constructor(private readonly options: JwtTokenVerifierOptions) {
    // createRemoteJWKSet handles JWKS fetching, caching, and kid-based re-fetch
    this.jwks = createRemoteJWKSet(new URL(options.jwksUri), {
      cooldownDuration: options.jwksCacheTtl ?? 300_000, // 5 minutes default
    });
  }

  async validate(token: string): Promise<TokenValidationResult | null> {
    if (!token) return null;
    try {
      const { payload } = await jwtVerify(token, this.jwks, {
        issuer: this.options.issuer,
        audience: this.options.audience,
        algorithms: this.options.algorithms,
      });
      return this.mapClaims(payload);
    } catch {
      return null; // expired, wrong issuer/audience, bad signature, malformed
    }
  }

  private mapClaims(payload: JWTPayload): TokenValidationResult {
    const scope = (payload.scope as string) ?? '';
    return {
      userId: payload.sub!,
      clientId: (payload.client_id as string) ?? undefined,
      scopes: scope ? scope.split(' ') : [],
      email: (payload.email as string) ?? undefined,
      displayName: (payload.name as string) ?? undefined,
      raw: payload,
    };
  }
}
```

### Configuration interface
```typescript
export interface JwtTokenVerifierOptions {
  /** JWKS endpoint URL (e.g. https://auth.unique.ch/.well-known/jwks.json) */
  jwksUri: string;
  /** Expected issuer claim */
  issuer: string;
  /** Expected audience claim(s) */
  audience: string | string[];
  /** Allowed signing algorithms (default: RS256) */
  algorithms?: string[];
  /** JWKS cache TTL in ms (default: 300000 = 5 minutes) */
  jwksCacheTtl?: number;
}
```

### Usage example
```typescript
// In a NestJS module — service behind Unique's JWT-issuing platform
McpAuthModule.forRootAsync({
  useFactory: () => ({
    auth: new JwtTokenVerifier({
      jwksUri: 'https://auth.unique.ch/.well-known/jwks.json',
      issuer: 'https://auth.unique.ch',
      audience: 'outlook-mcp-server',
    }),
  }),
})
```

### FastMCP parity
This is a direct equivalent of FastMCP's `JWTVerifier`:
```python
# FastMCP equivalent
server = FastMCP(auth=JWTVerifier(
    jwks_uri="https://auth.unique.ch/.well-known/jwks.json",
    issuer="https://auth.unique.ch",
    audience="outlook-mcp-server",
))
```

### Key design decisions
1. **`jose` over `jsonwebtoken`**: `jose` has built-in JWKS support via `createRemoteJWKSet()` with automatic caching and kid-based re-fetch. `jsonwebtoken` requires manual JWKS fetching via `jwks-rsa` — more dependencies and more code.
2. **Returns null, not throws**: Enables use in `MultiAuthProvider` where one verifier's rejection should not prevent the next from trying. The guard (or MultiAuthProvider) decides what null means.
3. **No IOAuthStore**: Stateless validation means no database interaction. This is the key advantage for simple deployments.
4. **JWKS cache with kid-based invalidation**: `jose`'s `createRemoteJWKSet` handles this natively — caches keys for the configured duration, but re-fetches when an unknown `kid` is encountered (key rotation scenario).
5. **Optional claims**: Not all JWTs will have `email`, `name`, `client_id`, or `scope`. The verifier gracefully handles missing claims with undefined/empty defaults.

### File locations
- `packages/nestjs-mcp/src/auth/providers/jwt-token-verifier.ts`
- `packages/nestjs-mcp/src/auth/providers/jwt-token-verifier.options.ts`
