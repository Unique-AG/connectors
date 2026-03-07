# AUTH-008: OAuthProxyProvider — Bridge for non-DCR OAuth providers

## Summary
Implement `OAuthProxyProvider` as an auth mode that bridges OAuth providers lacking Dynamic Client Registration (DCR) support — such as GitHub, Google, Azure, and AWS. It presents a DCR-compliant interface to MCP clients while using pre-registered credentials. Also implement `GitHubOAuthProvider` as a built-in specialization with GitHub-specific defaults.

## Background / Context
**FastMCP parity**: FastMCP v2.12.0+ includes `OAuthProxy` — a bridge that wraps non-DCR OAuth providers behind a standard MCP-compatible OAuth interface. MCP clients expect to discover and dynamically register via RFC 7591 (DCR), but many popular OAuth providers (GitHub, Google, Azure) don't support DCR. The proxy solves this by handling DCR on behalf of the client and forwarding the actual OAuth flow to the upstream provider using pre-registered app credentials.

FastMCP also ships `GitHubProvider` as a convenience wrapper over `OAuthProxy` with GitHub-specific authorization and token URLs pre-configured.

In NestJS, both `OAuthProxyProvider` and `GitHubOAuthProvider` implement the `McpAuthProvider` interface from AUTH-001 and can be passed to `McpAuthModule.forRootAsync()`.

## Acceptance Criteria

### OAuthProxyProvider
- [ ] `OAuthProxyProvider` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Implements `McpAuthProvider` interface: `validate(token: string): Promise<TokenValidationResult | null>`
- [ ] `servesOAuthRoutes` returns `true` — provider registers HTTP routes
- [ ] Constructor accepts `OAuthProxyProviderOptions`:
  - `clientId: string` — pre-registered app client ID at the upstream provider
  - `clientSecret: string` — pre-registered app client secret
  - `authorizationUrl: string` — upstream provider's authorization endpoint
  - `tokenUrl: string` — upstream provider's token endpoint
  - `scopes: string[]` — OAuth scopes to request from upstream
  - `callbackUrl: string` — this server's callback URL
  - `userInfoUrl?: string` — endpoint to validate tokens and fetch user info
  - `tokenIntrospectionUrl?: string` — alternative token validation endpoint
- [ ] Exposes OAuth metadata discovery endpoint at `/.well-known/oauth-authorization-server`
- [ ] Handles OAuth authorization code flow: redirects client to upstream, receives callback, exchanges code for token
- [ ] Validates access tokens by calling the upstream provider's userinfo or introspection endpoint
- [ ] Translates upstream token format to `TokenValidationResult` interface
- [ ] Registers HTTP routes: `/.well-known/oauth-authorization-server`, `/oauth/authorize`, `/oauth/token`, `/auth/callback`

### GitHubOAuthProvider
- [ ] `GitHubOAuthProvider` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Extends `OAuthProxyProvider` with GitHub-specific defaults:
  - `authorizationUrl`: `https://github.com/login/oauth/authorize`
  - `tokenUrl`: `https://github.com/login/oauth/access_token`
  - `userInfoUrl`: `https://api.github.com/user`
- [ ] Constructor accepts `GitHubOAuthProviderOptions`:
  - `clientId: string`
  - `clientSecret: string`
  - `baseUrl: string` — this server's base URL (used to construct callbackUrl)
  - `scopes?: string[]` — defaults to `['read:user']`
- [ ] GitHub tokens validated against `https://api.github.com/user`
- [ ] GitHub user profile mapped to `TokenValidationResult`: `login` → `userId`, `email` → `email`, `name` → `displayName`

### McpAuthModule integration
- [ ] `McpAuthModule.forRootAsync({ useFactory: () => ({ auth: new OAuthProxyProvider({...}) }) })` works
- [ ] `McpAuthModule.forRootAsync({ useFactory: () => ({ auth: new GitHubOAuthProvider({...}) }) })` works
- [ ] OAuth proxy routes registered only when `auth.servesOAuthRoutes` is true
- [ ] OAuth `state` parameter is validated on callback to prevent CSRF. The state is a signed JWT (same pattern as CONN-003). Validation failure returns HTTP 400.

## BDD Scenarios

```gherkin
Feature: OAuth proxy bridging non-DCR providers for MCP clients

  Rule: MCP clients discover the proxy's OAuth endpoints via standard metadata

    Scenario: OAuth metadata discovery returns proxy endpoints
      Given an MCP server configured with the OAuth proxy for GitHub
      When an MCP client requests the OAuth authorization server metadata
      Then the response includes authorization, token, and registration endpoints
      And all endpoints point to the MCP server's proxy URLs, not directly to GitHub

  Rule: The proxy redirects the OAuth authorization flow to the upstream provider

    Scenario: Client is redirected to the upstream provider for authorization
      Given an MCP server configured with the OAuth proxy for GitHub
      When an MCP client initiates the OAuth authorization flow
      Then the client is redirected to GitHub's authorization page
      And the redirect includes the pre-registered client ID and requested scopes
      And a state parameter is included for CSRF protection

    Scenario: Authorization callback exchanges code for a token
      Given GitHub redirects back to the MCP server with an authorization code
      When the server receives the callback
      Then it exchanges the code for an access token at GitHub's token endpoint
      And the access token is associated with the MCP client's session
      And the client is redirected to complete the flow

  Rule: Authenticated tool calls validate the upstream token

    Scenario: Tool call validates identity via the upstream user info endpoint
      Given a client authenticated through the GitHub OAuth proxy flow
      When the client calls a tool on the MCP server
      Then the bearer token is validated against GitHub's user API
      And the client identity is populated with the GitHub username, email, and scopes

  Rule: GitHubOAuthProvider provides sensible defaults for GitHub

    Scenario: GitHub provider auto-configures GitHub-specific URLs
      Given a GitHub OAuth provider configured with client ID "abc" and base URL "https://myserver.com"
      When the provider initializes
      Then it uses GitHub's authorization URL for login
      And it uses GitHub's token URL for code exchange
      And it uses GitHub's user API for token validation
      And the callback URL is "https://myserver.com/auth/callback"
      And the default scopes include "read:user"
```

## Dependencies
- **Depends on:** AUTH-001 — `McpAuthProvider` interface that `OAuthProxyProvider` implements
- **Depends on:** TRANS-001 — HTTP transport must serve the OAuth callback and proxy endpoints
- **Blocks:** none

## Technical Notes

### OAuthProxyProvider implementation sketch
```typescript
export class OAuthProxyProvider implements McpAuthProvider {
  readonly servesOAuthRoutes = true;

  constructor(private readonly options: OAuthProxyProviderOptions) {}

  async validate(token: string): Promise<TokenValidationResult | null> {
    if (!token) return null;
    try {
      // Validate by calling upstream userinfo/introspection endpoint
      const userInfo = await this.fetchUserInfo(token);
      return this.mapToValidationResult(userInfo);
    } catch {
      return null;
    }
  }

  private async fetchUserInfo(token: string): Promise<unknown> {
    const url = this.options.userInfoUrl ?? this.options.tokenIntrospectionUrl;
    if (!url) throw new Error('No userinfo or introspection URL configured');
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error('Token validation failed');
    return response.json();
  }

  // Subclasses override this for provider-specific mapping
  protected mapToValidationResult(userInfo: unknown): TokenValidationResult {
    // Generic mapping — subclasses provide specific logic
    const info = userInfo as Record<string, unknown>;
    return {
      userId: String(info.sub ?? info.id ?? ''),
      clientId: this.options.clientId,
      scopes: this.options.scopes,
      email: info.email as string | undefined,
      displayName: info.name as string | undefined,
      raw: userInfo,
    };
  }
}
```

### GitHubOAuthProvider implementation sketch
```typescript
export interface GitHubOAuthProviderOptions {
  clientId: string;
  clientSecret: string;
  baseUrl: string;
  scopes?: string[];
}

export class GitHubOAuthProvider extends OAuthProxyProvider {
  constructor(options: GitHubOAuthProviderOptions) {
    super({
      clientId: options.clientId,
      clientSecret: options.clientSecret,
      authorizationUrl: 'https://github.com/login/oauth/authorize',
      tokenUrl: 'https://github.com/login/oauth/access_token',
      userInfoUrl: 'https://api.github.com/user',
      scopes: options.scopes ?? ['read:user'],
      callbackUrl: `${options.baseUrl}/auth/callback`,
    });
  }

  protected override mapToValidationResult(userInfo: unknown): TokenValidationResult {
    const ghUser = userInfo as { login: string; id: number; email?: string; name?: string };
    return {
      userId: ghUser.login,
      clientId: this.options.clientId,
      scopes: this.options.scopes,
      email: ghUser.email,
      displayName: ghUser.name,
      raw: userInfo,
    };
  }
}
```

### OAuthProxyController implementation
`OAuthProxyController` is a standard `@Controller('mcp/oauth')` with `@Get('authorize')`, `@Post('token')`, `@Post('revoke')` routes delegating to `ProxyOAuthServerProvider`:

```typescript
@Controller('mcp/oauth')
export class OAuthProxyController {
  constructor(private readonly proxy: OAuthProxyProvider) {}

  @Get('authorize')
  authorize(@Query() query: AuthorizeQueryDto, @Res() res: Response) {
    return this.proxy.handleAuthorize(query, res);
  }

  @Post('token')
  token(@Body() body: TokenRequestDto) {
    return this.proxy.handleTokenExchange(body);
  }

  @Post('revoke')
  revoke(@Body() body: RevokeRequestDto) {
    return this.proxy.handleRevoke(body);
  }
}
```

### GitHub user ID mapping
GitHub user ID mapping: GitHub's `sub` claim in the OIDC token is the numeric user ID as a string (e.g., `'1234567'`). Map this to `userId` in `TokenValidationResult`. The `email` is available from the `/user` endpoint if the `user:email` scope is granted.

### OAuth proxy routes
The provider registers these HTTP routes via a standard `OAuthProxyController` (`@Controller()`):

- OAuth proxy routes (`/auth/callback`, `/.well-known/oauth-authorization-server`, `/oauth/authorize`, `/oauth/token`) are registered via a standard `OAuthProxyController` (`@Controller()`) — not raw Express middleware

| Route | Purpose |
|---|---|
| `GET /.well-known/oauth-authorization-server` | OAuth metadata discovery (DCR-compliant) |
| `POST /oauth/register` | Dynamic client registration (proxy accepts and stores client info) |
| `GET /oauth/authorize` | Redirects to upstream authorization URL |
| `POST /oauth/token` | Exchanges authorization code for token via upstream token URL |
| `GET /auth/callback` | Receives callback from upstream provider |

### OAuth metadata response
```json
{
  "issuer": "https://myserver.com",
  "authorization_endpoint": "https://myserver.com/oauth/authorize",
  "token_endpoint": "https://myserver.com/oauth/token",
  "registration_endpoint": "https://myserver.com/oauth/register",
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code"],
  "code_challenge_methods_supported": ["S256"]
}
```

### Configuration interface
```typescript
export interface OAuthProxyProviderOptions {
  clientId: string;
  clientSecret: string;
  authorizationUrl: string;
  tokenUrl: string;
  scopes: string[];
  callbackUrl: string;
  userInfoUrl?: string;
  tokenIntrospectionUrl?: string;
}
```

### FastMCP parity
| FastMCP | NestJS equivalent |
|---|---|
| `OAuthProxy(client_id=..., auth_url=..., token_url=...)` | `new OAuthProxyProvider({ clientId, authorizationUrl, tokenUrl, ... })` |
| `GitHubProvider(client_id=..., client_secret=...)` | `new GitHubOAuthProvider({ clientId, clientSecret, baseUrl })` |

### File locations
- `packages/nestjs-mcp/src/auth/providers/oauth-proxy.provider.ts`
- `packages/nestjs-mcp/src/auth/providers/oauth-proxy.options.ts`
- `packages/nestjs-mcp/src/auth/providers/github-oauth.provider.ts`
- `packages/nestjs-mcp/src/auth/providers/github-oauth.options.ts`
- `packages/nestjs-mcp/src/auth/controllers/oauth-proxy.controller.ts`
