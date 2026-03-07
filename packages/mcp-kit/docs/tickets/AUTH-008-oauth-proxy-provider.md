# AUTH-008: OAuthProxyProvider — Bridge for non-DCR OAuth providers

## Summary
Implement `OAuthProxyProvider` as an auth mode that bridges OAuth providers lacking Dynamic Client Registration (DCR) support — such as GitHub, Google, Azure, and AWS. It presents a DCR-compliant interface to MCP clients while using pre-registered credentials. Also implement `GitHubOAuthProvider` as a built-in specialization with GitHub-specific defaults.

## Background / Context
**FastMCP parity**: FastMCP v2.12.0+ includes `OAuthProxy` — a bridge that wraps non-DCR OAuth providers behind a standard MCP-compatible OAuth interface. MCP clients expect to discover and dynamically register via RFC 7591 (DCR), but many popular OAuth providers (GitHub, Google, Azure) don't support DCR. The proxy solves this by handling DCR on behalf of the client and forwarding the actual OAuth flow to the upstream provider using pre-registered app credentials.

FastMCP also ships `GitHubProvider` as a convenience wrapper over `OAuthProxy` with GitHub-specific authorization and token URLs pre-configured.

In NestJS, both `OAuthProxyProvider` and `GitHubOAuthProvider` implement the `McpAuthProvider` interface from AUTH-001 and can be passed to `McpAuthModule.forRootAsync()`.

## Acceptance Criteria

### Branded types (owned by this module)
- [ ] `ClientSecret = z.string().min(1).brand('ClientSecret')` — OAuth client secret; branded to prevent accidentally logging or passing it in place of other credential strings
- [ ] Exported from `auth/types.ts`

### OAuthProxyProvider
- [ ] `OAuthProxyProvider` class exported from `@unique-ag/nestjs-mcp/auth`
- [ ] Implements `McpAuthProvider` interface: `validate(token: string): Promise<TokenValidationResult | undefined>`
- [ ] `servesOAuthRoutes` returns `true` — provider registers HTTP routes
- [ ] Constructor accepts `OAuthProxyProviderOptions`:
  - `clientId: string` — pre-registered app client ID at the upstream provider
  - `clientSecret: string` — pre-registered app client secret
  - `authorizationUrl: string` — upstream provider's authorization endpoint
  - `tokenUrl: string` — upstream provider's token endpoint
  - `scopes: string[]` — OAuth scopes to request from upstream
  - `callbackUrl: string` — this server's callback URL
  - `userInfoUrl?: string` — endpoint to validate tokens and fetch user info (mutually exclusive with `tokenIntrospectionUrl`)
  - `tokenIntrospectionUrl?: string` — alternative token validation endpoint (mutually exclusive with `userInfoUrl`)
- [ ] `mapToValidationResult()` returns `undefined` (validation failure) when neither `sub` nor `id` is present in the userinfo response. MUST NOT fall back to an empty string `''` for userId — an empty userId would be treated as authenticated.
- [ ] `OAuthProxyProviderOptions` uses a discriminated union to require at least one validation endpoint at compile time: either `{ userInfoUrl: string }` or `{ tokenIntrospectionUrl: string }`. Both optional is not permitted — this is caught at construction, not runtime.
- [ ] `fetchUserInfo()` result is Zod-parsed before `mapToValidationResult()` accesses fields. `GitHubOAuthProvider` uses `GitHubUserSchema = z.object({ login: z.string(), id: z.number(), email: z.string().email().nullable().optional(), name: z.string().nullable().optional() })`.
- [ ] `OAuthProxyProviderOptionsSchema` validates at construction: all URLs are valid HTTPS URLs, `scopes` is non-empty.
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
// OAuthProxyProviderOptions — discriminated union requires at least one validation endpoint
export type OAuthProxyProviderOptions =
  | {
      clientId: string;
      clientSecret: string;
      authorizationUrl: string;
      tokenUrl: string;
      scopes: string[];
      callbackUrl: string;
      userInfoUrl: string;
      tokenIntrospectionUrl?: never;
    }
  | {
      clientId: string;
      clientSecret: string;
      authorizationUrl: string;
      tokenUrl: string;
      scopes: string[];
      callbackUrl: string;
      userInfoUrl?: never;
      tokenIntrospectionUrl: string;
    };

// GenericUserInfoSchema — validates the userinfo response before field access
const GenericUserInfoSchema = z.object({
  sub: z.union([z.string(), z.number()]).optional(),
  id: z.union([z.string(), z.number()]).optional(),
  email: z.string().optional(),
  name: z.string().optional(),
});

export class OAuthProxyProvider implements McpAuthProvider {
  readonly servesOAuthRoutes = true;

  constructor(protected readonly options: OAuthProxyProviderOptions) {}

  async validate(token: string): Promise<TokenValidationResult | undefined> {
    if (!token) return undefined;
    try {
      // Validate by calling upstream userinfo/introspection endpoint
      const userInfo = await this.fetchUserInfo(token);
      return this.mapToValidationResult(userInfo);
    } catch {
      return undefined;
    }
  }

  private async fetchUserInfo(token: string): Promise<unknown> {
    // url is always defined — discriminated union enforces at least one endpoint
    const url = this.options.userInfoUrl ?? this.options.tokenIntrospectionUrl;
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) throw new Error('Token validation failed');
    return response.json();
  }

  // Subclasses override this for provider-specific mapping
  protected mapToValidationResult(userInfo: unknown): TokenValidationResult | undefined {
    // Zod-parse the response before accessing fields
    const parsed = GenericUserInfoSchema.safeParse(userInfo);
    if (!parsed.success) return undefined;
    const info = parsed.data;

    // P0 security: never fall back to empty string — treat missing ID as auth failure
    const rawId = info.sub ?? info.id;
    if (rawId === undefined || rawId === null) return undefined;

    return {
      source: 'oauth',
      userId: String(rawId) as UserId,
      clientId: this.options.clientId as ClientId,
      scopes: this.options.scopes as Scope[],
      resource: this.options.callbackUrl,
      userProfileId: String(rawId) as UserProfileId,
      email: info.email,
      displayName: info.name,
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

// GitHubUserSchema — validates GitHub userinfo response before field access
const GitHubUserSchema = z.object({
  login: z.string(),
  id: z.number(),
  email: z.string().email().nullable().optional(),
  name: z.string().nullable().optional(),
});

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

  protected override mapToValidationResult(userInfo: unknown): TokenValidationResult | undefined {
    // Zod-parse the GitHub user response — never use unsafe cast
    const parsed = GitHubUserSchema.safeParse(userInfo);
    if (!parsed.success) return undefined;
    const ghUser = parsed.data;
    return {
      source: 'oauth',
      userId: ghUser.login as UserId,
      clientId: this.options.clientId as ClientId,
      scopes: this.options.scopes as Scope[],
      resource: this.options.callbackUrl,
      userProfileId: String(ghUser.id) as UserProfileId,
      email: ghUser.email ?? undefined,
      displayName: ghUser.name ?? undefined,
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
See `OAuthProxyProviderOptions` discriminated union in the implementation sketch above. Both `userInfoUrl` and `tokenIntrospectionUrl` as optional is not permitted — one must be provided. The union is enforced at compile time.

```typescript
// OAuthProxyProviderOptionsSchema — validates at construction time
const OAuthProxyProviderOptionsSchema = z.union([
  z.object({
    clientId: z.string().min(1),
    clientSecret: z.string().min(1),
    authorizationUrl: z.string().url(),
    tokenUrl: z.string().url(),
    scopes: z.array(z.string().min(1)).min(1),
    callbackUrl: z.string().url(),
    userInfoUrl: z.string().url(),
  }),
  z.object({
    clientId: z.string().min(1),
    clientSecret: z.string().min(1),
    authorizationUrl: z.string().url(),
    tokenUrl: z.string().url(),
    scopes: z.array(z.string().min(1)).min(1),
    callbackUrl: z.string().url(),
    tokenIntrospectionUrl: z.string().url(),
  }),
]);
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
