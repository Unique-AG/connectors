# AUTH-009: RemoteAuthProvider — DCR-compatible identity provider delegation

## Summary
Implement `RemoteAuthProvider` as an auth mode for identity providers with Dynamic Client Registration (DCR) support — such as Descope and WorkOS AuthKit. It extends `JwtTokenVerifier` (AUTH-005) with OAuth discovery metadata, enabling automatic MCP client registration without manual configuration. Also implement `AuthKitProvider` as a built-in specialization for WorkOS AuthKit.

## Background / Context
**FastMCP parity**: FastMCP's `RemoteAuthProvider` supports identity providers that already implement DCR (RFC 7591). Unlike `OAuthProxy` (AUTH-008) which bridges non-DCR providers, `RemoteAuthProvider` simply advertises the external IdP's endpoints to MCP clients so they can register and authenticate directly — no proxy needed.

The key insight: DCR-compliant IdPs already speak the protocol MCP clients expect. `RemoteAuthProvider` just needs to:
1. Fetch the IdP's OpenID Connect discovery document
2. Advertise the IdP's DCR endpoint to MCP clients
3. Validate the resulting JWTs (inherited from `JwtTokenVerifier`)

FastMCP ships `AuthKitProvider` as a convenience wrapper for WorkOS AuthKit with domain-based URL construction.

In NestJS, both implement `McpAuthProvider` from AUTH-001 and extend `JwtTokenVerifier` from AUTH-005.

## Acceptance Criteria

### RemoteAuthProvider
- [ ] `RemoteAuthProvider` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Extends `JwtTokenVerifier` (AUTH-005) — inherits JWKS-based JWT validation
- [ ] Implements `McpAuthProvider` interface (inherited from `JwtTokenVerifier`)
- [ ] `servesOAuthRoutes` returns `true` — exposes discovery metadata endpoint
- [ ] Constructor accepts `RemoteAuthProviderOptions`:
  - `issuerUrl: string` — base URL of the DCR-compatible IdP
  - `audience: string | string[]` — expected audience claim(s)
  - `algorithms?: string[]` — allowed signing algorithms (default: RS256)
  - `discoveryTtl?: number` — discovery document cache TTL in ms (default: 3600000 = 1 hour)
- [ ] On initialization, fetches OpenID Connect discovery document from `{issuerUrl}/.well-known/openid-configuration`
- [ ] Extracts `jwks_uri` from discovery and passes to parent `JwtTokenVerifier`
- [ ] Extracts `registration_endpoint` from discovery and advertises to MCP clients
- [ ] Exposes `/.well-known/oauth-authorization-server` endpoint that returns metadata pointing to the external IdP's endpoints
- [ ] Discovery document cached with configurable TTL (default 1 hour)
- [ ] Cache refreshed on key rotation errors (unknown kid in JWT)
- [ ] If discovery document unavailable at startup, logs warning (not error) and retries on first request

### AuthKitProvider
- [ ] `AuthKitProvider` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Extends `RemoteAuthProvider` with WorkOS AuthKit-specific defaults
- [ ] Constructor accepts `AuthKitProviderOptions`:
  - `authkitDomain: string` — WorkOS AuthKit domain (e.g. `myapp.workos.com`)
  - `clientId: string` — WorkOS client ID
  - `audience?: string | string[]` — defaults based on clientId
- [ ] Auto-constructs `issuerUrl` from `authkitDomain`: `https://{authkitDomain}`
- [ ] WorkOS-specific claim mapping: `org_id` → organizational context

### McpAuthModule integration
- [ ] `McpAuthModule.forRootAsync({ useFactory: () => ({ auth: new RemoteAuthProvider({...}) }) })` works
- [ ] `McpAuthModule.forRootAsync({ useFactory: () => ({ auth: new AuthKitProvider({...}) }) })` works
- [ ] Discovery metadata endpoint registered when `auth.servesOAuthRoutes` is true

## BDD Scenarios

```gherkin
Feature: Remote auth provider for DCR-compatible identity providers

  Rule: The provider auto-discovers the identity provider's endpoints on startup

    Scenario: Discovery document is fetched and endpoints are extracted
      Given a remote auth provider configured for issuer "https://auth.example.com"
      When the provider initializes
      Then it fetches the OpenID Connect discovery document from the issuer
      And it extracts the JWKS URI for token signature validation
      And it extracts the authorization, token, and registration endpoints

    Scenario: Discovery document unavailable at startup does not crash the server
      Given a remote auth provider configured for an unreachable issuer
      When the provider initializes
      Then a warning is logged
      And the application starts without error
      When the first token validation request arrives
      Then the provider retries fetching the discovery document
      And if the issuer is now reachable, validation proceeds normally
      And if still unreachable, the token is rejected

  Rule: MCP clients discover and register with the identity provider directly

    Scenario: OAuth metadata exposes the identity provider's DCR endpoint
      Given an MCP server configured with a remote auth provider
      When an MCP client requests the OAuth authorization server metadata
      Then the response includes the external identity provider's registration endpoint
      And the client can register directly with the identity provider
      And no proxy intermediary is needed

  Rule: Tokens are validated via JWKS from the discovery document

    Scenario: Valid JWT from the identity provider is accepted
      Given a remote auth provider initialized with a discovery document
      And a client presents a valid JWT for user "alice" with scopes "openid email" and audience "my-mcp-server"
      When the token is validated
      Then the client identity shows user ID "alice" with scopes "openid" and "email"
      And the JWKS keys used for validation come from the discovery document

    Scenario: Key rotation triggers discovery document refresh
      Given a remote auth provider with a cached discovery document
      And a valid JWT signed with a key not in the cached JWKS
      When the token is validated
      Then the JWKS cache is refreshed
      And if the key is still not found, the discovery document itself is re-fetched
      And the new JWKS URI from the refreshed discovery is used for validation

  Rule: AuthKit provider simplifies WorkOS AuthKit configuration

    Scenario: AuthKit provider constructs issuer URL from the domain
      Given an AuthKit provider configured with domain "myapp.workos.com" and client ID "client_abc123"
      When the provider initializes
      Then the issuer URL is "https://myapp.workos.com"
      And the discovery document is fetched from "https://myapp.workos.com/.well-known/openid-configuration"
```

## Dependencies
- **Depends on:** AUTH-001 — `McpAuthProvider` interface
- **Depends on:** AUTH-005 — `JwtTokenVerifier` that `RemoteAuthProvider` extends
- **Blocks:** none

## Technical Notes

### RemoteAuthProvider implementation sketch
```typescript
export interface RemoteAuthProviderOptions {
  issuerUrl: string;
  audience: string | string[];
  algorithms?: string[];
  discoveryTtl?: number; // ms, default 3600000 (1 hour)
}

export class RemoteAuthProvider extends JwtTokenVerifier {
  readonly servesOAuthRoutes = true; // overrides JwtTokenVerifier's false

  private discoveryDoc: OidcDiscoveryDocument | null = null;
  private discoveryFetchedAt: number = 0;
  private readonly discoveryTtl: number;

  constructor(private readonly remoteOptions: RemoteAuthProviderOptions) {
    // Defer JwtTokenVerifier initialization — jwksUri comes from discovery
    super({
      jwksUri: '', // placeholder — set after discovery
      issuer: remoteOptions.issuerUrl,
      audience: remoteOptions.audience,
      algorithms: remoteOptions.algorithms,
    });
    this.discoveryTtl = remoteOptions.discoveryTtl ?? 3_600_000;
    // Fire-and-forget initial discovery fetch (see note below on NestJS lifecycle)
    this.refreshDiscovery().catch(err => {
      console.warn(`[RemoteAuthProvider] Failed to fetch discovery doc on startup: ${err.message}`);
    });
  }

  async validate(token: string): Promise<TokenValidationResult | null> {
    // Ensure discovery is loaded before first validation
    if (!this.discoveryDoc) {
      await this.refreshDiscovery();
    }
    return super.validate(token);
  }

  private async refreshDiscovery(): Promise<void> {
    const now = Date.now();
    if (this.discoveryDoc && now - this.discoveryFetchedAt < this.discoveryTtl) return;

    const url = `${this.remoteOptions.issuerUrl}/.well-known/openid-configuration`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Discovery fetch failed: ${response.status}`);

    this.discoveryDoc = await response.json() as OidcDiscoveryDocument;
    this.discoveryFetchedAt = now;

    // Update parent JwtTokenVerifier's JWKS source
    this.updateJwksUri(this.discoveryDoc.jwks_uri);
  }

  getDiscoveryMetadata(): OAuthServerMetadata {
    return {
      issuer: this.remoteOptions.issuerUrl,
      authorization_endpoint: this.discoveryDoc?.authorization_endpoint ?? '',
      token_endpoint: this.discoveryDoc?.token_endpoint ?? '',
      registration_endpoint: this.discoveryDoc?.registration_endpoint ?? '',
      jwks_uri: this.discoveryDoc?.jwks_uri ?? '',
      response_types_supported: ['code'],
      grant_types_supported: ['authorization_code'],
      code_challenge_methods_supported: ['S256'],
    };
  }
}
```

### AuthKitProvider implementation sketch
```typescript
export interface AuthKitProviderOptions {
  authkitDomain: string;
  clientId: string;
  audience?: string | string[];
}

export class AuthKitProvider extends RemoteAuthProvider {
  constructor(options: AuthKitProviderOptions) {
    super({
      issuerUrl: `https://${options.authkitDomain}`,
      audience: options.audience ?? options.clientId,
    });
  }
}
```

### Discovery document interface
```typescript
interface OidcDiscoveryDocument {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  registration_endpoint?: string;
  jwks_uri: string;
  userinfo_endpoint?: string;
  scopes_supported?: string[];
  response_types_supported?: string[];
  grant_types_supported?: string[];
  code_challenge_methods_supported?: string[];
}
```

### Discovery metadata endpoint
`RemoteAuthProvider` registers a `GET /.well-known/oauth-authorization-server` endpoint that returns the external IdP's endpoints, enabling MCP clients to discover and register with the IdP directly:

```json
{
  "issuer": "https://auth.example.com",
  "authorization_endpoint": "https://auth.example.com/authorize",
  "token_endpoint": "https://auth.example.com/oauth/token",
  "registration_endpoint": "https://auth.example.com/connect/register",
  "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code"],
  "code_challenge_methods_supported": ["S256"]
}
```

### Key difference from OAuthProxy (AUTH-008)
| Aspect | OAuthProxy (AUTH-008) | RemoteAuthProvider (AUTH-009) |
|---|---|---|
| Upstream DCR support | No — proxy handles registration | Yes — client registers directly |
| Token flow | Proxy exchanges code/token | Client authenticates directly with IdP |
| Token validation | Call upstream userinfo endpoint | Validate JWT via JWKS (stateless) |
| Routes needed | Full proxy (authorize, token, callback) | Discovery metadata only |
| Use case | GitHub, Google, Azure (no DCR) | Descope, WorkOS, Auth0 (DCR) |

### FastMCP parity
| FastMCP | NestJS equivalent |
|---|---|
| `RemoteAuthProvider(issuer_url=..., audience=...)` | `new RemoteAuthProvider({ issuerUrl, audience })` |
| `AuthKitProvider(authkit_domain=..., client_id=...)` | `new AuthKitProvider({ authkitDomain, clientId })` |

### Async initialization
- If `RemoteAuthProvider` is managed as an injectable NestJS provider, async initialization should use `OnModuleInit` so NestJS awaits it during bootstrap. When used as a plain value object (instantiated by consumer and passed to `forRootAsync()`), the constructor fire-and-forget pattern is acceptable — document both usage patterns.

### File locations
- `packages/nestjs-mcp/src/auth/providers/remote-auth.provider.ts`
- `packages/nestjs-mcp/src/auth/providers/remote-auth.options.ts`
- `packages/nestjs-mcp/src/auth/providers/authkit.provider.ts`
- `packages/nestjs-mcp/src/auth/providers/authkit.options.ts`
