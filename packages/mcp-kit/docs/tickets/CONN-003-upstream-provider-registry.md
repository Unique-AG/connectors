# CONN-003: Upstream Provider Registry & OAuth Callback Controller

## Summary
Implement the registry that stores OAuth configuration per upstream provider, and the NestJS controller that handles OAuth authorization callbacks. The registry is the single source of truth for provider OAuth endpoints, client credentials, and scope requirements. The callback controller receives authorization codes, exchanges them for tokens, encrypts and stores them, and signals completion back to any waiting elicitation handler.

## Background / Context
Both the pre-auth portal flow (CONN-002) and the mid-session reconnection flow (CONN-005) need to perform OAuth authorization code exchanges with upstream providers. The `UpstreamProviderRegistry` centralizes all provider-specific OAuth configuration so that:

1. The well-known endpoint can advertise per-provider authorization URLs (CONN-002)
2. The callback controller can look up client credentials to exchange codes for tokens
3. The connection guard can build correct OAuth URLs for elicitation (CONN-005)

The callback controller is a standard NestJS `@Controller()` — not raw Express middleware. It handles the `GET /mcp/auth/callback/:providerId?code=...&state=...` route that upstream OAuth servers redirect to after user consent.

## Acceptance Criteria

### UpstreamProviderConfig interface
- [ ] `UpstreamProviderConfig` interface: `{ providerId, displayName, description?, authorizationUrl, tokenUrl, revocationUrl?, clientId, clientSecret, defaultScopes, callbackPath? }`
- [ ] `callbackPath` defaults to `/mcp/auth/callback/${providerId}` if not specified
- [ ] `defaultScopes` is the minimum set of scopes requested unless overridden by a specific `@RequiresConnection` call

### UpstreamProviderRegistry service
- [ ] `UpstreamProviderRegistry` is a `@Injectable()` singleton
- [ ] `register(config: UpstreamProviderConfig): void` — registers a provider; called during module init
- [ ] `get(providerId: string): UpstreamProviderConfig | null`
- [ ] `list(): UpstreamProviderConfig[]` — returns all registered providers
- [ ] Duplicate `providerId` registration at startup throws: `"Provider already registered: {providerId}"`
- [ ] Exported from `McpConnectionModule`

### Provider registration in McpConnectionModule
- [ ] `McpConnectionModule.forRoot({ providers: [{ providerId: 'microsoft-graph', ... }] })` accepts array of provider configs
- [ ] `McpConnectionModule.forRootAsync({ useFactory })` supports async config (e.g., loading client secrets from Vault)
- [ ] Each config entry is validated at startup: missing required fields throw descriptive errors

### PKCE support
- [ ] `buildAuthorizationUrl(providerId, redirectUri, state, scopes?, codeVerifier?): string` — constructs the OAuth authorization URL with PKCE `code_challenge` when `codeVerifier` is supplied
- [ ] `exchangeCode(providerId, code, redirectUri, codeVerifier?): Promise<OAuthTokenResponse>` — performs the token exchange (POST to `tokenUrl`) with `code_verifier` when present
- [ ] PKCE is optional per-provider: if `codeVerifier` is omitted, standard authorization code flow is used
- [ ] `OAuthTokenResponse`: `{ accessToken, refreshToken?, expiresIn, scopes, tokenType }`

### OAuth Callback Controller
- [ ] `McpOAuthCallbackController` is a standard `@Controller('mcp/auth/callback')` with `@Get(':providerId')`
- [ ] Validates `state` parameter against a short-lived CSRF state store (in-memory map with 10-minute TTL)
- [ ] Exchanges `code` for tokens using `UpstreamProviderRegistry.exchangeCode()`
- [ ] Stores tokens in `McpConnectionStore` encrypted (CONN-001)
- [ ] Resolves `userId` from the `state` parameter (state encodes `userId` + CSRF nonce)
- [ ] Calls `createElicitationCompletionNotifier(elicitationId)` if the connection was triggered by an elicitation (state encodes optional `elicitationId`)
- [ ] Returns an HTML success page (or redirect to configured `successRedirectUrl`) after successful exchange
- [ ] On error (invalid code, exchange failure): returns an HTML error page or redirects to `errorRedirectUrl`
- [ ] Controller is auto-registered when `McpConnectionModule` is imported
- [ ] The OAuth state CSRF store is pluggable via `{ provide: MCP_OAUTH_STATE_STORE, useClass: RedisOAuthStateStore }`. `InMemoryOAuthStateStore` is the default. In multi-instance deployments, a shared store (Redis) is required to ensure callbacks can be validated on any instance.

### State parameter encoding
- [ ] State is a signed JWT (HS256) containing: `{ userId, providerId, nonce, elicitationId?, exp }`
- [ ] Signed with `encryptionKey` (reuses CONN-001 key)
- [ ] Expiry: 10 minutes (OAuth callback must complete within this window)
- [ ] Validation failure (expired, tampered) returns HTTP 400 with `{ error: 'invalid_state' }`

### Token refresh utility
- [ ] `refreshToken(providerId, refreshToken): Promise<OAuthTokenResponse>` — performs OAuth refresh grant (POST to `tokenUrl` with `grant_type=refresh_token`)
- [ ] On refresh failure (token revoked, network error): throws `UpstreamConnectionLostError(providerId)`
- [ ] `UpstreamConnectionLostError` is exported — caught by CONN-005 reconnection handler

## BDD Scenarios

```gherkin
Feature: Upstream Provider Registry & OAuth Callback
  The provider registry stores OAuth configuration per upstream provider.
  The callback controller receives authorization codes, exchanges them for tokens,
  and signals completion to any waiting elicitation handler.

  Rule: Providers are registered with complete OAuth configuration

    Scenario: Registered provider is discoverable by ID
      Given McpConnectionModule configured with a "microsoft-graph" provider
      When UpstreamProviderRegistry.get("microsoft-graph") is called
      Then it returns the provider config with authorizationUrl and tokenUrl

    Scenario: Duplicate provider registration fails at startup
      Given "microsoft-graph" is already registered
      When a second registration for "microsoft-graph" is attempted at startup
      Then an error is thrown: "Provider already registered: microsoft-graph"

    Scenario: Unknown provider ID returns null
      Given no provider "acme" is registered
      When UpstreamProviderRegistry.get("acme") is called
      Then null is returned

  Rule: Authorization URLs include state and optional PKCE

    Scenario: Authorization URL includes state parameter
      Given a registered provider "google-drive"
      When buildAuthorizationUrl is called for user "alice" with provider "google-drive"
      Then the returned URL includes a "state" query parameter
      And the state decodes to contain userId "alice" and providerId "google-drive"

    Scenario: PKCE code challenge is included when code verifier is provided
      Given a registered provider "slack"
      When buildAuthorizationUrl is called with a codeVerifier
      Then the URL includes "code_challenge" and "code_challenge_method=S256"

  Rule: Callback controller exchanges code and stores tokens

    Scenario: Successful OAuth callback stores encrypted tokens
      Given a pending OAuth flow for user "alice" and provider "microsoft-graph"
      And the upstream provider issues authorization code "auth_code_xyz"
      When the upstream redirects to GET /mcp/auth/callback/microsoft-graph?code=auth_code_xyz&state=...
      Then the callback controller exchanges the code for tokens
      And an encrypted connection for "alice" + "microsoft-graph" is stored in the connection store
      And the user sees a success page

    Scenario: Callback triggered by elicitation signals completion
      Given an active elicitation with ID "elicit-123" waiting for provider "google-drive"
      And user "alice" completes the OAuth flow
      When the callback is received with state containing elicitationId "elicit-123"
      Then createElicitationCompletionNotifier("elicit-123") is called
      And the waiting tool handler is resumed

    Scenario: Expired state parameter is rejected
      Given a state JWT that expired 15 minutes ago
      When the callback is received with that state
      Then the callback returns HTTP 400 with error "invalid_state"
      And no tokens are stored

  Rule: Token refresh produces updated credentials

    Scenario: Successful refresh updates stored tokens
      Given user "alice" has a stored connection for "microsoft-graph" with a valid refresh token
      When refreshToken is called for "alice" + "microsoft-graph"
      Then a new access token is returned
      And the stored connection is updated with the new access token and new expiry

    Scenario: Revoked refresh token throws UpstreamConnectionLostError
      Given user "alice"'s refresh token for "google-drive" has been revoked upstream
      When refreshToken is called for "alice" + "google-drive"
      Then UpstreamConnectionLostError is thrown with providerId "google-drive"
```

## FastMCP Parity
FastMCP handles OAuth callbacks via its built-in auth server routes. Our `McpOAuthCallbackController` mirrors this but as a standard NestJS controller, making it fully compatible with NestJS guards, interceptors, and middleware.

## Dependencies
- **Depends on:** CONN-001 (McpConnectionStore — token storage after callback)
- **Blocks:** CONN-002 (needs registry to validate provider IDs + build authorizationUrls for well-known endpoint)
- **Blocks:** CONN-004/CONN-005 (needs registry to build OAuth URLs for elicitation + needs exchangeCode for token refresh)

## Technical Notes
- State JWT is signed with the same `encryptionKey` used for token encryption (CONN-001) — one key, two uses (signing + encryption). Document this clearly. In high-security scenarios, use separate keys.
- The HTML success/error pages are minimal by default (plain text confirmation). `successRedirectUrl` and `errorRedirectUrl` options allow redirecting to a custom UI (e.g., connection portal's confirmation page)
- Callback URL must be registered as an allowed redirect URI in the upstream provider's OAuth app settings — document this as a deployment requirement
- The CSRF state store is in-memory (10-min TTL). In multi-instance deployments, state validation may fail if the callback hits a different instance. Use Redis-backed state store in production — pluggable via `{ provide: MCP_OAUTH_STATE_STORE, useClass: RedisOAuthStateStore }`

### PKCE policy
PKCE policy: PKCE (`code_challenge` + `code_verifier`) is **mandatory** for public clients (those without a `clientSecret`). It is **optional but recommended** for confidential clients (those with a `clientSecret`). The `buildAuthorizationUrl()` method automatically includes PKCE when `codeVerifier` is supplied. Callers should always supply a `codeVerifier` unless they have a specific reason not to.
