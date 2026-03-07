# CONN-004: @RequiresConnection Decorator & McpConnectionGuard

## Summary
Implement the `@RequiresConnection('providerId')` decorator that marks a tool, resource, or prompt method as requiring a live upstream connection. The accompanying `McpConnectionGuard` checks the connection store before execution and, if the connection is missing or expired, throws `UpstreamConnectionRequiredError` which the pipeline catches and routes to the reconnection flow (CONN-005).

## Background / Context
This is **Layer 2** of the hybrid auth strategy — the runtime safety net. Even when all required connections were collected upfront (CONN-002), tokens can expire or be revoked mid-session. Additionally, for servers with optional upstream integrations, tools may declare their connection requirement lazily (no upfront gate, just a runtime check).

`@RequiresConnection('microsoft-graph')` is syntactic sugar over standard NestJS `@UseGuards(McpConnectionGuard)` with metadata that tells the guard which provider to check. It does NOT reinvent the guard system — it uses `SetMetadata` + `Reflector` exactly as any other NestJS guard metadata decorator would.

The guard has two responsibilities:
1. **Fast-path check**: Read `ctx.identity.connectedProviders` (from JWT — no store hit). If the provider is listed and the JWT isn't stale, allow through.
2. **Store check**: If the JWT doesn't list the provider (optional connection, or JWT predates the connection), check the connection store directly. If connected and token is fresh, allow through.

If the connection is missing or expired: throw `UpstreamConnectionRequiredError(providerId, requiredScopes?)` — the reconnection pipeline (CONN-005) catches this and triggers elicitation.

## Acceptance Criteria

### @RequiresConnection decorator
- [ ] `@RequiresConnection(providerId: string, options?: { scopes?: string[] })` exported from `@unique-ag/mcp-kit`
- [ ] Applies `SetMetadata(MCP_REQUIRED_CONNECTION, { providerId, scopes })` on the method
- [ ] Can be applied on a method or on a class (applies to all methods in the class)
- [ ] Multiple `@RequiresConnection` decorators on the same method are supported (requires connections to provider A AND provider B)
- [ ] Works alongside `@UseGuards()`, `@UseInterceptors()`, and other standard NestJS method decorators

### McpConnectionGuard
- [ ] `McpConnectionGuard` implements `CanActivate`
- [ ] Reads `MCP_REQUIRED_CONNECTION` metadata from the handler using `Reflector.getAllAndMerge()`
- [ ] If no `MCP_REQUIRED_CONNECTION` metadata: `canActivate` returns `true` (guard is a no-op)
- [ ] For each required connection metadata entry:
  1. Check `ctx.identity.connectedProviders` (fast path — no I/O)
  2. If not in JWT or JWT claim is stale: check `McpConnectionStore.get(userId, providerId)`
  3. If connection found and not expired (`!isExpired(connection)`): allow through
  4. If connection found but expired: attempt refresh via CONN-003's `refreshToken()` inline; on success, allow through; on `UpstreamConnectionLostError`, fall through to reconnect
  5. If connection missing or lost: throw `UpstreamConnectionRequiredError(providerId, scopes)`
- [ ] `McpConnectionGuard` is exported from `@unique-ag/mcp-kit` for explicit registration
- [ ] Guard can be registered globally via `{ provide: APP_GUARD, useClass: McpOnly(McpConnectionGuard) }`

### UpstreamConnectionRequiredError
- [ ] `UpstreamConnectionRequiredError` extends `Error`
- [ ] Fields: `providerId: string`, `requiredScopes?: string[]`
- [ ] Exported from `@unique-ag/mcp-kit`
- [ ] NOT an MCP protocol error — it is an internal signal caught by the reconnection pipeline (CONN-005) before it reaches the MCP error serializer

### UpstreamTokenService (session-scoped)
- [ ] `UpstreamTokenService` is a `@Injectable()` service registered with session scope
- [ ] `getToken(providerId: string): Promise<string>` — retrieves decrypted, refreshed-if-needed access token; throws `UpstreamConnectionRequiredError` if missing
- [ ] `hasConnection(providerId: string): Promise<boolean>` — non-throwing check
- [ ] Injected via standard NestJS DI in tool handlers: `constructor(private readonly upstream: UpstreamTokenService)`
- [ ] Caches the decrypted token in-memory for the duration of the request (avoids decrypt on every `getToken()` call within one tool execution)

## BDD Scenarios

```gherkin
Feature: @RequiresConnection Decorator & McpConnectionGuard
  Tools and resources declare upstream provider dependencies via
  @RequiresConnection. The guard checks live connection status before
  execution and signals reconnection when a token is missing or expired.

  Rule: Guard allows execution when a valid connection exists

    Scenario: Tool executes normally when connection is present and fresh
      Given user "alice" has a live connection to "microsoft-graph" not expiring for 5 minutes
      And a tool "list_emails" decorated with @RequiresConnection("microsoft-graph")
      When "alice" calls "list_emails"
      Then the tool handler executes
      And no OAuth flow is triggered

    Scenario: Fast-path check uses JWT connectedProviders without store lookup
      Given "alice"'s token claims connectedProviders ["microsoft-graph"]
      And the connection store is unavailable (simulated failure)
      And the connection is not expiring soon
      When "alice" calls a tool requiring "microsoft-graph"
      Then the tool executes without hitting the connection store

    Scenario: Multiple required connections are all checked
      Given a tool requiring connections to both "microsoft-graph" and "google-drive"
      And "alice" has both connections active
      When "alice" calls the tool
      Then the tool executes

  Rule: Guard attempts inline refresh for expired tokens

    Scenario: Expired token is refreshed inline before execution
      Given "alice" has a connection to "microsoft-graph" whose access token expired 2 minutes ago
      And the refresh token is still valid
      When "alice" calls a tool requiring "microsoft-graph"
      Then the guard refreshes the token silently
      And the tool executes with the new access token

    Scenario: Revoked refresh token triggers reconnection
      Given "alice"'s connection to "microsoft-graph" has an expired access token
      And the refresh token has been revoked
      When "alice" calls a tool requiring "microsoft-graph"
      Then the guard throws UpstreamConnectionRequiredError for "microsoft-graph"
      And the reconnection pipeline (CONN-005) is triggered

  Rule: Guard throws UpstreamConnectionRequiredError when connection is missing

    Scenario: Missing connection for optional provider triggers reconnection
      Given user "bob" has no connection to "slack"
      And a tool "post_message" decorated with @RequiresConnection("slack")
      When "bob" calls "post_message"
      Then UpstreamConnectionRequiredError is thrown with providerId "slack"

    Scenario: First required connection missing short-circuits before checking the second
      Given "alice" has no connection to "microsoft-graph" but has "google-drive"
      And a tool requiring both "microsoft-graph" and "google-drive"
      When "alice" calls the tool
      Then UpstreamConnectionRequiredError is thrown for "microsoft-graph"
      And "google-drive" is not checked

  Rule: UpstreamTokenService provides tokens to tool handlers

    Scenario: Tool handler retrieves a decrypted token via UpstreamTokenService
      Given "alice" has a live connection to "google-drive"
      And a tool handler that calls upstream.getToken("google-drive")
      When the tool executes
      Then getToken returns the decrypted access token for "google-drive"

    Scenario: getToken throws UpstreamConnectionRequiredError when not connected
      Given "alice" has no connection to "slack"
      When a tool handler calls upstream.getToken("slack")
      Then UpstreamConnectionRequiredError is thrown

    Scenario: getToken caches the decrypted token within one tool execution
      Given "alice" has a connection to "microsoft-graph"
      When a tool handler calls upstream.getToken("microsoft-graph") twice
      Then the connection store is only decrypted once

  Rule: Decorator can be applied at class level

    Scenario: Class-level decorator applies to all methods
      Given an EmailService class decorated with @RequiresConnection("microsoft-graph")
      And it has methods list_emails, send_email, and delete_email
      When any of those tools are called without a "microsoft-graph" connection
      Then UpstreamConnectionRequiredError is thrown for all three
```

## FastMCP Parity
FastMCP does not have a per-tool connection requirement decorator. Our `@RequiresConnection` is inspired by Composio's per-tool connection validation and NestJS's own `@UseGuards` + `Reflector` metadata pattern.

## Dependencies
- **Depends on:** CONN-001 (McpConnectionStore — token lookup and isExpired check)
- **Depends on:** CONN-002 (McpIdentity.connectedProviders — fast-path from JWT)
- **Depends on:** CONN-003 (token refresh on expiry)
- **Blocks:** CONN-005 (reconnection pipeline catches UpstreamConnectionRequiredError thrown here)

## Technical Notes
- `@RequiresConnection` uses `SetMetadata` — exactly the same pattern as `@Roles()` or `@RequiredScopes()` (AUTH ticket). No magic metadata keys; just `MCP_REQUIRED_CONNECTION` symbol.
- The inline refresh in the guard is intentionally synchronous within `canActivate()`. If refresh takes >2 seconds, it may feel slow — accept this as a UX trade-off vs. failing hard. Document the latency expectation.
- `UpstreamTokenService` is session-scoped so its per-request decrypt cache is naturally scoped to one tool call. Between calls, cache is cleared.
- Do NOT add `@RequiresConnection` to `@Resource()` or `@Prompt()` list handlers (the list/describe handlers that respond to `listTools`, `listResources`, `listPrompts`). Connection checks only apply to execution handlers. List handlers should not trigger OAuth flows.
